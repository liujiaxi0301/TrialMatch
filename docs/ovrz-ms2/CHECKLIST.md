# MS2 handoff checklist

## Personal application deliverables

- [x] Minimal working English UI and actual backend interaction.
- [x] Patient search/selection, questions, candidates, criterion evidence.
- [x] Loading, cancellation, errors and actual JSON inspection/download.
- [x] Explicit offline/live and vector-baseline labels.
- [x] API documentation, setup instructions and English presentation notes.
- [x] UI screenshots and functional evidence.
- [ ] Include the original MS1 mock-up/wireframe in the final team slides and
  explain the change from simulated output to actual API responses.
- [ ] Rehearse both your contribution and the team's other modules.

## Shared infrastructure and RAG deliverables

- [x] Dedicated Dockerfile, uv pyproject/lock and Compose configuration supplied.
- [x] One-command path from fixed snapshots to vector index, query/context and app.
- [x] Source/version hashes and actual local sample input/output.
- [x] Collection/preprocessing modules retained from the base branch.
- [ ] Infrastructure owner runs Compose on a Docker host and captures logs,
  input/output and running-instance screenshots.
- [ ] Team explains the collection/preprocessing stages and versioned snapshot
  boundary. A fresh internet download on every demo run is not explicitly required.
- [ ] If presenting live LLM answers, execute and record a real live model run.

The supplied MS2 text requires a basic functional RAG-ready workflow and a
query-to-retrieved-context example. It does not explicitly require completed
LLM-generated answers, public hosting, authentication, or a production app.
Basic frontend/backend interaction must be real; other features may be placeholders.

The local vector baseline demonstrates infrastructure, not semantic retrieval
quality or clinical accuracy. Do not describe default offline results as LLM output.

## Final team submission

- [ ] Integrate this additive branch with the team's final `milestone2` branch.
- [ ] Add final slides and actual container evidence.
- [ ] Push the final `milestone2` commit.
- [ ] Submit its full commit hash on Canvas by October 20, 10:00 PM ET.

The feature branch is a review/handoff branch, not the assignment's final
submission branch. A ZIP or feature-branch push does not complete Canvas submission.
