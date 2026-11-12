"""Run data validation, retrieval, optional training and eligibility on Vertex AI."""

import argparse
import json
import re
from pathlib import Path

from google.cloud import aiplatform
from kfp import compiler, dsl

from cloud import finetuned_retrieval, retrieval_evaluation
from cloud.eligibility import DEFAULT_MODEL, read_verified_results, verify_manifest
from cloud.release import read_target, save_target, verify_input_manifest
from cloud.tasks import blob
from cloud.training_inputs import pair_hashes, verify_training_manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--region", default="us-east1")
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--image", required=True, help="Versioned workflow image URI")
    parser.add_argument("--release", required=True)
    parser.add_argument("--release-target", type=Path,
                        help="Build record to bind to the successful deployment validation")
    parser.add_argument("--compile-only", action="store_true")
    parser.add_argument("--trainer-image",
                        help="Digest-pinned trainer image; adds the encoder training task")
    parser.add_argument("--finetuned-retrieval-image",
                        help="Digest-pinned retrieval image; ranks trials after this run's training")
    parser.add_argument("--retrieval-evaluation", action="store_true",
                        help="Score this run's fine-tuned rankings using C's frozen labels")
    parser.add_argument("--train-pairs", nargs="*", default=[],
                        help="Extra gs:// pair files; corpus pairs are already built from the release")
    parser.add_argument("--train-pairs-sha256", nargs="+", default=[],
                        help="Required expected SHA256 for each --train-pairs URI, in the same order")
    parser.add_argument("--trainer-batch-size", type=int, default=8,
                        help="Training batch size (default: 8, verified on the T4)")
    parser.add_argument("--wandb-secret", default="",
                        help="Secret Manager version with the W&B key, read by the task")
    parser.add_argument("--eligibility", action="store_true",
                        help="Evaluate C's frozen patient/trial pairs after data validation")
    parser.add_argument("--eligibility-model", help="Gemini model for eligibility (default: gemini-3.1-flash-lite)")
    args = parser.parse_args()
    target = Path("artifacts/cloud/pipeline.yaml")
    target.parent.mkdir(parents=True, exist_ok=True)
    if not args.compile_only:
        # Clear old success before validating this invocation's input configuration.
        for name in ("pipeline_job.txt", "validation.json", "validated_release.txt",
                     "validated_deployment.json", "training_manifest.json", "eligibility_manifest.json",
                     finetuned_retrieval.MANIFEST, retrieval_evaluation.MANIFEST):
            (target.parent / name).unlink(missing_ok=True)
    try:
        expected_pairs = pair_hashes(args.train_pairs, args.train_pairs_sha256)
    except ValueError as exc:
        parser.error(str(exc))
    if args.eligibility_model and not args.eligibility:
        parser.error("--eligibility-model requires --eligibility")
    if args.eligibility and not re.fullmatch(r"[^\s@]+@sha256:[0-9a-f]{64}", args.image):
        parser.error("--eligibility requires a workflow --image pinned by a complete SHA256 digest")
    eligibility_model = args.eligibility_model or DEFAULT_MODEL
    if args.trainer_image and not re.fullmatch(r"[^\s@]+@sha256:[0-9a-f]{64}", args.trainer_image):
        parser.error("--trainer-image must be pinned by a complete SHA256 digest")
    if args.finetuned_retrieval_image and (
        not args.trainer_image or not re.fullmatch(r"[^\s@]+@sha256:[0-9a-f]{64}", args.finetuned_retrieval_image)
    ):
        parser.error("--finetuned-retrieval-image requires --trainer-image and a complete image SHA256 digest")
    if args.trainer_batch_size < 1:
        parser.error("--trainer-batch-size must be positive")
    if any(not re.fullmatch(r"gs://[^/\s]+/\S+", uri) for uri in args.train_pairs):
        parser.error("--train-pairs must contain gs:// object URIs accessible to the training task")
    if (args.train_pairs or args.wandb_secret) and not args.trainer_image:
        parser.error("--train-pairs and --wandb-secret require --trainer-image")
    if args.retrieval_evaluation and (
        not args.finetuned_retrieval_image or not re.fullmatch(r"[^\s@]+@sha256:[0-9a-f]{64}", args.image)
    ):
        parser.error("--retrieval-evaluation requires --finetuned-retrieval-image and a digest-pinned workflow image")
    if args.retrieval_evaluation:
        evaluation_benchmark, evaluation_labels = retrieval_evaluation.load_benchmark()

    @dsl.container_component
    def fetch_raw(release: str, raw: dsl.Output[dsl.Dataset]):
        return dsl.ContainerSpec(image=args.image, command=["python", "-m", "cloud.tasks"],
            args=["fetch", "--source", release, "--output", raw.uri])

    @dsl.container_component
    def process_trials(raw: dsl.Input[dsl.Dataset], processed: dsl.Output[dsl.Dataset]):
        return dsl.ContainerSpec(image=args.image, command=["python", "-m", "cloud.tasks"],
            args=["process", "--source", raw.uri, "--output", processed.uri])

    @dsl.container_component
    def validate_data(processed: dsl.Input[dsl.Dataset], report: dsl.Output[dsl.Artifact]):
        return dsl.ContainerSpec(image=args.image, command=["python", "-m", "cloud.tasks"],
            args=["validate", "--source", processed.uri, "--output", report.uri])

    @dsl.container_component
    def retrieve_trials(report: dsl.Input[dsl.Artifact], rankings: dsl.Output[dsl.Artifact]):
        return dsl.ContainerSpec(image=args.image, command=["python", "-m", "cloud.tasks"],
            args=["retrieve", "--source", report.uri, "--output", rankings.uri])

    train_encoder = None
    if args.trainer_image:
        # Training is opt-in; the existing four-node data/retrieval workflow is preserved.
        @dsl.container_component
        def train_encoder(report: dsl.Input[dsl.Artifact], training: dsl.Output[dsl.Artifact]):
            # Consumes the report validate_data wrote, so it trains only on the release
            # this run validated; cloud.train rejects a report that is not PASSED.
            extra = (["--pairs", *args.train_pairs, "--pairs-sha256", *args.train_pairs_sha256]
                     if args.train_pairs else []) + (
                ["--wandb-secret", args.wandb_secret] if args.wandb_secret else [])
            return dsl.ContainerSpec(image=args.trainer_image,
                command=["python", "-m", "cloud.train"],
                args=["--validated-report", report.uri, "--output", training.uri,
                      "--image-uri", args.trainer_image,
                      "--batch-size", str(args.trainer_batch_size), *extra])

    if args.finetuned_retrieval_image:
        @dsl.container_component
        def retrieve_finetuned(report: dsl.Input[dsl.Artifact], training: dsl.Input[dsl.Artifact],
                               rankings: dsl.Output[dsl.Artifact]):
            return dsl.ContainerSpec(image=args.finetuned_retrieval_image,
                command=["python", "-m", "cloud.finetuned_retrieval"],
                args=["--source", report.uri, "--training", training.uri, "--output", rankings.uri,
                      "--image-uri", args.finetuned_retrieval_image, "--trainer-image", args.trainer_image,
                      "--trainer-batch-size", str(args.trainer_batch_size),
                      "--expected-pairs", json.dumps(expected_pairs, sort_keys=True)])

    if args.retrieval_evaluation:
        @dsl.container_component
        def evaluate_retrieval(report: dsl.Input[dsl.Artifact], training: dsl.Input[dsl.Artifact],
                               rankings: dsl.Input[dsl.Artifact], evaluation: dsl.Output[dsl.Artifact]):
            return dsl.ContainerSpec(image=args.image,
                command=["python", "-m", "cloud.retrieval_evaluation"],
                args=["--source", report.uri, "--training", training.uri, "--rankings", rankings.uri,
                      "--output", evaluation.uri, "--image-uri", args.image,
                      "--retrieval-image", args.finetuned_retrieval_image,
                      "--trainer-image", args.trainer_image,
                      "--trainer-batch-size", str(args.trainer_batch_size),
                      "--expected-pairs", json.dumps(expected_pairs, sort_keys=True),
                      "--benchmark-sha256", evaluation_benchmark["catalog_sha256"]])

    @dsl.container_component
    def evaluate_eligibility(report: dsl.Input[dsl.Artifact], evaluation: dsl.Output[dsl.Artifact]):
        return dsl.ContainerSpec(image=args.image, command=["python", "-m", "cloud.eligibility"],
            args=["--source", report.uri, "--output", evaluation.uri,
                  "--image-uri", args.image, "--model", eligibility_model])

    @dsl.pipeline(name="trialmatch-data-pipeline")
    def pipeline(release: str):
        raw = fetch_raw(release=release).set_cpu_limit("1").set_memory_limit("2Gi")
        processed = process_trials(raw=raw.outputs["raw"]).set_cpu_limit("1").set_memory_limit("2Gi")
        checked = validate_data(processed=processed.outputs["processed"]).set_cpu_limit("1").set_memory_limit("2Gi")
        retrieve_trials(report=checked.outputs["report"]).set_cpu_limit("1").set_memory_limit(
            "2Gi"
        ).set_env_variable("GCP_PROJECT", args.project).set_env_variable("GCP_LOCATION", "global")
        if train_encoder is not None:
            trained_task = (train_encoder(report=checked.outputs["report"]).set_cpu_limit("4")
                            .set_memory_limit("15Gi").set_accelerator_type("NVIDIA_TESLA_T4")
                            .set_accelerator_limit(1))
            if args.finetuned_retrieval_image:
                ranked_task = (retrieve_finetuned(report=checked.outputs["report"],
                                                  training=trained_task.outputs["training"])
                               .set_cpu_limit("4").set_memory_limit("16Gi")
                               .set_env_variable("GCP_PROJECT", args.project))
                if args.retrieval_evaluation:
                    (evaluate_retrieval(report=checked.outputs["report"], training=trained_task.outputs["training"],
                                        rankings=ranked_task.outputs["rankings"])
                     .set_cpu_limit("1").set_memory_limit("2Gi"))
        if args.eligibility:
            (evaluate_eligibility(report=checked.outputs["report"]).set_cpu_limit("1")
             .set_memory_limit("2Gi").set_env_variable("GCP_PROJECT", args.project)
             .set_env_variable("GCP_LOCATION", "global"))

    build_target = None
    if args.release_target:
        build_target = read_target(args.release_target)
        if (build_target["workflow_image"] != args.image
                or build_target["release_uri"] != args.release):
            raise ValueError("Pipeline image/release does not match the selected build")
    compiler.Compiler().compile(pipeline, package_path=str(target))
    if args.compile_only:
        return
    if build_target is not None:
        verify_input_manifest(json.loads(blob(args.release).download_as_text()), build_target)
    aiplatform.init(project=args.project, location=args.region)
    job = aiplatform.PipelineJob(
        display_name="trialmatch-data-pipeline", template_path=str(target),
        pipeline_root=f"gs://{args.bucket}/pipelines", parameter_values={"release": args.release},
        enable_caching=False,
    )
    job.submit(service_account=f"trialmatch-pipeline@{args.project}.iam.gserviceaccount.com")
    (target.parent / "pipeline_job.txt").write_text(job.resource_name + "\n")
    print(job.resource_name)
    job.wait()
    if job.state.name != "PIPELINE_STATE_SUCCEEDED":
        raise RuntimeError(f"Pipeline did not succeed: {job.state.name}")
    validation = next(task for task in job.task_details if task.task_name == "validate-data")
    report_uri = validation.outputs["report"].artifacts[0].uri + "/validation.json"
    report = json.loads(blob(report_uri).download_as_text())
    if report["status"] != "PASSED":
        raise RuntimeError("Data validation did not pass")
    processed = next(task for task in job.task_details if task.task_name == "process-trials")
    expected_release = processed.outputs["processed"].artifacts[0].uri + "/release.json"
    if report.get("release_uri") != expected_release:
        raise RuntimeError("Validation report release does not match this pipeline's output")
    manifest = None
    if args.trainer_image:
        trained = next(task for task in job.task_details if task.task_name == "train-encoder")
        training_uri = trained.outputs["training"].artifacts[0].uri.rstrip("/")
        manifest_uri = training_uri + "/training_manifest.json"
        training_bytes = blob(manifest_uri).download_as_text().encode("utf-8")
        manifest = json.loads(training_bytes)
        verify_training_manifest(
            manifest, expected_release, training_uri, args.trainer_image, args.trainer_batch_size,
            expected_pairs,
        )
    retrieval_manifest = None
    if args.finetuned_retrieval_image:
        retrieved = next(task for task in job.task_details if task.task_name == "retrieve-finetuned")
        ranking_uri = retrieved.outputs["rankings"].artifacts[0].uri.rstrip("/")
        retrieval_manifest_bytes = blob(f"{ranking_uri}/{finetuned_retrieval.MANIFEST}").download_as_bytes()
        retrieval_manifest = json.loads(retrieval_manifest_bytes)
        contract = finetuned_retrieval.benchmark_contract(expected_release)
        expected = finetuned_retrieval.expected_manifest(
            report_uri, report, training_uri, training_bytes, args.finetuned_retrieval_image, contract,
        )
        ranking_payloads = finetuned_retrieval.read_verified_results(retrieval_manifest, expected, ranking_uri)
    scoring_manifest = None
    if args.retrieval_evaluation:
        scored = next(task for task in job.task_details if task.task_name == "evaluate-retrieval")
        scoring_uri = scored.outputs["evaluation"].artifacts[0].uri.rstrip("/")
        scoring_manifest = json.loads(blob(f"{scoring_uri}/{retrieval_evaluation.MANIFEST}").download_as_bytes())
        expected_scoring = retrieval_evaluation.expected_manifest(
            expected, ranking_uri, retrieval_manifest_bytes, args.image, evaluation_benchmark,
        )
        expected_metrics = retrieval_evaluation.score_outputs(ranking_payloads, expected, evaluation_labels)
        retrieval_evaluation.read_verified_results(scoring_manifest, expected_scoring, scoring_uri, expected_metrics)
    evaluation_manifest = None
    if args.eligibility:
        evaluated = next(task for task in job.task_details if task.task_name == "evaluate-eligibility")
        evaluation_uri = evaluated.outputs["evaluation"].artifacts[0].uri.rstrip("/")
        evaluation_manifest = json.loads(blob(evaluation_uri + "/eligibility_manifest.json").download_as_text())
        verify_manifest(evaluation_manifest, expected_release, report_uri, evaluation_uri,
                        args.image, eligibility_model, report["source_sha256"])
        read_verified_results(evaluation_manifest)
    if build_target is not None and read_target(args.release_target) != build_target:
        raise RuntimeError("Selected build changed while the pipeline was running; rerun pipeline")
    # All enabled cloud output checks precede local publication of success markers.
    if scoring_manifest is not None:
        (target.parent / retrieval_evaluation.MANIFEST).write_text(json.dumps(scoring_manifest, indent=2) + "\n")
    if retrieval_manifest is not None:
        (target.parent / finetuned_retrieval.MANIFEST).write_text(json.dumps(retrieval_manifest, indent=2) + "\n")
    if evaluation_manifest is not None:
        (target.parent / "eligibility_manifest.json").write_text(json.dumps(evaluation_manifest, indent=2) + "\n")
    if manifest is not None:
        (target.parent / "training_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (target.parent / "validation.json").write_text(json.dumps(report, indent=2) + "\n")
    (target.parent / "validated_release.txt").write_text(report["release_uri"] + "\n")
    if build_target is not None:
        # Freeze the build chosen at submission; never attach a later build to this run.
        save_target(target.parent / "validated_deployment.json", {
            "schema_version": 1, "status": "PASSED", "build_target": build_target,
            "project": args.project, "region": args.region,
            "pipeline_job": job.resource_name, "validated_release_uri": expected_release,
        })
    print(f"Validated release: {report['release_uri']}")
    if manifest is not None:
        print(f"Training manifest: {manifest_uri}")
    if evaluation_manifest is not None:
        print(f"Eligibility manifest: {evaluation_uri}/eligibility_manifest.json")
    if scoring_manifest is not None:
        print(f"Retrieval evaluation manifest: {scoring_uri}/{retrieval_evaluation.MANIFEST}")


if __name__ == "__main__":
    main()
