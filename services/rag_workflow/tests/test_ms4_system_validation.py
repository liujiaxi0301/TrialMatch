"""MS4 system validation: corrupted source data must fail closed."""

import copy
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from services.rag_workflow.config import Settings
from services.rag_workflow.data import DataStore


class SystemValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings = Settings(mode="offline")
        store = DataStore(cls.settings)

        trial_id = next(tid for tid, rows in store.criteria.items() if rows)
        cls.trial = store.trials[trial_id]
        cls.criterion = store.criteria[trial_id][0]
        cls.patient = next(iter(store.patients.values()))

    def test_corrupted_source_data_rejected(self):
        trial = self.trial
        criterion = self.criterion
        patient = self.patient

        scenarios = [
            (
                "duplicate_trial_id",
                [trial, trial],
                [criterion],
                [patient],
                "Duplicate trial_id or patient_id",
            ),
            (
                "duplicate_patient_id",
                [trial],
                [criterion],
                [patient, patient],
                "Duplicate trial_id or patient_id",
            ),
            (
                "duplicate_criterion_id",
                [trial],
                [criterion, criterion],
                [patient],
                "Duplicate criterion_id",
            ),
            (
                "orphan_criterion",
                [trial],
                [{**criterion, "trial_id": "NCT99999999"}],
                [patient],
                "Orphan criterion",
            ),
        ]

        for name, trials, criteria, patients, error in scenarios:
            with self.subTest(scenario=name):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)

                    for filename, records in (
                        ("trials", trials),
                        ("criteria", criteria),
                        ("patients", patients),
                    ):
                        path = root / f"{filename}.jsonl"
                        path.write_text(
                            "".join(json.dumps(record) + "\n" for record in copy.deepcopy(records)),
                            encoding="utf-8",
                        )

                    settings = replace(
                        self.settings,
                        trials_path=root / "trials.jsonl",
                        criteria_path=root / "criteria.jsonl",
                        patients_path=root / "patients.jsonl",
                    )

                    with self.assertRaisesRegex(ValueError, error):
                        DataStore(settings)


if __name__ == "__main__":
    unittest.main()
