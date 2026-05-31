#!/usr/bin/env bash
# Set up Workload Identity Federation between a Google Cloud project and a
# GitHub repository, so GitHub Actions can call Vertex AI without a long-lived
# service-account key.
#
# Run once, locally, with gcloud auth as a project owner / IAM admin.
#
#   GH_REPO=org/repo bash scripts/setup-gcp-wif.sh
#
# After it finishes, copy the printed `workload_identity_provider` and
# `service_account` strings into the GitHub repo as Actions VARIABLES:
#
#   gh variable set GCP_WIF_PROVIDER  --body "<printed value>"
#   gh variable set GCP_SA_EMAIL      --body "<printed value>"
#   gh variable set GCP_PROJECT_ID    --body "$PROJECT_ID"
#   gh variable set GCP_LOCATION      --body "$LOCATION"
#
# No secrets are needed — WIF brokers a short-lived OIDC token instead.

set -euo pipefail

PROJECT_ID="${PROJECT_ID:-your-gcp-project-id}"
LOCATION="${LOCATION:-us-central1}"
POOL_ID="${POOL_ID:-github-pool}"
PROVIDER_ID="${PROVIDER_ID:-github-provider}"
SA_NAME="${SA_NAME:-spesefiscali-ci}"
GH_REPO="${GH_REPO:?set GH_REPO=org/repo (e.g. mygh/spesefiscali)}"

echo "PROJECT_ID=$PROJECT_ID  GH_REPO=$GH_REPO"

PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

echo "--- enabling APIs"
gcloud services enable iamcredentials.googleapis.com \
                       sts.googleapis.com \
                       aiplatform.googleapis.com \
                       --project "$PROJECT_ID"

echo "--- creating workload identity pool ($POOL_ID)"
gcloud iam workload-identity-pools create "$POOL_ID" \
    --project "$PROJECT_ID" \
    --location global \
    --display-name "GitHub Actions pool" 2>/dev/null || echo "(pool already exists)"

echo "--- creating OIDC provider ($PROVIDER_ID) restricted to repo $GH_REPO"
gcloud iam workload-identity-pools providers create-oidc "$PROVIDER_ID" \
    --project "$PROJECT_ID" \
    --location global \
    --workload-identity-pool "$POOL_ID" \
    --display-name "GitHub provider" \
    --issuer-uri "https://token.actions.githubusercontent.com" \
    --attribute-mapping "google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
    --attribute-condition "assertion.repository=='${GH_REPO}'" 2>/dev/null \
  || echo "(provider already exists; not modifying attribute condition)"

echo "--- creating service account ($SA_EMAIL)"
gcloud iam service-accounts create "$SA_NAME" \
    --project "$PROJECT_ID" \
    --display-name "spesefiscali CI" 2>/dev/null || echo "(SA already exists)"

echo "--- granting roles/aiplatform.user on the project"
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member "serviceAccount:${SA_EMAIL}" \
    --role "roles/aiplatform.user" \
    --condition=None >/dev/null

echo "--- allowing the GitHub repo's WIF principal to impersonate the SA"
POOL_RES="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}"
gcloud iam service-accounts add-iam-policy-binding "$SA_EMAIL" \
    --project "$PROJECT_ID" \
    --role "roles/iam.workloadIdentityUser" \
    --member "principalSet://iam.googleapis.com/${POOL_RES}/attribute.repository/${GH_REPO}" \
    --condition=None >/dev/null

PROVIDER_RES="${POOL_RES}/providers/${PROVIDER_ID}"

cat <<EOF

================================================================
DONE. Set these GitHub repository variables (Settings -> Variables):

  GCP_WIF_PROVIDER = ${PROVIDER_RES}
  GCP_SA_EMAIL     = ${SA_EMAIL}
  GCP_PROJECT_ID   = ${PROJECT_ID}
  GCP_LOCATION     = ${LOCATION}

Or with gh CLI:

  gh variable set GCP_WIF_PROVIDER --body "${PROVIDER_RES}"
  gh variable set GCP_SA_EMAIL     --body "${SA_EMAIL}"
  gh variable set GCP_PROJECT_ID   --body "${PROJECT_ID}"
  gh variable set GCP_LOCATION     --body "${LOCATION}"

No secrets are needed: WIF brokers a short-lived OIDC token at runtime.
================================================================
EOF
