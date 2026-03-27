#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# setup.sh — One-time GCP project bootstrap
# Run this ONCE before your first deployment.
# Usage: ./scripts/setup.sh <project-id> <region>
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

PROJECT_ID="${1:-}"
REGION="${2:-us-central1}"
APP_NAME="rag-on-gcp"

if [[ -z "$PROJECT_ID" ]]; then
  echo "Usage: $0 <project-id> [region]"
  exit 1
fi

echo "═══════════════════════════════════════════════════════"
echo "  RAG on GCP — Project Bootstrap"
echo "  Project: $PROJECT_ID | Region: $REGION"
echo "═══════════════════════════════════════════════════════"

# ── 1. Set active project ────────────────────────────────────────────────────
gcloud config set project "$PROJECT_ID"

# ── 2. Enable APIs ───────────────────────────────────────────────────────────
echo ""
echo "▶ Enabling required GCP APIs..."
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  storage.googleapis.com \
  aiplatform.googleapis.com \
  secretmanager.googleapis.com \
  vpcaccess.googleapis.com \
  redis.googleapis.com \
  cloudtasks.googleapis.com \
  logging.googleapis.com \
  monitoring.googleapis.com \
  cloudtrace.googleapis.com \
  --project "$PROJECT_ID"

echo "✓ APIs enabled"

# ── 3. Create Artifact Registry repository ──────────────────────────────────
echo ""
echo "▶ Creating Artifact Registry repository..."
if ! gcloud artifacts repositories describe "$APP_NAME" \
    --location="$REGION" --project="$PROJECT_ID" &>/dev/null; then
  gcloud artifacts repositories create "$APP_NAME" \
    --repository-format=docker \
    --location="$REGION" \
    --project="$PROJECT_ID" \
    --description="Docker images for $APP_NAME"
  echo "✓ Repository created: $REGION-docker.pkg.dev/$PROJECT_ID/$APP_NAME"
else
  echo "✓ Repository already exists"
fi

# ── 4. Configure Docker for Artifact Registry ────────────────────────────────
echo ""
echo "▶ Configuring Docker authentication..."
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet
echo "✓ Docker configured"

# ── 5. Create Terraform state bucket (optional) ──────────────────────────────
echo ""
echo "▶ Creating Terraform state bucket..."
TF_STATE_BUCKET="${PROJECT_ID}-tf-state"
if ! gsutil ls -b "gs://${TF_STATE_BUCKET}" &>/dev/null; then
  gsutil mb -p "$PROJECT_ID" -l "$REGION" "gs://${TF_STATE_BUCKET}"
  gsutil versioning set on "gs://${TF_STATE_BUCKET}"
  echo "✓ Terraform state bucket: gs://${TF_STATE_BUCKET}"
  echo ""
  echo "  To use remote state, uncomment the backend block in main.tf:"
  echo "  bucket = \"${TF_STATE_BUCKET}\""
else
  echo "✓ State bucket already exists"
fi

# ── 6. Initialize Terraform ──────────────────────────────────────────────────
echo ""
echo "▶ Initializing Terraform..."
cd infra/terraform
terraform init
cd ../..
echo "✓ Terraform initialized"

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  Bootstrap complete!"
echo ""
echo "  Next steps:"
echo "  1. Copy terraform.tfvars.example → terraform.tfvars"
echo "     cd infra/terraform && cp terraform.tfvars.example terraform.tfvars"
echo "  2. Edit terraform.tfvars with your values"
echo "  3. Run: ./scripts/deploy.sh $PROJECT_ID $REGION"
echo "═══════════════════════════════════════════════════════"
