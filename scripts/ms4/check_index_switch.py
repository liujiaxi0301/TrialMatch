"""Switch/rollback against the Compose HTTP Chroma with fake encoders; removes only its own collections."""

import copy
import io
import json
import random
import tempfile
from contextlib import redirect_stderr
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from unittest.mock import patch

from services.rag_workflow import encoders
from services.rag_workflow.config import Settings
from services.rag_workflow.data import DataStore
from services.rag_workflow.embedding_providers import checkpoint_digest
from services.rag_workflow.encoders import EncoderVersion, apply_encoder, selection_path
from services.rag_workflow.index import VectorIndex
from services.rag_workflow.index_switching import rollback_encoder, selection_status, switch_encoder
from services.rag_workflow.providers import ProviderError, content_hash


class Fake:
    def __init__(self, seed, fail_after=None):
        self.seed, self.fail_after, self.calls = seed, fail_after, 0

    def embed(self, text, task_type="RETRIEVAL_DOCUMENT"):
        self.calls += 1
        if self.fail_after is not None and self.calls > self.fail_after:
            raise ProviderError("TEST_ENCODER_FAILURE", "simulated")
        rng = random.Random(content_hash([self.seed, text]))
        return [rng.uniform(-1, 1) for _ in range(768)]


def show(step, value):
    print(json.dumps({"step": step, **value}, sort_keys=True))


base = Settings()
assert base.chroma_host, "Run inside the Compose rag-api container"
tmp = Path(tempfile.mkdtemp())
settings = replace(base, artifacts=tmp / "artifacts")
store = DataStore(settings)
manifest = copy.deepcopy(store.manifest())
manifest["trial_ids"] = manifest["trial_ids"][:2]
catalog = {}
for name, evaluated in (("check-a", True), ("check-b", False), ("check-c", True)):
    directory = tmp / name
    directory.mkdir()
    (directory / "model.safetensors").write_bytes(name.encode())
    catalog[name] = EncoderVersion(
        name,
        str(directory),
        checkpoint_digest(directory)[0],
        "ms4-part-b-http-check",
        "a" * 40,
        768,
        2048,
        evaluated,
        "check",
    )
fakes = {name: Fake(name) for name in catalog}
names = []
with (
    patch.object(encoders, "ENCODERS", MappingProxyType(catalog)),
    patch.object(encoders, "DEFAULT_FINETUNED", "check-a"),
    redirect_stderr(io.StringIO()),
):
    try:
        default = VectorIndex(
            apply_encoder(settings, catalog["check-a"]), store, manifest, fakes["check-a"]
        )
        names = [
            VectorIndex(apply_encoder(settings, e), store, manifest).name for e in catalog.values()
        ]
        default.build()
        show(
            "backend",
            {
                "chroma_host": settings.chroma_host,
                "selection_record": str(selection_path(settings).relative_to(tmp)),
            },
        )
        r = switch_encoder(
            settings, store, manifest, "check-c", provider_factory=lambda s: fakes["check-c"]
        )
        assert r["status"] == "SWITCHED" and r["active"] == "check-c"
        show("switch", {k: r[k] for k in ("status", "active", "previous")})
        before = selection_path(settings).read_bytes()
        try:
            switch_encoder(
                settings,
                store,
                manifest,
                "check-b",
                allow_unevaluated=True,
                provider_factory=lambda s: Fake("check-b", fail_after=16),
            )
        except ProviderError as exc:
            assert exc.code == "TEST_ENCODER_FAILURE"
            assert selection_path(settings).read_bytes() == before
            current = VectorIndex(apply_encoder(settings, catalog["check-c"]), store, manifest)
            show(
                "failed_switch",
                {
                    "error": exc.code,
                    "record_unchanged": selection_path(settings).read_bytes() == before,
                    "live_index": current.status()["status"],
                },
            )
            assert current.status()["status"] == "VERIFIED"
        else:
            raise AssertionError("The simulated encoder failure must reject the switch")
        calls = sum(f.calls for f in fakes.values())
        r = rollback_encoder(settings, store, manifest)
        assert r["status"] == "ROLLED_BACK" and r["active"] == "check-a"
        assert sum(f.calls for f in fakes.values()) == calls
        show(
            "rollback",
            {
                "status": r["status"],
                "active": r["active"],
                "previous": r["previous"],
                "encoder_calls_during_rollback": sum(f.calls for f in fakes.values()) - calls,
            },
        )
        s = selection_status(settings, store, manifest)
        assert s["active"]["index_status"] == s["previous"]["index_status"] == "VERIFIED"
        show(
            "status",
            {
                "active": s["active"]["name"],
                "active_index": s["active"]["index_status"],
                "previous": s["previous"]["name"],
                "previous_index": s["previous"]["index_status"],
            },
        )
    finally:
        removed = 0
        for name in names:
            try:
                default.client.delete_collection(name)
                removed += 1
            except Exception:  # noqa: BLE001 -- the candidate may not exist.
                pass
        show("cleanup", {"removed_test_collections": removed})
