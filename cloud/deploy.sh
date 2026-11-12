#!/usr/bin/env bash
# Cloud actions. Local Compose and its four Make commands remain unchanged.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a
source cloud/config.env
set +a
mkdir -p artifacts/cloud
action=${1:-help}
# Like the course workflow container, mount code, data and local credentials.
workflow() {
  if [[ ! -f secrets/google-credentials.json ]]; then
    echo 'Copy your Google ADC file to secrets/google-credentials.json. See README.md.' >&2
    exit 1
  fi
  docker build -f docker/workflow/Dockerfile --build-arg SOURCE_COMMIT="$(git rev-parse HEAD)" -t trialmatch-workflow:local .
  docker run --rm \
    -v "$PWD/cloud:/app/cloud:ro" \
    -v "$PWD/services:/app/services:ro" \
    -v "$PWD/evaluation:/app/evaluation:ro" \
    -v "$PWD/artifacts:/app/artifacts" \
    -v "$PWD/secrets:/secrets:ro" \
    -e GOOGLE_APPLICATION_CREDENTIALS=/secrets/google-credentials.json \
    -e GCP_PROJECT="$GCP_PROJECT" \
    -e GCP_LOCATION=global \
    trialmatch-workflow:local python -m "$@"
}

if [[ "$action" == build || ( "$action" == pipeline && "${2:-}" != --compile-only ) ]]; then
  # Clear deployment permission before target/dependency checks can fail.
  rm -f artifacts/cloud/validated_deployment.json artifacts/cloud/validated_release.txt \
    artifacts/cloud/validation.json artifacts/cloud/pipeline_job.txt
fi
if [[ "$action" == build ]]; then
  # A failed rebuild must not leave the previous build selected for publication.
  rm -f artifacts/cloud/image_version.txt artifacts/cloud/release_target.json
  BUILD_RESULT=$(mktemp artifacts/cloud/build-result.XXXXXX)
  BUILD_INPUTS="$BUILD_RESULT.inputs.json"
  trap 'rm -f "$BUILD_RESULT" "$BUILD_INPUTS"' EXIT
  python3 -m cloud.release capture-inputs --input-manifest="$BUILD_INPUTS"
  VERSION=$(python3 - <<'PY'
import hashlib, pathlib, subprocess
h = hashlib.sha256()
for name in sorted(set(subprocess.check_output(['git', 'ls-files', '-co', '--exclude-standard', '-z']).decode().split('\0'))):
    p = pathlib.Path(name)
    if name and p.is_file():
        h.update(name.encode() + b'\0' + p.read_bytes())
print(h.hexdigest()[:16])
PY
)
  gcloud builds submit . --project="$GCP_PROJECT" --region="$GCP_REGION" --config=cloud/build.yaml \
    --substitutions="_REGISTRY=$REGISTRY,_VERSION=$VERSION,_SOURCE_COMMIT=$(git rev-parse HEAD)" \
    --gcs-source-staging-dir="gs://$GCS_BUCKET/builds/source" \
    --service-account="projects/$GCP_PROJECT/serviceAccounts/trialmatch-build@$GCP_PROJECT.iam.gserviceaccount.com" \
    --suppress-logs --format=json > "$BUILD_RESULT"
  python3 -m cloud.release record --build-result="$BUILD_RESULT" --version="$VERSION" \
    --registry="$REGISTRY" --bucket="$GCS_BUCKET" --input-manifest="$BUILD_INPUTS"
  printf '%s\n' "$VERSION" > artifacts/cloud/image_version.txt
  exit
fi
if [[ "$action" == help ]]; then
  echo 'Usage: bash cloud/deploy.sh build|publish|database|pipeline|app'
  exit
fi
VERSION=$(cat artifacts/cloud/image_version.txt)
if [[ "$action" == publish || "$action" == pipeline ]]; then
  # Read the same saved build result for both actions; never resolve a mutable tag here.
  TARGET=$(python3 -m cloud.release resolve --version="$VERSION" \
    --registry="$REGISTRY" --bucket="$GCS_BUCKET")
  IFS=$'\t' read -r WORKFLOW_IMAGE RELEASE <<< "$TARGET"
fi
case "$action" in
  publish)
    workflow cloud.tasks publish --output="${RELEASE%/release.json}" \
      --image="$WORKFLOW_IMAGE" --release-target=artifacts/cloud/release_target.json
    ;;
  database)
    IMAGE_TAG=$(python3 -m cloud.release image-tag --version="$VERSION" \
      --registry="$REGISTRY" --bucket="$GCS_BUCKET")
    if ! gcloud compute disks describe chroma-data --zone="$GCP_ZONE" --project="$GCP_PROJECT" >/dev/null 2>&1; then
      gcloud compute disks create chroma-data --size=10GB --type=pd-standard --zone="$GCP_ZONE" --project="$GCP_PROJECT"
    fi
    if ! gcloud compute instances describe "$DATABASE" --zone="$GCP_ZONE" --project="$GCP_PROJECT" >/dev/null 2>&1; then
      gcloud compute instances create "$DATABASE" --project="$GCP_PROJECT" --zone="$GCP_ZONE" \
        --machine-type=e2-small --image-family=debian-12 --image-project=debian-cloud \
        --boot-disk-size=10GB --boot-disk-type=pd-standard \
        --disk=name=chroma-data,device-name=chroma-data,auto-delete=no \
        --network="$NETWORK" --subnet="$SUBNET" --private-network-ip="$CHROMA_IP" \
        --tags=trialmatch-chroma --service-account="trialmatch-chroma@$GCP_PROJECT.iam.gserviceaccount.com" \
        --scopes=cloud-platform --metadata="chroma-image=$REGISTRY/chroma:$IMAGE_TAG" \
        --metadata-from-file=startup-script=cloud/chroma-startup.sh
    fi
    ;;
  pipeline)
    workflow cloud.pipeline --project="$GCP_PROJECT" --region="$GCP_REGION" \
      --bucket="$GCS_BUCKET" --image="$WORKFLOW_IMAGE" --release="$RELEASE" \
      --release-target=artifacts/cloud/release_target.json "${@:2}"
    ;;
  app)
    TARGET=$(python3 -m cloud.release deployment --version="$VERSION" \
      --registry="$REGISTRY" --bucket="$GCS_BUCKET" --project="$GCP_PROJECT" --region="$GCP_REGION")
    IFS=$'\t' read -r API_IMAGE RELEASE <<< "$TARGET"
    # Deploy privately first. Enable browser login with IAP in the Cloud Run console.
    gcloud run deploy "$SERVICE" --project="$GCP_PROJECT" --region="$GCP_REGION" \
      --image="$API_IMAGE" --command=python --args=-m,cloud.tasks,serve \
      --service-account="trialmatch-api@$GCP_PROJECT.iam.gserviceaccount.com" \
      --network="$NETWORK" --subnet="$SUBNET" --vpc-egress=private-ranges-only \
      --no-allow-unauthenticated --min-instances=0 --max-instances=1 --max=1 \
      --cpu=1 --memory=2Gi --concurrency=1 --timeout=300 --port=8080 \
      --set-env-vars="TRIALMATCH_MODE=live,GCP_PROJECT=$GCP_PROJECT,GCP_LOCATION=global,RELEASE_URI=$RELEASE,CHROMADB_HOST=$CHROMA_IP,CHROMADB_PORT=8000,TRIALMATCH_ARTIFACTS=/app/artifacts,TRIALMATCH_CORS_ORIGINS="
    ;;
  *) echo "Unknown action: $action" >&2; exit 1 ;;
esac
