"""Thin local/demo HTTP adapter. Business logic stays in workflow.py."""

import os
from functools import lru_cache

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
from .schemas import ScreenRequest, ScreenResponse
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

    readiness = ReadinessProbe(config, workflow)

    @app.get("/ready", tags=["Operations"])
    def ready():
        report = readiness.check()
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
        except (FileNotFoundError, ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": "ARTIFACT_UNAVAILABLE", "message": "Data or manifest unavailable."},
            ) from exc
        try:
            result = service.screen(request)
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
        log_screening(result, config)
        if result.result_status == "ERROR":
            return JSONResponse(status_code=503, content=result.model_dump(mode="json"))
        return result

    return app


app = create_app()
