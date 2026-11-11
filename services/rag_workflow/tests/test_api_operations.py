"""Module E: HTTP behavior, safe logs and dependency diagnostics; no cloud calls."""

import io
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from services.frontend.app import create_app
from services.rag_workflow.config import Settings
from services.rag_workflow.observability import JsonFormatter, log_screening
from services.rag_workflow.providers import ProviderError
from services.rag_workflow.schemas import ErrorDetail, ScreenResponse


class ApiOperationsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.settings = replace(
            Settings(),
            mode="offline",
            artifacts=Path(cls.temp.name),
            chroma_host="",
        )
        cls.app = create_app(cls.settings)
        cls.client = TestClient(cls.app)
        cls.payload = {
            "patient_id": "060e72d3-912e-55cd-0c92-5faa6cb7a6db",
            "question": "Find type 2 diabetes trials and missing information.",
            "top_k": 1,
        }
        cls.example = ScreenResponse.model_validate(
            cls.client.post("/screen", json=cls.payload).json()
        )

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.temp.cleanup()

    def logs(self, records):
        return [json.loads(JsonFormatter().format(r)) for r in records]

    def test_success_contract_and_request_log(self):
        with self.assertLogs("trialmatch.api", level="INFO") as captured:
            response = self.client.post("/screen", json=self.payload)
        result = ScreenResponse.model_validate(response.json())
        events = self.logs(captured.records)
        summary = next(e for e in events if e["message"] == "screening_completed")
        http = next(e for e in events if e["message"] == "http_request")
        self.assertEqual(summary["request_id"], response.headers["x-request-id"])
        self.assertEqual(http["request_id"], summary["request_id"])
        self.assertEqual(summary["run_id"], result.run_id)
        self.assertEqual(
            summary["unknown_count"],
            sum(t.assessment_coverage.unknown for t in result.candidate_trials),
        )
        self.assertEqual(http["status_code"], 200)
        self.assertGreaterEqual(http["latency_ms"], 0)
        self.assertNotIn(self.payload["patient_id"], json.dumps(events))
        self.assertNotIn(self.payload["question"], json.dumps(events))

    def test_invalid_requests_have_422_and_request_ids(self):
        cases = [
            {},
            {**self.payload, "question": " "},
            {**self.payload, "top_k": 0},
            {**self.payload, "top_k": 6},
            {**self.payload, "extra": True},
            {**self.payload, "patient": {}},
            {"question": "Find trials"},
            {"patient": {"schema_version": "wrong"}, "question": "Find trials"},
        ]
        for body in cases:
            with self.subTest(body=body):
                response = self.client.post("/screen", json=body)
                self.assertEqual(response.status_code, 422)
                self.assertRegex(response.headers["x-request-id"], r"^[a-f0-9]{32}$")
        self.assertEqual(
            self.client.post(
                "/screen",
                content="{broken",
                headers={"Content-Type": "application/json"},
            ).status_code,
            422,
        )

    def test_unknown_patient_has_no_eligibility_result(self):
        response = self.client.post("/screen", json={**self.payload, "patient_id": "missing"})
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("candidate_trials", response.json())

    def test_patient_route_logs_template_not_identifier(self):
        with self.assertLogs("trialmatch.api", level="INFO") as captured:
            self.client.get("/patients/private-patient-marker?token=secret-marker")
        text = json.dumps(self.logs(captured.records))
        self.assertIn("/patients/{patient_id}", text)
        self.assertNotIn("private-patient-marker", text)
        self.assertNotIn("secret-marker", text)

    def test_provider_error_result_is_503_not_barrier(self):
        result = self.example.model_copy(deep=True)
        result.result_status, result.candidate_trials = "ERROR", []
        result.errors = [ErrorDetail(code="GCP_403", message="Model access unavailable")]
        with (
            patch("services.rag_workflow.workflow.ScreeningWorkflow.screen", return_value=result),
            self.assertLogs("trialmatch.api", level="INFO") as captured,
        ):
            response = self.client.post("/screen", json=self.payload)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["candidate_trials"], [])
        event = next(
            e for e in self.logs(captured.records) if e["message"] == "screening_completed"
        )
        self.assertEqual(event["error_codes"], ["GCP_403"])

    def test_partial_results_remain_explicit(self):
        result = self.example.model_copy(deep=True)
        result.result_status = "PARTIAL"
        result.errors = [ErrorDetail(code="INVALID_EXPLANATION", message="Review required")]
        with patch("services.rag_workflow.workflow.ScreeningWorkflow.screen", return_value=result):
            response = self.client.post("/screen", json=self.payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result_status"], "PARTIAL")
        self.assertTrue(response.json()["errors"])

    def test_gemini_metrics_remain_distinct_from_retrieval_encoder(self):
        result = self.example.model_copy(deep=True)
        result.mode = "live"
        result.metrics = {"embedding_requests": 1, "generation_requests": 5, "cache_hits": 2}
        with self.assertLogs("trialmatch.api", level="INFO") as captured:
            log_screening(result, self.settings)
        event = self.logs(captured.records)[0]
        self.assertEqual(event["embedding_provider"], "gemini")
        self.assertEqual(event["embedding_model"], self.settings.embedding_model)
        self.assertEqual(event["generation_requests"], 5)
        self.assertEqual(event["embedding_requests"], 1)
        self.assertEqual(event["cache_hits"], 2)
        self.assertEqual(event["retrieval_embedding_requests"], 0)

    def test_bioclinical_identity_and_nested_counts_without_loading_model(self):
        result = self.example.model_copy(deep=True)
        result.mode = "live"
        result.metrics = {
            "generation_requests": 5,
            "retrieval_encoder": {
                "embedding_requests": 1,
                "embedded_texts": 3,
                "cache_hits": 2,
                "question": "private-question-marker",
                "checkpoint_path": "secret-path",
            },
        }
        settings = SimpleNamespace(
            **{
                **self.settings.__dict__,
                "embedding_provider": "bioclinical",
                "embedding_model": "thomas-sounack/BioClinical-ModernBERT-base",
                "embedding_revision": "a" * 40,
                "dimension": 768,
                "embedding_checkpoint_sha256": "b" * 64,
            }
        )
        with self.assertLogs("trialmatch.api", level="INFO") as captured:
            log_screening(result, settings)
        event = self.logs(captured.records)[0]
        self.assertEqual(event["embedding_provider"], "bioclinical")
        self.assertEqual(event["embedding_revision"], "a" * 40)
        self.assertEqual(event["embedding_checkpoint_sha256"], "b" * 64)
        self.assertEqual(event["embedding_dimension"], 768)
        self.assertEqual(event["retrieval_embedding_requests"], 1)
        self.assertEqual(event["retrieval_embedded_texts"], 3)
        self.assertEqual(event["retrieval_cache_hits"], 2)
        self.assertEqual(event["generation_requests"], 5)
        self.assertEqual(event["embedding_requests"], 0)
        self.assertNotIn("private-question-marker", json.dumps(event))
        self.assertNotIn("secret-path", json.dumps(event))

    def test_offline_logging_does_not_claim_model_use(self):
        with self.assertLogs("trialmatch.api", level="INFO") as captured:
            log_screening(self.example, self.settings)
        event = self.logs(captured.records)[0]
        self.assertEqual(event["embedding_provider"], "NOT_USED")
        self.assertNotIn("embedding_model", event)
        self.assertNotIn("generation_model", event)

    def test_malformed_diagnostics_cannot_break_screening_or_leak_payloads(self):
        result = self.example.model_copy(deep=True)
        result.mode = "live"
        result.metrics = {
            "embedding_requests": "private-marker",
            "cache_hits": -1,
            "prompt_tokens": float("nan"),
            "output_tokens": True,
            "retrieval_encoder": ["private-marker"],
        }
        settings = SimpleNamespace(
            **{
                **self.settings.__dict__,
                "embedding_model": "bad\nprivate-marker",
                "embedding_revision": "private-marker",
                "embedding_checkpoint_sha256": "secret-path",
            }
        )
        with self.assertLogs("trialmatch.api", level="INFO") as captured:
            log_screening(result, settings)
        event = self.logs(captured.records)[0]
        self.assertEqual(event["embedding_model"], "UNAVAILABLE")
        for key in ("embedding_requests", "cache_hits", "prompt_tokens", "output_tokens"):
            self.assertEqual(event[key], 0)
        self.assertNotIn("embedding_revision", event)
        self.assertNotIn("embedding_checkpoint_sha256", event)
        self.assertNotIn("private-marker", json.dumps(event))

    def test_raised_provider_failure_is_503(self):
        with patch(
            "services.rag_workflow.workflow.ScreeningWorkflow.screen",
            side_effect=ProviderError("INDEX_NOT_READY", "sensitive-marker"),
        ):
            response = self.client.post("/screen", json=self.payload)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"]["code"], "INDEX_NOT_READY")
        self.assertNotIn("sensitive-marker", response.text)

    def test_timeout_is_504_not_eligibility(self):
        with patch(
            "services.rag_workflow.workflow.ScreeningWorkflow.screen",
            side_effect=TimeoutError("sensitive-marker"),
        ):
            response = self.client.post("/screen", json=self.payload)
        self.assertEqual(response.status_code, 504)
        self.assertEqual(response.json()["detail"]["code"], "SCREENING_TIMEOUT")
        self.assertNotIn("candidate_trials", response.json())

    def test_unexpected_error_is_sanitized_and_logged(self):
        with (
            patch(
                "services.rag_workflow.workflow.ScreeningWorkflow.screen",
                side_effect=RuntimeError("private-record-and-credential-marker"),
            ),
            self.assertLogs("trialmatch.api", level="INFO") as captured,
        ):
            response = self.client.post("/screen", json=self.payload)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["detail"]["code"], "INTERNAL_ERROR")
        self.assertEqual(response.json()["request_id"], response.headers["x-request-id"])
        self.assertNotIn(
            "private-record-and-credential-marker",
            response.text + json.dumps(self.logs(captured.records)),
        )

    def test_offline_ready_without_model_or_index(self):
        response = self.client.get("/ready")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["model_access"], "NOT_REQUIRED")
        self.assertEqual(response.json()["checks"]["index"]["status"], "NOT_REQUIRED")

    def test_live_health_does_not_imply_ready(self):
        settings = replace(self.settings, mode="live", project="trialmatch-test")
        with TestClient(create_app(settings)) as client:
            self.assertEqual(client.get("/health").status_code, 200)
            response = client.get("/ready")
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()["checks"]["index"]["code"], "INDEX_NOT_READY")
        self.assertFalse((settings.artifacts / "chroma").exists())

    def test_missing_data_readiness_503(self):
        settings = replace(self.settings, patients_path=Path(self.temp.name) / "absent.jsonl")
        with TestClient(create_app(settings)) as client:
            response = client.get("/ready")
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()["checks"]["data"]["code"], "MISSING_ARTIFACT")
            self.assertNotIn(str(settings.patients_path), response.text)

    def test_missing_data_screening_503(self):
        with patch(
            "services.rag_workflow.workflow.ScreeningWorkflow.screen",
            side_effect=FileNotFoundError("secret-path-marker"),
        ):
            response = self.client.post("/screen", json=self.payload)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("secret-path-marker", response.text)

    def test_invalid_server_manifest_is_503_not_invalid_patient(self):
        with (
            patch(
                "services.rag_workflow.api.ScreeningWorkflow",
                side_effect=ValueError("manifest-private-path"),
            ),
            TestClient(create_app(self.settings)) as client,
        ):
            response = client.post("/screen", json=self.payload)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"]["code"], "ARTIFACT_UNAVAILABLE")
        self.assertNotIn("manifest-private-path", response.text)

    def test_live_index_diagnostics_are_cached_and_do_not_call_models(self):
        settings = replace(
            self.settings, mode="live", project="trialmatch-test", chroma_host="database.example"
        )
        with patch("services.rag_workflow.readiness.VectorIndex") as index:
            index.return_value.status.return_value = {"index_version": "test", "vector_count": 607}
            with patch("services.rag_workflow.providers.GeminiProvider") as model:
                with TestClient(create_app(settings)) as client:
                    first, second = client.get("/ready"), client.get("/ready")
                self.assertEqual(first.status_code, 200)
                self.assertEqual(first.json(), second.json())
                self.assertEqual(first.json()["model_access"], "NOT_PROBED")
                self.assertEqual(index.return_value.status.call_count, 1)
                model.assert_not_called()

    def test_unavailable_database_readiness_503(self):
        settings = replace(
            self.settings, mode="live", project="trialmatch-test", chroma_host="database.example"
        )
        with (
            patch(
                "services.rag_workflow.readiness.VectorIndex",
                side_effect=ConnectionError("credential-marker"),
            ),
            TestClient(create_app(settings)) as client,
        ):
            response = client.get("/ready")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["checks"]["index"]["code"], "DEPENDENCY_UNAVAILABLE")
        self.assertNotIn("credential-marker", response.text)

    def test_request_ids_are_unique_and_cannot_be_injected(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(
                pool.map(
                    lambda _: self.client.get(
                        "/health",
                        headers={"X-Request-ID": "private-marker"},
                    ),
                    range(2),
                )
            )
        ids = [r.headers["x-request-id"] for r in responses]
        self.assertEqual(len(set(ids)), 2)
        self.assertTrue(all(len(value) == 32 for value in ids))

    def test_cloud_trace_correlation(self):
        trace = "a" * 32
        with (
            TestClient(create_app(replace(self.settings, project="trialmatch-test"))) as client,
            self.assertLogs("trialmatch.api", level="INFO") as captured,
        ):
            client.get("/health", headers={"X-Cloud-Trace-Context": trace + "/123;o=1"})
        event = self.logs(captured.records)[-1]
        self.assertEqual(
            event["logging.googleapis.com/trace"], "projects/trialmatch-test/traces/" + trace
        )

    def test_openapi_and_static_frontend_still_available(self):
        schema = self.client.get("/openapi.json").json()
        self.assertIn("/ready", schema["paths"])
        self.assertIn("/screen", schema["paths"])
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/assets/app.js").status_code, 200)

    def test_json_formatter_writes_one_parseable_line(self):
        import logging

        from services.rag_workflow.observability import emit

        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(JsonFormatter())
        logger = logging.getLogger("trialmatch.api")
        logger.addHandler(handler)
        try:
            emit("test_event", question="sensitive-marker", patient={"secret": True}, ready=True)
        finally:
            logger.removeHandler(handler)
        self.assertEqual(len(stream.getvalue().splitlines()), 1)
        entry = json.loads(stream.getvalue())
        self.assertTrue(entry["ready"])
        self.assertNotIn("sensitive-marker", stream.getvalue())


class HttpVerifierTests(unittest.TestCase):
    def test_smoke_checks_reject_false_readiness_and_nonobject_screen(self):
        from demo.ovrz.verify_ms3_api import verify

        for ready, screening, expected in (
            (True, {"result_status": "OK", "candidate_trials": [{}]}, True),
            (False, {"result_status": "OK", "candidate_trials": [{}]}, False),
            (True, [], False),
        ):
            with self.subTest(ready=ready, screening=screening):
                responses = []
                for status, body in (
                    (200, {"status": "ok", "mode": "offline"}),
                    (200, {"patients": [{}]}),
                    (200, {"paths": {"/screen": {}, "/ready": {}}}),
                    (422, {}),
                    (404, {}),
                    (422, {}),
                    (200, {"ready": ready, "check_scope": "data_and_index"}),
                    (200, screening),
                ):
                    response = io.BytesIO(json.dumps(body).encode())
                    response.code = status
                    response.headers = {
                        "Content-Type": "application/json",
                        "X-Request-ID": "a" * 32,
                    }
                    responses.append(response)
                opener = Mock()
                opener.open.side_effect = responses
                with patch("demo.ovrz.verify_ms3_api.build_opener", return_value=opener):
                    report = verify(
                        "http://127.0.0.1:8080",
                        screen=True,
                        require_operations=True,
                    )
                self.assertEqual(report["passed"], expected)
                self.assertEqual(len(report["checks"]), 8)


if __name__ == "__main__":
    unittest.main()
