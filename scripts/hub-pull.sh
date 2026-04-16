#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

[[ -f "$PROJECT_ROOT/.env.hub" ]] && source "$PROJECT_ROOT/.env.hub"
[[ -f "$PROJECT_ROOT/.env.local" ]] && source "$PROJECT_ROOT/.env.local"

GCR_HOST="gcr.io/minio-demoforge"

GREEN='\033[0;32m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${GREEN}[hub-pull]${NC} $*"; }
err()  { echo -e "${RED}[hub-pull]${NC} $*" >&2; }

# Core images always pulled with fa-update / make hub-pull (FA day-to-day + deploy pre-cache)
CRITICAL_IMAGES=(
  "demoforge/demoforge-frontend"
  "demoforge/demoforge-backend"
  "demoforge/data-generator"
  "demoforge/event-processor"
  "demoforge/external-system"
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

echo -e "${CYAN}Pulling core images from GCR:${NC}\n"
for repo in "${CRITICAL_IMAGES[@]}"; do
    if pull_image "$repo"; then ((++PULLED)); else ((++FAILED)); fi
done

echo -e "\n${GREEN}Pulled: ${PULLED}${NC}  ${RED}Failed: ${FAILED}${NC}"
[[ $FAILED -gt 0 ]] && exit 1
