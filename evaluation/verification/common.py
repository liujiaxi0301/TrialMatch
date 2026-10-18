"""Shared helpers for the reconstructed verification package (standard library only)."""
import csv
import hashlib
import io
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
PATIENT_IDS = (
    "475803f3-ae29-ba8d-bdd1-25145a94eaee",
    "bf113937-f532-94bb-66e1-9c7111f68207",
)
TRIAL_IDS = ("NCT07156539", "NCT07580638", "NCT07658417")
STATUSES = {"MET", "NOT_MET", "UNKNOWN"}


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def csv_bytes(rows, fields):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def fact_ids(value):
    if isinstance(value, dict):
        result = {value["fact_id"]} if "fact_id" in value else set()
        for child in value.values():
            result.update(fact_ids(child))
        return result
    if isinstance(value, list):
        return set().union(*(fact_ids(child) for child in value))
    return set()


def normalize_text(text):
    """Ignore whitespace and Markdown escapes, preserving clinical wording."""
    return re.sub(r"\s+", " ", re.sub(r"\\([<>.*-])", r"\1", text)).strip()


def parse_response(data):
    """Accept a JSON response with fences/preamble, without changing its bytes."""
    text = data.decode("utf-8-sig")
    decoder = json.JSONDecoder()
    found = []
    offset = 0
    while offset < len(text):
        start = text.find("{", offset)
        if start < 0:
            break
        try:
            value, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            offset = start + 1
            continue
        if isinstance(value, dict) and "pair_id" in value and "criteria" in value:
            found.append((value, start, end))
        offset = end
    if len(found) != 1:
        raise ValueError(f"Expected one response object; found {len(found)}")
    obj, start, end = found[0]
    outside = (text[:start] + text[end:]).replace("```json", "").replace("```", "").strip()
    return obj, bool(outside)
