"""Validate source data, or reproduce the trial snapshot before validation."""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from services.trial_ingestion.scripts.parse_criteria import parse_trial_criteria

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "artifacts/infra"
TRIAL_DATA = ROOT / "services/trial_ingestion/data/processed"
PATIENTS = ROOT / "services/patient_processing/data/processed/batch25_patients.jsonl"
MANIFEST = ROOT / "services/rag_workflow/examples/demo_manifest.json"
REBUILD_SCRIPT = ROOT / "services/trial_ingestion/scripts/rebuild_snapshot.py"
RAW_MANIFEST = ROOT / "services/trial_ingestion/data/raw_snapshot.json"


def rebuild_trials(manifest):
    if not REBUILD_SCRIPT.is_file() or not RAW_MANIFEST.is_file():
        raise SystemExit(
            "Raw snapshot handoff is incomplete: rebuild_snapshot.py and "
            "data/raw_snapshot.json are required. See README.md under Data Reproduction."
        )

    with TemporaryDirectory(prefix="trialmatch-trials-") as directory:
        output = Path(directory)
        subprocess.run(
            [sys.executable, str(REBUILD_SCRIPT), "--output", str(output)],
            check=True,
        )
        # Check both outputs before replacing either committed source file.
        for name in ("trials", "criteria"):
            source = output / f"{name}.jsonl"
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            if digest != manifest["source_sha256"][name]:
                raise SystemExit(
                    f"Rebuilt {name} does not match the demo manifest. "
                    "Existing processed data was not changed."
                )
        for name in ("trials", "criteria"):
            shutil.copyfile(output / f"{name}.jsonl", TRIAL_DATA / f"{name}.jsonl")


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
                "source": str(RAW_MANIFEST.relative_to(ROOT)),
                "sha256": hashlib.sha256(RAW_MANIFEST.read_bytes()).hexdigest(),
            },
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
