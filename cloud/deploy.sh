#!/usr/bin/env bash
# Cloud actions. Local Compose and its four Make commands remain unchanged.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a
source cloud/config.env
set +a
mkdir -p artifacts/cloud
action=${1:-help}
if [[ "$action" == build ]]; then
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
    --substitutions="_REGISTRY=$REGISTRY,_VERSION=$VERSION" \
    --gcs-source-staging-dir="gs://$GCS_BUCKET/builds/source" \
    --service-account="projects/$GCP_PROJECT/serviceAccounts/trialmatch-build@$GCP_PROJECT.iam.gserviceaccount.com"
  printf '%s\n' "$VERSION" > artifacts/cloud/image_version.txt
  exit
fi
if [[ "$action" == help ]]; then
  echo 'Usage: bash cloud/deploy.sh build|publish|database|pipeline|app'
  exit
fi
VERSION=$(cat artifacts/cloud/image_version.txt)
RELEASE="gs://$GCS_BUCKET/releases/$VERSION/release.json"
case "$action" in
  publish)
    uv run --group cloud python -m cloud.tasks publish --output="${RELEASE%/release.json}" \
      --image="$REGISTRY/workflow:$VERSION"
    ;;
  database)
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
        --scopes=cloud-platform --metadata="chroma-image=$REGISTRY/chroma:$VERSION" \
        --metadata-from-file=startup-script=cloud/chroma-startup.sh
    fi
    ;;
  pipeline)
    uv run --group cloud python -m cloud.pipeline --project="$GCP_PROJECT" --region="$GCP_REGION" \
      --bucket="$GCS_BUCKET" --image="$REGISTRY/workflow:$VERSION" --release="$RELEASE"
    ;;
  app)
    RELEASE=$(cat artifacts/cloud/validated_release.txt)
    # Deploy privately first. Enable browser login with IAP in the Cloud Run console.
    gcloud run deploy "$SERVICE" --project="$GCP_PROJECT" --region="$GCP_REGION" \
      --image="$REGISTRY/api:$VERSION" --command=python --args=-m,cloud.tasks,serve \
      --service-account="trialmatch-api@$GCP_PROJECT.iam.gserviceaccount.com" \
      --network="$NETWORK" --subnet="$SUBNET" --vpc-egress=private-ranges-only \
      --no-allow-unauthenticated --min-instances=0 --max-instances=1 --max=1 \
      --cpu=1 --memory=2Gi --concurrency=1 --timeout=300 --port=8080 \
      --set-env-vars="TRIALMATCH_MODE=live,GCP_PROJECT=$GCP_PROJECT,GCP_LOCATION=global,RELEASE_URI=$RELEASE,CHROMADB_HOST=$CHROMA_IP,CHROMADB_PORT=8000,TRIALMATCH_ARTIFACTS=/app/artifacts,TRIALMATCH_CORS_ORIGINS="
    ;;
  *) echo "Unknown action: $action" >&2; exit 1 ;;
esac
