import subprocess
import sys
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parent


def run_script(script_name: str):
    script_path = SCRIPTS_DIR / script_name

    print(f"\n=== Running {script_name} ===")

    subprocess.run(
        [sys.executable, str(script_path)],
        check=True,
    )


if __name__ == "__main__":
    run_script("fetch_trials.py")
    run_script("normalize_trial.py")
    run_script("parse_criteria.py")

    print("\n=== Trial ingestion pipeline completed successfully ===")