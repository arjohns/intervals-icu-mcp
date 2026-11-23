#!/usr/bin/env bash
# Deploy intervals-icu-mcp to Google Cloud Run with Google sign-in.
#
# Safe to re-run: every step checks before it creates. Secrets are typed in
# at a hidden prompt the first time and never echoed or written to disk.
#
# Usage:
#   PROJECT=my-project ALLOWED_EMAILS=me@example.com ./deploy/cloud-run/deploy.sh
#
# Optional: REGION (default us-central1), SERVICE (default intervals-mcp),
#           ATHLETE_ID (asked for if unset), DELETE_MODE (default safe).
set -euo pipefail

: "${PROJECT:?Set PROJECT to your Google Cloud project id}"
: "${ALLOWED_EMAILS:?Set ALLOWED_EMAILS to the Google account(s) allowed to sign in}"
REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-intervals-mcp}"
DELETE_MODE="${DELETE_MODE:-safe}"
SA_NAME="${SERVICE}-run"
SA="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
BUCKET="${PROJECT}-${SERVICE}-state"

SECRET_API_KEY="intervals-icu-api-key"
SECRET_OAUTH="${SERVICE}-google-oauth-client-secret"
SECRET_JWT="${SERVICE}-jwt-signing-key"

g() { gcloud --project="$PROJECT" "$@"; }
say() { printf '\n== %s\n' "$*"; }

say "Enabling the APIs this needs (no-op if already on)"
g services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com secretmanager.googleapis.com >/dev/null

PROJECT_NUMBER="$(g projects describe "$PROJECT" --format='value(projectNumber)')"
BASE_URL="https://${SERVICE}-${PROJECT_NUMBER}.${REGION}.run.app"
say "Service URL will be ${BASE_URL}"
echo "   Google OAuth redirect URI: ${BASE_URL}/auth/callback"
echo "   Claude connector URL:      ${BASE_URL}/mcp"

secret_exists() { g secrets describe "$1" >/dev/null 2>&1; }
create_secret_from_prompt() {
  local name="$1" prompt="$2" value
  read -r -s -p "$prompt: " value; echo
  [ -n "$value" ] || { echo "Empty value; aborting." >&2; exit 1; }
  printf '%s' "$value" | g secrets create "$name" --replication-policy=automatic --data-file=- >/dev/null
  unset value
}

say "Secrets"
if secret_exists "$SECRET_API_KEY"; then echo "   $SECRET_API_KEY: present"
else create_secret_from_prompt "$SECRET_API_KEY" "Intervals.icu API key (hidden)"; fi

if secret_exists "$SECRET_OAUTH"; then echo "   $SECRET_OAUTH: present"
else create_secret_from_prompt "$SECRET_OAUTH" "Google OAuth client secret (hidden)"; fi

if secret_exists "$SECRET_JWT"; then echo "   $SECRET_JWT: present"
else
  # Random, never shown. Must stay stable: rotating it signs everyone out.
  python3 -c 'import secrets; print(secrets.token_urlsafe(48), end="")' \
    | g secrets create "$SECRET_JWT" --replication-policy=automatic --data-file=- >/dev/null
  echo "   $SECRET_JWT: generated"
fi

if [ -z "${ATHLETE_ID:-}" ]; then read -r -p "Intervals.icu athlete id (e.g. i123456): " ATHLETE_ID; fi
if [ -z "${GOOGLE_OAUTH_CLIENT_ID:-}" ]; then read -r -p "Google OAuth client id: " GOOGLE_OAUTH_CLIENT_ID; fi

say "Service account ${SA}"
g iam service-accounts describe "$SA" >/dev/null 2>&1 || \
  g iam service-accounts create "$SA_NAME" --display-name="intervals-icu-mcp on Cloud Run" >/dev/null
for s in "$SECRET_API_KEY" "$SECRET_OAUTH" "$SECRET_JWT"; do
  g secrets add-iam-policy-binding "$s" --member="serviceAccount:${SA}" \
    --role=roles/secretmanager.secretAccessor >/dev/null
done

say "State bucket gs://${BUCKET} (encrypted OAuth sessions survive restarts)"
gcloud storage buckets describe "gs://${BUCKET}" --project="$PROJECT" >/dev/null 2>&1 || \
  gcloud storage buckets create "gs://${BUCKET}" --project="$PROJECT" --location="$REGION" \
    --uniform-bucket-level-access --public-access-prevention >/dev/null
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member="serviceAccount:${SA}" --role=roles/storage.objectUser >/dev/null

say "Building and deploying (Cloud Build, a few minutes)"
g run deploy "$SERVICE" \
  --source=. \
  --region="$REGION" \
  --service-account="$SA" \
  --allow-unauthenticated \
  --execution-environment=gen2 \
  --min-instances=0 --max-instances=1 \
  --memory=512Mi --cpu=1 \
  --port=8080 \
  --args="--transport,http,--host,0.0.0.0,--port,8080" \
  --add-volume="name=state,type=cloud-storage,bucket=${BUCKET}" \
  --add-volume-mount="volume=state,mount-path=/data" \
  --set-env-vars="MCP_AUTH=google,MCP_BASE_URL=${BASE_URL},GOOGLE_OAUTH_CLIENT_ID=${GOOGLE_OAUTH_CLIENT_ID},MCP_ALLOWED_EMAILS=${ALLOWED_EMAILS},INTERVALS_ICU_ATHLETE_ID=${ATHLETE_ID},INTERVALS_ICU_DELETE_MODE=${DELETE_MODE},FASTMCP_HOME=/data/fastmcp" \
  --set-secrets="INTERVALS_ICU_API_KEY=${SECRET_API_KEY}:latest,GOOGLE_OAUTH_CLIENT_SECRET=${SECRET_OAUTH}:latest,MCP_JWT_SIGNING_KEY=${SECRET_JWT}:latest"

say "Checks"
curl -fsS "${BASE_URL}/health" && echo "   /health ok"
code="$(curl -s -o /dev/null -w '%{http_code}' -X POST "${BASE_URL}/mcp")"
if [ "$code" = "401" ]; then echo "   /mcp requires sign-in (401) - good"
else echo "   WARNING: /mcp returned ${code}, expected 401" >&2; fi

say "Done. Add a custom connector in Claude with URL ${BASE_URL}/mcp"
