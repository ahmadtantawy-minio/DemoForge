#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

[[ -f "$PROJECT_ROOT/.env.hub" ]] && source "$PROJECT_ROOT/.env.hub"
[[ -f "$PROJECT_ROOT/.env.local" ]] && source "$PROJECT_ROOT/.env.local"

REGISTRY_HOST="${DEMOFORGE_REGISTRY_HOST:-localhost:5050}"
GCR_HOST="gcr.io/minio-demoforge"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${GREEN}[hub-pull]${NC} $*"; }
err()  { echo -e "${RED}[hub-pull]${NC} $*" >&2; }

# Catalog comes from the connector (small response, no size limit)
log "Getting image catalog via connector..."
CATALOG=$(curl -sf --connect-timeout 5 --max-time 10 "http://${REGISTRY_HOST}/v2/_catalog" 2>/dev/null || echo '{"repositories":[]}')
REPOS=$(echo "$CATALOG" | python3 -c "
import sys, json
repos = json.load(sys.stdin).get('repositories', [])
# Exclude test images
print('\n'.join(r for r in repos if not r.startswith('test/')))
" 2>/dev/null)

[[ -z "$REPOS" ]] && { echo -e "${YELLOW}No images in catalog. Dev needs to run: make hub-push${NC}"; exit 0; }

echo -e "${CYAN}Pulling custom images from GCR (${GCR_HOST}):${NC}\n"
PULLED=0; FAILED=0

while IFS= read -r repo; do
    [[ -z "$repo" ]] && continue
    GCR_IMAGE="${GCR_HOST}/${repo}:latest"
    log "Pulling ${GCR_IMAGE}..."
    if docker pull "$GCR_IMAGE" 2>&1 | tail -2; then
        # Retag to canonical name (e.g. demoforge/data-generator) so backend
        # image-existence check finds it without rebuilding from source
        docker tag "$GCR_IMAGE" "${repo}:latest" 2>/dev/null && log "  ↳ tagged ${repo}:latest"
        log "  ✓ ${repo}"; ((PULLED++))
    else
        err "  ✗ ${repo}"; ((FAILED++))
    fi
done <<< "$REPOS"

echo -e "\n${GREEN}Pulled: ${PULLED}${NC}  ${RED}Failed: ${FAILED}${NC}"
[[ $FAILED -gt 0 ]] && exit 1
