import json
from pathlib import Path

import requests


API_URL = "https://clinicaltrials.gov/api/v2/studies"

RAW_DIR = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "raw"
)

CONDITION = "Type 2 Diabetes"

RECRUITMENT_STATUSES = [
    "RECRUITING",
    "NOT_YET_RECRUITING",
    "ENROLLING_BY_INVITATION",
]

PAGE_SIZE = 100


def search_trials(
    condition: str,
    status: str,
    page_token: str = None,
):
    params = {
        "query.cond": condition,
        "filter.overallStatus": status,
        "pageSize": PAGE_SIZE,
    }

    if page_token:
        params["pageToken"] = page_token

    response = requests.get(
        API_URL,
        params=params,
        timeout=30,
    )

    response.raise_for_status()

    return response.json()


def fetch_all_trials(
    condition: str,
    status: str,
):
    studies = []
    next_token = None

    while True:
        data = search_trials(
            condition=condition,
            status=status,
            page_token=next_token,
        )

        page_studies = data.get("studies", [])
        studies.extend(page_studies)

        next_token = data.get("nextPageToken")

        if not next_token:
            break

    return studies


def save_trials(studies: list):
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    # Remove the previous raw snapshot only after
    # the new API fetch has completed successfully.
    for old_file in RAW_DIR.glob("*.json"):
        old_file.unlink()

    for study in studies:
        nct_id = study["protocolSection"]["identificationModule"]["nctId"]
        output_path = RAW_DIR / f"{nct_id}.json"

        with open(output_path, "w") as f:
            json.dump(study, f, indent=2)

    print(f"Saved {len(studies)} unique raw trials to {RAW_DIR}")


if __name__ == "__main__":
    trials_by_id = {}

    for status in RECRUITMENT_STATUSES:
        studies = fetch_all_trials(
            condition=CONDITION,
            status=status,
        )

        print(
            f"{status}: "
            f"{len(studies)} studies"
        )

        for study in studies:
            nct_id = (
                study["protocolSection"]
                ["identificationModule"]
                ["nctId"]
            )

            trials_by_id[nct_id] = study

    all_studies = list(
        trials_by_id.values()
    )

    save_trials(all_studies)

    print(
        f"Collected {len(all_studies)} "
        f"unique candidate trials"
    )