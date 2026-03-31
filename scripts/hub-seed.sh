#!/usr/bin/env bash
set -euo pipefail

HUB_ALIAS="demoforge-hub"
HUB_BUCKET="demoforge-templates"
HUB_PREFIX="templates"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
TEMPLATES_DIR="${PROJECT_ROOT}/demo-templates"

GREEN='\033[0;32m'; RED='\033[0;31m'; NC='\033[0m'
log() { echo -e "${GREEN}[hub-seed]${NC} $*"; }
err() { echo -e "${RED}[hub-seed]${NC} $*" >&2; }

# Source env to get credentials
[[ -f "${PROJECT_ROOT}/.env.hub" ]]   && source "${PROJECT_ROOT}/.env.hub"
[[ -f "${PROJECT_ROOT}/.env.local" ]] && source "${PROJECT_ROOT}/.env.local"

ENDPOINT="${DEMOFORGE_SYNC_ENDPOINT:-}"
ACCESS_KEY="${DEMOFORGE_SYNC_ACCESS_KEY:-}"
SECRET_KEY="${DEMOFORGE_SYNC_SECRET_KEY:-}"

if [[ -z "$ENDPOINT" || -z "$ACCESS_KEY" || -z "$SECRET_KEY" ]]; then
    err "Sync credentials not set. Configure DEMOFORGE_SYNC_ENDPOINT, DEMOFORGE_SYNC_ACCESS_KEY, DEMOFORGE_SYNC_SECRET_KEY in .env.hub or .env.local"
    exit 1
fi

# Configure mc alias from env
mc alias set "${HUB_ALIAS}" "${ENDPOINT}" "${ACCESS_KEY}" "${SECRET_KEY}" --api S3v4 2>/dev/null || {
    err "Cannot connect to MinIO at ${ENDPOINT}"
    exit 1
}

log "Syncing templates to ${HUB_ALIAS}/${HUB_BUCKET}/${HUB_PREFIX}/"

mc mirror --overwrite --remove "${TEMPLATES_DIR}/" "${HUB_ALIAS}/${HUB_BUCKET}/${HUB_PREFIX}/" \
  --exclude ".*" 2>/dev/null || \
mc cp --recursive "${TEMPLATES_DIR}/" "${HUB_ALIAS}/${HUB_BUCKET}/${HUB_PREFIX}/"

REMOTE_COUNT=$(mc ls "${HUB_ALIAS}/${HUB_BUCKET}/${HUB_PREFIX}/" 2>/dev/null | grep -c "\.yaml" || echo "0")
log "✓ ${REMOTE_COUNT} templates on hub"
