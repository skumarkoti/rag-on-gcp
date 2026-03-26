#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# deploy.sh — Build Docker image, push to Artifact Registry, deploy via Terraform
# Usage: ./scripts/deploy.sh <project-id> [region] [image-tag]
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

PROJECT_ID="${1:-}"
REGION="${2:-us-central1}"
IMAGE_TAG="${3:-$(git rev-parse --short HEAD 2>/dev/null || echo latest)}"
APP_NAME="rag-on-gcp"

if [[ -z "$PROJECT_ID" ]]; then
  echo "Usage: $0 <project-id> [region] [image-tag]"
  exit 1
fi

REGISTRY="${REGION}-docker.pkg.dev"
IMAGE_BASE="${REGISTRY}/${PROJECT_ID}/${APP_NAME}/${APP_NAME}"
IMAGE_URI="${IMAGE_BASE}:${IMAGE_TAG}"
IMAGE_LATEST="${IMAGE_BASE}:latest"

echo "═══════════════════════════════════════════════════════"
echo "  RAG on GCP — Deployment"
echo "  Project:   $PROJECT_ID"
echo "  Region:    $REGION"
echo "  Image tag: $IMAGE_TAG"
echo "═══════════════════════════════════════════════════════"

# ── 1. Build Docker image ────────────────────────────────────────────────────
echo ""
echo "▶ Building Docker image..."
docker build \
  --platform linux/amd64 \
  --tag "$IMAGE_URI" \
  --tag "$IMAGE_LATEST" \
  --file Dockerfile \
  .
echo "✓ Image built: $IMAGE_URI"

# ── 2. Push to Artifact Registry ────────────────────────────────────────────
echo ""
echo "▶ Pushing image to Artifact Registry..."
docker push "$IMAGE_URI"
docker push "$IMAGE_LATEST"
echo "✓ Image pushed: $IMAGE_URI"

# ── 3. Terraform apply ───────────────────────────────────────────────────────
echo ""
echo "▶ Applying Terraform configuration..."
cd infra/terraform

if [[ ! -f "terraform.tfvars" ]]; then
  echo "ERROR: terraform.tfvars not found!"
  echo "Copy infra/terraform/terraform.tfvars.example to infra/terraform/terraform.tfvars and fill in your values."
  exit 1
fi

terraform init -input=false
terraform plan \
  -var="project_id=${PROJECT_ID}" \
  -var="region=${REGION}" \
  -var="image_tag=${IMAGE_TAG}" \
  -out=tfplan \
  -input=false

terraform apply -input=false -auto-approve tfplan
rm -f tfplan

echo ""
RAG_URL=$(terraform output -raw rag_app_url 2>/dev/null || echo "")
GRAFANA_URL=$(terraform output -raw grafana_url 2>/dev/null || echo "")
cd ../..

# ── 4. Smoke test ────────────────────────────────────────────────────────────
if [[ -n "$RAG_URL" ]]; then
  echo ""
  echo "▶ Running smoke test..."
  sleep 10  # Allow Cloud Run to stabilize
  HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${RAG_URL}/api/v1/health/live" || echo "000")
  if [[ "$HTTP_STATUS" == "200" ]]; then
    echo "✓ Smoke test passed (HTTP $HTTP_STATUS)"
  else
    echo "⚠ Smoke test returned HTTP $HTTP_STATUS — check Cloud Run logs"
  fi
fi

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  Deployment complete!"
echo ""
echo "  RAG App:  ${RAG_URL:-<see terraform output>}"
echo "  Grafana:  ${GRAFANA_URL:-<see terraform output>}"
echo ""
echo "  API docs: ${RAG_URL}/docs"
echo "  Metrics:  ${RAG_URL}/metrics"
echo "  Health:   ${RAG_URL}/api/v1/health/ready"
echo ""
echo "  Upload a PDF:"
echo "  curl -X POST ${RAG_URL}/api/v1/documents/upload \\"
echo "       -F 'file=@your-document.pdf'"
echo ""
echo "  Query your documents:"
echo "  curl -X POST ${RAG_URL}/api/v1/query/ \\"
echo "       -H 'Content-Type: application/json' \\"
echo "       -d '{\"question\": \"What is this document about?\"}'"
echo "═══════════════════════════════════════════════════════"
