#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

[[ -f "$PROJECT_ROOT/.env.hub" ]] && source "$PROJECT_ROOT/.env.hub"
[[ -f "$PROJECT_ROOT/.env.local" ]] && source "$PROJECT_ROOT/.env.local"

REGISTRY_HOST="${DEMOFORGE_REGISTRY_HOST:-34.18.90.197:5000}"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${GREEN}[hub-pull]${NC} $*"; }
err()  { echo -e "${RED}[hub-pull]${NC} $*" >&2; }

log "Checking registry at ${REGISTRY_HOST}..."
curl -sf --connect-timeout 5 --max-time 10 "http://${REGISTRY_HOST}/v2/" &>/dev/null || { err "Registry unreachable at http://${REGISTRY_HOST}"; exit 1; }
log "✓ Registry reachable"

CATALOG=$(curl -sf "http://${REGISTRY_HOST}/v2/_catalog" 2>/dev/null || echo '{"repositories":[]}')
REPOS=$(echo "$CATALOG" | python3 -c "import sys,json; [print(r) for r in json.load(sys.stdin).get('repositories',[])]" 2>/dev/null)

[[ -z "$REPOS" ]] && { echo -e "${YELLOW}No images in registry. Dev needs to run: make hub-push${NC}"; exit 0; }

echo -e "${CYAN}Pulling custom images from ${REGISTRY_HOST}:${NC}\n"
PULLED=0; FAILED=0

while IFS= read -r repo; do
    [[ -z "$repo" ]] && continue
    IMAGE="${REGISTRY_HOST}/${repo}:latest"
    log "Pulling ${IMAGE}..."
    if docker pull "$IMAGE" 2>&1 | tail -2; then
        log "  ✓ ${repo}"; ((PULLED++))
    else
        err "  ✗ ${repo}"; ((FAILED++))
    fi
done <<< "$REPOS"

echo -e "\n${GREEN}Pulled: ${PULLED}${NC}  ${RED}Failed: ${FAILED}${NC}"
[[ $FAILED -gt 0 ]] && exit 1
