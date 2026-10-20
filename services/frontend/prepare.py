"""One-command reproducible preparation and evidence capture from fixed snapshots."""

import json
import platform
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from services.rag_workflow.config import Settings
from services.rag_workflow.schemas import ScreenRequest
from services.rag_workflow.workflow import ScreeningWorkflow
from .vector_demo import LocalVectorDemo


def main():
    settings = Settings()
    output = settings.artifacts.parent / "ms2"
    output.mkdir(parents=True, exist_ok=True)
    workflow = ScreeningWorkflow(settings)
    patient_id = "060e72d3-912e-55cd-0c92-5faa6cb7a6db"
    question = "Which type 2 diabetes trials may suit this patient, and what information needs review?"
    request = ScreenRequest(patient_id=patient_id, question=question, top_k=3)
    print("[1/4] Validated source snapshots and fixed manifest", flush=True)
    if settings.chroma_host:
        for attempt in range(60):
            try:
                with urllib.request.urlopen(
                    f"http://{settings.chroma_host}:{settings.chroma_port}/api/v2/heartbeat",
                    timeout=2,
                ) as response:
                    if response.status == 200:
                        break
            except (OSError, TimeoutError):
                pass
            if attempt == 59:
                raise RuntimeError("Chroma did not become ready within the startup window")
            time.sleep(1)
    vector = LocalVectorDemo(settings)
    index = vector.build()
    print(f"[2/4] Chroma index verified: {index['vector_count']} criterion fragments", flush=True)
    retrieved = vector.retrieve(patient_id, question, 5)
    print(f"[3/4] Retrieved {len(retrieved['chunks'])} actual context fragments", flush=True)
    result = workflow.screen(request).model_dump(mode="json")
    records = {
        "request.json": request.model_dump(exclude_none=True),
        "retrieved_context.json": retrieved,
        "screen_response.json": result,
        "run_manifest.json": {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "python": platform.python_version(), "mode": settings.mode,
            "source_hashes": workflow.store.hashes,
            "patients": len(workflow.store.patients), "trials": len(workflow.store.trials),
            "subset_trials": len(workflow.manifest["trial_ids"]),
            "vector_model": "local-signed-tokenhash-sha256-v1",
            "local_vector_collection": index["collection"],
            "vector_count": index["vector_count"],
            "result_status": result["result_status"],
            "note": "Vector probe uses local lexical embeddings; screening preserves Part 3's selected offline/live mode. Docker verification is recorded separately.",
        },
    }
    for name, data in records.items():
        (output / name).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    if result["result_status"] in {"ERROR", "PARTIAL"}:
        raise RuntimeError("Screening did not complete successfully; inspect saved errors")
    print(f"[4/4] Saved request, retrieval context, response, and manifest to {output}", flush=True)


if __name__ == "__main__":
    main()
