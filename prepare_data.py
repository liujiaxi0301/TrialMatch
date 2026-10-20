"""Validate the existing source data and record its versions."""

import hashlib
import json
from pathlib import Path

from services.trial_ingestion.scripts.parse_criteria import parse_trial_criteria

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "artifacts/infra"
TRIAL_DATA = ROOT / "services/trial_ingestion/data/processed"
PATIENTS = ROOT / "services/patient_processing/data/processed/batch25_patients.jsonl"
MANIFEST = ROOT / "services/rag_workflow/examples/demo_manifest.json"


def main():
    sources = {
        "trials": TRIAL_DATA / "trials.jsonl",
        "criteria": TRIAL_DATA / "criteria.jsonl",
        "patients": PATIENTS,
    }
    manifest = json.loads(MANIFEST.read_text())
    versions = {}
    for name, source in sources.items():
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if digest != manifest["source_sha256"][name]:
            raise ValueError(f"{name} does not match the supplied demo manifest")
        versions[name] = {"source": str(source.relative_to(ROOT)), "sha256": digest}

    trials = [json.loads(line) for line in sources["trials"].read_text().splitlines()]
    criteria = [criterion for trial in trials for criterion in parse_trial_criteria(trial)]
    parsed = "".join(json.dumps(criterion) + "\n" for criterion in criteria).encode("utf-8")
    if parsed != sources["criteria"].read_bytes():
        raise ValueError("Parsed criteria differ from the committed snapshot")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "data_versions.json").write_text(
        json.dumps(versions, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Validated {len(trials)} trials and {len(criteria)} criteria.")
    print(f"Saved data versions to {OUTPUT / 'data_versions.json'}")
    print("The app reads source data directly from services/.")


if __name__ == "__main__":
    main()
