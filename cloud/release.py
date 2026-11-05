"""Bind publication, pipeline validation and deployment to one cloud build."""

import argparse
import hashlib
import json
import re
import tempfile
from pathlib import Path

FILES = [
    "services/trial_ingestion/data/raw.dvc",
    "services/trial_ingestion/data/raw_metadata.json",
    "services/trial_ingestion/data/processed/trials.jsonl",
    "services/trial_ingestion/data/processed/criteria.jsonl",
    "services/patient_processing/data/processed/batch25_patients.jsonl",
    "services/rag_workflow/examples/demo_manifest.json",
    "services/rag_workflow/index_snapshots/current.json",
]


def input_hashes(root):
    hashes = {}
    for name in FILES:
        try:
            with (root / name).open("rb") as stream:
                hashes[name] = hashlib.file_digest(stream, "sha256").hexdigest()
        except OSError as error:
            raise ValueError(f"Cannot read publication input: {name}; restore the fixed data") from error
    return hashes


def data_fingerprint(hashes):
    if not isinstance(hashes, dict) or set(hashes) != set(FILES):
        raise ValueError("Input hash record must contain all seven publication files")
    for name, value in hashes.items():
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError(f"Invalid input SHA256: {name}")
    encoded = json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def check_input_hashes(actual, expected):
    data_fingerprint(expected)
    data_fingerprint(actual)
    changed = [name for name in FILES if actual[name] != expected[name]]
    if changed:
        raise ValueError("Publication inputs changed since build: " + ", ".join(changed)
                         + "; restore the original data or rebuild")


def verify_input_manifest(manifest, target):
    """Check the cloud input before submitting a job bound to a build record."""
    try:
        actual = {name: item["sha256"] for name, item in manifest["files"].items()}
        if manifest["schema_version"] != 1 or manifest["image"] != target["workflow_image"]:
            raise ValueError("Published release schema/image does not match the build")
    except (KeyError, AttributeError, TypeError) as error:
        raise ValueError("Invalid published release manifest") from error
    check_input_hashes(actual, target["input_sha256"])


def image_tag(version, build_id):
    if not isinstance(build_id, str) or not re.fullmatch(r"[A-Za-z0-9-]+", build_id):
        raise ValueError("Expected a Cloud Build ID")
    return f"{version}-{build_id}"


def release_target(version, registry, bucket, digest, api_digest, build_id, hashes):
    for name, value in (("workflow", digest), ("API", api_digest)):
        if not isinstance(value, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
            raise ValueError(f"Expected a complete {name} image SHA256 digest")
    tag = image_tag(version, build_id)
    fingerprint = data_fingerprint(hashes)
    return {
        "schema_version": 4,
        "build_id": build_id,
        "source_version": version,
        "image_tag": tag,
        "workflow_image": f"{registry}/workflow@{digest}",
        "api_image": f"{registry}/api@{api_digest}",
        "input_sha256": dict(hashes),
        "data_fingerprint": fingerprint,
        "release_uri": f"gs://{bucket}/releases/{version}/{digest[7:]}/{fingerprint}/release.json",
    }


def target_from_build(build, version, registry, bucket, hashes):
    if build.get("status") != "SUCCESS":
        raise ValueError("Cloud Build must succeed before selecting a release")
    tag_suffix = image_tag(version, build.get("id"))
    digests = {}
    for name in ("workflow", "api"):
        tag = f"{registry}/{name}:{tag_suffix}"
        images = [item for item in build.get("results", {}).get("images", []) if item["name"] == tag]
        if len(images) != 1:
            raise ValueError(f"Cloud Build must return exactly one matching {name} image")
        digests[name] = images[0].get("digest")
    return release_target(
        version, registry, bucket, digests["workflow"], digests["api"], build.get("id"), hashes,
    )


def read_target(path):
    if not path.is_file():
        raise ValueError("Missing release target; run bash cloud/deploy.sh build first")
    target = json.loads(path.read_text())
    if not isinstance(target, dict) or target.get("schema_version") != 4:
        raise ValueError("Release target requires schema 4 with a build-specific tag; run bash cloud/deploy.sh build again")
    try:
        registry, digest = target["workflow_image"].split("/workflow@")
        bucket = target["release_uri"].split("/")[2]
        expected = release_target(
            target["source_version"], registry, bucket, digest,
            target["api_image"].partition("@")[2], target["build_id"], target["input_sha256"],
        )
    except (KeyError, IndexError, AttributeError, TypeError) as error:
        raise ValueError("Invalid release target; rebuild") from error
    if target != expected:
        raise ValueError("Inconsistent release target; rebuild")
    return target


def load_target(path, version, registry, bucket):
    target = read_target(path)
    expected = release_target(
        version, registry, bucket, target["workflow_image"].partition("@")[2],
        target["api_image"].partition("@")[2], target["build_id"], target["input_sha256"],
    )
    if target != expected:
        raise ValueError("Release target does not match the current version/registry/bucket; rebuild")
    return target


def load_deployment(path, target, project, region):
    if not path.is_file():
        raise ValueError("No validated deployment; run bash cloud/deploy.sh pipeline first")
    record = json.loads(path.read_text())
    if (
        not isinstance(record, dict)
        or record.get("schema_version") != 1
        or record.get("status") != "PASSED"
        or record.get("build_target") != target
        or record.get("project") != project
        or record.get("region") != region
    ):
        raise ValueError("Deployment validation does not match this build/environment; rerun pipeline")
    job = record.get("pipeline_job")
    output = record.get("validated_release_uri")
    if (
        not isinstance(job, str)
        or not re.fullmatch(r"projects/[^/\s]+/locations/" + re.escape(region) + r"/pipelineJobs/[^/\s]+", job)
        or not isinstance(output, str)
        or not re.fullmatch(r"gs://[^/\s]+/\S+/release\.json", output)
    ):
        raise ValueError("Deployment validation lacks a valid pipeline job/output release; rerun pipeline")
    return record


def save_target(path, target):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(json.dumps(target, indent=2) + "\n")
            stream.close()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["capture-inputs", "record", "resolve", "image-tag", "deployment"])
    parser.add_argument("--version")
    parser.add_argument("--registry")
    parser.add_argument("--bucket")
    parser.add_argument("--input-manifest", type=Path)
    parser.add_argument("--build-result", type=Path)
    parser.add_argument("--record", type=Path, default=Path("artifacts/cloud/release_target.json"))
    parser.add_argument("--deployment-record", type=Path,
                        default=Path("artifacts/cloud/validated_deployment.json"))
    parser.add_argument("--project")
    parser.add_argument("--region")
    args = parser.parse_args()
    if args.action == "capture-inputs":
        if args.input_manifest is None:
            parser.error("capture-inputs requires --input-manifest")
        save_target(args.input_manifest, input_hashes(Path.cwd()))
        return
    if not args.version or not args.registry or not args.bucket:
        parser.error("record/resolve/image-tag/deployment require --version, --registry and --bucket")
    if args.action == "record":
        if args.build_result is None or args.input_manifest is None:
            parser.error("record requires --build-result and --input-manifest")
        hashes = json.loads(args.input_manifest.read_text())
        check_input_hashes(input_hashes(Path.cwd()), hashes)
        target = target_from_build(
            json.loads(args.build_result.read_text()), args.version, args.registry, args.bucket, hashes,
        )
        save_target(args.record, target)
    else:
        target = load_target(args.record, args.version, args.registry, args.bucket)
        if args.action == "image-tag":
            print(target["image_tag"])
        elif args.action == "deployment":
            if not args.project or not args.region:
                parser.error("deployment requires --project and --region")
            record = load_deployment(args.deployment_record, target, args.project, args.region)
            print(target["api_image"] + "\t" + record["validated_release_uri"])
        else:
            print(target["workflow_image"] + "\t" + target["release_uri"])


if __name__ == "__main__":
    main()
