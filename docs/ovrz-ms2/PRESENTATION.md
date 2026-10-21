# Part 5 presentation and individual preparation

## Short English introduction

“My contribution is the application skeleton and its integration with our
backend. Users can select a synthetic patient, ask a trial-related question,
and review candidate trials with criterion-level decisions and evidence.

The frontend sends an actual HTTP request and displays the backend response.
It also handles loading and errors, preserves unknown findings, and lets us
inspect the returned JSON.

The default demo uses offline retrieval and rules, which is clearly labeled.
The `/retrieve` API shows actual vector retrieval from Chroma. The live model
workflow is available through the team's configuration.

For MS2, I have prepared the application, API handoff, a dedicated environment
and container configuration, plus example inputs, outputs and test evidence.”

## Three-minute demonstration

1. Select patient `060e72d3…`. Show the reference date and source records.
2. Use the default question and 3 trials. Click Run screening.
3. Explain that OFFLINE means no cloud LLM; the backend still runs retrieval.
4. Show candidate trial IDs and registry links.
5. Collapse the first trial and expand the second trial's criteria. Show an age
   assessment, fact references and UNKNOWN entries.
6. Open the actual response JSON, then close it.
7. Use `/docs` to call `/retrieve`. Show criterion text, source IDs and distance.
   Explain that this is a separate lexical-vector baseline, not offline
   screening's BM25 retriever.
8. Show the source hashes and saved input/output in the repository.

## Material to put in the team's slides

This is slide content and speaker preparation, not a finished team slide deck.

**Application slide:** patient selection, question submission, actual backend
response, criterion evidence and missing information. Use `../ms2/evidence/ui-screening.png`.

**Interface slide:** browser sends patient ID, question and top_k to `/screen`.
Backend loads patient facts, retrieves trials and returns structured assessments.
Browser renders the response and preserves errors.

**Reproducibility slide:** locked uv environment, isolated Compose project,
fixed data hashes, actual query/context artifacts. Use
`../ms2/evidence/retrieved_context.json`. Explicitly state the container/cloud validation
status supported by the final team's evidence.

## Individual-check questions and concise answers

**Is this only a static webpage?**
No. JavaScript calls the actual API. FastAPI reads the team's data and invokes
the existing workflow. The page renders the returned JSON.

**Where is your code?**
`services/frontend/static/app.js` handles requests and rendering.
`services/frontend/app.py` wraps the team API and serves static assets.
Run commands and container files are in `demo/ovrz`.

**Does the frontend send only an ID or the entire patient?**
This UI sends an ID; the backend resolves the complete normalized record.
The original API also supports an inline normalized patient object.

**Where does the patient data originate?**
Part 2 processes official synthetic Synthea FHIR data. The cohort is 25
patients and has a historical reference date, not a current clinical assessment.

**Where do the trial results come from?**
Part 1's versioned ClinicalTrials.gov snapshot. The demo searches a fixed
50-trial subset rather than the entire registry in real time.

**What is RAG doing in this demo?**
The vector view demonstrates question/patient context to stored criterion
fragments in Chroma. Default screening uses BM25 and rules. The team's live
mode adds Gemini embeddings and generation with evidence checks.

**Why does the default answer sometimes contain many UNKNOWNs?**
Offline rules cover limited cases. We preserve uncertainty when a condition
needs interpretation or sufficient evidence is unavailable.

**Why not simply ask a general model?**
The workflow supplies traceable trial conditions and patient facts, and checks
evidence references. That structure supports inspection and reproducibility.
It does not by itself establish validated clinical accuracy.

**What is the local vector model?**
A deterministic signed token-hash baseline, 512 dimensions. It is lexical,
not a pretrained semantic embedding model. Gemini has a separate index identity.

**What happens when the backend fails?**
The UI shows an explicit failure and does not invent a result. Structured
workflow errors are preserved. Browser cancellation may not stop backend work.

**How are secrets handled?**
The optional live configuration mounts a credential file from outside the repo.
The browser never receives credentials. Do not display secret values in Q&A.

**How do you know the app works?**
Show the current branch's frontend tests, actual HTTP checks, screenshots and
recorded query/context. Container and cloud claims require separate run evidence.

**What code did AI help write?**
AI assisted the frontend, wrapper, demo configuration and verification.
Be able to trace `run()` in app.js to `/screen`, then to the upstream workflow.
Explain the checks and limits rather than claiming to have memorized every line.

## What to rehearse

The latest assignment specifies a 10–15-minute team presentation, about
10 minutes of group Q&A, then about 5 minutes per student with 3–4 individual
questions in a separate breakout room. Everyone must understand the whole
project, including AI-assisted code. Bring the final team slides and be ready
to navigate to code, data manifests, Docker configuration and tests.

## Screenshot files

The original PNG bytes are preserved in `docs/ovrz-ms2/evidence/screenshots.base64.json`.
Run `python demo/ovrz/restore-screenshots.py` from the repository root to restore
`ui-screening.png` and `ui-retrieval.png` under `artifacts/ovrz/screenshots/`.
This text encoding is used because the browser upload channel did not complete.
