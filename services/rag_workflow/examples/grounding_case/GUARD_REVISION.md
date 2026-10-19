# Evidence-check revision: fewer false abstentions

## Actual rerun, October 19, 2026

The same normalized fixture, source trial/criteria, cohort manifest, Chroma index and model defaults were retained. No albumin reference range or prednisone classification was inserted into the fixture. The code now performs bounded evidence checks before model interpretation, and uses the same checks to validate cited evidence after generation.

| Criterion | Initial guarded result | Revised actual result | Evidence check |
|---|---|---|---|
| inc_001 | UNKNOWN | MET | BMI 37.2 >= 35, matching measurement/unit |
| inc_002 | MET | MET | Model judgment using the supplied diabetes diagnosis |
| inc_003 | UNKNOWN | MET | HbA1c 7.8 >= 6.5 OR fasting glucose 8.1 >= 7; missing non-fasting glucose does not invalidate true alternatives |
| inc_004 | UNKNOWN | MET | Explicit ability to provide informed consent, not merely alertness |
| exc_001 | UNKNOWN | NOT_MET | Explicit negative pregnancy-test text; an unrelated Boolean false does not qualify |
| exc_002 | UNKNOWN | NOT_MET | Explicit negative history covers all three named surgery types |
| exc_003 | UNKNOWN | UNKNOWN | Symptoms/history still insufficient |
| exc_004 | UNKNOWN | NOT_MET | Negative history covers gastric AND duodenal ulcer alternatives; "no known history" qualifier preserved |
| exc_005 | UNKNOWN | UNKNOWN | No source-provided albumin range and pre-operative timing |
| exc_006 | UNKNOWN | UNKNOWN | Severe organ-disease history still insufficient |
| exc_007 | UNKNOWN | UNKNOWN | Relative date passes the calendar window; medication class is not supplied |
| exc_008 | UNKNOWN | UNKNOWN | Psychological/functional evidence still insufficient |
| exc_009 | UNKNOWN | NOT_MET | Negative history covers drug use and alcohol abuse over the full 12-month window |
| exc_010 | UNKNOWN | UNKNOWN | A narrower negative history cannot exclude the broader category |

All IDs have prefix `NCT02390973_`. The result changed from **1 known / 13 UNKNOWN** to **8 known / 6 UNKNOWN**, with all **4/4 inclusion positive controls MET**. Match score is **57.1**, calculated as 8 favorable / 14 total criteria. Status remains **NEEDS_MORE_INFORMATION**. This is not an enrollment probability or clinical validation.

The fixed-trial live rerun made one model generation request for unsupported statements; supported statements were checked deterministically. An additional comparison revalidated the original captured Gemini proposals against the new guards without any model requests. It produced the same eight definite results, demonstrating that guard changes, rather than a favorable new model sample, account for the coverage improvement.

The ordinary 50-trial retrieval path still returns the same three candidates and does not select this trial. It remains **PARTIAL** because a separate six-item model batch fails per-criterion alias validation after one repair. This revision does not force the target into top-three retrieval or relax citation validation to hide that failure.

## Numeric and OR rules

`rules.py` now parses complete supported BMI, HbA1c, fasting glucose and non-fasting glucose comparisons, including decimal commas. Units and sample labels must match; generic glucose is not assumed fasting, and no medical unit conversions or thresholds are invented.

Supported flat OR/AND expressions use three-valued logic:

| Expression | Sufficient for MET | Sufficient for NOT_MET | Otherwise |
|---|---|---|---|
| A OR B | At least one MET | Both NOT_MET | UNKNOWN |
| A AND B | Both MET | At least one NOT_MET | UNKNOWN |

All branches must first parse as supported comparisons. Mixed AND/OR precedence, parentheses and unrecognized clauses are not partially evaluated. The existing age comparisons remain available.

Where a criterion requires a recency window, a usable date is required. A threshold-only statement can use an undated source measurement with a warning and no recency claim. Latest-date conflicts, incompatible units, invalid statuses and future observations do not produce a favorable answer by default.

## Explicit source statements and negative scope

`evidence_rules.py` checks the actual cited fact content:

- Consent requires an explicit ability/inability statement; alertness alone does not suffice. Conflicting assertions remain UNKNOWN.
- Negative pregnancy-test text is recognized separately from Boolean false. A Boolean must name the pregnancy predicate, rather than any unrelated test. A known old test is not moved forward to the snapshot date. Undated fixture results retain a timing-review warning and do not establish present-day status.
- Negative history must explicitly deny every relevant alternative and cover the requested interval. "No history of X" differs from "no information about X". A shorter negative window does not cover a longer requested one; a broader positive-history window does not prove recent occurrence.
- Simple shared suffixes are expanded: "gastric or duodenal ulcer" names two ulcer histories. The original "no known history" qualifier remains in the reason and warnings.
- Positive/negative conflicts, incomplete alternatives and narrower disease categories remain unresolved. Exact label/orthographic matching is implemented; a general disease ontology is not.
- Pre-operative albumin can only be compared against a lower reference bound supplied in the same source with matching units and explicit pre-operative context. No built-in normal range is supplied.

These are bounded source templates, not a universal clinical natural-language parser. Unsupported composite, severity or subjective requirements still need review.

## Medication time versus medication classification

The fixture's declared reference date is **2026-10-11**, not the execution date. Subtracting two weeks gives **2026-09-27**, which lies inside the inclusive one-calendar-month interval **2026-09-11 to 2026-10-11**. That time check now runs and passes.

The original medication statement contains the name prednisone but no medication-class mapping. Under the declared closed-context policy, the classification step therefore remains UNKNOWN. The reason distinguishes `MEDICATION_CLASS_NOT_SUPPLIED` from a failed time check.

Tests verify that adding an explicit source `medication_class=corticosteroid` makes the same within-window use MET. This is test-supplied metadata, not a built-in prednisone lookup or a change to the original fixture. Orders/definitions alone do not prove use; an old dose does not establish absence of more recent use.

## Disease-category follow-up

The implemented protection checks whether explicit negative evidence covers the entire named category. It does not infer that "no known inflammatory bowel disease" means absence of all gastrointestinal inflammatory diseases.

A future terminology layer should use versioned concept IDs and directed subtype relationships, with source provenance, rather than embedding similarity as proof of logical equivalence. SNOMED CT represents these using directed `is a` relationships; see the [official logical-model documentation](https://docs.snomed.org/snomed-ct-practical-guides/snomed-ct-starter-guide/5-snomed-ct-logical-model). The full terminology service has not been integrated by this revision.

## Verification and files

**67 automated tests and Ruff passed.** New checks cover BMI boundaries, OR/AND with missing branches, decimal commas, unit/sample mismatches, dated windows, contradictions, explicit consent, pregnancy-text/Boolean representations, negative scope, qualified histories, medication time/class separation and source-provided albumin ranges. Tests make no model calls.

- `guard_revision_verification.json`: compact actual rerun and original-model-response replay.
- `artifacts/rag_workflow/grounding_case_guard_revision/fixed_trial_response.json`: all revised fixed-trial judgments.
- `artifacts/rag_workflow/grounding_case_guard_revision/same_response_guard_replay.json`: comparison holding the old model proposals constant.
- `artifacts/rag_workflow/grounding_case_guard_revision/full_rag_response.json`: ordinary RAG result, including PARTIAL errors.
- `tests/test_evidence_rules.py`: evidence-check regressions.

From the repository root:

```bash
uv run --project services/rag_workflow --locked --group versioning \
  python -m unittest discover -s services/rag_workflow/tests -v

uv run --project services/rag_workflow --locked \
  --env-file services/rag_workflow/.env \
  python -m services.rag_workflow.verify_grounding --live \
  --output-dir artifacts/rag_workflow/grounding_case_guard_revision_replay
```

The initial run is retained separately. Replaying can reuse caches; inspect metrics. A complete end-to-end success is still not established, and the runner exits 1 for PARTIAL. These local changes have not been pushed.
