#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# local_dev.sh — Start the full local development stack
# Usage: ./scripts/local_dev.sh [up|down|logs|reset]
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

COMMAND="${1:-up}"

check_env() {
  if [[ ! -f ".env" ]]; then
    echo "⚠  .env file not found. Copying from .env.example..."
    cp .env.example .env
    echo "   Edit .env and add your GCP_PROJECT_ID and GCS_BUCKET_NAME, then re-run."
    exit 1
  fi
}

case "$COMMAND" in
  up)
    check_env
    echo "▶ Starting local development stack with monitoring..."
    docker compose --profile monitoring up --build -d
    echo ""
    echo "Services:"
    echo "  RAG App:    http://localhost:8080/docs"
    echo "  Prometheus: http://localhost:9090"
    echo "  Grafana:    http://localhost:3000 (admin/admin)"
    echo ""
    echo "Logs: ./scripts/local_dev.sh logs"
    ;;
  down)
    docker compose --profile monitoring down
    echo "✓ Stack stopped"
    ;;
  logs)
    docker compose logs -f rag
    ;;
  reset)
    echo "⚠ This will delete all local data (ChromaDB, Redis, Prometheus, Grafana)"
    read -r -p "Are you sure? (y/N) " confirm
    if [[ "$confirm" == "y" || "$confirm" == "Y" ]]; then
      docker compose --profile monitoring down -v
      echo "✓ All volumes deleted"
    fi
    ;;
  *)
    echo "Usage: $0 [up|down|logs|reset]"
    exit 1
    ;;
esac
