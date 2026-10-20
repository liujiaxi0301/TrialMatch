# TrialMatch
Explainable clinical trial eligibility screening

## Run the shared application

With Docker running, use `make up` from the repository root and open
http://localhost:8080. Use `make down` to stop it.

The root Dockerfile, Compose files, `pyproject.toml` and `uv.lock` provide the
shared environment. See [infrastructure setup](README_INFRA.md) for modules
and Make commands.

## MS2 Part 3: RAG / Retrieval / Workflow

Patient record + question → candidate trials + match scores + evidence-linked explanations.
Start with [the Part 3 README](services/rag_workflow/README.md) for local commands, every file's purpose,
the API contract, live/offline behavior, verification, and handoff to Parts 4 and 5.
This development branch is based on `feat/patient-processing` so the 25-patient T2D cohort is available.
