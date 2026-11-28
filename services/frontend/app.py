"""Application API, with optional static hosting for the Cloud Run deployment."""

import os
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from services.rag_workflow.api import create_app as create_rag_app
from services.rag_workflow.config import Settings
from services.rag_workflow.data import DataStore

STATIC = Path(__file__).parent / "static"


def create_app(settings=None, *, serve_ui=True):
    config = settings or Settings()
    app = create_rag_app(config)
    app.title = "TrialMatch API"

    @lru_cache(maxsize=1)
    def store():
        return DataStore(config)

    @app.get("/patients/{patient_id}")
    def patient(patient_id: str):
        try:
            return store().patient(patient_id)
        except KeyError as exc:
            raise HTTPException(404, "Patient not found") from exc

    @app.get("/metadata")
    def metadata():
        data = store()
        manifest = data.manifest()
        return {
            "mode": config.mode,
            "synthetic_patients": True,
            "patient_count": len(data.patients),
            "trial_count": len(data.trials),
            "screening_subset_count": len(manifest["trial_ids"]),
            "source_hashes": data.hashes,
            "patient_reference_dates": sorted(
                {p["reference_date"] for p in data.patients.values()}
            ),
            "trial_snapshot_dates": sorted({t["snapshot_date"] for t in data.trials.values()}),
            "health_scope": "Data and manifest only; /health does not verify cloud access or vector readiness.",
        }

    if serve_ui:

        @app.get("/", include_in_schema=False)
        def home():
            return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})

        @app.get("/en.html", include_in_schema=False)
        def english_alias():
            return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})

        app.mount("/assets", StaticFiles(directory=STATIC), name="assets")
    return app


app = create_app(serve_ui=os.environ.get("TRIALMATCH_SERVE_UI", "true").lower() == "true")
