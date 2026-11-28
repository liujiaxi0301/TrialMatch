"""Model selection through the real HTTP/workflow/embedded-Chroma integration.

Only model adapters are replaced. Deterministic test vectors do not establish
Gemini availability, checkpoint quality, or a live-model evaluation result.
"""

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from services.frontend.app import create_app
from services.rag_workflow.tests.api_fixtures import ApiFixture


class ApiModelSelectionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(temporary.cleanup)
        self.fixture = ApiFixture(Path(temporary.name))

    def assert_screened_with(self, response, model):
        self.assertEqual(response.status_code, 200, response.text)
        self.assertRegex(response.headers["x-request-id"], r"^[a-f0-9]{32}$")
        body = response.json()
        expected = self.fixture.settings.for_retrieval(model)
        self.assertEqual(body["mode"], "live")
        self.assertEqual(body["result_status"], "OK")
        self.assertEqual(body["errors"], [])
        self.assertEqual(body["provenance"]["retrieval_model"], model)
        self.assertEqual(body["provenance"]["embedding_model"], expected.embedding_model)
        self.assertEqual(
            body["provenance"]["generation_model"], self.fixture.settings.generation_model
        )
        self.assertEqual(len(body["candidate_trials"]), 1)
        trial = body["candidate_trials"][0]
        self.assertEqual(trial["trial_id"], self.fixture.trial_id)
        self.assertEqual(trial["retrieval"]["method"], "hybrid_rrf")
        self.assertEqual(trial["retrieval"]["semantic_hit"]["trial_id"], self.fixture.trial_id)
        self.assertIn(
            trial["retrieval"]["semantic_hit"]["criterion_id"],
            {criterion["criterion_id"] for criterion in self.fixture.criteria},
        )
        configuration = body["provenance"]["embedding_configuration"]
        if model == "finetuned":
            self.assertEqual(configuration["provider"], "bioclinical")
            self.assertEqual(configuration["revision"], expected.embedding_revision)
            self.assertEqual(
                configuration["checkpoint_sha256"], expected.embedding_checkpoint_sha256
            )
            self.assertEqual(body["metrics"]["embedding_requests"], 0)
            self.assertEqual(body["metrics"]["retrieval_encoder"]["embedding_requests"], 1)
        else:
            self.assertEqual(configuration, {})
            self.assertEqual(body["metrics"]["embedding_requests"], 1)
            self.assertNotIn("retrieval_encoder", body["metrics"])
        return body

    def test_per_request_selection_uses_matching_vectors_without_state_leakage(self):
        gemini = self.fixture.build_index("gemini")
        finetuned = self.fixture.build_index("finetuned")
        self.assertNotEqual(gemini.version, finetuned.version)
        with (
            self.fixture.providers() as providers,
            TestClient(create_app(self.fixture.settings)) as client,
        ):
            for model in ("gemini", "finetuned", "gemini"):
                with self.subTest(model=model, request_number=len(providers)):
                    previous_count = len(providers)
                    response = client.post(
                        "/screen", json={**self.fixture.payload, "retrieval_model": model}
                    )
                    self.assert_screened_with(response, model)
                    current = providers[previous_count:]
                    encoders = [p for p in current if p.metrics["embedding_requests"]]
                    self.assertEqual(len(encoders), 1)
                    self.assertEqual(
                        encoders[0].settings.dimension, 768 if model == "finetuned" else 256
                    )
                    self.assertEqual(
                        encoders[0].settings.embedding_provider,
                        "bioclinical" if model == "finetuned" else "gemini",
                    )
                    self.assertTrue(all(provider.closed for provider in current))

    def test_omitted_or_null_model_uses_server_configured_encoder(self):
        index = self.fixture.build_index("finetuned")
        configured = self.fixture.settings.for_retrieval("finetuned")
        with (
            self.fixture.providers() as providers,
            TestClient(create_app(configured)) as client,
        ):
            readiness = client.get("/ready")
            self.assertEqual(readiness.status_code, 200, readiness.text)
            self.assertEqual(readiness.json()["checks"]["index"]["index_version"], index.version)
            self.assertEqual(providers, [])
            for selection in ({}, {"retrieval_model": None}):
                with self.subTest(selection=selection):
                    response = client.post("/screen", json={**self.fixture.payload, **selection})
                    self.assert_screened_with(response, "finetuned")

    def test_readiness_checks_each_real_selected_index_without_creating_models(self):
        indexes = {model: self.fixture.build_index(model) for model in ("gemini", "finetuned")}
        with (
            self.fixture.providers() as providers,
            TestClient(create_app(self.fixture.settings)) as client,
        ):
            reports = {}
            for model, index in indexes.items():
                response = client.get("/ready", params={"retrieval_model": model})
                self.assertEqual(response.status_code, 200, response.text)
                reports[model] = response.json()
                self.assertEqual(reports[model]["model_access"], "NOT_PROBED")
                self.assertEqual(reports[model]["checks"]["index"]["index_version"], index.version)
                self.assertEqual(reports[model]["checks"]["index"]["vector_count"], 3)
            for model in ("finetuned", "gemini"):
                self.assertEqual(
                    client.get("/ready", params={"retrieval_model": model}).json(), reports[model]
                )
            self.assertEqual(providers, [])

    def test_missing_selected_index_does_not_reuse_other_readiness_or_fallback(self):
        gemini = self.fixture.build_index("gemini")
        with (
            self.fixture.providers() as providers,
            TestClient(create_app(self.fixture.settings)) as client,
        ):
            available = client.get("/ready", params={"retrieval_model": "gemini"})
            self.assertEqual(available.status_code, 200)
            self.assertEqual(available.json()["checks"]["index"]["index_version"], gemini.version)
            missing = client.get("/ready", params={"retrieval_model": "finetuned"})
            self.assertEqual(missing.status_code, 503)
            self.assertEqual(missing.json()["checks"]["index"]["code"], "INDEX_NOT_READY")
            self.assertEqual(providers, [])
            response = client.post(
                "/screen", json={**self.fixture.payload, "retrieval_model": "finetuned"}
            )
            self.assertEqual(response.status_code, 503, response.text)
            body = response.json()
            self.assertEqual(body["result_status"], "ERROR")
            self.assertEqual(body["candidate_trials"], [])
            self.assertEqual(body["errors"][0]["code"], "INDEX_NOT_READY")
            self.assertEqual(body["provenance"]["retrieval_model"], "finetuned")
            self.assertTrue(providers)
            self.assertTrue(
                all(p.closed and p.metrics["generation_requests"] == 0 for p in providers)
            )
            self.assertEqual(
                client.get("/ready", params={"retrieval_model": "gemini"}).json(), available.json()
            )
            self.assert_screened_with(
                client.post("/screen", json={**self.fixture.payload, "retrieval_model": "gemini"}),
                "gemini",
            )

    def test_offline_selection_is_rejected_without_creating_models(self):
        settings = replace(self.fixture.settings, mode="offline")
        with self.fixture.providers() as providers, TestClient(create_app(settings)) as client:
            for model in ("gemini", "finetuned"):
                with self.subTest(model=model):
                    response = client.post(
                        "/screen", json={**self.fixture.payload, "retrieval_model": model}
                    )
                    self.assertEqual(response.status_code, 422, response.text)
                    self.assertEqual(
                        response.json()["detail"], "Retrieval model selection requires live mode"
                    )
                    readiness = client.get("/ready", params={"retrieval_model": model})
                    self.assertEqual(readiness.status_code, 200)
                    self.assertEqual(readiness.json()["model_access"], "NOT_REQUIRED")
                    self.assertEqual(readiness.json()["checks"]["index"]["status"], "NOT_REQUIRED")
            for selection in ({}, {"retrieval_model": None}):
                response = client.post("/screen", json={**self.fixture.payload, **selection})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["provenance"]["retrieval_model"], "bm25")
            self.assertEqual(providers, [])
            self.assertFalse((self.fixture.settings.artifacts / "chroma").exists())

    def test_invalid_model_is_rejected_by_screen_and_readiness(self):
        with (
            self.fixture.providers() as providers,
            TestClient(create_app(self.fixture.settings)) as client,
        ):
            for model in ("bioclinical", "unknown", ""):
                with self.subTest(model=model):
                    responses = [
                        client.post(
                            "/screen", json={**self.fixture.payload, "retrieval_model": model}
                        ),
                        client.get("/ready", params={"retrieval_model": model}),
                    ]
                    for response in responses:
                        self.assertEqual(response.status_code, 422, response.text)
                        self.assertIsInstance(response.json()["detail"], list)
                        self.assertNotIn("candidate_trials", response.json())
            self.assertEqual(providers, [])


if __name__ == "__main__":
    unittest.main()
