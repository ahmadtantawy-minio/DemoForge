#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

[[ -f "$PROJECT_ROOT/.env.hub" ]] && source "$PROJECT_ROOT/.env.hub"
[[ -f "$PROJECT_ROOT/.env.local" ]] && source "$PROJECT_ROOT/.env.local"

# Must match scripts/hub-push.sh: GCR_HOST/REGISTRY_PREFIX/component -> gcr.io/minio-demoforge/demoforge/<name>
GCR_HOST="${DEMOFORGE_GCR_HOST:-gcr.io/minio-demoforge}"
GCR_HOST="${GCR_HOST%/}"

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

echo -e "${CYAN}Pulling core images from GCR (${GCR_HOST}):${NC}\n"

# Preflight: DNS must work for gcr.io (and often registry-1.docker.io for base layers inside the image).
_resolve_ok() {
  local h="$1"
  if command -v python3 &>/dev/null; then
    python3 -c "import socket; socket.gethostbyname('$h')" &>/dev/null
  elif command -v getent &>/dev/null; then
    getent hosts "$h" &>/dev/null
  else
    return 0
  fi
}
if ! _resolve_ok gcr.io; then
  err "DNS: cannot resolve gcr.io from this host. Fix host/VPN DNS, or set Docker Desktop \"dns\" (e.g. 8.8.8.8) under Settings > Docker Engine."
  err "If your registry mirror uses a different host, set DEMOFORGE_GCR_HOST (must match hub-push, default gcr.io/minio-demoforge)."
  exit 1
fi
if ! _resolve_ok registry-1.docker.io; then
  echo -e "${YELLOW}[hub-pull]${NC}  Warning: cannot resolve registry-1.docker.io (base image layers may still pull if cached)."
fi

for repo in "${CRITICAL_IMAGES[@]}"; do
    if pull_image "$repo"; then ((++PULLED)); else ((++FAILED)); fi
done

echo -e "\n${GREEN}Pulled: ${PULLED}${NC}  ${RED}Failed: ${FAILED}${NC}"
[[ $FAILED -gt 0 ]] && exit 1
