"""Real compilation and simulated Vertex results; no cloud jobs or credentials."""

import io
import json
import tempfile
import unittest
from contextlib import chdir, redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml

from cloud import pipeline, release


class PipelineTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.enterContext(chdir(directory.name))
        self.enterContext(redirect_stdout(io.StringIO()))
        self.init = self.enterContext(patch.object(pipeline.aiplatform, "init"))
        self.job_class = self.enterContext(patch.object(pipeline.aiplatform, "PipelineJob"))
        self.blob = self.enterContext(patch.object(pipeline, "blob"))
        self.output = Path("artifacts/cloud")
        self.argv = [
            "pipeline",
            "--project",
            "trialmatch-test",
            "--region",
            "us-east1",
            "--bucket",
            "trialmatch-test-data",
            "--image",
            "example/workflow:fixed-version",
            "--release",
            "gs://trialmatch-test-data/releases/fixed/release.json",
        ]

    def run_pipeline(self, *extra):
        with patch("sys.argv", self.argv + list(extra)):
            pipeline.main()

    def seed_previous_success(self):
        self.output.mkdir(parents=True, exist_ok=True)
        (self.output / "validated_release.txt").write_text("gs://old/release.json\n")
        (self.output / "validation.json").write_text('{"status":"PASSED"}\n')
        (self.output / "validated_deployment.json").write_text('{"status":"PASSED"}\n')

    def bind_build(self):
        target = release.release_target(
            "0123456789abcdef", "example", "trialmatch-test-data",
            "sha256:" + "a" * 64, "sha256:" + "b" * 64, "build-A",
            dict.fromkeys(release.FILES, "c" * 64),
        )
        path = self.output / "release_target.json"
        release.save_target(path, target)
        self.argv[self.argv.index("--image") + 1] = target["workflow_image"]
        self.argv[self.argv.index("--release") + 1] = target["release_uri"]
        self.argv += ["--release-target", str(path)]
        return target

    def success_job(self):
        def artifact(uri):
            return SimpleNamespace(artifacts=[SimpleNamespace(uri=uri)])

        job = self.job_class.return_value
        job.resource_name = "projects/test/locations/us-east1/pipelineJobs/current"
        job.state = SimpleNamespace(name="PIPELINE_STATE_SUCCEEDED")
        job.task_details = [
            SimpleNamespace(
                task_name="process-trials",
                outputs={"processed": artifact("gs://test-run/processed")},
            ),
            SimpleNamespace(
                task_name="validate-data", outputs={"report": artifact("gs://test-run/report")}
            ),
        ]
        self.blob.return_value.download_as_text.return_value = json.dumps(
            {
                "status": "PASSED",
                "release_uri": "gs://test-run/processed/release.json",
            }
        )
        if "--release-target" in self.argv:
            target = release.read_target(self.output / "release_target.json")
            self.input_manifest = {
                "schema_version": 1, "image": target["workflow_image"],
                "files": {name: {"sha256": sha} for name, sha in target["input_sha256"].items()},
            }
            input_blob = SimpleNamespace(download_as_text=lambda: json.dumps(self.input_manifest))
            self.blob.side_effect = lambda uri: (
                input_blob if uri == target["release_uri"] else self.blob.return_value
            )
        return job

    def test_compile_only_has_data_dependencies_and_no_cloud_calls(self):
        self.seed_previous_success()
        self.run_pipeline("--compile-only")
        spec = yaml.safe_load((self.output / "pipeline.yaml").read_text())
        tasks = spec["root"]["dag"]["tasks"]
        self.assertEqual(set(tasks), {"fetch-raw", "process-trials", "validate-data"})
        self.assertEqual(tasks["process-trials"]["dependentTasks"], ["fetch-raw"])
        self.assertEqual(tasks["validate-data"]["dependentTasks"], ["process-trials"])
        for task in tasks.values():
            self.assertNotEqual(
                task.get("triggerPolicy", {}).get("strategy"), "ALL_UPSTREAM_TASKS_COMPLETED"
            )
        self.assertEqual(
            tasks["validate-data"]["inputs"]["artifacts"]["processed"]["taskOutputArtifact"],
            {"producerTask": "process-trials", "outputArtifactKey": "processed"},
        )
        for executor in spec["deploymentSpec"]["executors"].values():
            self.assertEqual(executor["container"]["image"], "example/workflow:fixed-version")
        self.init.assert_not_called()
        self.job_class.assert_not_called()
        self.blob.assert_not_called()
        self.assertTrue((self.output / "validated_release.txt").exists())
        self.assertTrue((self.output / "validated_deployment.json").exists())

    def test_failed_submission_invalidates_previous_success(self):
        self.seed_previous_success()
        self.job_class.return_value.submit.side_effect = RuntimeError("permission denied")
        with self.assertRaisesRegex(RuntimeError, "permission denied"):
            self.run_pipeline()
        self.assertFalse((self.output / "validated_release.txt").exists())
        self.assertFalse((self.output / "validation.json").exists())
        self.assertFalse((self.output / "validated_deployment.json").exists())

    def test_failed_job_invalidates_previous_success(self):
        self.seed_previous_success()
        job = self.success_job()
        job.state = SimpleNamespace(name="PIPELINE_STATE_FAILED")
        with self.assertRaisesRegex(RuntimeError, "PIPELINE_STATE_FAILED"):
            self.run_pipeline()
        self.assertFalse((self.output / "validated_release.txt").exists())
        self.assertFalse((self.output / "validated_deployment.json").exists())
        self.blob.assert_not_called()

    def test_failed_report_does_not_publish_deployable_release(self):
        self.seed_previous_success()
        self.success_job()
        self.blob.return_value.download_as_text.return_value = '{"status":"FAILED"}'
        with self.assertRaisesRegex(RuntimeError, "validation did not pass"):
            self.run_pipeline()
        self.assertFalse((self.output / "validated_release.txt").exists())
        self.assertFalse((self.output / "validated_deployment.json").exists())

    def test_foreign_report_release_is_rejected(self):
        self.seed_previous_success()
        self.bind_build()
        self.success_job()
        self.blob.return_value.download_as_text.return_value = json.dumps(
            {
                "status": "PASSED",
                "release_uri": "gs://another-run/release.json",
            }
        )
        with self.assertRaisesRegex(RuntimeError, "release"):
            self.run_pipeline()
        self.assertFalse((self.output / "validated_release.txt").exists())
        self.assertFalse((self.output / "validated_deployment.json").exists())

    def test_success_writes_current_release_and_uses_expected_runtime_config(self):
        self.success_job()
        self.run_pipeline()
        self.assertEqual(
            (self.output / "validated_release.txt").read_text(),
            "gs://test-run/processed/release.json\n",
        )
        self.init.assert_called_once_with(project="trialmatch-test", location="us-east1")
        job_kwargs = self.job_class.call_args.kwargs
        self.assertEqual(job_kwargs["pipeline_root"], "gs://trialmatch-test-data/pipelines")
        self.assertFalse(job_kwargs["enable_caching"])
        self.job_class.return_value.submit.assert_called_once_with(
            service_account="trialmatch-pipeline@trialmatch-test.iam.gserviceaccount.com"
        )
        # Direct legacy runs still produce data evidence, but cannot authorize API deployment.
        self.assertFalse((self.output / "validated_deployment.json").exists())

    def test_bound_success_records_the_build_and_verified_output(self):
        target = self.bind_build()
        job = self.success_job()
        self.run_pipeline()
        record = release.load_deployment(
            self.output / "validated_deployment.json", target, "trialmatch-test", "us-east1",
        )
        self.assertEqual(record["build_target"], target)
        self.assertEqual(record["pipeline_job"], job.resource_name)
        self.assertEqual(record["validated_release_uri"], "gs://test-run/processed/release.json")

    def test_mismatched_build_inputs_stop_before_submission(self):
        self.bind_build()
        for flag in ("--image", "--release"):
            index = self.argv.index(flag) + 1
            original = self.argv[index]
            with self.subTest(flag=flag):
                self.seed_previous_success()
                self.argv[index] = "mismatched-value"
                with self.assertRaisesRegex(ValueError, "does not match"):
                    self.run_pipeline()
                self.assertFalse((self.output / "validated_deployment.json").exists())
                self.init.assert_not_called()
                self.job_class.assert_not_called()
                self.argv[index] = original

    def test_wait_exception_cannot_leave_deployment_permission(self):
        self.seed_previous_success()
        self.bind_build()
        job = self.success_job()
        job.wait.side_effect = RuntimeError("Job failed with: node failure")
        with self.assertRaisesRegex(RuntimeError, "node failure"):
            self.run_pipeline()
        self.assertFalse((self.output / "validated_deployment.json").exists())
        self.blob.assert_called_once_with(self.argv[self.argv.index("--release") + 1])
        self.blob.return_value.download_as_text.assert_not_called()

    def test_build_changed_during_run_cannot_authorize_deployment(self):
        self.seed_previous_success()
        target = self.bind_build()
        job = self.success_job()
        job.wait.side_effect = lambda: release.save_target(
            self.output / "release_target.json", dict(
                target, build_id="build-B", image_tag=target["source_version"] + "-build-B",
            ),
        )
        with self.assertRaisesRegex(RuntimeError, "Selected build changed"):
            self.run_pipeline()
        self.assertFalse((self.output / "validated_deployment.json").exists())
        self.assertFalse((self.output / "validated_release.txt").exists())

    def test_cloud_manifest_must_match_bound_data_before_submission(self):
        self.bind_build()
        self.success_job()
        original = json.loads(json.dumps(self.input_manifest))
        for change in ("data", "image", "schema"):
            with self.subTest(change=change):
                self.seed_previous_success()
                self.input_manifest = json.loads(json.dumps(original))
                if change == "data":
                    self.input_manifest["files"][release.FILES[-1]]["sha256"] = "d" * 64
                elif change == "image":
                    self.input_manifest["image"] = "example/workflow:other"
                else:
                    self.input_manifest["schema_version"] = 2
                with self.assertRaises(ValueError):
                    self.run_pipeline()
                self.init.assert_not_called()
                self.job_class.assert_not_called()
                self.assertFalse((self.output / "validated_deployment.json").exists())

    TRAINER = "example/trainer@sha256:" + "d" * 64

    def test_trainer_image_adds_a_training_task_fed_by_the_validation_report(self):
        self.run_pipeline("--compile-only", "--trainer-image", self.TRAINER,
                          "--train-pairs", "gs://trialmatch-test-data/training/pairs_llm.jsonl",
                          "--wandb-secret", "projects/p/secrets/wandb-api-key/versions/latest")
        spec = yaml.safe_load((self.output / "pipeline.yaml").read_text())
        tasks = spec["root"]["dag"]["tasks"]
        self.assertEqual(
            set(tasks), {"fetch-raw", "process-trials", "validate-data", "train-encoder"}
        )
        training = tasks["train-encoder"]
        self.assertEqual(training["dependentTasks"], ["validate-data"])
        self.assertEqual(
            training["inputs"]["artifacts"]["report"]["taskOutputArtifact"],
            {"producerTask": "validate-data", "outputArtifactKey": "report"},
        )
        self.assertNotEqual(
            training.get("triggerPolicy", {}).get("strategy"), "ALL_UPSTREAM_TASKS_COMPLETED"
        )
        executors = spec["deploymentSpec"]["executors"]
        container = executors[spec["components"][training["componentRef"]["name"]]
                              ["executorLabel"]]["container"]
        self.assertEqual(container["image"], self.TRAINER)
        self.assertEqual(container["command"], ["python", "-m", "cloud.train"])
        self.assertIn("--validated-report", container["args"])
        self.assertIn("gs://trialmatch-test-data/training/pairs_llm.jsonl", container["args"])
        self.assertIn("NVIDIA_TESLA_T4", json.dumps(container["resources"]))
        others = [e["container"]["image"] for name, e in executors.items()
                  if e["container"] is not container]
        self.assertEqual(set(others), {"example/workflow:fixed-version"})
        self.job_class.assert_not_called()

    def test_trainer_image_must_be_pinned_by_digest(self):
        with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
            self.run_pipeline("--compile-only", "--trainer-image", "example/trainer:latest")

    def test_training_manifest_must_reference_this_runs_release(self):
        for source, accepted in (("gs://test-run/processed/release.json", True),
                                 ("gs://other-run/processed/release.json", False)):
            with self.subTest(source=source):
                job = self.success_job()
                job.task_details.append(SimpleNamespace(
                    task_name="train-encoder",
                    outputs={"training": SimpleNamespace(
                        artifacts=[SimpleNamespace(uri="gs://test-run/training")])},
                ))
                report = self.blob.return_value
                manifest = SimpleNamespace(download_as_text=lambda source=source: json.dumps(
                    {"source_release_uri": source, "artifact_sha256": "e" * 64}))
                self.blob.side_effect = lambda uri, manifest=manifest, report=report: (
                    manifest if uri.endswith("/training_manifest.json") else report
                )
                saved = self.output / "training_manifest.json"
                if accepted:
                    self.run_pipeline("--trainer-image", self.TRAINER)
                    self.assertEqual(json.loads(saved.read_text())["artifact_sha256"], "e" * 64)
                else:
                    with self.assertRaisesRegex(RuntimeError, "Training manifest"):
                        self.run_pipeline("--trainer-image", self.TRAINER)
                    self.assertFalse(saved.exists())  # The earlier run's copy is cleared.


if __name__ == "__main__":
    unittest.main()
