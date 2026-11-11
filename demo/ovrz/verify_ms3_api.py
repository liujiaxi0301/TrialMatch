"""Module E HTTP smoke checks. No model request unless --screen is supplied."""

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # An IAP login redirect is not a successful API response.


def verify(base_url, *, token=None, timeout=180, screen=False, require_operations=False):
    parsed = urlsplit(base_url)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Use an origin URL without credentials, query or fragment")
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    ):
        raise ValueError("Remote API checks require HTTPS")
    base_url = base_url.rstrip("/")
    opener = build_opener(NoRedirect())
    results = []

    def check(path, expected, payload=None):
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode("utf-8")
        started = time.monotonic()
        row = {"path": path, "expected_status": expected}
        body = None
        try:
            try:
                response = opener.open(
                    Request(base_url + path, data=data, headers=headers), timeout=timeout
                )
            except HTTPError as exc:
                response = exc
            with response:
                row["status_code"] = response.code
                row["request_id"] = response.headers.get("X-Request-ID")
                content_type = response.headers.get("Content-Type", "")
                if "application/json" in content_type:
                    body = json.loads(response.read())
                else:
                    row["error"] = "NON_JSON_RESPONSE_OR_LOGIN_REDIRECT"
            row["passed"] = row["status_code"] == expected and body is not None
        except (URLError, TimeoutError, OSError, ValueError):
            row.update(passed=False, error="TRANSPORT_TIMEOUT_OR_INVALID_JSON")
        row["latency_ms"] = round((time.monotonic() - started) * 1000, 2)
        results.append(row)
        return body

    health = check("/health", 200)
    results[-1]["passed"] = (
        results[-1]["passed"]
        and isinstance(health, dict)
        and (health.get("status") == "ok" and health.get("mode") in {"offline", "live"})
    )
    patients = check("/patients", 200)
    results[-1]["passed"] = (
        results[-1]["passed"]
        and isinstance(patients, dict)
        and (isinstance(patients.get("patients"), list) and bool(patients["patients"]))
    )
    schema = check("/openapi.json", 200)
    results[-1]["passed"] = (
        results[-1]["passed"]
        and isinstance(schema, dict)
        and ("/screen" in schema.get("paths", {}))
    )
    check("/screen", 422, {})
    check("/screen", 404, {"patient_id": "missing-ms3-smoke", "question": "Find trials"})
    check("/screen", 422, {"patient_id": "missing-ms3-smoke", "question": " ", "top_k": 6})
    operations_present = isinstance(schema, dict) and "/ready" in schema.get("paths", {})
    readiness = check("/ready", 200) if operations_present or require_operations else None
    if operations_present or require_operations:
        results[-1]["passed"] = (
            results[-1]["passed"]
            and isinstance(readiness, dict)
            and readiness.get("ready") is True
            and readiness.get("check_scope") == "data_and_index"
        )
    screening = None
    if screen:
        screening = check(
            "/screen",
            200,
            {
                "patient_id": "060e72d3-912e-55cd-0c92-5faa6cb7a6db",
                "question": "Which type 2 diabetes trials may suit this patient, and what information needs review?",
                "top_k": 1,
            },
        )
        results[-1]["result_status"] = (
            screening.get("result_status") if isinstance(screening, dict) else None
        )
        results[-1]["passed"] = (
            results[-1]["passed"]
            and isinstance(screening, dict)
            and screening.get("result_status") == "OK"
            and isinstance(screening.get("candidate_trials"), list)
            and len(screening["candidate_trials"]) == 1
        )
    report = {
        "checked_at": datetime.now(UTC).isoformat(),
        "base_url": base_url,
        "mode": health.get("mode") if isinstance(health, dict) else None,
        "authentication": "bearer_supplied" if token else "none",
        "operations_present": operations_present,
        "scope": "HTTP integration, not clinical accuracy; no authentication material saved",
        "screening_requested": screen,
        "checks": results,
        "passed": all(row["passed"] for row in results),
    }
    if readiness is not None:
        report["readiness"] = readiness
    if isinstance(screening, dict):
        report["screening"] = {
            "run_id": screening.get("run_id"),
            "result_status": screening.get("result_status"),
            "metrics": screening.get("metrics"),
            "candidates": [
                {
                    "trial_id": trial.get("trial_id"),
                    "screening_status": trial.get("screening_status"),
                    "assessment_coverage": trial.get("assessment_coverage"),
                }
                for trial in screening.get("candidate_trials", [])
            ],
        }
    if require_operations:
        import re

        report["passed"] = report["passed"] and all(
            re.fullmatch(r"[0-9a-f]{32}", row.get("request_id") or "") for row in results
        )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--screen", action="store_true", help="Opt in to one real screening call")
    parser.add_argument("--require-operations", action="store_true")
    parser.add_argument(
        "--token-stdin", action="store_true", help="Read token privately from stdin"
    )
    parser.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args()
    token = sys.stdin.read().strip() if args.token_stdin else None
    if args.token_stdin and not token:
        parser.error("No bearer token received on stdin")
    report = verify(
        args.base_url,
        token=token,
        timeout=args.timeout,
        screen=args.screen,
        require_operations=args.require_operations,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "checks": len(report["checks"]),
                "operations_present": report["operations_present"],
            }
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
