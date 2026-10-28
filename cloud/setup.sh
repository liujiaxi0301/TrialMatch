#!/usr/bin/env bash
# One-time project setup. Run with a Google account that can manage this project.
set -euo pipefail
cd "$(dirname "$0")/.."
source cloud/config.env

gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com \
  compute.googleapis.com aiplatform.googleapis.com iap.googleapis.com --project="$GCP_PROJECT"
PROJECT_NUMBER=$(gcloud projects describe "$GCP_PROJECT" --format='value(projectNumber)')

if ! gcloud storage buckets describe "gs://$GCS_BUCKET" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://$GCS_BUCKET" --project="$GCP_PROJECT" \
    --location="$GCP_REGION" --uniform-bucket-level-access --public-access-prevention
fi
if ! gcloud artifacts repositories describe trialmatch --location="$GCP_REGION" --project="$GCP_PROJECT" >/dev/null 2>&1; then
  gcloud artifacts repositories create trialmatch --repository-format=docker --immutable-tags \
    --location="$GCP_REGION" --project="$GCP_PROJECT"
fi
for name in api pipeline build chroma; do
  email="trialmatch-$name@$GCP_PROJECT.iam.gserviceaccount.com"
  if ! gcloud iam service-accounts describe "$email" --project="$GCP_PROJECT" >/dev/null 2>&1; then
    gcloud iam service-accounts create "trialmatch-$name" --project="$GCP_PROJECT"
  fi
done
for name in api pipeline; do
  for role in aiplatform.user serviceusage.serviceUsageConsumer; do
    gcloud projects add-iam-policy-binding "$GCP_PROJECT" --condition=None \
      --member="serviceAccount:trialmatch-$name@$GCP_PROJECT.iam.gserviceaccount.com" \
      --role="roles/$role" --quiet >/dev/null
  done
done
for name in api build; do
  gcloud storage buckets add-iam-policy-binding "gs://$GCS_BUCKET" \
    --member="serviceAccount:trialmatch-$name@$GCP_PROJECT.iam.gserviceaccount.com" \
    --role=roles/storage.objectViewer >/dev/null
done
gcloud storage buckets add-iam-policy-binding "gs://$GCS_BUCKET" \
  --member="serviceAccount:trialmatch-pipeline@$GCP_PROJECT.iam.gserviceaccount.com" \
  --role=roles/storage.objectAdmin >/dev/null
gcloud storage buckets add-iam-policy-binding "gs://$GCS_BUCKET" \
  --member="serviceAccount:trialmatch-pipeline@$GCP_PROJECT.iam.gserviceaccount.com" \
  --role=roles/storage.bucketViewer >/dev/null
gcloud storage buckets add-iam-policy-binding gs://trialmatch-ac215-yixiao-dvc \
  --member="serviceAccount:trialmatch-pipeline@$GCP_PROJECT.iam.gserviceaccount.com" \
  --role=roles/storage.objectViewer >/dev/null
for name in pipeline chroma; do
  gcloud artifacts repositories add-iam-policy-binding trialmatch --location="$GCP_REGION" --project="$GCP_PROJECT" \
    --member="serviceAccount:trialmatch-$name@$GCP_PROJECT.iam.gserviceaccount.com" \
    --role=roles/artifactregistry.reader >/dev/null
done
gcloud artifacts repositories add-iam-policy-binding trialmatch --location="$GCP_REGION" --project="$GCP_PROJECT" \
  --member="serviceAccount:service-$PROJECT_NUMBER@gcp-sa-aiplatform-cc.iam.gserviceaccount.com" \
  --role=roles/artifactregistry.reader >/dev/null
gcloud artifacts repositories add-iam-policy-binding trialmatch --location="$GCP_REGION" --project="$GCP_PROJECT" \
  --member="serviceAccount:trialmatch-build@$GCP_PROJECT.iam.gserviceaccount.com" \
  --role=roles/artifactregistry.writer >/dev/null
gcloud projects add-iam-policy-binding "$GCP_PROJECT" --condition=None \
  --member="serviceAccount:trialmatch-build@$GCP_PROJECT.iam.gserviceaccount.com" \
  --role=roles/logging.logWriter --quiet >/dev/null

if ! gcloud compute networks describe "$NETWORK" --project="$GCP_PROJECT" >/dev/null 2>&1; then
  gcloud compute networks create "$NETWORK" --subnet-mode=custom --project="$GCP_PROJECT"
fi
if ! gcloud compute networks subnets describe "$SUBNET" --region="$GCP_REGION" --project="$GCP_PROJECT" >/dev/null 2>&1; then
  gcloud compute networks subnets create "$SUBNET" --network="$NETWORK" --range=10.41.0.0/24 \
    --region="$GCP_REGION" --enable-private-ip-google-access --project="$GCP_PROJECT"
fi
if ! gcloud compute firewall-rules describe trialmatch-chroma-internal --project="$GCP_PROJECT" >/dev/null 2>&1; then
  gcloud compute firewall-rules create trialmatch-chroma-internal --network="$NETWORK" \
    --allow=tcp:8000 --source-ranges=10.41.0.0/24 --target-tags=trialmatch-chroma --project="$GCP_PROJECT"
fi
echo "Project resources ready. The Chroma port is accessible only within the TrialMatch subnet."
