"""Switch and roll back the fine-tuned retrieval encoder without touching the live index.

A switch builds or restores the candidate into its own content-addressed collection,
verifies and probes it, and only then replaces the active-encoder record. Every failure
before that final atomic write leaves the record, and therefore the served index,
unchanged. A rollback re-verifies the previous collection and never re-encodes.
Single writer, as for build-index and restore-index: there is no distributed lock.
"""

import math

from . import encoders as catalog
from .embedding_providers import create_embedding_provider, resolve_checkpoint
from .encoders import (
    apply_encoder,
    encoder,
    load_selection,
    next_selection,
    selection_path,
    write_selection,
)
from .index import VectorIndex
from .providers import ProviderError

# A generic retrieval phrase used only to prove the encoder returns vectors that Chroma
# can search; no patient data and no benchmark query.
SMOKE_QUERY = "adult participants with type 2 diabetes"


def _require_evaluated(entry, allow_unevaluated):
    if not entry.evaluated and not allow_unevaluated:
        raise ProviderError(
            "ENCODER_NOT_EVALUATED",
            f"{entry.name} was not scored in the retrieval benchmark; "
            "pass --allow-unevaluated to activate it for a demonstration.",
        )


def smoke_check(index) -> dict:
    """Verify checksums, then run real nearest-neighbour queries against the collection."""
    _, records = index.verify()
    collection = index._collection()
    probe = records[0]
    result = collection.query(
        query_embeddings=[probe["embedding"]], n_results=1, include=["distances"]
    )
    if not result["ids"][0] or result["distances"][0][0] > 1e-3:
        raise ProviderError("INDEX_SMOKE_FAILED", "A stored vector did not find itself.")
    report = {"stored_vector_probe": "PASS", "dimension": len(probe["embedding"])}
    if index.provider is not None:
        vector = index.provider.embed(SMOKE_QUERY, "RETRIEVAL_QUERY")
        if len(vector) != index.settings.dimension or not all(map(math.isfinite, vector)):
            raise ProviderError(
                "INDEX_SMOKE_FAILED", "Query vector has the wrong dimension or nonfinite values."
            )
        hits = collection.query(query_embeddings=[vector], n_results=1, include=[])
        if not hits["ids"][0]:
            raise ProviderError("INDEX_SMOKE_FAILED", "The encoder query returned no results.")
        report["encoder_query_probe"] = "PASS"
    return report


def switch_encoder(
    settings,
    store,
    manifest,
    target,
    *,
    allow_unevaluated=False,
    snapshot=None,
    provider_factory=None,
) -> dict:
    current = load_selection(settings)  # A damaged record stops here, before any work.
    active = current["active"] if current else catalog.DEFAULT_FINETUNED
    entry = encoder(target)
    _require_evaluated(entry, allow_unevaluated)
    candidate_settings = apply_encoder(settings, entry)
    candidate_settings.validate()
    # Digest check before any vectors are written or a model is loaded.
    resolve_checkpoint(candidate_settings)
    index = VectorIndex(candidate_settings, store, manifest)
    provider = None
    try:
        if snapshot is not None:
            index.restore(snapshot)
        else:
            try:
                index.build()  # Reuses a verified collection without a provider.
            except ProviderError as exc:
                if exc.code != "MISSING_PROVIDER":
                    raise
                provider = (provider_factory or create_embedding_provider)(candidate_settings)
                index.provider = provider
                index.build()
        smoke = smoke_check(index)
    finally:
        if provider is not None and hasattr(provider, "close"):
            provider.close()
    if target == active:
        return {
            "status": "ALREADY_ACTIVE",
            "active": target,
            "index_version": index.version,
            "smoke": smoke,
            "selection_record": str(selection_path(settings)),
        }
    previous_version = VectorIndex(
        apply_encoder(settings, catalog.ENCODERS[active]), store, manifest
    ).version
    record = next_selection(
        current,
        action="switch",
        active=target,
        index_version=index.version,
        previous=active,
        previous_index_version=previous_version,
    )
    path = write_selection(settings, record)
    return {
        "status": "SWITCHED",
        "active": target,
        "evaluated": entry.evaluated,
        "previous": active,
        "index_version": index.version,
        "previous_index_version": previous_version,
        "smoke": smoke,
        "selection_record": str(path),
    }


def rollback_encoder(settings, store, manifest, *, allow_unevaluated=False) -> dict:
    current = load_selection(settings)
    if current is None or current["previous"] is None:
        raise ProviderError(
            "ENCODER_ROLLBACK_UNAVAILABLE", "No previous fine-tuned encoder is recorded."
        )
    target, active = current["previous"], current["active"]
    _require_evaluated(catalog.ENCODERS[target], allow_unevaluated)
    # No provider: rollback must only re-verify existing vectors, never re-encode them.
    index = VectorIndex(apply_encoder(settings, catalog.ENCODERS[target]), store, manifest)
    try:
        smoke = smoke_check(index)
    except ProviderError as exc:
        raise ProviderError(
            "ROLLBACK_TARGET_NOT_READY",
            f"{target} index failed verification ({exc.code}); the selection is unchanged. "
            "Restore its snapshot with restore-index, then retry the rollback.",
        ) from exc
    record = next_selection(
        current,
        action="rollback",
        active=target,
        index_version=index.version,
        previous=active,
        previous_index_version=current["index_version"],
    )
    path = write_selection(settings, record)
    return {
        "status": "ROLLED_BACK",
        "active": target,
        "evaluated": catalog.ENCODERS[target].evaluated,
        "previous": active,
        "index_version": index.version,
        "smoke": smoke,
        "selection_record": str(path),
    }


def selection_status(settings, store, manifest) -> dict:
    """Which encoder serves this backend, and whether the previous one could be rolled back to."""
    current = load_selection(settings)
    active = current["active"] if current else catalog.DEFAULT_FINETUNED
    previous = current["previous"] if current else None

    def describe(name):
        index = VectorIndex(apply_encoder(settings, catalog.ENCODERS[name]), store, manifest)
        try:
            index.verify()
            ready = "VERIFIED"
        except ProviderError as exc:
            ready = exc.code
        return {
            "name": name,
            "evaluated": catalog.ENCODERS[name].evaluated,
            "checkpoint_sha256": catalog.ENCODERS[name].checkpoint_sha256,
            "index_version": index.version,
            "index_status": ready,
        }

    return {
        "source": "record" if current else "default",
        "selection_record": str(selection_path(settings)),
        "activated_at": current["activated_at"] if current else None,
        "active": describe(active),
        "previous": describe(previous) if previous else None,
    }
