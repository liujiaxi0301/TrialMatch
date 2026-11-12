"""Shared training-input and manifest checks for pipeline consumers (Python 3.10+)."""

import hashlib
import json
import re


def pair_hashes(uris, hashes, *, required=True):
    """Return URI -> expected SHA256, rejecting ambiguous or incomplete input lists."""
    if len(set(uris)) != len(uris):
        raise ValueError("Duplicate training pair paths are not allowed")
    if not hashes and not required:
        return {}
    if len(uris) != len(hashes):
        raise ValueError("Each training pair path requires exactly one expected SHA256, in the same order")
    if any(not re.fullmatch(r"[0-9a-f]{64}", digest) for digest in hashes):
        raise ValueError("Expected pair SHA256 values must contain exactly 64 lowercase hexadecimal characters")
    return dict(zip(uris, hashes, strict=True))


def verify_training_manifest(manifest, release_uri, output_uri, image, batch_size, expected_pairs=None):
    """Bind training metadata to this run before writing any success markers.

    Checkpoint bytes are verified by the eventual consumer; this validates the
    producer's manifest and the aggregate digest of its per-file checksums.
    """
    expected = {
        "schema_version": 1,
        "workflow_type": "contrastive-encoder-finetune",
        "source_release_uri": release_uri,
        "artifact_uri": output_uri.rstrip("/") + "/model",
        "image_uri": image,
    }
    if not isinstance(manifest, dict) or any(manifest.get(k) != v for k, v in expected.items()):
        raise RuntimeError("Training manifest does not match this run's release, output or image")
    files = manifest.get("artifact_files")
    if (not isinstance(files, dict) or not files
            or any(not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v)
                   for v in files.values())):
        raise RuntimeError("Training manifest has missing or invalid checkpoint checksums")
    digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    if manifest.get("artifact_sha256") != digest:
        raise RuntimeError("Training manifest checkpoint digest does not match its file checksums")
    config = manifest.get("config")
    if not isinstance(config, dict) or config.get("batch_size") != batch_size:
        raise RuntimeError("Training manifest does not match the submitted batch size")
    if expected_pairs is not None:
        sources = manifest.get("pair_files")
        built_uri = f"built-from:{release_uri}"
        if (not isinstance(sources, list) or any(not isinstance(item, dict) for item in sources)
                or len(sources) != len(expected_pairs) + 1
                or {item.get("uri") for item in sources} != set(expected_pairs) | {built_uri}):
            raise RuntimeError("Training manifest does not match the submitted pair sources")
        for item in sources:
            if item["uri"] == built_uri:
                continue
            expected = expected_pairs[item["uri"]]
            if item.get("sha256") != expected or item.get("expected_sha256") != expected:
                raise RuntimeError("Training manifest pair checksums do not match the submitted expectations")
