import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from services.frontend.app import create_app
from services.frontend.vector_demo import LocalVectorDemo, TokenHashProvider
from services.rag_workflow.config import Settings


class ApplicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.settings = replace(Settings(), mode="offline", artifacts=Path(cls.temp.name), chroma_host="")
        cls.client = TestClient(create_app(cls.settings))
        cls.patient_id = "060e72d3-912e-55cd-0c92-5faa6cb7a6db"
        cls.request = {"patient_id": cls.patient_id, "question": "Find type 2 diabetes trials with HbA1c eligibility criteria", "top_k": 2}

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.temp.cleanup()

    def test_actual_patient_and_static_app(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/assets/app.js").status_code, 200)
        self.assertEqual(len(self.client.get("/patients").json()["patients"]), 25)
        self.assertEqual(self.client.get(f"/patients/{self.patient_id}").json()["schema_version"], "0.3")
        self.assertEqual(self.client.get("/patients/not-present").status_code, 404)

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
        for change, status in [({"patient_id":"missing"},404),({"question":" "},422),({"top_k":6},422)]:
            self.assertEqual(self.client.post("/screen",json={**self.request,**change}).status_code,status)

    def test_chroma_context_and_persistence(self):
        demo = LocalVectorDemo(self.settings)
        index = demo.build()
        self.assertEqual(index["vector_count"], 607)
        first = self.client.post("/retrieve", json=self.request)
        self.assertEqual(first.status_code, 200)
        body = first.json()
        self.assertEqual(len(body["chunks"]), 2)
        actual = {key: text for key,text,_ in demo.index.fragments()}
        for chunk in body["chunks"]:
            self.assertEqual(chunk["text"], actual[chunk["chunk_id"]])
        restored = LocalVectorDemo(self.settings).retrieve(self.patient_id,self.request["question"],2)
        self.assertEqual([x["chunk_id"] for x in body["chunks"]],[x["chunk_id"] for x in restored["chunks"]])

    def test_hash_vectors_are_stable_and_normalized(self):
        provider=TokenHashProvider()
        vector=provider.embed("type 2 diabetes HbA1c")
        self.assertEqual(vector,provider.embed("type 2 diabetes HbA1c"))
        self.assertAlmostEqual(sum(x*x for x in vector),1.0)


if __name__ == "__main__":
    unittest.main()
