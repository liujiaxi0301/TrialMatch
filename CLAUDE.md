# Working agreements for TrialMatch

## Commits

Write the commit message and stop there. **Do not append `Co-Authored-By:` or
`Claude-Session:` trailers, or any other generated attribution line.** Commits are
authored by the team member whose Git identity made them.

## Before changing anything

- Module plans live in `docs/ms3/`. Read the plan for the module you are touching
  (`module-a-plan.md`, `module-b-plan.md`) before writing code; they record the
  interfaces other modules depend on and the constraints that invalidate results.
- `cloud/`, `docker/` and `.github/` belong to the infrastructure and pipeline
  owners. Changes there must be additive and agreed before pushing.

## Constraints that are not negotiable

- The 50 trials in `services/rag_workflow/examples/demo_manifest.json` are the fixed
  retrieval benchmark universe. Nothing trains on them. Assert it; do not assume it.
- Relevance labels and benchmark metrics belong to the evaluation owner. Q01–Q02 are
  for development; Q03–Q08 are not inspected or tuned against.
- Credentials never enter Git, an image, or a manifest.
- Never describe any output of this project as clinically validated. The patients are
  synthetic and no clinician has reviewed the judgements.
