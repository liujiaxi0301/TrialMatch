"""Verify the exact pre-cleanup snapshot; optionally replay it in a temporary tree."""
import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def checked_name(name):
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name:
        raise ValueError(f"Invalid snapshot path: {name}")
    if not name.startswith(("services/patient_processing/", "evaluation/verification/")):
        raise ValueError(f"Snapshot path outside personal scope: {name}")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-checks", action="store_true",
                        help="Replay three historical checks and fifteen tests in a temporary tree")
    args = parser.parse_args()
    history = json.loads((ROOT / "manifest.json").read_text())["history_archive"]
    archive_path = ROOT / history["path"]
    if digest(archive_path.read_bytes()) != history["sha256"]:
        raise ValueError("History archive SHA-256 differs from the delivery index")
    with ZipFile(archive_path) as archive:
        snapshot = json.loads(archive.read(history["snapshot_member"]))
        expected = set(snapshot["files_sha256"]) | {history["snapshot_member"]}
        if set(archive.namelist()) != expected or len(archive.namelist()) != len(expected):
            raise ValueError("History archive has missing, extra or duplicate members")
        contents = {}
        for name, checksum in snapshot["files_sha256"].items():
            checked_name(name)
            data = archive.read(name)
            if digest(data) != checksum:
                raise ValueError(f"Archived file SHA-256 differs: {name}")
            contents[name] = data
    if len(contents) != history["preserved_files"]:
        raise ValueError("History file count differs from the delivery index")
    print(f"Verified exact pre-cleanup snapshot: {len(contents)} files.", flush=True)
    if not args.run_checks:
        return

    # Patient sources and old verification code are inside the snapshot. Only
    # the three pinned shared trial files are read from this checkout.
    sources = snapshot["external_sources_sha256"]
    if sources != history["external_sources_sha256"]:
        raise ValueError("Historical external-source declarations differ")
    with tempfile.TemporaryDirectory(prefix="trialmatch-history-") as temp:
        checkout = Path(temp)
        for name, data in contents.items():
            target = checkout / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        for name, checksum in sources.items():
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or not name.startswith("services/trial_ingestion/"):
                raise ValueError(f"Invalid historical external source: {name}")
            data = (REPO / name).read_bytes()
            if digest(data) != checksum:
                raise ValueError(f"Historical trial source changed; use the pinned base commit: {name}")
            target = checkout / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        commands = [
            ["evaluation/verification/build_cases.py", "--check"],
            ["evaluation/verification/analyze_cohort.py", "--check"],
            ["evaluation/verification/build_v2.py", "--check"],
            ["-m", "unittest", "discover", "-s", "evaluation/verification/tests", "-v"],
        ]
        for command in commands:
            subprocess.run([sys.executable, *command], cwd=checkout, check=True)
    print("Historical replay passed; working-tree files were not restored.")


if __name__ == "__main__":
    main()
