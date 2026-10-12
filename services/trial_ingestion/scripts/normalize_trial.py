import json
import re
from datetime import date
from pathlib import Path


RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"
PROCESSED_DIR = Path(__file__).resolve().parents[1] / "data" / "processed"


def load_trial(nct_id: str):
    input_path = RAW_DIR / f"{nct_id}.json"

    with open(input_path, "r") as f:
        return json.load(f)


def normalize_trial(trial: dict):
    protocol = trial["protocolSection"]

    identification = protocol.get("identificationModule", {})
    status = protocol.get("statusModule", {})
    conditions_module = protocol.get("conditionsModule", {})
    description = protocol.get("descriptionModule", {})
    eligibility = protocol.get("eligibilityModule", {})
    design = protocol.get("designModule", {})
    enrollment = design.get("enrollmentInfo", {})

    derived = trial.get("derivedSection", {})
    condition_browse = derived.get("conditionBrowseModule", {})
    meshes = condition_browse.get("meshes", [])

    locations_module = protocol.get("contactsLocationsModule", {})
    raw_locations = locations_module.get("locations", [])

    locations = []

    for location in raw_locations:
        geo = location.get("geoPoint", {})

        locations.append({
            "facility": location.get("facility"),
            "status": location.get("status"),
            "city": location.get("city"),
            "state": location.get("state"),
            "zip": location.get("zip"),
            "country": location.get("country"),
            "latitude": geo.get("lat"),
            "longitude": geo.get("lon"),
        })

    return {
        "trial_id": identification["nctId"],
        "brief_title": identification.get("briefTitle"),
        "official_title": identification.get("officialTitle"),
        "overall_status": status.get("overallStatus"),
        "conditions": conditions_module.get("conditions", []),
        "keywords": conditions_module.get("keywords", []),
        "mesh_terms": [
            mesh.get("term")
            for mesh in meshes
            if mesh.get("term")
        ],
        "study_type": design.get("studyType"),
        "phases": design.get("phases", []),
        "brief_summary": description.get("briefSummary"),
        "minimum_age": eligibility.get("minimumAge"),
        "maximum_age": eligibility.get("maximumAge"),
        "sex": eligibility.get("sex"),
        "healthy_volunteers": eligibility.get("healthyVolunteers"),
        "eligibility_text": eligibility.get("eligibilityCriteria"),
        "locations": locations,
        "enrollment_count": enrollment.get("count"),
        "enrollment_type": enrollment.get("type"),
        "start_date": status.get("startDateStruct", {}).get("date"),
        "completion_date": status.get("completionDateStruct", {}).get("date"),
        "last_update_date": status.get(
            "lastUpdatePostDateStruct", {}
        ).get("date"),
        "source": "ClinicalTrials.gov API v2",
        "snapshot_date": date.today().isoformat(),
    }


def is_t2d_related(trial: dict):
    text_parts = [
        *trial.get("conditions", []),
        trial.get("brief_title") or "",
        trial.get("official_title") or "",
        trial.get("brief_summary") or "",
    ]

    text = " ".join(text_parts).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)

    t2d_markers = [
        "type 2",
        "type ii",
        "t2d",
        "non insulin dependent",
    ]

    return any(marker in text for marker in t2d_markers)


def save_normalized_trials(records: list):
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    output_path = PROCESSED_DIR / "trials.jsonl"

    with open(output_path, "w") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")

    print(f"Saved {len(records)} trials to {output_path}")


if __name__ == "__main__":
    records = []

    for input_path in sorted(RAW_DIR.glob("*.json")):
        nct_id = input_path.stem

        raw_trial = load_trial(nct_id)
        normalized = normalize_trial(raw_trial)

        if is_t2d_related(normalized):
            records.append(normalized)

    save_normalized_trials(records)