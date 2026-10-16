# MLOps Infrastructure (MS2 Part 4)

The development container and Part 3 API use the same Python 3.12 / uv 0.13.1
environment. The root `pyproject.toml` and `uv.lock` define the shared packages.

## Running the Project

Run these commands from the repository root with Docker running:

```bash
make up    # Start Part 3's offline API and Chroma
make down  # Stop the services; keep the Chroma data
make run   # Run offline screening with the existing data
make dev   # Open the shared environment for development
```

## Inputs and Outputs

The API and `make run` use the processed data already provided by Parts 1 and 2:

- `services/trial_ingestion/data/processed/trials.jsonl`
- `services/trial_ingestion/data/processed/criteria.jsonl`
- `services/patient_processing/data/processed/batch25_patients.jsonl`

Both use Part 3's supplied 50-trial demo manifest without downloading or
reprocessing data. Screening runs offline without a GPU or LLM API call.
The first Docker build and Chroma image download require internet access.

`make run` calls Part 3's existing CLI for one patient and saves the result to
`artifacts/rag_workflow/demo_offline.json`.

## API and Chroma

The API is available at `http://localhost:8080`. Check `/health`, list patients
at `/patients`, or send Part 3's existing example request:

```bash
curl --fail http://localhost:8080/screen \
  -H 'Content-Type: application/json' \
  --data-binary @services/rag_workflow/examples/screen_request.json
```

Chroma is reachable from the API at `rag-chromadb:8000`; its data is stored in
the `rag-chroma-data` Docker volume. Offline screening does not use the vector
index. Live indexing and LLM calls have not been verified in this setup.

## Development

Inside `make dev`, use `uv add package-name` to add a dependency.
Share both `pyproject.toml` and `uv.lock` when changing packages.

## TODO: Part 5

- Add the frontend service when its code and startup command are available.
- Connect it to Part 3's existing API and check the complete user flow together.
