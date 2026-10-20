"""Serve Part 5 UI and Part 3 API on one origin; no duplicated screening logic."""

import logging
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from services.rag_workflow.api import create_app as create_rag_app
from services.rag_workflow.config import Settings
from services.rag_workflow.data import DataStore
from services.rag_workflow.providers import ProviderError
from services.rag_workflow.schemas import ScreenRequest
from .vector_demo import LocalVectorDemo

STATIC = Path(__file__).parent / "static"
logger = logging.getLogger(__name__)


def create_app(settings=None):
    config = settings or Settings()
    app = create_rag_app(config)
    app.title = "TrialMatch MS2 Application"

    @lru_cache(maxsize=1)
    def store():
        return DataStore(config)

    @lru_cache(maxsize=1)
    def vector():
        return LocalVectorDemo(config)

    @app.get("/patients/{patient_id}")
    def patient(patient_id: str):
        try:
            return store().patient(patient_id)
        except KeyError as exc:
            raise HTTPException(404, "Patient not found") from exc

    @app.post("/retrieve")
    def retrieve(request: ScreenRequest):
        if request.patient_id is None:
            raise HTTPException(422, "This demo retrieval endpoint requires a built-in patient_id")
        try:
            return vector().retrieve(request.patient_id, request.question, request.top_k)
        except KeyError as exc:
            raise HTTPException(404, "Patient not found") from exc
        except ProviderError as exc:
            raise HTTPException(503, {"code": exc.code, "message": str(exc)}) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except Exception as exc:
            logger.exception("Vector store unavailable")
            raise HTTPException(503, "Vector database unavailable. Run the preparation step and check the database service.") from exc

    @app.get("/metadata")
    def metadata():
        data = store()
        manifest = data.manifest()
        return {
            "mode": config.mode, "synthetic_patients": True,
            "patient_count": len(data.patients), "trial_count": len(data.trials),
            "screening_subset_count": len(manifest["trial_ids"]),
            "source_hashes": data.hashes,
            "patient_reference_dates": sorted({p["reference_date"] for p in data.patients.values()}),
            "trial_snapshot_dates": sorted({t["snapshot_date"] for t in data.trials.values()}),
            "vector_demo_model": "local-signed-tokenhash-sha256-v1",
            "health_scope": "Data and manifest only; /health does not verify cloud access or vector readiness.",
        }

    @app.get("/", include_in_schema=False)
    def home():
        return FileResponse(STATIC / "index.html")

    @app.get("/en.html", include_in_schema=False)
    def english_alias():
        return FileResponse(STATIC / "index.html")

    app.mount("/assets", StaticFiles(directory=STATIC), name="assets")
    return app


app = create_app()
