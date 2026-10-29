#!/usr/bin/env bash
# Install the private $5 shutdown handler and connect the existing monthly budget.
set -euo pipefail
cd "$(dirname "$0")/../.."
source cloud/config.env
BILLING_ACCOUNT=010756-86A438-122A4C
BUDGET_ID=09b952ae-b595-4834-beab-4ebb149040f0
HANDLER=trialmatch-budget-stop
TOPIC=trialmatch-budget
RUNTIME="trialmatch-budget@$GCP_PROJECT.iam.gserviceaccount.com"
PUSH="trialmatch-budget-push@$GCP_PROJECT.iam.gserviceaccount.com"
ROLE="projects/$GCP_PROJECT/roles/trialmatchBudgetStop"

gcloud services enable billingbudgets.googleapis.com pubsub.googleapis.com --project="$GCP_PROJECT"
PROJECT_NUMBER=$(gcloud projects describe "$GCP_PROJECT" --format='value(projectNumber)')
for name in trialmatch-budget trialmatch-budget-push; do
  if ! gcloud iam service-accounts describe "$name@$GCP_PROJECT.iam.gserviceaccount.com" --project="$GCP_PROJECT" >/dev/null 2>&1; then
    gcloud iam service-accounts create "$name" --project="$GCP_PROJECT"
  fi
done
if ! gcloud iam roles describe trialmatchBudgetStop --project="$GCP_PROJECT" >/dev/null 2>&1; then
  gcloud iam roles create trialmatchBudgetStop --project="$GCP_PROJECT" \
    --title='TrialMatch budget stop' --stage=GA \
    --permissions=run.services.get,run.services.update,compute.instances.get,compute.instances.stop
fi
# Grant access on the two target resources, not across the project.
gcloud run services add-iam-policy-binding "$SERVICE" --project="$GCP_PROJECT" --region="$GCP_REGION" \
  --member="serviceAccount:$RUNTIME" --role="$ROLE" --quiet >/dev/null
gcloud compute instances add-iam-policy-binding "$DATABASE" --project="$GCP_PROJECT" --zone="$GCP_ZONE" \
  --member="serviceAccount:$RUNTIME" --role="$ROLE" --quiet >/dev/null
# Cloud Run also checks actAs on the app identity when updating scaling.
gcloud iam service-accounts add-iam-policy-binding "trialmatch-api@$GCP_PROJECT.iam.gserviceaccount.com" \
  --project="$GCP_PROJECT" --member="serviceAccount:$RUNTIME" \
  --role=roles/iam.serviceAccountUser --quiet >/dev/null

if ! gcloud pubsub topics describe "$TOPIC" --project="$GCP_PROJECT" >/dev/null 2>&1; then
  gcloud pubsub topics create "$TOPIC" --project="$GCP_PROJECT"
fi
gcloud pubsub topics add-iam-policy-binding "$TOPIC" --project="$GCP_PROJECT" \
  --member=serviceAccount:billing-budget-alert@system.gserviceaccount.com \
  --role=roles/pubsub.publisher --quiet >/dev/null
gcloud iam service-accounts add-iam-policy-binding "$PUSH" --project="$GCP_PROJECT" \
  --member="serviceAccount:service-$PROJECT_NUMBER@gcp-sa-pubsub.iam.gserviceaccount.com" \
  --role=roles/iam.serviceAccountTokenCreator --quiet >/dev/null

VERSION=$(python3 - <<'PY'
import hashlib, pathlib
h = hashlib.sha256()
for name in ('main.py', 'pyproject.toml', 'uv.lock', 'Dockerfile'):
    h.update(pathlib.Path('cloud/budget', name).read_bytes())
print(h.hexdigest()[:16])
PY
)
IMAGE="$REGISTRY/budget-stop:$VERSION"
if ! gcloud artifacts docker images describe "$IMAGE" --project="$GCP_PROJECT" >/dev/null 2>&1; then
  gcloud builds submit cloud/budget --project="$GCP_PROJECT" --region="$GCP_REGION" \
    --config=cloud/budget/build.yaml --substitutions="_IMAGE=$IMAGE" \
    --gcs-source-staging-dir="gs://$GCS_BUCKET/builds/source" \
    --service-account="projects/$GCP_PROJECT/serviceAccounts/trialmatch-build@$GCP_PROJECT.iam.gserviceaccount.com"
fi
gcloud run deploy "$HANDLER" --project="$GCP_PROJECT" --region="$GCP_REGION" \
  --image="$IMAGE" --service-account="$RUNTIME" --no-allow-unauthenticated \
  --min-instances=0 --max-instances=1 --max=1 --cpu=1 --memory=256Mi --concurrency=1 --timeout=300 \
  --set-env-vars="GCP_PROJECT=$GCP_PROJECT,GCP_REGION=$GCP_REGION,GCP_ZONE=$GCP_ZONE,TARGET_SERVICE=$SERVICE,TARGET_VM=$DATABASE,BILLING_ACCOUNT=$BILLING_ACCOUNT,BUDGET_ID=$BUDGET_ID"
gcloud run services add-iam-policy-binding "$HANDLER" --project="$GCP_PROJECT" --region="$GCP_REGION" \
  --member="serviceAccount:$PUSH" --role=roles/run.invoker --quiet >/dev/null
URL=$(gcloud run services describe "$HANDLER" --project="$GCP_PROJECT" --region="$GCP_REGION" --format='value(status.url)')
if gcloud pubsub subscriptions describe "$HANDLER" --project="$GCP_PROJECT" >/dev/null 2>&1; then
  gcloud pubsub subscriptions update "$HANDLER" --project="$GCP_PROJECT" \
    --push-endpoint="$URL" --push-auth-service-account="$PUSH" --push-auth-token-audience="$URL" \
    --ack-deadline=300 --min-retry-delay=10s --max-retry-delay=600s --expiration-period=never
else
  gcloud pubsub subscriptions create "$HANDLER" --project="$GCP_PROJECT" --topic="$TOPIC" \
    --push-endpoint="$URL" --push-auth-service-account="$PUSH" --push-auth-token-audience="$URL" \
    --ack-deadline=300 --min-retry-delay=10s --max-retry-delay=600s --expiration-period=never
fi
gcloud billing budgets update "$BUDGET_ID" --billing-account="$BILLING_ACCOUNT" --project="$GCP_PROJECT" \
  --notifications-rule-pubsub-topic="projects/$GCP_PROJECT/topics/$TOPIC" --quiet
echo 'The $5 monthly budget now sends notifications to the shutdown handler.'
