"""Capture actual HTTP input/output artifacts; no mock substitution."""
import argparse
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--output", type=Path, default=Path("artifacts/ovrz/ms2/http"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    checks = []

    def call(path, payload=None, expected=200):
        request = Request(args.base_url + path,
                          data=json.dumps(payload).encode() if payload is not None else None,
                          headers={"Content-Type": "application/json"})
        try:
            response = urlopen(request, timeout=300)
        except HTTPError as error:
            response = error
        with response:
            status = response.status
            data = json.load(response)
        assert status == expected, (path, status, data)
        checks.append({"path": path, "status": status})
        return data

    health = call("/health")
    patients = call("/patients")["patients"]
    assert len(patients) == 25
    patient_id = "060e72d3-912e-55cd-0c92-5faa6cb7a6db"
    assert call(f"/patients/{patient_id}")["patient_id"] == patient_id
    request = {"patient_id": patient_id, "question": "Which type 2 diabetes trials may suit this patient, and what information needs review?", "top_k": 3}
    screen = call("/screen", request)
    assert screen["mode"] == health["mode"] and screen["result_status"] == "OK"
    assert len(screen["candidate_trials"]) == 3
    for trial in screen["candidate_trials"]:
        assert trial["eligibility_probability"] is None
        for assessment in trial["criteria_assessments"]:
            assert all(key in trial["evidence"] for key in assessment["evidence_fact_ids"])
    retrieved = call("/retrieve", request)
    assert len(retrieved["chunks"]) == 3 and retrieved["vector_count"] == 607
    call("/screen", {**request, "patient_id": "unknown-patient"}, 404)
    call("/screen", {**request, "question": " "}, 422)
    call("/screen", {**request, "top_k": 9}, 422)
    for filename, data in {"request": request, "screen_response": screen, "retrieved_context": retrieved, "metadata": call("/metadata"), "checks": checks}.items():
        (args.output / f"{filename}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"status": "PASS", "checks": checks, "output": str(args.output)}))


if __name__ == "__main__":
    main()
