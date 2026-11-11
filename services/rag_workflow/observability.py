"""Small, payload-free JSON logs shared by local Python and Cloud Run."""

import json
import logging
import re
import sys
import time
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime

from starlette.responses import JSONResponse

REQUEST_ID = ContextVar("trialmatch_request_id", default=None)
TRACE = ContextVar("trialmatch_trace", default=None)
LOGGER = logging.getLogger("trialmatch.api")


class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "severity": record.levelname,
                "message": record.getMessage(),
                **getattr(record, "event_fields", {}),
            },
            ensure_ascii=True,
            allow_nan=False,
        )


def configure_logging():
    if not LOGGER.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False


def emit(event, *, level=logging.INFO, **fields):
    # Deliberate allowlist: never log patient records, questions, tokens or exception text.
    allowed = {
        "run_id",
        "mode",
        "result_status",
        "candidate_count",
        "unknown_count",
        "screening_barrier_count",
        "embedding_requests",
        "generation_requests",
        "cache_hits",
        "prompt_tokens",
        "output_tokens",
        "embedding_provider",
        "embedding_model",
        "embedding_revision",
        "embedding_checkpoint_sha256",
        "embedding_dimension",
        "generation_model",
        "retrieval_embedding_requests",
        "retrieval_embedded_texts",
        "retrieval_cache_hits",
        "error_codes",
        "method",
        "route",
        "status_code",
        "latency_ms",
        "error_type",
        "ready",
        "check_scope",
    }
    data = {key: value for key, value in fields.items() if key in allowed}
    data["request_id"] = REQUEST_ID.get()
    if TRACE.get():
        data["logging.googleapis.com/trace"] = TRACE.get()
    LOGGER.log(level, event, extra={"event_fields": data})


def safe_code(value):
    value = str(value)
    return value if re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", value) else "UNCLASSIFIED_ERROR"


def counter(value):
    # Metrics are diagnostic only: malformed values must not break a valid response.
    return value if type(value) is int and value >= 0 else 0


def model_name(value):
    return (
        value
        if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,159}", value)
        else "UNAVAILABLE"
    )


def log_screening(result, settings):
    trials = result.candidate_trials
    metrics = result.metrics
    encoder = metrics.get("retrieval_encoder")
    encoder = encoder if isinstance(encoder, dict) else {}
    identity = {"embedding_provider": "NOT_USED"}
    if result.mode == "live":
        provider = getattr(settings, "embedding_provider", "gemini")
        revision = getattr(settings, "embedding_revision", "")
        checkpoint = getattr(settings, "embedding_checkpoint_sha256", "")
        identity = {
            "embedding_provider": provider if provider in {"gemini", "bioclinical"} else "UNKNOWN",
            "embedding_model": model_name(settings.embedding_model),
            "generation_model": model_name(settings.generation_model),
            "embedding_dimension": counter(settings.dimension),
        }
        if isinstance(revision, str) and re.fullmatch(r"[0-9a-f]{40}", revision):
            identity["embedding_revision"] = revision
        if isinstance(checkpoint, str) and re.fullmatch(r"[0-9a-f]{64}", checkpoint):
            identity["embedding_checkpoint_sha256"] = checkpoint
    emit(
        "screening_completed",
        level=logging.WARNING if result.errors else logging.INFO,
        run_id=result.run_id,
        mode=result.mode,
        result_status=result.result_status,
        candidate_count=len(trials),
        unknown_count=sum(t.assessment_coverage.unknown for t in trials),
        screening_barrier_count=sum(t.assessment_coverage.screening_barriers for t in trials),
        error_codes=sorted({safe_code(e.code) for e in result.errors}),
        **identity,
        **{
            "retrieval_" + key: counter(encoder.get(key, 0))
            for key in ("embedding_requests", "embedded_texts", "cache_hits")
        },
        **{
            key: counter(metrics.get(key, 0))
            for key in (
                "embedding_requests",
                "generation_requests",
                "cache_hits",
                "prompt_tokens",
                "output_tokens",
            )
        },
    )


class RequestLoggingMiddleware:
    """Pure ASGI middleware: log the final HTTP status, including validation errors."""

    def __init__(self, app, project=""):
        self.app, self.project = app, project

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request_id = uuid.uuid4().hex  # Do not echo arbitrary client-supplied identifiers.
        scope.setdefault("state", {})["request_id"] = request_id
        request_token = REQUEST_ID.set(request_id)
        headers = dict(scope.get("headers", []))
        trace_header = headers.get(b"x-cloud-trace-context", b"").decode("ascii", "ignore")
        trace = trace_header.split("/", 1)[0]
        project_valid = re.fullmatch(r"[a-z][a-z0-9-]{4,61}[a-z0-9]", self.project)
        trace_token = TRACE.set(
            f"projects/{self.project}/traces/{trace}"
            if project_valid and re.fullmatch(r"[0-9a-f]{32}", trace)
            else None
        )
        started, status, response_started = time.monotonic(), 500, False

        async def observed_send(message):
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                status, response_started = message["status"], True
                message = {
                    **message,
                    "headers": [
                        (k, v)
                        for k, v in message.get("headers", [])
                        if k.lower() != b"x-request-id"
                    ]
                    + [(b"x-request-id", request_id.encode("ascii"))],
                }
            await send(message)

        try:
            await self.app(scope, receive, observed_send)
        except Exception as exc:
            emit("request_failed", level=logging.ERROR, error_type=type(exc).__name__)
            if response_started:
                raise
            response = JSONResponse(
                status_code=500,
                content={
                    "detail": {
                        "code": "INTERNAL_ERROR",
                        "message": "The request could not complete. No eligibility conclusion was made.",
                    },
                    "request_id": request_id,
                },
            )
            await response(scope, receive, observed_send)
        finally:
            # Log the route TEMPLATE, so /patients/{patient_id} never leaks an ID.
            route = getattr(scope.get("route"), "path", "unmatched")
            emit(
                "http_request",
                level=logging.ERROR
                if status >= 500
                else (logging.WARNING if status >= 400 else logging.INFO),
                method=scope["method"],
                route=route,
                status_code=status,
                latency_ms=round((time.monotonic() - started) * 1000, 2),
            )
            REQUEST_ID.reset(request_token)
            TRACE.reset(trace_token)
