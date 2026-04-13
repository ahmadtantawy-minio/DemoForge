#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
PROJECT_ID="minio-demoforge"
REGION="me-central1"
TEMPLATES_BUCKET="gs://demoforge-hub-templates"
TEMPLATES_PREFIX="templates/"

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${CYAN}═══ DemoForge Hub Status ═══${NC}"
echo ""

# ── Local templates ──
BUILTIN=$(find "$PROJECT_ROOT/demo-templates" -name "*.yaml" -type f 2>/dev/null | wc -l | tr -d ' ')
USER=$(find "$PROJECT_ROOT/user-templates" -name "*.yaml" -type f 2>/dev/null | wc -l | tr -d ' ')
SYNCED=$(find "$PROJECT_ROOT/synced-templates" -name "*.yaml" -type f 2>/dev/null | wc -l | tr -d ' ')

echo -e "  Local templates:"
echo -e "    Built-in:  ${GREEN}${BUILTIN}${NC}"
echo -e "    User:      ${GREEN}${USER}${NC}"
echo -e "    Synced:    ${GREEN}${SYNCED}${NC}"
echo ""

# ── GCS remote templates ──
echo -e "  Remote templates (GCS):"
REMOTE=$(gcloud storage ls "${TEMPLATES_BUCKET}/${TEMPLATES_PREFIX}" 2>/dev/null | grep -c '\.yaml$' || echo "0")
echo -e "    Templates: ${GREEN}${REMOTE}${NC} on ${TEMPLATES_BUCKET}/${TEMPLATES_PREFIX}"
echo ""

# ── Cloud Run: hub-api ──
echo -e "  Cloud Run:"
HUB_API_STATUS=$(gcloud run services describe demoforge-hub-api \
  --project="${PROJECT_ID}" --region="${REGION}" \
  --format='value(status.conditions[0].status)' 2>/dev/null || echo "not deployed")
HUB_API_URL=$(gcloud run services describe demoforge-hub-api \
  --project="${PROJECT_ID}" --region="${REGION}" \
  --format='value(status.url)' 2>/dev/null || echo "")
if [[ "$HUB_API_STATUS" == "True" ]]; then
  echo -e "    hub-api:   ${GREEN}running${NC}  ${CYAN}${HUB_API_URL}${NC}"
else
  echo -e "    hub-api:   ${YELLOW}${HUB_API_STATUS}${NC}"
fi

GATEWAY_STATUS=$(gcloud run services describe demoforge-gateway \
  --project="${PROJECT_ID}" --region="${REGION}" \
  --format='value(status.conditions[0].status)' 2>/dev/null || echo "not deployed")
GATEWAY_URL=$(gcloud run services describe demoforge-gateway \
  --project="${PROJECT_ID}" --region="${REGION}" \
  --format='value(status.url)' 2>/dev/null || echo "")
if [[ "$GATEWAY_STATUS" == "True" ]]; then
  echo -e "    gateway:   ${GREEN}running${NC}  ${CYAN}${GATEWAY_URL}${NC}"
else
  echo -e "    gateway:   ${YELLOW}${GATEWAY_STATUS}${NC}"
fi
echo ""

# ── Config files ──
if [[ -f "$PROJECT_ROOT/.env.hub" ]]; then
  echo -e "  .env.hub:    ${GREEN}exists${NC}"
else
  echo -e "  .env.hub:    ${YELLOW}missing${NC} (run: make hub-deploy)"
fi
if [[ -f "$PROJECT_ROOT/.env.local" ]]; then
  echo -e "  .env.local:  ${GREEN}exists${NC}"
else
  echo -e "  .env.local:  ${YELLOW}missing${NC} (cp .env.hub .env.local)"
fi
echo ""
