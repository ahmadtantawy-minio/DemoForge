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

# Core images always pulled on fa-update (small set, always needed)
CRITICAL_IMAGES=(
  "demoforge/demoforge-frontend"
  "demoforge/demoforge-backend"
  "demoforge/data-generator"
)

pull_image() {
    local repo="$1"
    local gcr_image="${GCR_HOST}/${repo}:latest"
    log "Pulling ${gcr_image}..."
    if docker pull "$gcr_image" 2>&1 | tail -2; then
        docker tag "$gcr_image" "${repo}:latest" 2>/dev/null && log "  ↳ tagged ${repo}:latest"
        log "  ✓ ${repo}"; return 0
    else
        err "  ✗ ${repo}"; return 1
    fi
}

PULLED=0; FAILED=0

if [[ "${1:-}" == "--all" ]]; then
    # Pull everything from catalog (e.g. after fresh install)
    log "Getting full image catalog via connector..."
    CATALOG=$(curl -sf --connect-timeout 5 --max-time 10 "http://${REGISTRY_HOST}/v2/_catalog" 2>/dev/null || echo '{"repositories":[]}')
    REPOS=$(echo "$CATALOG" | python3 -c "
import sys, json
repos = json.load(sys.stdin).get('repositories', [])
print('\n'.join(r for r in repos if not r.startswith('test/')))
" 2>/dev/null)

    [[ -z "$REPOS" ]] && { echo -e "${YELLOW}No images in catalog. Dev needs to run: make hub-push${NC}"; exit 0; }

    echo -e "${CYAN}Pulling all images from GCR (${GCR_HOST}):${NC}\n"
    while IFS= read -r repo; do
        [[ -z "$repo" ]] && continue
        if pull_image "$repo"; then ((++PULLED)); else ((++FAILED)); fi
    done <<< "$REPOS"
else
    # Default: pull only critical images (components pull on-demand at deploy time)
    echo -e "${CYAN}Pulling core images from GCR:${NC}\n"
    for repo in "${CRITICAL_IMAGES[@]}"; do
        if pull_image "$repo"; then ((++PULLED)); else ((++FAILED)); fi
    done
fi

echo -e "\n${GREEN}Pulled: ${PULLED}${NC}  ${RED}Failed: ${FAILED}${NC}"
[[ $FAILED -gt 0 ]] && exit 1
