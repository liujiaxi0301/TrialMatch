"""Exercise real HTTP/workflow/index failure paths without remote model calls."""

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
from fastapi.testclient import TestClient

from services.frontend.app import create_app
from services.rag_workflow.observability import JsonFormatter
from services.rag_workflow.providers import ProviderError
from services.rag_workflow.schemas import LLMExplanation, LLMJudgments, ScreenResponse
from services.rag_workflow.tests.api_fixtures import ApiFixture, DeterministicProvider


class AssessmentUnavailable(DeterministicProvider):
    def generate(self, system, payload, schema):
        self.metrics["generation_requests"] += 1
        raise ProviderError("GCP_503", "private-provider-marker")


class InvalidJudgments(DeterministicProvider):
    def generate(self, system, payload, schema):
        self.metrics["generation_requests"] += 1
        if schema is not LLMJudgments:
            raise AssertionError("Invalid assessments must not be explained as completed")
        return LLMJudgments(assessments=[])


class ExplanationUnavailable(DeterministicProvider):
    def generate(self, system, payload, schema):
        if schema is LLMExplanation:
            self.metrics["generation_requests"] += 1
            raise ProviderError("GCP_503", "private-provider-marker")
        return super().generate(system, payload, schema)


class ApiDependencyFailureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.fixture = ApiFixture(Path(temporary.name))

    def screen(self, client, payload=None):
        with self.assertLogs("trialmatch.api", level="INFO") as captured:
            response = client.post("/screen", json=payload or self.fixture.payload)
        events = [json.loads(JsonFormatter().format(record)) for record in captured.records]
        self.assertRegex(response.headers["x-request-id"], r"^[a-f0-9]{32}$")
        request = next(event for event in events if event["message"] == "http_request")
        self.assertEqual(request["status_code"], response.status_code)
        self.assertEqual(request["request_id"], response.headers["x-request-id"])
        self.assertNotIn("private-", response.text)
        self.assertNotIn("private-", json.dumps(events))
        if "run_id" in response.json():
            screening = next(event for event in events if event["message"] == "screening_completed")
            self.assertEqual(screening["run_id"], response.json()["run_id"])
            self.assertEqual(screening["request_id"], response.headers["x-request-id"])
        return response

    def assert_unavailable(self, response, code):
        self.assertEqual(response.status_code, 503, response.text)
        result = ScreenResponse.model_validate(response.json())
        self.assertEqual(result.result_status, "ERROR")
        self.assertEqual(result.candidate_trials, [])
        self.assertEqual(result.metrics["candidate_count"], 0)
        self.assertEqual([error.code for error in result.errors], [code])

    def assert_retained_assessments(self, response):
        self.assertEqual(response.status_code, 200, response.text)
        result = ScreenResponse.model_validate(response.json())
        self.assertEqual(result.result_status, "PARTIAL")
        self.assertEqual(len(result.candidate_trials), 1)
        trial = result.candidate_trials[0]
        self.assertEqual(trial.screening_status, "NEEDS_MORE_INFORMATION")
        self.assertEqual(trial.assessment_coverage.known, 1)
        self.assertEqual(trial.assessment_coverage.unknown, 2)
        self.assertEqual(trial.assessment_coverage.screening_barriers, 0)
        self.assertIsNone(trial.eligibility_probability)
        self.assertTrue(trial.review_required)
        age, *unsupported = trial.criteria_assessments
        self.assertEqual((age.decision, age.method), ("MET", "rule"))
        self.assertEqual(age.evidence_fact_ids, [self.fixture.patient["demographics"]["fact_id"]])
        self.assertTrue(set(age.evidence_fact_ids) <= set(trial.evidence))
        for assessment in unsupported:
            self.assertEqual(assessment.decision, "UNKNOWN")
            self.assertEqual(assessment.evidence_fact_ids, [])
            self.assertTrue(assessment.missing_information)
        return result, trial

    def test_missing_index_keeps_its_error_code_and_returns_no_candidates(self):
        with (
            self.fixture.providers() as providers,
            TestClient(create_app(self.fixture.settings)) as client,
        ):
            response = self.screen(client)
        self.assert_unavailable(response, "INDEX_NOT_READY")
        self.assertTrue(providers[0].closed)
        self.assertEqual(providers[0].metrics["generation_requests"], 0)

    def test_chroma_connection_failure_is_not_invalid_patient_input(self):
        settings = replace(self.fixture.settings, chroma_host="unused-test-host")
        with (
            self.fixture.providers() as providers,
            patch("chromadb.HttpClient", side_effect=ValueError("private-index-connection")),
            TestClient(create_app(settings)) as client,
        ):
            response = self.screen(client)
        self.assert_unavailable(response, "INDEX_UNAVAILABLE")
        self.assertTrue(providers[0].closed)

    def test_corrupt_index_manifest_is_not_a_client_validation_error(self):
        index = self.fixture.build_index()
        for invalid_json in ("{", "null", "[]"):
            with self.subTest(index_manifest=invalid_json):
                index.manifest_path.write_text(invalid_json)
                with (
                    self.fixture.providers() as providers,
                    TestClient(create_app(self.fixture.settings)) as client,
                ):
                    response = self.screen(client)
                self.assert_unavailable(response, "INDEX_UNAVAILABLE")
                self.assertTrue(providers[0].closed)

    def test_invalid_chroma_query_payload_is_not_a_missing_patient(self):
        self.fixture.build_index()
        trial = {
            "trial_id": self.fixture.trial_id,
            "criterion_id": self.fixture.criteria[0]["criterion_id"],
        }
        for payload in (
            {},
            {"metadatas": [[trial]], "distances": [[]]},
            {"metadatas": [[{}]], "distances": [[0.1]]},
            {"metadatas": [[{**trial, "trial_id": "AAA_UNKNOWN_TRIAL"}]], "distances": [[0.1]]},
            {
                "metadatas": [[{**trial, "criterion_id": "OTHER_TRIAL_inc_001"}]],
                "distances": [[0.1]],
            },
            {"metadatas": None, "distances": [[0.1]]},
            {"metadatas": [], "distances": []},
        ):
            with (
                self.subTest(query_payload=payload),
                self.fixture.providers(),
                patch("chromadb.api.models.Collection.Collection.query", return_value=payload),
                TestClient(create_app(self.fixture.settings)) as client,
            ):
                response = self.screen(client)
                self.assert_unavailable(response, "INDEX_UNAVAILABLE")

    def test_chroma_query_connection_error_is_a_dependency_failure(self):
        self.fixture.build_index()
        with (
            self.fixture.providers() as providers,
            patch(
                "chromadb.api.models.Collection.Collection.query",
                side_effect=ConnectionError("private-index-connection"),
            ),
            TestClient(create_app(self.fixture.settings)) as client,
        ):
            response = self.screen(client)
        self.assert_unavailable(response, "INDEX_UNAVAILABLE")
        self.assertTrue(providers[0].closed)

    def test_direct_index_timeout_preserves_504_and_releases_provider(self):
        self.fixture.build_index()
        with (
            self.fixture.providers() as providers,
            patch(
                "chromadb.api.models.Collection.Collection.query",
                side_effect=TimeoutError("private-index-timeout"),
            ),
            TestClient(create_app(self.fixture.settings)) as client,
        ):
            response = self.screen(client)
        self.assertEqual(response.status_code, 504)
        self.assertEqual(response.json()["detail"]["code"], "SCREENING_TIMEOUT")
        self.assertNotIn("candidate_trials", response.json())
        self.assertTrue(providers[0].closed)

    def test_sdk_timeout_is_wrapped_by_real_provider_and_propagates_as_503(self):
        self.fixture.build_index()
        sdk = Mock()
        sdk.models.embed_content.side_effect = httpx.ReadTimeout("private-provider-timeout")
        with (
            patch("google.genai.Client", return_value=sdk),
            patch("services.rag_workflow.providers.time.sleep") as sleep,
            TestClient(create_app(self.fixture.settings)) as client,
        ):
            response = self.screen(client)
        self.assert_unavailable(response, "PROVIDER_UNAVAILABLE")
        self.assertEqual(sdk.models.embed_content.call_count, 2)
        sleep.assert_called_once_with(1)
        sdk.models.generate_content.assert_not_called()
        sdk.close.assert_called_once_with()

    def test_assessment_provider_failure_retains_rules_and_evidence(self):
        self.fixture.build_index()
        with (
            self.fixture.providers(AssessmentUnavailable) as providers,
            TestClient(create_app(self.fixture.settings)) as client,
        ):
            result, trial = self.assert_retained_assessments(self.screen(client))
        self.assertEqual({error.code for error in result.errors}, {"GCP_503"})
        self.assertEqual(
            {error.criterion_id for error in result.errors},
            {criterion["criterion_id"] for criterion in self.fixture.criteria[1:]},
        )
        self.assertEqual(trial.assessment_coverage.completed, 1)
        self.assertEqual(providers[0].metrics["generation_requests"], 1)
        self.assertTrue(providers[0].closed)

    def test_invalid_model_output_is_bounded_and_retains_partial_results(self):
        self.fixture.build_index()
        with (
            self.fixture.providers(InvalidJudgments) as providers,
            TestClient(create_app(self.fixture.settings)) as client,
        ):
            result, _ = self.assert_retained_assessments(self.screen(client))
        self.assertEqual({error.code for error in result.errors}, {"INVALID_LLM_OUTPUT"})
        self.assertEqual(providers[0].metrics["generation_requests"], 2)
        self.assertTrue(providers[0].closed)

    def test_explanation_failure_preserves_assessments_and_marks_template(self):
        self.fixture.build_index()
        with (
            self.fixture.providers(ExplanationUnavailable),
            TestClient(create_app(self.fixture.settings)) as client,
        ):
            result, trial = self.assert_retained_assessments(self.screen(client))
        self.assertEqual([error.code for error in result.errors], ["GCP_503"])
        self.assertIn("TEMPLATE_EXPLANATION_AFTER_MODEL_ERROR", trial.warnings)
        self.assertIn(self.fixture.criteria[0]["criterion_id"], trial.question_response)

    def test_incomplete_data_manifest_is_an_artifact_failure(self):
        self.fixture.settings.manifest_path.write_text(
            json.dumps({"trial_ids": [self.fixture.trial_id]})
        )
        with (
            self.fixture.providers() as providers,
            TestClient(create_app(self.fixture.settings)) as client,
        ):
            response = self.screen(client)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"]["code"], "ARTIFACT_UNAVAILABLE")
        self.assertEqual(providers, [])

    def test_invalid_patient_input_still_returns_4xx_before_dependency_calls(self):
        with (
            self.fixture.providers() as providers,
            TestClient(create_app(self.fixture.settings)) as client,
        ):
            for payload, status in (
                ({**self.fixture.payload, "patient_id": "unknown"}, 404),
                ({"patient": {"schema_version": "wrong"}, "question": "Find trials"}, 422),
            ):
                with self.subTest(payload=payload):
                    self.assertEqual(self.screen(client, payload).status_code, status)
        self.assertEqual(providers, [])


if __name__ == "__main__":
    unittest.main()
