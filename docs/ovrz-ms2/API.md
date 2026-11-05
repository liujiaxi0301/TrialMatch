# Application API contract

The frontend is served by `services.frontend.app` on the same origin as the API.
It reuses `services.rag_workflow.api.create_app`; it does not copy or replace
the team's screening logic. `/docs` exposes the generated OpenAPI schema.

- `GET /patients`: cohort summaries.
- `GET /patients/{patient_id}`: full normalized patient record.
- `POST /screen`: original screening endpoint.
- `POST /retrieve`: separate local Chroma vector demonstration.
- `GET /metadata`: hashes, counts, dates and actual mode.
- `GET /health`: source/manifest readiness, not proof of cloud availability.

The UI sends:

```json
{
  "patient_id": "060e72d3-912e-55cd-0c92-5faa6cb7a6db",
  "question": "Which type 2 diabetes trials may suit this patient, and what information needs review?",
  "top_k": 3
}
```

The backend loads the full normalized patient record. The original `/screen`
also accepts a normalized patient object instead of a patient ID. Raw FHIR
must first pass through Part 2. Patient upload is not in this UI.

The screening response includes run ID, mode, status, answer, candidate trials,
warnings, errors, provenance and metrics. Each candidate includes criterion
assessments, evidence indexed by fact ID, missing information and a source URL.
The frontend preserves MET/NOT_MET/UNKNOWN and separates supporting evidence
from context that does not prove a decision.

Exclusion MET means a screening barrier. UNKNOWN does not mean absent.
The score is not an enrollment probability.

Actual responses are in `evidence/http/`. Unknown patients return 404, invalid
requests return 422, and unavailable local vector infrastructure returns an
explicit error. Workflow errors may be in a structured response; read
`result_status` and `errors`, not only HTTP status.

The browser displays progress and allows cancellation. It times out after
300 seconds. An error never triggers a mock success response.
