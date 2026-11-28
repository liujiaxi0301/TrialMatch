import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from services.frontend.app import create_app
from services.rag_workflow.config import Settings


class ApplicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.settings = replace(
            Settings(), mode="offline", artifacts=Path(cls.temp.name), chroma_host=""
        )
        cls.client = TestClient(create_app(cls.settings))
        cls.patient_id = "060e72d3-912e-55cd-0c92-5faa6cb7a6db"
        cls.request = {
            "patient_id": cls.patient_id,
            "question": "Find type 2 diabetes trials with HbA1c eligibility criteria",
            "top_k": 2,
        }

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.temp.cleanup()

    def test_actual_patient_and_static_app(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/assets/app.js").status_code, 200)
        self.assertEqual(len(self.client.get("/patients").json()["patients"]), 25)
        self.assertEqual(
            self.client.get(f"/patients/{self.patient_id}").json()["schema_version"], "0.3"
        )
        self.assertEqual(self.client.get("/patients/not-present").status_code, 404)

    def test_separate_backend_keeps_api_without_static_routes(self):
        with TestClient(create_app(self.settings, serve_ui=False)) as client:
            self.assertEqual(client.get("/").status_code, 404)
            self.assertEqual(client.get("/assets/app.js").status_code, 404)
            self.assertEqual(client.get("/health").status_code, 200)
            self.assertEqual(client.post("/screen", json=self.request).status_code, 200)

    def test_real_offline_screen_and_evidence(self):
        response = self.client.post("/screen", json=self.request)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["mode"], "offline")
        self.assertEqual(body["result_status"], "OK")
        self.assertEqual(len(body["candidate_trials"]), 2)
        for trial in body["candidate_trials"]:
            self.assertIsNone(trial["eligibility_probability"])
            self.assertTrue(trial["trial_id"].startswith("NCT"))
            for assessment in trial["criteria_assessments"]:
                self.assertTrue(set(assessment["evidence_fact_ids"]).issubset(trial["evidence"]))

    def test_invalid_input_has_no_mock_fallback(self):
        for change, status in [
            ({"patient_id": "missing"}, 404),
            ({"question": " "}, 422),
            ({"top_k": 6}, 422),
        ]:
            self.assertEqual(
                self.client.post("/screen", json={**self.request, **change}).status_code, status
            )


if __name__ == "__main__":
    unittest.main()
