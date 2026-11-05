"""Validate source data, or reproduce the trial snapshot before validation."""

import argparse
import hashlib
import json
from pathlib import Path

from services.trial_ingestion.scripts.normalize_trial import normalize_trial, is_t2d_related
from services.trial_ingestion.scripts.parse_criteria import parse_trial_criteria

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "artifacts/infra"
TRIAL_DATA = ROOT / "services/trial_ingestion/data/processed"
PATIENTS = ROOT / "services/patient_processing/data/processed/batch25_patients.jsonl"
MANIFEST = ROOT / "services/rag_workflow/examples/demo_manifest.json"
RAW_DATA = ROOT / "services/trial_ingestion/data/raw"
RAW_METADATA = ROOT / "services/trial_ingestion/data/raw_metadata.json"


def rebuild_trials(manifest):
    metadata = json.loads(RAW_METADATA.read_text(encoding="utf-8"))
    raw_files = sorted(RAW_DATA.glob("*.json"))
    if len(raw_files) != metadata["raw_file_count"]:
        raise SystemExit(
            "Raw trial count does not match raw_metadata.json. "
            "Run make reproduce to restore the DVC snapshot."
        )

    snapshot_date, = manifest["trial_snapshot_dates"]
    trials = []
    for source in raw_files:
        trial = normalize_trial(json.loads(source.read_text(encoding="utf-8")))
        if is_t2d_related(trial):
            # Reproduce the recorded processing date, not today's date.
            trial["snapshot_date"] = snapshot_date
            trials.append(trial)
    criteria = [criterion for trial in trials for criterion in parse_trial_criteria(trial)]
    outputs = {
        name: "".join(json.dumps(record) + "\n" for record in records).encode("utf-8")
        for name, records in (("trials", trials), ("criteria", criteria))
    }

    # Check both outputs before replacing either committed source file.
    for name, content in outputs.items():
        if hashlib.sha256(content).hexdigest() != manifest["source_sha256"][name]:
            raise SystemExit(
                f"Rebuilt {name} does not match the demo manifest. "
                "Existing processed data was not changed."
            )
    TRIAL_DATA.mkdir(parents=True, exist_ok=True)
    for name, content in outputs.items():
        (TRIAL_DATA / f"{name}.jsonl").write_bytes(content)
    print(f"Rebuilt trial data from {len(raw_files)} raw records, dated {snapshot_date}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-raw", action="store_true", help="Rebuild the fixed trial snapshot.")
    args = parser.parse_args()

    sources = {
        "trials": TRIAL_DATA / "trials.jsonl",
        "criteria": TRIAL_DATA / "criteria.jsonl",
        "patients": PATIENTS,
    }
    manifest = json.loads(MANIFEST.read_text())
    if args.from_raw:
        rebuild_trials(manifest)

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
    if args.from_raw:
        reproduction = {
            "raw_snapshot": {
                "source": str(RAW_METADATA.relative_to(ROOT)),
                "sha256": hashlib.sha256(RAW_METADATA.read_bytes()).hexdigest(),
            },
            "trial_snapshot_dates": manifest["trial_snapshot_dates"],
            "outputs": versions,
        }
        (OUTPUT / "raw_reproduction.json").write_text(
            json.dumps(reproduction, indent=2) + "\n", encoding="utf-8"
        )
    print(f"Validated {len(trials)} trials and {len(criteria)} criteria.")
    print(f"Saved data versions to {OUTPUT / 'data_versions.json'}")
    print("The app reads source data directly from services/.")


if __name__ == "__main__":
    main()
