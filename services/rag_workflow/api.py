"""Thin local/demo HTTP adapter. Business logic stays in workflow.py."""

import os
from datetime import UTC, datetime
from functools import lru_cache
from threading import Lock

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import Settings
from .observability import (
    RequestLoggingMiddleware,
    configure_logging,
    emit,
    log_screening,
    safe_code,
)
from .providers import ProviderError
from .readiness import ReadinessProbe
from .schemas import RetrievalModel, ScreenRequest, ScreenResponse
from .workflow import ScreeningWorkflow


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()
    app = FastAPI(title="TrialMatch MS2 Part 3", version="0.1.0")
    origins = [
        item.strip()
        for item in os.environ.get(
            "TRIALMATCH_CORS_ORIGINS", "http://localhost:3000,http://localhost:5173"
        ).split(",")
        if item.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        expose_headers=["X-Request-ID"],
    )
    configure_logging()
    app.add_middleware(RequestLoggingMiddleware, project=config.project)

    @lru_cache(maxsize=1)
    def workflow():
        return ScreeningWorkflow(config)

    readiness_probes = {}
    readiness_lock = Lock()

    def readiness(retrieval_model=None):
        # Resolve selection on every request, even while the index report is cached.
        # Keep only the latest probe per selector so an observed rollback rechecks it.
        with readiness_lock:
            try:
                resolved = config.for_retrieval(retrieval_model)
            except ProviderError:
                readiness_probes.pop(retrieval_model, None)
                raise
            probe = readiness_probes.get(retrieval_model)
            if probe is None or probe.settings != resolved:
                probe = ReadinessProbe(resolved, workflow)
                readiness_probes[retrieval_model] = probe
            return probe

    @app.get("/ready", tags=["Operations"])
    def ready(retrieval_model: RetrievalModel | None = None):
        try:
            report = readiness(retrieval_model).check()
        except ProviderError as exc:
            report = {
                "ready": False,
                "mode": config.mode,
                "check_scope": "encoder_selection",
                "checked_at": datetime.now(UTC).isoformat(),
                "cache_ttl_seconds": 0,
                "model_access": "NOT_REQUIRED" if config.mode == "offline" else "NOT_PROBED",
                "note": "Current retrieval encoder selection is unavailable.",
                "checks": {
                    "encoder_selection": {"status": "FAIL", "code": safe_code(exc.code)},
                },
            }
        emit("readiness_checked", ready=report["ready"], check_scope=report["check_scope"])
        return JSONResponse(status_code=200 if report["ready"] else 503, content=report)

    @app.get("/health")
    def health():
        try:
            service = workflow()
            return {
                "status": "ok",
                "mode": config.mode,
                "patients": len(service.store.patients),
                "corpus_trials": len(service.manifest["trial_ids"]),
                "note": "Data/manifest health only; this does not verify GCP permissions or live index readiness.",
            }
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/patients")
    def patients():
        return {
            "patients": [
                {
                    "patient_id": p["patient_id"],
                    "reference_date": p["reference_date"],
                    "age_years_at_reference": p["demographics"].get("age_years_at_reference"),
                    "gender": p["demographics"].get("gender"),
                    "deceased_date": p["demographics"].get("deceased_date"),
                }
                for p in workflow().store.patients.values()
            ]
        }

    @app.post("/screen", response_model=ScreenResponse)
    def screen(request: ScreenRequest):
        try:
            service = workflow()
        except (FileNotFoundError, ValueError, TypeError, KeyError) as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": "ARTIFACT_UNAVAILABLE", "message": "Data or manifest unavailable."},
            ) from exc
        try:
            resolved = config.for_retrieval(request.retrieval_model)
            result = service.screen(request, resolved_settings=resolved)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Patient not found") from exc
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=503, detail="Processed data or manifest is missing"
            ) from exc
        except TimeoutError as exc:
            raise HTTPException(
                status_code=504,
                detail={
                    "code": "SCREENING_TIMEOUT",
                    "message": "Screening timed out. No eligibility conclusion was made.",
                },
            ) from exc
        except ProviderError as exc:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": safe_code(exc.code),
                    "message": "Screening dependency unavailable.",
                },
            ) from exc
        log_screening(result, resolved)
        if result.result_status == "ERROR":
            return JSONResponse(status_code=503, content=result.model_dump(mode="json"))
        return result

    return app


app = create_app()
