# Current-version data pipeline: 2026-11-05

Result: **PASSED** for the data pipeline at commit
`a8f138630dd5aa8ff4ff4d6844a76f5a4c473170` on `xuyang/ms3-pipeline`.
Xuyang ran the verification script in Google Cloud Shell and supplied the terminal
screenshot and this evidence archive. The files were checked locally against the
reviewed commit; the reviewer did not independently query the GCP APIs.

## Run identity

| Item | Value |
| --- | --- |
| Project / region | `trialmatch-ac215-yixiao` / `us-east1` |
| Pipeline run | `trialmatch-data-pipeline-20261105205047` |
| Cloud Build ID | `55298693-4647-4890-b5eb-bf0a22f2fae0` |
| Source version | `eb47d5598bf2cd57` |
| Workflow digest | `sha256:5d5078d427720f231a79228edd0011a4d7f330086014db2c4211b92d948930ae` |
| Exit code | `0` |
| Validated records | 1,313 trials; 25 patients; 18,456 criteria; 607 vectors |
| Offline screening | `OK` |

- [Vertex run](https://console.cloud.google.com/vertex-ai/locations/us-east1/pipelines/runs/trialmatch-data-pipeline-20261105205047?project=15733748057)
- [Cloud Build](https://console.cloud.google.com/cloud-build/builds;region=us-east1/55298693-4647-4890-b5eb-bf0a22f2fae0?project=trialmatch-ac215-yixiao)
- [Summary with full image and release URIs](summary.json)

## Evidence and checks

- [Build target](cloud/release_target.json) records the unique image tag, workflow
  and API digests, seven input hashes and the combined data fingerprint.
- [Validation](cloud/validation.json), [job ID](cloud/pipeline_job.txt),
  [output release](cloud/validated_release.txt) and
  [deployment binding](cloud/validated_deployment.json) identify the same run and output.
- [Pipeline log](pipeline.log) records job completion and the validated release.
  [Publication log](publish.log) identifies the input release from the build target.
  [Build log](build.log) records submission; detailed builder logs remain in Cloud Build.
- [Compiled YAML](cloud/pipeline.yaml) matches a fresh compilation from the reviewed
  code and uses the recorded workflow digest for all three task containers.
- [Audit](audit.json) records 27 local evidence-consistency checks, all passing,
  and SHA256 hashes for the 16 supplied files. These checks are separate from the
  existing 45 regression tests. The source version was recomputed, the six
  Git-tracked publication inputs match the commit, and the ignored snapshot hash
  matches its committed snapshot summary. No common credential patterns were found.

The uploaded archive SHA256 is
`efc99b554cd6dc92dace990275f708f17331190b8cdcd69c37bd75339ebd80dc`.
Original evidence bytes are preserved. `audit.json`, this README and `.gitignore`
were added during review. The capture script was outside the repository and was
not part of the tested commit.

## Scope and remaining evidence

This run covers `fetch-raw -> process-trials -> validate-data`, using the fixed
snapshot and the current release protections. It does not demonstrate cloud
failure behavior for deliberately invalid inputs, a second rebuild of identical
source, model training, clinical benchmarking, or deployment of the new API image.
The successful deployment binding is an input to a future deployment, not a record
that deployment occurred.

The saved YAML contains KFP's default `enableCache: true`; the reviewed submission
code overrides it with `enable_caching=False`. Job API metadata is not in the
archive, so the effective runtime flag was not independently inspected here.
The archive also omits the raw Cloud Build result, GCS release manifests, snapshot
bytes and `offline_screening.json`; their references and the validation report are
available. No new execution is needed simply to collect those existing artifacts.

Still add the Vertex runtime graph screenshot showing this run's three successful
nodes. A separate invalid-input cloud run and the agreed B/C training/evaluation
integration remain outstanding. This evidence does not establish completion of
the full Module A assignment or all MS3 requirements.
