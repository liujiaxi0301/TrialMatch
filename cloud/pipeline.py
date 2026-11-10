"""Run data reproduction, validation and Gemini retrieval on Vertex AI Pipelines."""

import argparse
import json
from pathlib import Path

from google.cloud import aiplatform
from kfp import compiler, dsl

from cloud.release import read_target, save_target, verify_input_manifest
from cloud.tasks import blob


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
    args = parser.parse_args()

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

    @dsl.pipeline(name="trialmatch-data-pipeline")
    def pipeline(release: str):
        raw = fetch_raw(release=release).set_cpu_limit("1").set_memory_limit("2Gi")
        processed = process_trials(raw=raw.outputs["raw"]).set_cpu_limit("1").set_memory_limit("2Gi")
        checked = validate_data(processed=processed.outputs["processed"]).set_cpu_limit("1").set_memory_limit("2Gi")
        retrieve_trials(report=checked.outputs["report"]).set_cpu_limit("1").set_memory_limit(
            "2Gi"
        ).set_env_variable("GCP_PROJECT", args.project).set_env_variable("GCP_LOCATION", "global")

    target = Path("artifacts/cloud/pipeline.yaml")
    target.parent.mkdir(parents=True, exist_ok=True)
    if not args.compile_only:
        # These files describe the current submission. A failed rerun must not
        # leave an older release available for cloud/deploy.sh app to consume.
        for name in ("pipeline_job.txt", "validation.json", "validated_release.txt",
                     "validated_deployment.json"):
            (target.parent / name).unlink(missing_ok=True)
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
    if build_target is not None and read_target(args.release_target) != build_target:
        raise RuntimeError("Selected build changed while the pipeline was running; rerun pipeline")
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


if __name__ == "__main__":
    main()
