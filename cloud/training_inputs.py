"""Small shared argument checks for pinned training-pair inputs (Python 3.10+)."""

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
