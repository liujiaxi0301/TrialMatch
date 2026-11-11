"""Real compilation and simulated Vertex results; no cloud jobs or credentials."""

import hashlib
import io
import json
import tempfile
import unittest
from contextlib import chdir, redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml

from cloud import eligibility, pipeline, release
from cloud.tests.eligibility_fixtures import HASHES, valid_payloads


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
        (self.output / "training_manifest.json").write_text('{"source_release_uri":"gs://old/release.json"}\n')
        (self.output / "eligibility_manifest.json").write_text('{"status":"PASSED","output_uri":"gs://old/evaluation"}\n')

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
        self.assertEqual(set(tasks), {"fetch-raw", "process-trials", "validate-data", "retrieve-trials"})
        self.assertEqual(tasks["process-trials"]["dependentTasks"], ["fetch-raw"])
        self.assertEqual(tasks["validate-data"]["dependentTasks"], ["process-trials"])
        self.assertEqual(tasks["retrieve-trials"]["dependentTasks"], ["validate-data"])
        self.assertEqual(
            tasks["retrieve-trials"]["inputs"]["artifacts"]["report"]["taskOutputArtifact"],
            {"producerTask": "validate-data", "outputArtifactKey": "report"},
        )
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
        self.assertTrue((self.output / "training_manifest.json").exists())
        self.assertTrue((self.output / "eligibility_manifest.json").exists())

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
                          "--train-pairs-sha256", "c" * 64,
                          "--wandb-secret", "projects/p/secrets/wandb-api-key/versions/latest")
        spec = yaml.safe_load((self.output / "pipeline.yaml").read_text())
        tasks = spec["root"]["dag"]["tasks"]
        self.assertEqual(
            set(tasks), {"fetch-raw", "process-trials", "validate-data", "retrieve-trials", "train-encoder"}
        )
        self.assertEqual(tasks["retrieve-trials"]["dependentTasks"], ["validate-data"])
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
        self.assertEqual(container["args"][container["args"].index("--pairs-sha256") + 1], "c" * 64)
        self.assertEqual(container["args"][container["args"].index("--batch-size") + 1], "8")
        self.assertIn("projects/p/secrets/wandb-api-key/versions/latest", container["args"])
        self.assertIn("NVIDIA_TESLA_T4", json.dumps(container["resources"]))
        others = [e["container"]["image"] for name, e in executors.items()
                  if e["container"] is not container]
        self.assertEqual(set(others), {"example/workflow:fixed-version"})
        self.job_class.assert_not_called()

    def test_trainer_image_must_be_pinned_by_digest(self):
        for image in ("example/trainer:latest", "example/trainer@sha256:abc"):
            with self.subTest(image=image), self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
                self.run_pipeline("--compile-only", "--trainer-image", image)

    def test_training_arguments_reject_unusable_cloud_inputs(self):
        for extra in (
            ["--trainer-image", self.TRAINER, "--trainer-batch-size", "0"],
            ["--trainer-image", self.TRAINER, "--train-pairs", "/local/pairs.jsonl"],
            ["--train-pairs", "gs://b/ignored.jsonl"],
            ["--wandb-secret", "projects/p/secrets/wandb/versions/1"],
        ):
            with self.subTest(extra=extra), self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
                self.run_pipeline("--compile-only", *extra)
        self.init.assert_not_called()
        self.job_class.assert_not_called()

    def test_training_batch_size_override_reaches_container(self):
        self.run_pipeline("--compile-only", "--trainer-image", self.TRAINER,
                          "--trainer-batch-size", "4")
        spec = yaml.safe_load((self.output / "pipeline.yaml").read_text())
        container = spec["deploymentSpec"]["executors"]["exec-train-encoder"]["container"]
        self.assertEqual(container["args"][container["args"].index("--batch-size") + 1], "4")

    def test_extra_pair_arguments_fail_before_cloud_access_and_clear_old_success(self):
        uri = "gs://test/pairs.jsonl"
        for extra in (
            ["--train-pairs", uri],
            ["--train-pairs-sha256", "c" * 64],
            ["--train-pairs", uri, "--train-pairs-sha256", "invalid"],
            ["--train-pairs", uri, "--train-pairs-sha256", "c" * 64, "d" * 64],
            ["--train-pairs", uri, uri, "--train-pairs-sha256", "c" * 64, "c" * 64],
        ):
            with self.subTest(extra=extra), redirect_stderr(io.StringIO()):
                self.seed_previous_success()
                with self.assertRaises(SystemExit):
                    self.run_pipeline("--trainer-image", self.TRAINER, *extra)
                self.assert_no_success_markers()
        self.init.assert_not_called()
        self.job_class.assert_not_called()
        self.blob.assert_not_called()

    def test_two_extra_pairs_keep_uri_hash_order_in_compiled_training_command(self):
        self.run_pipeline("--compile-only", "--trainer-image", self.TRAINER,
                          "--train-pairs", "gs://test/a.jsonl", "gs://test/b.jsonl",
                          "--train-pairs-sha256", "c" * 64, "d" * 64)
        spec = yaml.safe_load((self.output / "pipeline.yaml").read_text())
        args = spec["deploymentSpec"]["executors"]["exec-train-encoder"]["container"]["args"]
        self.assertEqual(args[args.index("--pairs") + 1:args.index("--pairs-sha256")],
                         ["gs://test/a.jsonl", "gs://test/b.jsonl"])
        self.assertEqual(args[args.index("--pairs-sha256") + 1:], ["c" * 64, "d" * 64])

    def training_job(self):
        self.blob.side_effect = None
        job = self.success_job()
        existing_lookup = self.blob.side_effect
        job.task_details.append(SimpleNamespace(
            task_name="train-encoder",
            outputs={"training": SimpleNamespace(
                artifacts=[SimpleNamespace(uri="gs://test-run/training")])},
        ))
        files = {"model.safetensors": "e" * 64, "config.json": "f" * 64}
        self.training_manifest = {
            "schema_version": 1,
            "workflow_type": "contrastive-encoder-finetune",
            "source_release_uri": "gs://test-run/processed/release.json",
            "image_uri": self.TRAINER,
            "artifact_uri": "gs://test-run/training/model",
            "artifact_files": files,
            "artifact_sha256": hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest(),
            "config": {"batch_size": 8},
            "pair_files": [{"uri": "built-from:gs://test-run/processed/release.json",
                            "sha256": "b" * 64, "expected_sha256": None}],
        }
        self.training_blob = SimpleNamespace(
            download_as_text=lambda: json.dumps(self.training_manifest),
        )
        self.blob.side_effect = lambda uri: (
            self.training_blob if uri == "gs://test-run/training/training_manifest.json"
            else existing_lookup(uri) if existing_lookup else self.blob.return_value
        )
        return job

    def assert_no_success_markers(self):
        for name in ("training_manifest.json", "validation.json", "validated_release.txt",
                     "validated_deployment.json", "eligibility_manifest.json"):
            self.assertFalse((self.output / name).exists(), name)

    def test_training_success_publishes_bound_manifest_and_data_evidence(self):
        self.seed_previous_success()
        target = self.bind_build()
        self.training_job()
        self.run_pipeline("--trainer-image", self.TRAINER)
        self.assertEqual(
            json.loads((self.output / "training_manifest.json").read_text()), self.training_manifest,
        )
        record = release.load_deployment(
            self.output / "validated_deployment.json", target, "trialmatch-test", "us-east1",
        )
        self.assertEqual(record["validated_release_uri"], self.training_manifest["source_release_uri"])

    def pinned_pair_job(self):
        job = self.training_job()
        self.training_manifest["pair_files"] = [
            {"uri": "built-from:gs://test-run/processed/release.json", "sha256": "b" * 64,
             "expected_sha256": None},
            {"uri": "gs://test/pairs_llm.jsonl", "sha256": "c" * 64, "expected_sha256": "c" * 64},
        ]
        return job

    def run_with_pinned_pairs(self):
        self.run_pipeline("--trainer-image", self.TRAINER,
                          "--train-pairs", "gs://test/pairs_llm.jsonl", "--train-pairs-sha256", "c" * 64)

    def test_expected_and_actual_pair_hashes_are_bound_to_success_record(self):
        self.bind_build()
        self.pinned_pair_job()
        self.run_with_pinned_pairs()
        manifest = json.loads((self.output / "training_manifest.json").read_text())
        self.assertEqual(manifest["pair_files"][1]["expected_sha256"], "c" * 64)
        self.assertEqual(manifest["pair_files"][1]["sha256"], "c" * 64)
        self.assertTrue((self.output / "validated_deployment.json").exists())

    def test_training_without_extra_inputs_rejects_undeclared_pair_files(self):
        self.seed_previous_success()
        self.bind_build()
        self.pinned_pair_job()
        with self.assertRaisesRegex(RuntimeError, "submitted pair sources"):
            self.run_pipeline("--trainer-image", self.TRAINER)
        self.assert_no_success_markers()

    def test_unverified_wrong_or_missing_pairs_cannot_publish_success(self):
        self.bind_build()
        for case in ("missing-list", "missing-extra", "duplicate", "foreign-uri", "foreign-release",
                     "wrong-actual", "wrong-expected", "old-manifest"):
            with self.subTest(case=case):
                self.seed_previous_success()
                self.pinned_pair_job()
                sources = self.training_manifest["pair_files"]
                if case == "missing-list":
                    del self.training_manifest["pair_files"]
                elif case == "missing-extra":
                    sources.pop()
                elif case == "duplicate":
                    sources.append(dict(sources[-1]))
                elif case == "foreign-uri":
                    sources[-1]["uri"] = "gs://other/pairs_llm.jsonl"
                elif case == "foreign-release":
                    sources[0]["uri"] = "built-from:gs://other/release.json"
                elif case == "old-manifest":
                    del sources[-1]["expected_sha256"]
                else:
                    sources[-1]["sha256" if case == "wrong-actual" else "expected_sha256"] = "d" * 64
                with self.assertRaisesRegex(RuntimeError, "Training manifest"):
                    self.run_with_pinned_pairs()
                self.assert_no_success_markers()

    def test_foreign_or_invalid_training_output_cannot_publish_any_success(self):
        self.bind_build()
        for field, value in (
            ("source_release_uri", "gs://another-run/release.json"),
            ("image_uri", "example/trainer@sha256:" + "a" * 64),
            ("artifact_uri", "gs://older-run/model"),
            ("artifact_files", {}),
            ("artifact_files", {"model.safetensors": "invalid"}),
            ("artifact_sha256", "0" * 64),
            ("config", {"batch_size": 16}),
        ):
            with self.subTest(field=field):
                self.seed_previous_success()
                self.training_job()
                self.training_manifest[field] = value
                with self.assertRaisesRegex(RuntimeError, "Training manifest"):
                    self.run_pipeline("--trainer-image", self.TRAINER)
                self.assert_no_success_markers()

    def test_training_manifest_download_failure_cannot_leave_success(self):
        self.seed_previous_success()
        self.bind_build()
        self.training_job()

        def unavailable():
            raise RuntimeError("Training manifest unavailable")

        self.training_blob.download_as_text = unavailable
        with self.assertRaisesRegex(RuntimeError, "unavailable"):
            self.run_pipeline("--trainer-image", self.TRAINER)
        self.assert_no_success_markers()

    def test_failed_training_run_clears_earlier_success(self):
        self.seed_previous_success()
        job = self.training_job()
        job.state = SimpleNamespace(name="PIPELINE_STATE_FAILED")
        with self.assertRaisesRegex(RuntimeError, "PIPELINE_STATE_FAILED"):
            self.run_pipeline("--trainer-image", self.TRAINER)
        self.assert_no_success_markers()

    def test_eligibility_graph_is_independent_of_training_and_uses_validated_data(self):
        self.bind_build()
        for extra in ([], ["--trainer-image", self.TRAINER]):
            with self.subTest(training=bool(extra)):
                self.run_pipeline("--compile-only", "--eligibility", "--eligibility-model", "selected-model", *extra)
                spec = yaml.safe_load((self.output / "pipeline.yaml").read_text())
                tasks = spec["root"]["dag"]["tasks"]
                self.assertEqual(len(tasks), 6 if extra else 5)
                evaluation = tasks["evaluate-eligibility"]
                self.assertEqual(evaluation["dependentTasks"], ["validate-data"])
                self.assertEqual(evaluation["inputs"]["artifacts"]["report"]["taskOutputArtifact"],
                                 {"producerTask": "validate-data", "outputArtifactKey": "report"})
                self.assertNotEqual(evaluation.get("triggerPolicy", {}).get("strategy"), "ALL_UPSTREAM_TASKS_COMPLETED")
                container = spec["deploymentSpec"]["executors"]["exec-evaluate-eligibility"]["container"]
                self.assertEqual(container["image"], self.argv[self.argv.index("--image") + 1])
                self.assertEqual(container["command"], ["python", "-m", "cloud.eligibility"])
                self.assertEqual(container["args"][container["args"].index("--model") + 1], "selected-model")
                env = {item["name"]: item["value"] for item in container["env"]}
                self.assertEqual(env["GCP_PROJECT"], "trialmatch-test")
                self.assertEqual(env["GCP_LOCATION"], "global")
                self.assertNotIn("accelerator", container.get("resources", {}))
        self.job_class.assert_not_called()

    def test_eligibility_requires_versioned_image_and_explicit_enablement(self):
        for extra in (["--eligibility"], ["--eligibility-model", "ignored-model"]):
            with self.subTest(extra=extra), self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
                self.run_pipeline("--compile-only", *extra)
        self.job_class.assert_not_called()

    def eligibility_job(self, training=False):
        self.blob.side_effect = None
        job = self.training_job() if training else self.success_job()
        lookup = self.blob.side_effect
        report = json.loads(self.blob.return_value.download_as_text.return_value)
        report["source_sha256"] = HASHES
        self.blob.return_value.download_as_text.return_value = json.dumps(report)
        output = "gs://test-run/evaluation"
        job.task_details.append(SimpleNamespace(
            task_name="evaluate-eligibility",
            outputs={"evaluation": SimpleNamespace(artifacts=[SimpleNamespace(uri=output)])},
        ))
        self.evaluation_payloads = valid_payloads()
        self.evaluation_manifest = {
            "schema_version": 1, "status": "PASSED", "workflow_type": "fixed-pair-eligibility",
            "source_release_uri": "gs://test-run/processed/release.json",
            "validation_report_uri": "gs://test-run/report/validation.json",
            "output_uri": output, "source_sha256": HASHES, "provider": "vertex",
            "image_uri": self.argv[self.argv.index("--image") + 1], "model": eligibility.DEFAULT_MODEL,
            "files": {name: {"uri": f"{output}/{name}", "sha256": hashlib.sha256(data).hexdigest()}
                      for name, data in self.evaluation_payloads.items()},
        }

        def get_blob(uri):
            if uri == output + "/eligibility_manifest.json":
                return SimpleNamespace(download_as_text=lambda: json.dumps(self.evaluation_manifest))
            if uri.startswith(output + "/"):
                return SimpleNamespace(download_as_bytes=lambda: self.evaluation_payloads[uri.rsplit("/", 1)[1]])
            return lookup(uri) if lookup else self.blob.return_value

        self.blob.side_effect = get_blob
        self.enterContext(patch.object(eligibility, "blob", side_effect=get_blob))
        return job

    def test_training_and_eligibility_success_publish_both_manifests(self):
        self.seed_previous_success()
        self.bind_build()
        self.eligibility_job(training=True)
        self.run_pipeline("--eligibility", "--trainer-image", self.TRAINER)
        self.assertEqual(json.loads((self.output / "eligibility_manifest.json").read_text()), self.evaluation_manifest)
        self.assertEqual(json.loads((self.output / "training_manifest.json").read_text()), self.training_manifest)
        self.assertTrue((self.output / "validated_deployment.json").exists())

    def test_foreign_or_failed_eligibility_manifest_cannot_publish_success(self):
        self.bind_build()
        for field, value in (
            ("status", "FAILED"), ("source_release_uri", "gs://old/release.json"),
            ("validation_report_uri", "gs://old/validation.json"),
            ("output_uri", "gs://old/evaluation"), ("image_uri", "example/wrong:latest"),
            ("model", "another-model"), ("source_sha256", {}), ("files", {}),
        ):
            with self.subTest(field=field):
                self.seed_previous_success()
                self.eligibility_job()
                self.evaluation_manifest[field] = value
                with self.assertRaisesRegex(RuntimeError, "Eligibility manifest"):
                    self.run_pipeline("--eligibility")
                self.assert_no_success_markers()

    def test_modified_or_missing_eligibility_outputs_cannot_publish_success(self):
        self.bind_build()
        for name in eligibility.RESULT_FILES:
            with self.subTest(file=name):
                self.seed_previous_success()
                self.eligibility_job()
                self.evaluation_payloads[name] += b"tampered"
                with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
                    self.run_pipeline("--eligibility")
                self.assert_no_success_markers()
        self.eligibility_job()
        self.evaluation_payloads.clear()
        with self.assertRaises(KeyError):
            self.run_pipeline("--eligibility")
        self.assert_no_success_markers()

    def test_eligibility_unready_metrics_block_training_and_data_success_markers(self):
        self.seed_previous_success()
        self.bind_build()
        self.eligibility_job(training=True)
        name = eligibility.RESULT_FILES[2]
        scores = json.loads(self.evaluation_payloads[name])
        scores["official_reporting_ready"] = False
        self.evaluation_payloads[name] = json.dumps(scores).encode()
        self.evaluation_manifest["files"][name]["sha256"] = hashlib.sha256(self.evaluation_payloads[name]).hexdigest()
        with self.assertRaisesRegex(RuntimeError, "not ready"):
            self.run_pipeline("--eligibility", "--trainer-image", self.TRAINER)
        self.assert_no_success_markers()

    def test_failed_eligibility_job_clears_previous_success(self):
        self.seed_previous_success()
        self.bind_build()
        job = self.eligibility_job()
        job.state = SimpleNamespace(name="PIPELINE_STATE_FAILED")
        with self.assertRaisesRegex(RuntimeError, "PIPELINE_STATE_FAILED"):
            self.run_pipeline("--eligibility")
        self.assert_no_success_markers()


if __name__ == "__main__":
    unittest.main()
