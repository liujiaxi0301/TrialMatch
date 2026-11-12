"""Restore the original PNG evidence from its text transport encoding."""
import base64
import json
from pathlib import Path
root = Path(__file__).resolve().parents[2]
source = root / "docs/ovrz-ms2/evidence/screenshots.base64.json"
output = root / "artifacts/ovrz/screenshots"
output.mkdir(parents=True, exist_ok=True)
for name, data in json.loads(source.read_text(encoding="utf-8")).items():
    if name not in {"ui-screening.png", "ui-retrieval.png"}:
        raise ValueError("Unexpected screenshot name")
    (output / name).write_bytes(base64.b64decode(data, validate=True))
print(f"Restored original screenshots to {output}")
