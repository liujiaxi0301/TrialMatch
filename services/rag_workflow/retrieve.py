"""Small BM25 baseline, hybrid trial retrieval, and criterion-aware patient context."""

import json
import math
import re
from collections import Counter

from .data import event_date, label, patient_facts

STOP = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "of",
    "in",
    "to",
    "for",
    "with",
    "from",
    "at",
    "is",
    "are",
    "be",
    "as",
    "by",
    "on",
    "that",
    "this",
    "have",
    "has",
}


def tokens(text: str) -> list[str]:
    # The corpus is English; expand common Chinese questions used in this demo.
    for source, target in (
        (" diabetes type 2 "),
        (" age "),
        (" medication treatment "),
        (" risk exclusion "),
        (" renal kidney "),
        (" obesity BMI "),
        (" HbA1c "),
    ):
        text = text.replace(source, target)
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOP]


class BM25:
    def __init__(self, documents: dict[str, str]):
        self.docs = {key: Counter(tokens(value)) for key, value in documents.items()}
        self.lengths = {key: sum(tf.values()) for key, tf in self.docs.items()}
        self.average = sum(self.lengths.values()) / max(1, len(self.docs)) or 1
        self.df = Counter(t for tf in self.docs.values() for t in tf)

    def rank(self, query: str) -> list[tuple[str, float]]:
        result = []
        for key, tf in self.docs.items():
            score = 0.0
            for token in set(tokens(query)):
                f = tf.get(token, 0)
                if f:
                    idf = math.log(
                        1 + (len(self.docs) - self.df[token] + 0.5) / (self.df[token] + 0.5)
                    )
                    score += (
                        idf * f * 2.5 / (f + 1.5 * (0.25 + 0.75 * self.lengths[key] / self.average))
                    )
            if score > 0:
                result.append((key, score))
        return sorted(result, key=lambda pair: (-pair[1], pair[0]))


def fact_summary(fact: dict) -> dict:
    result = {
        "fact_id": fact["fact_id"],
        "resource_type": fact.get("resource_type"),
        "label": label(fact),
        "event_date": event_date(fact),
    }
    for key in (
        "source_file",
        "source_resource_id",
        "code",
        "value",
        "components",
        "gender",
        "birth_date",
        "age_years_at_reference",
        "deceased_date",
        "raw_status",
        "onset_date",
        "abatement_date",
        "event_time_certainty",
        "status_at_reference_date",
        "effective_period",
        "dosage_instruction",
        "intent",
    ):
        if key in fact:
            result[key] = fact[key]
    return result


def fact_text(fact: dict) -> str:
    components = " ".join(label(c) for c in fact.get("components", []))
    return label(fact) + " " + components + " " + json.dumps(fact.get("value"))


def patient_query(patient: dict, question: str) -> str:
    demo = patient["demographics"]
    diagnoses = list(dict.fromkeys(label(f) for f in patient.get("conditions", []) if label(f)))
    # Put the disease anchor before secondary history, so a general question still has context.
    t2d = [name for name in diagnoses if "diabetes" in name.lower()]
    medication_names = list(
        dict.fromkeys(
            label(f) for f in patient.get("medications", {}).get("requests", []) if label(f)
        )
    )
    labs = sorted(patient.get("observations", []), key=lambda f: event_date(f) or "", reverse=True)
    selected, codes = [], set()
    for fact in labs:
        coding = {
            (c.get("system"), c.get("code")) for c in (fact.get("code") or {}).get("coding", [])
        }
        relevant = coding & {("http://loinc.org", c) for c in ("4548-4", "2339-0", "39156-5")}
        if relevant and not (relevant & codes):
            selected.append(fact_text(fact))
            codes.update(relevant)
    return " ".join(
        [
            question,
            f"age {demo.get('age_years_at_reference')} {demo.get('gender')}",
            *t2d,
            *diagnoses[:15],
            *medication_names[:10],
            *selected,
        ]
    )


class ContextSelector:
    def __init__(self, patient: dict, limit: int = 12):
        self.patient = patient
        self.limit = limit
        self.facts = {f["fact_id"]: f for f in patient_facts(patient)}
        self.lexical = BM25({key: fact_text(fact) for key, fact in self.facts.items()})

    def select(self, criterion: dict) -> list[dict]:
        ranked = self.lexical.rank(criterion["criterion_text"])
        # Tie-break within relevance using event date to retain more recent measurements.
        ranked.sort(key=lambda pair: (pair[1], event_date(self.facts[pair[0]]) or ""), reverse=True)
        demo_id = self.patient["demographics"]["fact_id"]
        text = criterion["criterion_text"].lower()
        targeted_codes = set()
        if re.search(r"hba1c|a1c|glycosylated|glycated", text):
            targeted_codes.add("4548-4")
        elif "hemoglobin" in text:
            targeted_codes.add("718-7")
        if "glucose" in text:
            targeted_codes.add("2339-0")
        if "body mass" in text or "bmi" in text:
            targeted_codes.add("39156-5")
        targeted = [
            key
            for key, f in self.facts.items()
            if any(
                c.get("system") == "http://loinc.org" and c.get("code") in targeted_codes
                for c in (f.get("code") or {}).get("coding", [])
            )
        ]
        targeted.sort(key=lambda key: event_date(self.facts[key]) or "", reverse=True)
        diagnosis_ids = []
        if re.search(r"diabet|t2dm?|dm2", text):
            diagnosis_ids = [
                f["fact_id"]
                for f in self.patient.get("conditions", [])
                if any(
                    c.get("system") == "http://snomed.info/sct" and c.get("code") == "44054006"
                    for c in (f.get("code") or {}).get("coding", [])
                )
            ]
        ids = list(
            dict.fromkeys([demo_id, *diagnosis_ids, *targeted[:4], *[key for key, _ in ranked]])
        )
        result, size = [], 0
        terms = set(tokens(criterion["criterion_text"]))
        for key in ids:
            fact = fact_summary(self.facts[key])
            if "components" in fact:
                fact["components"] = [
                    c for c in fact["components"] if terms & set(tokens(label(c)))
                ]
                if len(fact["components"]) != len(self.facts[key].get("components", [])):
                    fact["context_note"] = (
                        "Only criterion-relevant components included; absence is not negative evidence."
                    )
            length = len(json.dumps(fact, ensure_ascii=False))
            # Omit an oversized fact as a whole instead of truncating clinical values.
            if length > 2500 or size + length > 12000:
                continue
            result.append(fact)
            size += length
            if len(result) >= self.limit:
                break
        return result


class Retriever:
    def __init__(self, store, manifest: dict, vector_index=None):
        self.store, self.manifest, self.vector_index = store, manifest, vector_index
        docs = {}
        for trial_id in manifest["trial_ids"]:
            trial = store.trials[trial_id]
            docs[trial_id] = " ".join(
                [
                    trial.get("brief_title") or "",
                    " ".join(trial.get("conditions", [])),
                    trial.get("brief_summary") or "",
                    " ".join(c["criterion_text"] for c in store.criteria[trial_id]),
                ]
            )
        self.lexical = BM25(docs)

    def retrieve(self, patient: dict, question: str, top_k: int) -> list[dict]:
        query = patient_query(patient, question)
        lexical = self.lexical.rank(query)
        rankings = [lexical]
        semantic = {}
        if self.vector_index is not None:
            vector_hits = self.vector_index.query(query)
            rankings.append([(hit["trial_id"], 0) for hit in vector_hits])
            semantic = {hit["trial_id"]: hit for hit in vector_hits}
        scores = Counter()
        for ranking in rankings:
            for rank, (key, _) in enumerate(ranking, 1):
                scores[key] += 1 / (60 + rank)
        result = []
        for trial_id, score in sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))[:top_k]:
            result.append(
                {
                    "trial_id": trial_id,
                    "method": "hybrid_rrf" if semantic else "bm25",
                    "rank_score": round(score, 8),
                    "bm25_score": round(dict(lexical).get(trial_id, 0), 4),
                    "semantic_hit": semantic.get(trial_id),
                }
            )
        return result
