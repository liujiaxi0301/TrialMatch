"""Compile and submit the three existing data steps to Vertex AI Pipelines."""

import argparse
import json
from pathlib import Path

from google.cloud import aiplatform
from kfp import compiler, dsl

from cloud.tasks import blob


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--region", default="us-east1")
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--image", required=True, help="Versioned workflow image URI")
    parser.add_argument("--release", required=True)
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

    @dsl.pipeline(name="trialmatch-data-pipeline")
    def pipeline(release: str):
        raw = fetch_raw(release=release).set_cpu_limit("1").set_memory_limit("2Gi")
        processed = process_trials(raw=raw.outputs["raw"]).set_cpu_limit("1").set_memory_limit("2Gi")
        validate_data(processed=processed.outputs["processed"]).set_cpu_limit("1").set_memory_limit("2Gi")

    target = Path("artifacts/cloud/pipeline.yaml")
    target.parent.mkdir(parents=True, exist_ok=True)
    compiler.Compiler().compile(pipeline, package_path=str(target))
    if args.compile_only:
        return
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
    (target.parent / "validation.json").write_text(json.dumps(report, indent=2) + "\n")
    (target.parent / "validated_release.txt").write_text(report["release_uri"] + "\n")
    print(f"Validated release: {report['release_uri']}")


if __name__ == "__main__":
    main()
