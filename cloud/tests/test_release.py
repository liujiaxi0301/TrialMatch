"""Release identity and the real deployment script, with cloud commands simulated."""

import copy
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import chdir, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cloud import pipeline, release, tasks

VERSION = "0123456789abcdef"
REGISTRY = "example.test/project/images"
BUCKET = "trialmatch-test"
DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
API_DIGEST = "sha256:" + "d" * 64
HASHES = dict.fromkeys(release.FILES, "c" * 64)
ROOT = Path(__file__).resolve().parents[2]


def build_result(digest=DIGEST_A, build_id="build-A"):
    return {
        "id": build_id,
        "status": "SUCCESS",
        "results": {"images": [
            {"name": f"{REGISTRY}/workflow:{VERSION}-{build_id}", "digest": digest},
            {"name": f"{REGISTRY}/api:{VERSION}-{build_id}", "digest": API_DIGEST},
        ]},
    }


class MemoryBlob:
    def __init__(self, objects, uri):
        self.objects, self.uri = objects, uri

    def exists(self):
        return self.uri in self.objects

    def download_as_bytes(self):
        return self.objects[self.uri]

    def download_as_text(self):
        return self.download_as_bytes().decode()

    def upload_from_filename(self, path, if_generation_match):
        self.upload_from_string(Path(path).read_bytes(), if_generation_match)

    def upload_from_string(self, value, if_generation_match):
        if if_generation_match != 0 or self.exists():
            raise AssertionError("Publication attempted to overwrite an immutable object")
        self.objects[self.uri] = value.encode() if isinstance(value, str) else value


class ReleaseIdentityTests(unittest.TestCase):
    def test_rebuild_and_republish_preserve_existing_releases(self):
        first = release.target_from_build(build_result(), VERSION, REGISTRY, BUCKET, HASHES)
        second = release.target_from_build(
            build_result(DIGEST_B, build_id="build-B"), VERSION, REGISTRY, BUCKET, HASHES,
        )
        objects = {}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data.json").write_text('{"data":"fixed"}\n')
            with (
                patch.object(tasks, "ROOT", root),
                patch.object(tasks, "FILES", ["data.json"]),
                patch.object(tasks, "blob", side_effect=lambda uri: MemoryBlob(objects, uri)),
                redirect_stdout(io.StringIO()),
            ):
                prefix_a = first["release_uri"].removesuffix("/release.json")
                prefix_b = second["release_uri"].removesuffix("/release.json")
                tasks.publish(prefix_a, first["workflow_image"])
                old_objects = objects.copy()
                # Reproduce the original defect: a new digest in the old directory conflicts.
                with self.assertRaisesRegex(ValueError, "manifest already exists"):
                    tasks.publish(prefix_a, second["workflow_image"])
                tasks.publish(prefix_b, second["workflow_image"])
                after_publish = objects.copy()
                tasks.publish(prefix_b, second["workflow_image"])
                self.assertNotEqual(prefix_a, prefix_b)
                self.assertEqual(objects, after_publish)
                self.assertEqual({uri: objects[uri] for uri in old_objects}, old_objects)
                self.assertEqual(
                    json.loads(objects[second["release_uri"]])["image"], second["workflow_image"],
                )
                (root / "data.json").write_text('{"data":"changed"}\n')
                with self.assertRaisesRegex(ValueError, "different content"):
                    tasks.publish(prefix_b, second["workflow_image"])
                self.assertEqual(objects, after_publish)

    def test_build_requires_success_and_exact_workflow_digest(self):
        cases = [
            {"status": "FAILURE"},
            {"status": "SUCCESS", "results": {"images": []}},
            build_result(None), build_result("sha256:abc"), build_result("latest"),
        ]
        wrong_image = build_result()
        wrong_image["results"]["images"][0]["name"] = f"{REGISTRY}/api:{VERSION}"
        cases.append(wrong_image)
        duplicate = build_result()
        duplicate["results"]["images"] *= 2
        cases.append(duplicate)
        missing_id = build_result()
        del missing_id["id"]
        cases.append(missing_id)
        missing_api = build_result()
        missing_api["results"]["images"].pop()
        cases.append(missing_api)
        invalid_api = build_result()
        invalid_api["results"]["images"][1]["digest"] = "latest"
        cases.append(invalid_api)
        for image_index in (0, 1):
            for suffix in (VERSION, f"{VERSION}-other-build"):
                wrong_tag = build_result()
                image = wrong_tag["results"]["images"][image_index]
                image["name"] = image["name"].rsplit(":", 1)[0] + ":" + suffix
                cases.append(wrong_tag)
        for result in cases:
            with self.subTest(result=result), self.assertRaises(ValueError):
                release.target_from_build(result, VERSION, REGISTRY, BUCKET, HASHES)

    def test_saved_target_rejects_changed_configuration_or_content(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "release_target.json"
            target = release.target_from_build(build_result(), VERSION, REGISTRY, BUCKET, HASHES)
            release.save_target(path, target)
            self.assertEqual(release.load_target(path, VERSION, REGISTRY, BUCKET), target)
            for version, registry, bucket in (
                ("another-version", REGISTRY, BUCKET),
                (VERSION, "another/registry", BUCKET),
                (VERSION, REGISTRY, "another-bucket"),
            ):
                with (
                    self.subTest(version=version, registry=registry, bucket=bucket),
                    self.assertRaises(ValueError),
                ):
                    release.load_target(path, version, registry, bucket)
            for key, value in (
                ("workflow_image", f"{REGISTRY}/workflow:{VERSION}"),
                ("release_uri", "gs://old-release/release.json"),
                ("schema_version", 1),
                ("schema_version", 2),
                ("schema_version", 3),
                ("image_tag", VERSION),
                ("image_tag", f"{VERSION}-other-build"),
                ("data_fingerprint", "f" * 64),
                ("input_sha256", {}),
            ):
                changed = copy.deepcopy(target)
                changed[key] = value
                path.write_text(json.dumps(changed))
                with self.subTest(key=key), self.assertRaises(ValueError):
                    release.load_target(path, VERSION, REGISTRY, BUCKET)


class DeployReleaseTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name) / "checkout"
        (self.root / "cloud").mkdir(parents=True)
        for name in ("deploy.sh", "release.py", "build.yaml", "__init__.py"):
            shutil.copy2(ROOT / "cloud" / name, self.root / "cloud" / name)
        (self.root / ".gitignore").write_text("artifacts/\n__pycache__/\n" + release.FILES[-1] + "\n")
        for name in release.FILES:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(name + "\n")
        (self.root / "cloud/config.env").write_text(
            f"GCP_PROJECT=test-project\nGCP_REGION=us-east1\nGCS_BUCKET={BUCKET}\n"
            f"REGISTRY={REGISTRY}\nSERVICE=test-api\nNETWORK=test-net\nSUBNET=test-subnet\n"
            "CHROMA_IP=10.0.0.2\nGCP_ZONE=us-east1-b\nDATABASE=test-chroma\n"
        )
        subprocess.run(["git", "init", "-q", str(self.root)], check=True, capture_output=True)
        binaries = Path(directory.name) / "bin"
        binaries.mkdir()
        (binaries / "python3").symlink_to(sys.executable)
        self.log = Path(directory.name) / "calls.jsonl"
        self.registry_state = Path(directory.name) / "registry.json"
        fake = f"#!{sys.executable}\n" + '''import json, os, sys, uuid
from pathlib import Path
import yaml
args = sys.argv[1:]
name = Path(sys.argv[0]).name
with open(os.environ["FAKE_CALL_LOG"], "a") as log:
    log.write(json.dumps({"tool": name, "args": args}) + "\\n")
if name == "gcloud":
    if args[:2] == ["run", "deploy"]:
        sys.exit(0)
    if args[:3] == ["compute", "disks", "describe"]:
        sys.exit(0)
    if args[:3] == ["compute", "instances", "describe"]:
        sys.exit(0 if os.environ.get("FAKE_DATABASE_EXISTS") else 1)
    if args[:3] == ["compute", "instances", "create"]:
        tag = next(arg.removeprefix("--metadata=chroma-image=") for arg in args
                   if arg.startswith("--metadata=chroma-image="))
        assert tag in json.loads(Path(os.environ["FAKE_REGISTRY_STATE"]).read_text()), tag
        sys.exit(0)
    assert args[:2] == ["builds", "submit"], args
    assert "--format=json" in args and "--suppress-logs" in args, args
    if os.environ.get("FAKE_BUILD_FAIL"):
        sys.exit(7)
    substitutions = next(arg.split("=", 1)[1] for arg in args if arg.startswith("--substitutions="))
    values = dict(item.split("=", 1) for item in substitutions.split(","))
    build_id = os.environ.get("FAKE_BUILD_ID", str(uuid.uuid4()))
    values["BUILD_ID"] = build_id
    config_path = next(arg.split("=", 1)[1] for arg in args if arg.startswith("--config="))
    config = yaml.safe_load(Path(config_path).read_text())
    def expand(value):
        for key, replacement in values.items():
            value = value.replace("${" + key + "}", replacement)
        assert "${" not in value, value
        return value
    built = [expand(step["args"][step["args"].index("-t") + 1]) for step in config["steps"]]
    images = [expand(image) for image in config["images"]]
    assert set(built) == set(images), (built, images)
    digests = {"workflow": os.environ["FAKE_DIGEST"], "api": os.environ["FAKE_API_DIGEST"],
               "chroma": os.environ.get("FAKE_CHROMA_DIGEST", "sha256:" + "e" * 64)}
    results = [{"name": image, "digest": digests[image.rsplit("/", 1)[1].split(":")[0]]}
               for image in images]
    state_path = Path(os.environ["FAKE_REGISTRY_STATE"])
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    for item in results:
        if item["name"] in state and state[item["name"]] != item["digest"]:
            print("immutable tag already points to another digest", file=sys.stderr)
            sys.exit(9)
    state.update({item["name"]: item["digest"] for item in results})
    state_path.write_text(json.dumps(state))
    if os.environ.get("FAKE_CHANGE_INPUT"):
        Path(os.environ["FAKE_CHANGE_INPUT"]).write_text("changed during cloud build")
    print(json.dumps({"id": build_id, "status": "SUCCESS", "results": {"images": results}}))
'''
        for name in ("gcloud", "uv"):
            executable = binaries / name
            executable.write_text(fake)
            executable.chmod(0o755)
        self.env = dict(
            os.environ, PATH=f"{binaries}:{os.environ['PATH']}",
            FAKE_CALL_LOG=str(self.log), FAKE_DIGEST=DIGEST_A,
            FAKE_API_DIGEST=API_DIGEST, FAKE_REGISTRY_STATE=str(self.registry_state),
        )
        self.artifacts = self.root / "artifacts/cloud"

    def run_action(self, action, success=True):
        result = subprocess.run(
            ["bash", "cloud/deploy.sh", action], cwd=self.root, env=self.env,
            text=True, capture_output=True, check=False,
        )
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def validate_current_build(self):
        """Run the real compiler/record writer; simulate only Vertex and GCS responses."""
        target = json.loads((self.artifacts / "release_target.json").read_text())
        output = f"gs://{BUCKET}/pipelines/test-run/processed"
        report = {"status": "PASSED", "release_uri": output + "/release.json"}
        with (
            chdir(self.root), redirect_stdout(io.StringIO()),
            patch.object(pipeline.aiplatform, "init"),
            patch.object(pipeline.aiplatform, "PipelineJob") as job_class,
            patch.object(pipeline, "blob") as blob,
            patch("sys.argv", [
                "pipeline", "--project=test-project", "--region=us-east1",
                f"--bucket={BUCKET}", "--image=" + target["workflow_image"],
                "--release=" + target["release_uri"],
                "--release-target=artifacts/cloud/release_target.json",
            ]),
        ):
            job = job_class.return_value
            job.resource_name = "projects/test-project/locations/us-east1/pipelineJobs/current"
            job.state = SimpleNamespace(name="PIPELINE_STATE_SUCCEEDED")
            job.task_details = [
                SimpleNamespace(task_name=name, outputs={key: SimpleNamespace(
                    artifacts=[SimpleNamespace(uri=uri)],
                )})
                for name, key, uri in (
                    ("process-trials", "processed", output),
                    ("validate-data", "report", f"gs://{BUCKET}/pipelines/test-run/report"),
                )
            ]
            blob.return_value.download_as_text.return_value = json.dumps(report)
            input_manifest = {
                "schema_version": 1, "image": target["workflow_image"],
                "files": {name: {"sha256": sha} for name, sha in target["input_sha256"].items()},
            }
            input_blob = SimpleNamespace(download_as_text=lambda: json.dumps(input_manifest))
            blob.side_effect = lambda uri: input_blob if uri == target["release_uri"] else blob.return_value
            pipeline.main()
        return json.loads((self.artifacts / "validated_deployment.json").read_text())

    def test_rebuild_uses_unique_tags_in_immutable_registry_and_pins_consumers(self):
        targets = []
        old_registry = {}
        for build_id, digest in (("build-A", DIGEST_A), ("build-B", DIGEST_B)):
            self.env["FAKE_BUILD_ID"] = build_id
            self.env["FAKE_DIGEST"] = digest
            self.env["FAKE_API_DIGEST"] = digest
            self.env["FAKE_CHROMA_DIGEST"] = digest
            self.run_action("build")
            target = json.loads((self.artifacts / "release_target.json").read_text())
            targets.append(target)
            self.assertEqual(target["image_tag"], target["source_version"] + "-" + build_id)
            self.assertEqual(target["workflow_image"], f"{REGISTRY}/workflow@{digest}")
            registry = json.loads(self.registry_state.read_text())
            for name in ("api", "workflow", "chroma"):
                self.assertEqual(registry[f"{REGISTRY}/{name}:" + target["image_tag"]], digest)
            self.assertEqual({name: registry[name] for name in old_registry}, old_registry)
            old_registry = registry
            # A later registry result must not replace the recorded digest.
            self.env["FAKE_DIGEST"] = "sha256:" + "c" * 64
            self.run_action("publish")
            self.run_action("pipeline")
            publish, pipeline = self.calls()[-2:]
            for call in (publish, pipeline):
                self.assertEqual(call["tool"], "uv")
                self.assertIn("--image=" + target["workflow_image"], call["args"])
            self.assertIn(
                "--output=" + target["release_uri"].removesuffix("/release.json"), publish["args"],
            )
            self.assertIn("--release=" + target["release_uri"], pipeline["args"])
            self.assertIn("--release-target=artifacts/cloud/release_target.json", publish["args"])
        self.assertEqual(targets[0]["source_version"], targets[1]["source_version"])
        self.assertNotEqual(targets[0]["image_tag"], targets[1]["image_tag"])
        self.assertNotEqual(targets[0]["release_uri"], targets[1]["release_uri"])
        self.assertEqual(len(old_registry), 6)
        self.assertEqual(sum(c["tool"] == "gcloud" for c in self.calls()), 2)

    def test_failed_or_unusable_build_cannot_reuse_previous_selection(self):
        for failure in ("command", "digest"):
            with self.subTest(failure=failure):
                self.env.pop("FAKE_BUILD_FAIL", None)
                self.env["FAKE_DIGEST"] = DIGEST_A
                self.run_action("build")
                self.validate_current_build()
                if failure == "command":
                    self.env["FAKE_BUILD_FAIL"] = "1"
                else:
                    self.env["FAKE_DIGEST"] = "invalid"
                self.run_action("build", success=False)
                self.assertFalse((self.artifacts / "image_version.txt").exists())
                self.assertFalse((self.artifacts / "release_target.json").exists())
                self.assertFalse((self.artifacts / "validated_deployment.json").exists())
                self.assertEqual(list(self.artifacts.glob("build-result.*")), [])
                self.run_action("publish", success=False)
                self.run_action("pipeline", success=False)
                self.run_action("app", success=False)
        self.assertTrue(all(call["tool"] == "gcloud" for call in self.calls()))

    def test_missing_or_stale_target_blocks_publication_and_submission(self):
        self.run_action("build")
        path = self.artifacts / "release_target.json"
        target = json.loads(path.read_text())
        for invalid in (None, dict(target, source_version="older-version")):
            with self.subTest(target=invalid):
                if invalid is None:
                    path.unlink()
                else:
                    path.write_text(json.dumps(invalid))
                for action in ("publish", "pipeline", "database"):
                    self.run_action(action, success=False)
        self.assertEqual(len(self.calls()), 1)

    def test_app_uses_validated_api_digest_and_output_release(self):
        self.run_action("build")
        record = self.validate_current_build()
        # Legacy marker/tag changes must not control deployment after validation.
        (self.artifacts / "validated_release.txt").write_text("gs://old/release.json\n")
        self.env["FAKE_API_DIGEST"] = DIGEST_B
        self.run_action("app")
        call = self.calls()[-1]
        self.assertEqual(call["args"][:2], ["run", "deploy"])
        self.assertIn("--image=" + record["build_target"]["api_image"], call["args"])
        environment = next(arg for arg in call["args"] if arg.startswith("--set-env-vars="))
        self.assertIn("RELEASE_URI=" + record["validated_release_uri"] + ",", environment)
        self.assertNotIn("gs://old/release.json", environment)

    def test_rebuild_blocks_old_validation_even_with_same_source_version(self):
        self.run_action("build")
        old_record = self.validate_current_build()
        self.env.update(FAKE_BUILD_ID="build-B", FAKE_API_DIGEST=DIGEST_B)
        self.run_action("build")
        target = json.loads((self.artifacts / "release_target.json").read_text())
        self.assertEqual(target["source_version"], old_record["build_target"]["source_version"])
        self.assertEqual(target["workflow_image"], old_record["build_target"]["workflow_image"])
        path = self.artifacts / "validated_deployment.json"
        self.assertFalse(path.exists())
        self.assertFalse((self.artifacts / "validated_release.txt").exists())
        before = self.calls()
        self.run_action("app", success=False)
        # Even restoring an old success record cannot authorize the rebuilt API.
        path.write_text(json.dumps(old_record))
        self.run_action("app", success=False)
        self.assertEqual(self.calls(), before)

    def test_pipeline_target_failure_clears_previous_deployment_permission(self):
        self.run_action("build")
        self.validate_current_build()
        target_path = self.artifacts / "release_target.json"
        saved = target_path.read_text()
        target_path.unlink()
        self.run_action("pipeline", success=False)
        self.assertFalse((self.artifacts / "validated_deployment.json").exists())
        target_path.write_text(saved)
        self.run_action("app", success=False)
        self.assertEqual(len(self.calls()), 1)

    def test_app_rejects_incomplete_failed_or_mismatched_validation(self):
        self.run_action("build")
        record = self.validate_current_build()
        path = self.artifacts / "validated_deployment.json"
        invalid_records = [
            None, {}, dict(record, status="FAILED"), dict(record, project="another-project"),
            dict(record, region="us-west1"), dict(record, validated_release_uri=""),
            dict(record, pipeline_job=""),
        ]
        for field, value in (
            ("build_id", "old-build"), ("api_image", f"{REGISTRY}/api@{DIGEST_B}"),
            ("workflow_image", f"{REGISTRY}/workflow@{DIGEST_B}"),
            ("release_uri", "gs://old-input/release.json"),
        ):
            invalid_records.append(dict(record, build_target=dict(record["build_target"], **{field: value})))
        for invalid in invalid_records:
            with self.subTest(record=invalid):
                if invalid is None:
                    path.unlink()
                else:
                    path.write_text(json.dumps(invalid))
                self.run_action("app", success=False)
        self.assertEqual(len(self.calls()), 1)

    def test_missing_build_input_stops_before_cloud_build(self):
        (self.root / release.FILES[-1]).unlink()
        result = self.run_action("build", success=False)
        self.assertIn("current.json", result.stderr)
        self.assertEqual(self.calls(), [])
        self.assertFalse((self.artifacts / "image_version.txt").exists())
        self.assertFalse((self.artifacts / "release_target.json").exists())
        self.assertEqual(list(self.artifacts.glob("build-result.*")), [])

    def test_inputs_changed_during_build_cannot_activate_new_target(self):
        self.run_action("build")
        self.validate_current_build()
        self.env["FAKE_CHANGE_INPUT"] = release.FILES[-1]
        result = self.run_action("build", success=False)
        self.assertIn("current.json", result.stderr)
        self.assertFalse((self.artifacts / "image_version.txt").exists())
        self.assertFalse((self.artifacts / "release_target.json").exists())
        self.assertFalse((self.artifacts / "validated_deployment.json").exists())
        self.assertEqual(list(self.artifacts.glob("build-result.*")), [])
        before = self.calls()
        self.run_action("publish", success=False)
        self.run_action("app", success=False)
        self.assertEqual(self.calls(), before)

    def test_rebuilding_only_ignored_data_selects_a_new_release(self):
        self.run_action("build")
        old = json.loads((self.artifacts / "release_target.json").read_text())
        (self.root / release.FILES[-1]).write_text("new fixed snapshot")
        self.env["FAKE_BUILD_ID"] = "build-B"
        self.run_action("build")
        new = json.loads((self.artifacts / "release_target.json").read_text())
        self.assertEqual(old["source_version"], new["source_version"])
        self.assertEqual(old["workflow_image"], new["workflow_image"])
        self.assertNotEqual(old["data_fingerprint"], new["data_fingerprint"])
        self.assertNotEqual(old["release_uri"], new["release_uri"])
        self.assertEqual(new["input_sha256"], release.input_hashes(self.root))

    def test_database_creation_uses_the_selected_build_tag(self):
        self.run_action("build")
        target = json.loads((self.artifacts / "release_target.json").read_text())
        self.run_action("database")
        call = self.calls()[-1]
        self.assertEqual(call["args"][:3], ["compute", "instances", "create"])
        self.assertIn("--metadata=chroma-image=" + REGISTRY + "/chroma:" + target["image_tag"], call["args"])

    def test_database_does_not_update_an_existing_vm(self):
        self.run_action("build")
        self.env["FAKE_DATABASE_EXISTS"] = "1"
        self.run_action("database")
        self.assertEqual([call["args"][:3] for call in self.calls()[1:]], [
            ["compute", "disks", "describe"], ["compute", "instances", "describe"],
        ])


if __name__ == "__main__":
    unittest.main()
