"""Prepare the fixed offline data using Part 1's existing criterion parser."""

import hashlib
import json
import shutil
from pathlib import Path

from services.trial_ingestion.scripts.parse_criteria import parse_trial_criteria

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "artifacts/infra/data"
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
        raise ValueError("Parsed criteria differ from Part 1's committed snapshot")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(sources["trials"], OUTPUT / "trials.jsonl")
    (OUTPUT / "criteria.jsonl").write_bytes(parsed)
    shutil.copyfile(PATIENTS, OUTPUT / "patients.jsonl")
    shutil.copyfile(MANIFEST, OUTPUT / "demo_manifest.json")
    (OUTPUT / "data_versions.json").write_text(
        json.dumps(versions, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Prepared {len(trials)} trials and {len(criteria)} criteria in {OUTPUT}")
    print("Copied Part 2's 25-patient snapshot. Source files were not changed.")
    print("Raw trial ingestion is pending the original snapshot; no data was downloaded.")


if __name__ == "__main__":
    main()
