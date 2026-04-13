#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
TEMPLATES_DIR="${PROJECT_ROOT}/demo-templates"
GCS_BUCKET="gs://demoforge-hub-templates"
GCS_PREFIX="templates"

GREEN='\033[0;32m'; RED='\033[0;31m'; NC='\033[0m'
log() { echo -e "${GREEN}[hub-seed]${NC} $*"; }
err() { echo -e "${RED}[hub-seed]${NC} $*" >&2; }

log "Syncing templates → ${GCS_BUCKET}/${GCS_PREFIX}/"

gcloud storage rsync \
  --delete-unmatched-destination-objects \
  --exclude="^\." \
  "${TEMPLATES_DIR}/" \
  "${GCS_BUCKET}/${GCS_PREFIX}/" 2>&1 | grep -v "^$" || {
    err "gcloud storage rsync failed"
    exit 1
}

REMOTE_COUNT=$(gcloud storage ls "${GCS_BUCKET}/${GCS_PREFIX}/" 2>/dev/null | grep -c '\.yaml$' || echo "0")
log "✓ ${REMOTE_COUNT} templates on GCS"
