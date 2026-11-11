"""Small synthetic output fixtures; not evaluation evidence."""

import hashlib
import json

from cloud import eligibility

HASHES = dict.fromkeys(("trials", "criteria", "patients"), "c" * 64)


def valid_payloads():
    predictions = b''.join(json.dumps({"error_code": None}).encode() + b'\n' for _ in range(115))
    digest = hashlib.sha256(predictions).hexdigest()
    common = {"provider": "vertex", "split": "all", "model": eligibility.DEFAULT_MODEL}
    metadata = dict(common, source_sha256=HASHES, predictions_sha256=digest,
                    prediction_count=115, prediction_errors=0, case_ids=eligibility.CASE_IDS)
    metrics = dict(common, official_reporting_ready=True, prediction_sha256=digest,
                   inference_failures={"count": 0}, by_case={key: {} for key in eligibility.CASE_IDS},
                   criterion_metrics_all_outputs_including_failures={"n": 115})
    return dict(zip(eligibility.RESULT_FILES, (
        predictions, json.dumps(metadata).encode(), json.dumps(metrics).encode(), b"case_id,error_code\n",
    ), strict=True))
