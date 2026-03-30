#!/usr/bin/env bash
set -euo pipefail

HUB_ALIAS="demoforge-hub"
HUB_BUCKET="demoforge-templates"
HUB_PREFIX="templates"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATES_DIR="$(dirname "$SCRIPT_DIR")/demo-templates"

GREEN='\033[0;32m'
NC='\033[0m'
log() { echo -e "${GREEN}[hub-seed]${NC} $*"; }

if ! mc admin info "${HUB_ALIAS}" &>/dev/null 2>&1; then
    echo "Hub alias '${HUB_ALIAS}' not configured. Run hub-setup.sh first."
    exit 1
fi

log "Syncing templates to ${HUB_ALIAS}/${HUB_BUCKET}/${HUB_PREFIX}/"

mc mirror --overwrite --remove "${TEMPLATES_DIR}/" "${HUB_ALIAS}/${HUB_BUCKET}/${HUB_PREFIX}/" \
  --exclude ".*" 2>/dev/null || \
mc cp --recursive "${TEMPLATES_DIR}/" "${HUB_ALIAS}/${HUB_BUCKET}/${HUB_PREFIX}/"

REMOTE_COUNT=$(mc ls "${HUB_ALIAS}/${HUB_BUCKET}/${HUB_PREFIX}/" 2>/dev/null | grep -c "\.yaml" || echo "0")
log "✓ ${REMOTE_COUNT} templates on hub"
