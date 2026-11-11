"""Run data validation, retrieval, optional training and eligibility on Vertex AI."""

import argparse
import hashlib
import json
import re
from pathlib import Path

from google.cloud import aiplatform
from kfp import compiler, dsl

from cloud.eligibility import DEFAULT_MODEL, read_verified_results, verify_manifest
from cloud.release import read_target, save_target, verify_input_manifest
from cloud.tasks import blob
from cloud.training_inputs import pair_hashes


def verify_training_manifest(manifest, release_uri, output_uri, image, batch_size, expected_pairs=None):
    """Bind training metadata to this run before writing any success markers.

    Checkpoint bytes are verified by the eventual consumer; this validates the
    producer's manifest and the aggregate digest of its per-file checksums.
    """
    expected = {
        "schema_version": 1,
        "workflow_type": "contrastive-encoder-finetune",
        "source_release_uri": release_uri,
        "artifact_uri": output_uri.rstrip("/") + "/model",
        "image_uri": image,
    }
    if not isinstance(manifest, dict) or any(manifest.get(k) != v for k, v in expected.items()):
        raise RuntimeError("Training manifest does not match this run's release, output or image")
    files = manifest.get("artifact_files")
    if (not isinstance(files, dict) or not files
            or any(not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v)
                   for v in files.values())):
        raise RuntimeError("Training manifest has missing or invalid checkpoint checksums")
    digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    if manifest.get("artifact_sha256") != digest:
        raise RuntimeError("Training manifest checkpoint digest does not match its file checksums")
    config = manifest.get("config")
    if not isinstance(config, dict) or config.get("batch_size") != batch_size:
        raise RuntimeError("Training manifest does not match the submitted batch size")
    if expected_pairs is not None:
        sources = manifest.get("pair_files")
        built_uri = f"built-from:{release_uri}"
        if (not isinstance(sources, list) or any(not isinstance(item, dict) for item in sources)
                or len(sources) != len(expected_pairs) + 1
                or {item.get("uri") for item in sources} != set(expected_pairs) | {built_uri}):
            raise RuntimeError("Training manifest does not match the submitted pair sources")
        for item in sources:
            if item["uri"] == built_uri:
                continue
            expected = expected_pairs[item["uri"]]
            if item.get("sha256") != expected or item.get("expected_sha256") != expected:
                raise RuntimeError("Training manifest pair checksums do not match the submitted expectations")


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
                     "validated_deployment.json", "training_manifest.json", "eligibility_manifest.json"):
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
    if args.trainer_batch_size < 1:
        parser.error("--trainer-batch-size must be positive")
    if any(not re.fullmatch(r"gs://[^/\s]+/\S+", uri) for uri in args.train_pairs):
        parser.error("--train-pairs must contain gs:// object URIs accessible to the training task")
    if (args.train_pairs or args.wandb_secret) and not args.trainer_image:
        parser.error("--train-pairs and --wandb-secret require --trainer-image")

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
            (train_encoder(report=checked.outputs["report"]).set_cpu_limit("4")
             .set_memory_limit("15Gi").set_accelerator_type("NVIDIA_TESLA_T4")
             .set_accelerator_limit(1))
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
        manifest = json.loads(blob(manifest_uri).download_as_text())
        verify_training_manifest(
            manifest, expected_release, training_uri, args.trainer_image, args.trainer_batch_size,
            expected_pairs,
        )
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


if __name__ == "__main__":
    main()
