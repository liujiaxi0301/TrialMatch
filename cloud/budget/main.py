"""Pause the demo and stop Chroma after this month's $5 budget is reached."""

import base64
import json
import os
import time
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import google.auth
from flask import Flask, request
from google.auth.transport.requests import AuthorizedSession

app = Flask(__name__)
PROJECT = os.environ["GCP_PROJECT"]
REGION = os.environ["GCP_REGION"]
ZONE = os.environ["GCP_ZONE"]
SERVICE = os.environ["TARGET_SERVICE"]
VM = os.environ["TARGET_VM"]
BUDGET = os.environ["BUDGET_ID"]
ACCOUNT = os.environ["BILLING_ACCOUNT"]
LIMIT = Decimal("5")


def budget_reached(envelope):
    message = envelope["message"]
    attributes = message.get("attributes", {})
    if attributes.get("budgetId") != BUDGET or attributes.get("billingAccountId") != ACCOUNT:
        return False
    data = json.loads(base64.b64decode(message["data"], validate=True))
    start = datetime.fromisoformat(data["costIntervalStart"].replace("Z", "+00:00"))
    now = datetime.now(ZoneInfo("America/Los_Angeles"))
    cost = Decimal(str(data["costAmount"]))
    # Ignore old months, forecasts, other currencies, and changed budget amounts.
    return (
        start.tzinfo is not None
        and (start.year, start.month) == (now.year, now.month)
        and start.day == 1
        and data["currencyCode"] == "USD"
        and Decimal(str(data["budgetAmount"])) == LIMIT
        and cost.is_finite()
        and cost >= LIMIT
    )


def api(session, method, url, **kwargs):
    response = session.request(method, url, timeout=30, **kwargs)
    if not response.ok:
        raise RuntimeError(f"{method} failed ({response.status_code}): {response.text}")
    return response.json()


def pause_app(session):
    url = f"https://run.googleapis.com/v2/projects/{PROJECT}/locations/{REGION}/services/{SERVICE}"
    service = api(session, "GET", url)
    scaling = service.get("scaling", {})
    if scaling.get("scalingMode") != "MANUAL" or scaling.get("manualInstanceCount", 0) != 0:
        api(session, "PATCH", url,
            params={"updateMask": "scaling.scalingMode,scaling.manualInstanceCount"},
            json={"scaling": {"scalingMode": "MANUAL", "manualInstanceCount": 0}})
    for _ in range(30):
        service = api(session, "GET", url)
        scaling = service.get("scaling", {})
        if (scaling.get("scalingMode") == "MANUAL"
                and scaling.get("manualInstanceCount", 0) == 0
                and not service.get("reconciling", False)):
            # Tagged revision URLs can bypass service-level zero scaling.
            if any(item.get("tag") for item in service.get("traffic", [])):
                raise RuntimeError("Remove tagged revision URLs from the demo service")
            return
        time.sleep(2)
    raise TimeoutError("Cloud Run has not finished pausing; retry the notification")


def stop_vm(session):
    url = f"https://compute.googleapis.com/compute/v1/projects/{PROJECT}/zones/{ZONE}/instances/{VM}"
    status = api(session, "GET", url)["status"]
    if status not in {"TERMINATED", "STOPPING"}:
        api(session, "POST", url + "/stop")
    for _ in range(45):
        if api(session, "GET", url)["status"] == "TERMINATED":
            return
        time.sleep(2)
    raise TimeoutError("VM has not finished stopping; retry the notification")


@app.post("/")
def handle_budget():
    try:
        reached = budget_reached(request.get_json())
    except (KeyError, ValueError, TypeError, ArithmeticError):
        app.logger.warning("Ignoring malformed budget notification")
        return "Ignored invalid notification", 204
    if not reached:
        return "Below limit or unrelated notification", 204

    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    errors = []
    with AuthorizedSession(credentials) as session:
        # Try both actions even if one fails. Pub/Sub retries on HTTP 500.
        for action in (pause_app, stop_vm):
            try:
                action(session)
            except Exception:
                app.logger.exception("Budget action failed: %s", action.__name__)
                errors.append(action.__name__)
    if errors:
        return "Retry failed actions: " + ", ".join(errors), 500
    print(json.dumps({"severity": "NOTICE", "event": "budget_shutdown_complete",
                      "budget_usd": 5, "service": SERVICE, "vm": VM,
                      "data_preserved": True}), flush=True)
    return "Demo paused; VM off; disks and buckets preserved", 200
