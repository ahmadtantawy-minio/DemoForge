#!/usr/bin/env bash
set -euo pipefail

HUB_ALIAS="demoforge-hub"
HUB_BUCKET="demoforge-templates"
HUB_PREFIX="templates"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${CYAN}═══ DemoForge Hub Status ═══${NC}"
echo ""

BUILTIN=$(find "$PROJECT_ROOT/demo-templates" -name "*.yaml" -type f 2>/dev/null | wc -l | tr -d ' ')
USER=$(find "$PROJECT_ROOT/user-templates" -name "*.yaml" -type f 2>/dev/null | wc -l | tr -d ' ')
SYNCED=$(find "$PROJECT_ROOT/synced-templates" -name "*.yaml" -type f 2>/dev/null | wc -l | tr -d ' ')

echo -e "  Local templates:"
echo -e "    Built-in:  ${GREEN}${BUILTIN}${NC}"
echo -e "    User:      ${GREEN}${USER}${NC}"
echo -e "    Synced:    ${GREEN}${SYNCED}${NC}"
echo ""

if mc admin info "${HUB_ALIAS}" &>/dev/null 2>&1; then
    REMOTE=$(mc ls "${HUB_ALIAS}/${HUB_BUCKET}/${HUB_PREFIX}/" 2>/dev/null | grep -c "\.yaml" || echo "0")
    echo -e "  Remote hub (${HUB_ALIAS}):"
    echo -e "    Templates: ${GREEN}${REMOTE}${NC}"
    echo ""

    echo -e "  ${YELLOW}Remote-only (not in built-in):${NC}"
    comm -23 \
        <(mc ls "${HUB_ALIAS}/${HUB_BUCKET}/${HUB_PREFIX}/" 2>/dev/null | awk '{print $NF}' | grep "\.yaml$" | sort) \
        <(ls "$PROJECT_ROOT/demo-templates/"*.yaml 2>/dev/null | xargs -n1 basename | sort) \
      | sed 's/^/    /' || echo "    (none)"

    echo -e "  ${YELLOW}Local-only (not on hub):${NC}"
    comm -13 \
        <(mc ls "${HUB_ALIAS}/${HUB_BUCKET}/${HUB_PREFIX}/" 2>/dev/null | awk '{print $NF}' | grep "\.yaml$" | sort) \
        <(ls "$PROJECT_ROOT/demo-templates/"*.yaml 2>/dev/null | xargs -n1 basename | sort) \
      | sed 's/^/    /' || echo "    (none)"
else
    echo -e "  Remote hub: ${YELLOW}not configured${NC} (run scripts/hub-setup.sh)"
fi

REGISTRY_HOST="$(echo "${HUB_ENDPOINT:-http://34.18.90.197:9000}" | sed 's|http[s]*://||' | sed 's|:[0-9]*$||'):5000"

echo -e "  ${CYAN}Registry:${NC}"
if curl -sf "http://${REGISTRY_HOST}/v2/" &>/dev/null 2>&1; then
    CATALOG=$(curl -sf "http://${REGISTRY_HOST}/v2/_catalog" 2>/dev/null)
    REPO_COUNT=$(echo "$CATALOG" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('repositories',[])))" 2>/dev/null || echo "?")
    echo -e "    Status:      ${GREEN}healthy${NC}"
    echo -e "    URL:         ${CYAN}http://${REGISTRY_HOST}${NC}"
    echo -e "    Repositories:${GREEN} ${REPO_COUNT}${NC}"
    if [[ "$REPO_COUNT" != "0" && "$REPO_COUNT" != "?" ]]; then
        echo -e "    ${YELLOW}Images:${NC}"
        for repo in $(echo "$CATALOG" | python3 -c "import sys,json; [print(r) for r in json.load(sys.stdin).get('repositories',[])]" 2>/dev/null); do
            TAGS=$(curl -sf "http://${REGISTRY_HOST}/v2/${repo}/tags/list" 2>/dev/null \
              | python3 -c "import sys,json; print(', '.join(json.load(sys.stdin).get('tags',[])))" 2>/dev/null || echo "?")
            echo -e "      ${repo}: ${CYAN}${TAGS}${NC}"
        done
    fi
else
    echo -e "    Status:      ${YELLOW}unreachable${NC} (http://${REGISTRY_HOST})"
    echo -e "    ${YELLOW}Run scripts/hub-setup.sh to deploy the registry${NC}"
fi
echo ""

if [[ -f "$PROJECT_ROOT/.env.hub" ]]; then
    echo -e "  .env.hub:    ${GREEN}exists${NC}"
else
    echo -e "  .env.hub:    ${YELLOW}missing${NC} (run scripts/hub-setup.sh)"
fi
if [[ -f "$PROJECT_ROOT/.env.local" ]]; then
    ENABLED=$(grep "DEMOFORGE_SYNC_ENABLED" "$PROJECT_ROOT/.env.local" 2>/dev/null | grep -c "true" || echo "0")
    if [[ "$ENABLED" -gt 0 ]]; then
        echo -e "  .env.local:  ${GREEN}sync enabled${NC}"
    else
        echo -e "  .env.local:  ${YELLOW}sync disabled${NC}"
    fi
else
    echo -e "  .env.local:  ${YELLOW}missing${NC} (cp .env.hub .env.local)"
fi
echo ""
