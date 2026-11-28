"""Exercise active-encoder changes through the real API and embedded Chroma.

Checkpoint files and model adapters are synthetic. Selection validation, index
construction/verification, switch/rollback, workflow and request logging are real;
these tests never download weights or make a cloud/model request.
"""

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from unittest.mock import patch

from fastapi.testclient import TestClient

from services.frontend.app import create_app
from services.rag_workflow import encoders
from services.rag_workflow.data import DataStore
from services.rag_workflow.embedding_providers import checkpoint_digest
from services.rag_workflow.encoders import selection_path
from services.rag_workflow.index import VectorIndex
from services.rag_workflow.index_switching import rollback_encoder, switch_encoder
from services.rag_workflow.providers import ProviderError
from services.rag_workflow.tests.api_fixtures import ApiFixture, DeterministicProvider


class ApiSelectionLifecycleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(temporary.cleanup)
        directory = Path(temporary.name)
        sample = next(iter(encoders.ENCODERS.values()))
        self.catalog = {}
        for name in ("fixture-a", "fixture-b"):
            checkpoint = directory / name
            checkpoint.mkdir()
            (checkpoint / "model.safetensors").write_bytes(name.encode())
            digest, _ = checkpoint_digest(checkpoint)
            self.catalog[name] = replace(
                sample,
                name=name,
                checkpoint=str(checkpoint),
                checkpoint_sha256=digest,
                evaluated=True,
            )
        self.enterContext(patch.object(encoders, "ENCODERS", MappingProxyType(self.catalog)))
        self.enterContext(patch.object(encoders, "DEFAULT_FINETUNED", "fixture-a"))
        self.fixture = ApiFixture(directory)
        self.default_index = self.fixture.build_index("finetuned")
        self.store = DataStore(self.fixture.settings)
        self.manifest = self.store.manifest()
        self.record_path = selection_path(self.fixture.settings)
        self.payload = {**self.fixture.payload, "retrieval_model": "finetuned"}

    def switch(self, name="fixture-b"):
        return switch_encoder(
            self.fixture.settings,
            self.store,
            self.manifest,
            name,
            provider_factory=DeterministicProvider,
        )

    def rollback(self):
        return rollback_encoder(self.fixture.settings, self.store, self.manifest)

    def assert_selected_response(self, response, name):
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["result_status"], "OK")
        self.assertEqual(body["errors"], [])
        self.assertEqual(body["provenance"]["retrieval_model"], "finetuned")
        self.assertEqual(
            body["provenance"]["embedding_configuration"]["checkpoint_sha256"],
            self.catalog[name].checkpoint_sha256,
        )
        self.assertEqual(len(body["candidate_trials"]), 1)
        self.assertEqual(body["candidate_trials"][0]["retrieval"]["method"], "hybrid_rrf")
        self.assertRegex(response.headers["x-request-id"], r"^[a-f0-9]{32}$")
        return body

    def assert_ready(self, client, index_version):
        response = client.get("/ready", params={"retrieval_model": "finetuned"})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["ready"])
        self.assertEqual(body["checks"]["index"]["index_version"], index_version)
        self.assertEqual(body["model_access"], "NOT_PROBED")
        return body

    def assert_invalid_selection(self, client):
        ready = client.get("/ready", params={"retrieval_model": "finetuned"})
        screen = client.post("/screen", json=self.payload)
        for response in (ready, screen):
            self.assertEqual(response.status_code, 503, response.text)
            self.assertRegex(response.headers["x-request-id"], r"^[a-f0-9]{32}$")
            self.assertNotIn(str(self.record_path), response.text)
        report = ready.json()
        self.assertFalse(report["ready"])
        self.assertEqual(report["check_scope"], "encoder_selection")
        self.assertEqual(report["cache_ttl_seconds"], 0)
        self.assertEqual(report["model_access"], "NOT_PROBED")
        self.assertEqual(report["checks"]["encoder_selection"]["code"], "ENCODER_SELECTION_INVALID")
        self.assertEqual(screen.json()["detail"]["code"], "ENCODER_SELECTION_INVALID")
        self.assertNotIn("candidate_trials", screen.json())

    def assert_log_matches(self, records, response, name):
        matches = [
            record.event_fields
            for record in records
            if record.getMessage() == "screening_completed"
            and record.event_fields["request_id"] == response.headers["x-request-id"]
        ]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["run_id"], response.json()["run_id"])
        self.assertEqual(
            matches[0]["embedding_checkpoint_sha256"], self.catalog[name].checkpoint_sha256
        )

    def test_same_app_follows_default_switch_and_rollback_without_model_readiness_calls(self):
        with (
            self.fixture.providers() as providers,
            TestClient(create_app(self.fixture.settings)) as client,
        ):
            self.assert_ready(client, self.default_index.version)
            self.assertEqual(providers, [])
            self.assert_selected_response(client.post("/screen", json=self.payload), "fixture-a")

            switched = self.switch()
            count = len(providers)
            self.assert_ready(client, switched["index_version"])
            self.assertEqual(len(providers), count)
            self.assert_selected_response(client.post("/screen", json=self.payload), "fixture-b")

            rolled_back = self.rollback()
            count = len(providers)
            self.assert_ready(client, rolled_back["index_version"])
            self.assertEqual(rolled_back["index_version"], self.default_index.version)
            self.assertEqual(len(providers), count)
            self.assert_selected_response(client.post("/screen", json=self.payload), "fixture-a")

    def test_cold_corrupt_selection_is_503_then_recovers_without_restarting_app(self):
        self.record_path.write_text("{broken")
        with (
            self.fixture.providers() as providers,
            TestClient(create_app(self.fixture.settings)) as client,
        ):
            self.assert_invalid_selection(client)
            self.assertEqual(providers, [])
            self.record_path.unlink()
            self.assert_ready(client, self.default_index.version)
            self.assertEqual(providers, [])
            self.assert_selected_response(client.post("/screen", json=self.payload), "fixture-a")

    def test_rollback_rechecks_previous_encoder_instead_of_reusing_cached_pass(self):
        with (
            self.fixture.providers() as providers,
            TestClient(create_app(self.fixture.settings)) as client,
        ):
            self.assert_ready(client, self.default_index.version)
            switched = self.switch()
            self.assert_ready(client, switched["index_version"])
            rolled_back = self.rollback()
            self.assertEqual(rolled_back["index_version"], self.default_index.version)
            # Rollback validated A, but its manifest was lost before the next probe.
            self.default_index.manifest_path.unlink()
            response = client.get("/ready", params={"retrieval_model": "finetuned"})
            self.assertEqual(response.status_code, 503, response.text)
            self.assertEqual(response.json()["checks"]["index"]["code"], "INDEX_NOT_READY")
            self.assertEqual(providers, [])

    def test_warm_corrupt_selection_is_not_hidden_by_readiness_cache(self):
        switched = self.switch()
        original = self.record_path.read_bytes()
        with (
            self.fixture.providers() as providers,
            TestClient(create_app(self.fixture.settings)) as client,
        ):
            for content in (b"{broken", b"\xff"):
                with self.subTest(content=content):
                    self.assert_ready(client, switched["index_version"])
                    self.record_path.write_bytes(content)
                    try:
                        self.assert_invalid_selection(client)
                        self.assertEqual(providers, [])
                    finally:
                        self.record_path.write_bytes(original)
                    self.assert_ready(client, switched["index_version"])
                    self.assertEqual(providers, [])
            self.assert_selected_response(client.post("/screen", json=self.payload), "fixture-b")

    def test_restored_record_rechecks_index_instead_of_reusing_old_cached_pass(self):
        switched = self.switch()
        original = self.record_path.read_bytes()
        selected = VectorIndex(
            self.fixture.settings.for_retrieval("finetuned"), self.store, self.manifest
        )
        with (
            self.fixture.providers() as providers,
            TestClient(create_app(self.fixture.settings)) as client,
        ):
            self.assert_ready(client, switched["index_version"])
            self.record_path.write_text("{broken")
            self.assert_invalid_selection(client)
            selected.manifest_path.unlink()
            self.record_path.write_bytes(original)
            response = client.get("/ready", params={"retrieval_model": "finetuned"})
            self.assertEqual(response.status_code, 503, response.text)
            self.assertEqual(response.json()["checks"]["index"]["code"], "INDEX_NOT_READY")
            self.assertEqual(providers, [])

    def test_mid_request_switch_keeps_response_and_log_on_original_encoder(self):
        changed = []
        switch = self.switch

        class SwitchingProvider(DeterministicProvider):
            def generate(self, *args, **kwargs):
                if not changed:
                    changed.append(switch())
                return super().generate(*args, **kwargs)

        with (
            self.fixture.providers(SwitchingProvider),
            TestClient(create_app(self.fixture.settings)) as client,
            self.assertLogs("trialmatch.api", level="INFO") as captured,
        ):
            first = client.post("/screen", json=self.payload)
            self.assert_selected_response(first, "fixture-a")
            second = client.post("/screen", json=self.payload)
            self.assert_selected_response(second, "fixture-b")
        self.assertEqual(len(changed), 1)
        self.assert_log_matches(captured.records, first, "fixture-a")
        self.assert_log_matches(captured.records, second, "fixture-b")

    def test_mid_request_corruption_does_not_discard_completed_response(self):
        changed = []
        path = self.record_path

        class CorruptingProvider(DeterministicProvider):
            def generate(self, *args, **kwargs):
                if not changed:
                    changed.append(True)
                    path.write_text("{broken")
                return super().generate(*args, **kwargs)

        with (
            self.fixture.providers(CorruptingProvider),
            TestClient(create_app(self.fixture.settings)) as client,
            self.assertLogs("trialmatch.api", level="INFO") as captured,
        ):
            first = client.post("/screen", json=self.payload)
            self.assert_selected_response(first, "fixture-a")
            self.assert_invalid_selection(client)
        self.assert_log_matches(captured.records, first, "fixture-a")

    def test_failed_switch_preserves_current_api_encoder(self):
        switched = self.switch()
        original = self.record_path.read_bytes()
        with self.fixture.providers(), TestClient(create_app(self.fixture.settings)) as client:
            self.assert_ready(client, switched["index_version"])
            checkpoint = Path(self.catalog["fixture-a"].checkpoint) / "model.safetensors"
            checkpoint.write_bytes(b"not-the-registered-checkpoint")
            with self.assertRaises(ProviderError) as raised:
                self.switch("fixture-a")
            self.assertEqual(raised.exception.code, "EMBEDDING_CHECKPOINT_MISMATCH")
            self.assertEqual(self.record_path.read_bytes(), original)
            self.assert_ready(client, switched["index_version"])
            self.assert_selected_response(client.post("/screen", json=self.payload), "fixture-b")

    def test_refused_rollback_preserves_current_api_encoder(self):
        switched = self.switch()
        original = self.record_path.read_bytes()
        with self.fixture.providers(), TestClient(create_app(self.fixture.settings)) as client:
            self.assert_ready(client, switched["index_version"])
            self.default_index.manifest_path.unlink()
            with self.assertRaises(ProviderError) as raised:
                self.rollback()
            self.assertEqual(raised.exception.code, "ROLLBACK_TARGET_NOT_READY")
            self.assertEqual(self.record_path.read_bytes(), original)
            self.assert_ready(client, switched["index_version"])
            self.assert_selected_response(client.post("/screen", json=self.payload), "fixture-b")

    def test_invalid_active_and_previous_types_are_selection_errors(self):
        self.switch()
        original = json.loads(self.record_path.read_text())
        with (
            self.fixture.providers() as providers,
            TestClient(create_app(self.fixture.settings)) as client,
        ):
            for field, value in (("active", []), ("previous", {})):
                with self.subTest(field=field):
                    self.record_path.write_text(json.dumps({**original, field: value}))
                    self.assert_invalid_selection(client)
            self.assertEqual(providers, [])

    def test_patient_validation_and_unknown_patient_keep_existing_statuses(self):
        with (
            self.fixture.providers() as providers,
            TestClient(create_app(self.fixture.settings)) as client,
        ):
            invalid_patient = {**self.fixture.patient, "observations": "not-an-array"}
            response = client.post(
                "/screen",
                json={
                    "patient": invalid_patient,
                    "question": self.payload["question"],
                    "retrieval_model": "finetuned",
                },
            )
            self.assertEqual(response.status_code, 422)
            self.assertNotIn("candidate_trials", response.json())
            missing = client.post("/screen", json={**self.payload, "patient_id": "not-present"})
            self.assertEqual(missing.status_code, 404)
            self.assertEqual(missing.json()["detail"], "Patient not found")
            self.assertEqual(providers, [])

    def test_omitted_null_and_gemini_ignore_unrelated_corrupt_finetuned_record(self):
        gemini = self.fixture.build_index("gemini")
        self.record_path.write_text("{broken")
        with (
            self.fixture.providers() as providers,
            TestClient(create_app(self.fixture.settings)) as client,
        ):
            for choice in ({}, {"retrieval_model": None}, {"retrieval_model": "gemini"}):
                with self.subTest(choice=choice):
                    before = len(providers)
                    params = {key: value for key, value in choice.items() if value is not None}
                    ready = client.get("/ready", params=params)
                    self.assertEqual(ready.status_code, 200, ready.text)
                    self.assertEqual(
                        ready.json()["checks"]["index"]["index_version"], gemini.version
                    )
                    self.assertEqual(len(providers), before)
                    response = client.post("/screen", json={**self.fixture.payload, **choice})
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(response.json()["result_status"], "OK")
                    self.assertEqual(response.json()["provenance"]["retrieval_model"], "gemini")
                    self.assertEqual(response.json()["provenance"]["embedding_configuration"], {})


if __name__ == "__main__":
    unittest.main()
