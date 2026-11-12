"""Offline checks; fake cloud calls and one real cloud.tasks.fetch invocation."""
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

import verify_checksum_failure as check

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "docs/ms3/evidence/module-a/gcp-20261110/raw"
sys.path.insert(0, str(REPO))
from cloud import tasks


class FakeCloud:
    def __init__(self):
        self.baseline = json.loads((RAW / "vertex-job.json").read_text())
        self.manifest = (RAW / "input-release.json").read_bytes()
        manifest = json.loads(self.manifest)
        self.objects = {check.RELEASE_URI: self.manifest,
                        manifest["files"][check.FAULT_FILE]["uri"]: (REPO / check.FAULT_FILE).read_bytes()}
        self.uploads, self.submissions = [], []
        self.negative = None

    def job(self, job_id):
        return copy.deepcopy(self.baseline if job_id == check.BASELINE_ID else self.negative)

    def object(self, uri):
        return self.objects[uri], {"generation": "42", "size": str(len(self.objects[uri]))}

    def create_object(self, job_id, uri, content):
        if uri in self.objects:
            raise AssertionError("Test attempted to replace an existing object")
        self.objects[uri] = content
        self.uploads.append(uri)
        return {"name": uri, "generation": "43"}

    def submit(self, plan):
        check.validate_plan(plan)
        self.submissions.append(plan)
        self.negative = {
            "name": f'projects/{check.PROJECT_NUMBER}/locations/{check.REGION}/pipelineJobs/{plan["job_id"]}',
            "state": "PIPELINE_STATE_FAILED", "serviceAccount": check.SERVICE_ACCOUNT,
            "pipelineSpec": copy.deepcopy(plan["pipeline_spec"]),
            "runtimeConfig": {"parameterValues": {"release": plan["uris"]["bad_release"]},
                              "gcsOutputDirectory": plan["uris"]["pipeline_root"]},
            "jobDetail": {"taskDetails": [
                {"taskName": "fetch-raw", "state": "FAILED", "startTime": "2026-11-10T20:00:00Z",
                 "executorDetail": {"containerDetail": {"mainJob": f"projects/{check.PROJECT_NUMBER}/locations/us-east1/customJobs/123"}},
                 "error": {"message": "Worker exited non-zero"}},
                *[{"taskName": name, "state": "NOT_TRIGGERED"} for name in check.NODES[1:]],
            ]},
        }
        return copy.deepcopy(self.negative)

    def logs(self, executor):
        return {"filter": 'resource.type="ml_job" AND resource.labels.job_id="123"', "truncated": False,
                "entries": [{"textPayload": "ValueError: " + check.EXPECTED_ERROR,
                             "resource": {"type": "ml_job", "labels": {"project_id": check.PROJECT, "job_id": "123"}}}]}


class FailureCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name) / "case"
        self.api = FakeCloud()

    def run_case(self):
        with contextlib.redirect_stdout(io.StringIO()):
            code = check.run(self.api, self.directory, 0)
        self.assertEqual(code, 0)
        return json.loads((self.directory / "plan.json").read_text())

    def test_full_flow_isolated_uploads_and_all_three_downstream_tasks(self):
        before = dict(self.api.objects)
        plan = self.run_case()
        self.assertEqual(len(self.api.uploads), 2)
        self.assertEqual(len(self.api.submissions), 1)
        self.assertEqual({uri: self.api.objects[uri] for uri in before}, before)
        report = json.loads((self.directory / "result.json").read_text())
        self.assertEqual(report["status"], "PASSED")
        self.assertEqual(report["task_states"]["retrieve-trials"], "NOT_TRIGGERED")
        self.assertTrue(all(t["cachingOptions"] == {"enableCache": False} for t in plan["pipeline_spec"]["root"]["dag"]["tasks"].values()))

    def test_collect_does_not_upload_or_resubmit(self):
        self.run_case()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(check.collect(self.api, self.directory, 0), 0)
        self.assertEqual((len(self.api.uploads), len(self.api.submissions)), (2, 1))

    def test_repeat_run_refuses_existing_case(self):
        self.run_case()
        with self.assertRaises(FileExistsError):
            check.run(self.api, self.directory, 0)
        self.assertEqual(len(self.api.submissions), 1)

    def test_failed_recollection_does_not_leave_stale_pass(self):
        self.run_case()
        self.api.job = Mock(side_effect=RuntimeError("permission revoked"))
        with self.assertRaisesRegex(RuntimeError, "permission revoked"):
            check.collect(self.api, self.directory, 0)
        self.assertEqual(json.loads((self.directory / "result.json").read_text())["status"], "INCONCLUSIVE")
        history = list(self.directory.glob("previous-result-*.json"))
        self.assertEqual(len(history), 1)
        self.assertEqual(json.loads(history[0].read_text())["status"], "PASSED")

    def test_live_baseline_change_stops_before_writes(self):
        self.api.baseline["state"] = "PIPELINE_STATE_FAILED"
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ValueError):
            check.run(self.api, self.directory, 0)
        self.assertEqual((self.api.uploads, self.api.submissions), ([], []))

    def test_corrupt_original_stops_before_writes(self):
        uri = json.loads(self.api.manifest)["files"][check.FAULT_FILE]["uri"]
        self.api.objects[uri] += b"already changed"
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(ValueError, "Baseline raw.dvc"):
            check.run(self.api, self.directory, 0)
        self.assertEqual((self.api.uploads, self.api.submissions), ([], []))

    def test_real_fetch_rejects_bad_copy_before_dvc_or_output(self):
        original = json.loads(self.api.manifest)
        original_copy = copy.deepcopy(original)
        payload = self.api.objects[original["files"][check.FAULT_FILE]["uri"]]
        bad, damaged = check.make_fault(original, payload, f"gs://{check.BUCKET}/negative-tests/test/bad")
        self.assertEqual(original, original_copy)
        self.assertEqual(bad["files"][check.FAULT_FILE]["sha256"], check.sha(payload))
        self.assertNotEqual(check.sha(damaged), check.sha(payload))
        release_uri = f"gs://{check.BUCKET}/negative-tests/test/release.json"
        store = {release_uri: json.dumps(bad).encode(), bad["files"][check.FAULT_FILE]["uri"]: damaged}

        def fake_blob(uri):
            obj = Mock()
            obj.download_as_text.return_value = store[uri].decode()
            obj.download_to_filename.side_effect = lambda path: Path(path).write_bytes(store[uri])
            return obj

        with patch.object(tasks, "ROOT", Path(self.tmp.name)), patch.object(tasks, "blob", side_effect=fake_blob), \
                patch.object(tasks, "command") as dvc, patch.object(tasks, "write_json") as publish:
            with self.assertRaisesRegex(ValueError, "Checksum mismatch") as raised:
                tasks.fetch(release_uri, "gs://unused/output")
            self.assertEqual(str(raised.exception), check.EXPECTED_ERROR)
            dvc.assert_not_called()
            publish.assert_not_called()

    def test_generic_failure_cannot_pass(self):
        plan = self.run_case()
        report = check.evaluate(plan, self.api.negative, [], True)
        self.assertEqual(report["status"], "INCONCLUSIVE")

    def test_wrong_job_or_missing_downstream_cannot_pass(self):
        plan = self.run_case()
        logs = self.api.logs("unused")["entries"]
        for mutation in ("job", "downstream", "cache", "input"):
            with self.subTest(mutation=mutation):
                job = copy.deepcopy(self.api.negative)
                if mutation == "job":
                    job["name"] += "wrong"
                elif mutation == "downstream":
                    job["jobDetail"]["taskDetails"].pop()
                elif mutation == "cache":
                    job["pipelineSpec"]["root"]["dag"]["tasks"]["fetch-raw"]["cachingOptions"] = {"enableCache": True}
                self.assertEqual(check.evaluate(plan, job, logs, mutation != "input")["status"], "INCONCLUSIVE")

    def test_success_or_executed_downstream_is_failed_acceptance(self):
        plan = self.run_case()
        logs = self.api.logs("unused")["entries"]
        for mutation in ("success", "downstream"):
            job = copy.deepcopy(self.api.negative)
            if mutation == "success":
                job["state"] = "PIPELINE_STATE_SUCCEEDED"
            else:
                job["jobDetail"]["taskDetails"][-1]["state"] = "RUNNING"
            self.assertEqual(check.evaluate(plan, job, logs, True)["status"], "FAILED")

    def test_modified_local_fault_is_rejected_even_if_plan_hash_changes(self):
        plan = self.run_case()
        (self.directory / "bad-raw.dvc").write_bytes(b"a different experiment")
        plan["test_file_sha256"]["bad-raw.dvc"] = check.sha(b"a different experiment")
        with self.assertRaisesRegex(ValueError, "one-file"):
            check.verify_saved_inputs(self.directory, plan)

    def test_storage_guard_and_create_only_precondition(self):
        api = check.Google.__new__(check.Google)
        seen = []
        api.request = lambda url, *args: seen.append(url) or b'{}'
        job_id = "xuyang-ms3-hash-20261110t200000z-12345678"
        with self.assertRaises(ValueError):
            api.create_object(job_id, check.RELEASE_URI, b"bad")
        self.assertEqual(seen, [])
        api.create_object(job_id, check.locations(job_id)["bad_object"], b"bad")
        self.assertEqual(parse_qs(urlsplit(seen[0]).query)["ifGenerationMatch"], ["0"])

    def test_object_reads_pin_generation(self):
        api = check.Google.__new__(check.Google)
        seen = []
        api.json = lambda url: {"generation": "4321"}
        api.request = lambda url: seen.append(url) or b"data"
        api.object(check.RELEASE_URI)
        query = parse_qs(urlsplit(seen[0]).query)
        self.assertEqual(query["generation"], ["4321"])
        self.assertEqual(query["ifGenerationMatch"], ["4321"])

    def test_log_query_uses_observed_resource_and_rejects_wrong_job(self):
        api = check.Google.__new__(check.Google)
        seen = []
        api.json = lambda url, body: seen.append(body) or {"entries": []}
        resource = f"projects/{check.PROJECT_NUMBER}/locations/us-east1/customJobs/123"
        api.logs(resource)
        self.assertEqual(seen[0]["filter"], 'resource.type="ml_job" AND resource.labels.job_id="123"')
        api.json = lambda url, body: {"entries": [{"resource": {"type": "ml_job", "labels": {"job_id": "other"}}}]}
        with self.assertRaisesRegex(ValueError, "different job"):
            api.logs(resource)

    def test_submit_body_uses_fixed_id_image_and_isolated_root(self):
        plan = self.run_case()
        api = check.Google.__new__(check.Google)
        seen = []
        api.json = lambda url, body: seen.append((url, body)) or {}
        api.submit(plan)
        url, body = seen[0]
        self.assertEqual(parse_qs(urlsplit(url).query)["pipelineJobId"], [plan["job_id"]])
        self.assertEqual(body["runtimeConfig"]["parameterValues"]["release"], plan["uris"]["bad_release"])
        self.assertEqual(body["runtimeConfig"]["gcsOutputDirectory"], plan["uris"]["pipeline_root"])
        self.assertEqual({e["container"]["image"] for e in body["pipelineSpec"]["deploymentSpec"]["executors"].values()}, {check.IMAGE})


if __name__ == "__main__":
    unittest.main(verbosity=2)
