#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

[[ -f "$PROJECT_ROOT/.env.hub" ]] && source "$PROJECT_ROOT/.env.hub"
[[ -f "$PROJECT_ROOT/.env.local" ]] && source "$PROJECT_ROOT/.env.local"

# Must match scripts/hub-push.sh: GCR_HOST/REGISTRY_PREFIX/component -> gcr.io/minio-demoforge/demoforge/<name>
GCR_HOST="${DEMOFORGE_GCR_HOST:-gcr.io/minio-demoforge}"
GCR_HOST="${GCR_HOST%/}"

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${GREEN}[hub-pull]${NC} $*"; }
err()  { echo -e "${RED}[hub-pull]${NC} $*" >&2; }

# Core images always pulled with fa-update / make hub-pull (FA day-to-day + deploy pre-cache)
CRITICAL_IMAGES=(
  "demoforge/demoforge-frontend"
  "demoforge/demoforge-backend"
  "demoforge/data-generator"
  "demoforge/event-processor"
  "demoforge/external-system"
  "demoforge/inference-sim"
  "demoforge/inference-client"
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

# Host DNS can work while the Docker engine resolver does not (common on Docker Desktop for Windows).
docker_engine_dns_probe() {
  set +e
  docker pull alpine:3.19 >/dev/null 2>&1
  if [[ $? -ne 0 ]]; then
    echo -e "${YELLOW}[hub-pull]${NC}  Skipping in-container DNS probe (could not pull alpine:3.19; docker.io may be blocked)."
    set -e
    return 0
  fi
  if docker run --rm alpine:3.19 nslookup gcr.io >/dev/null 2>&1; then
    log "  Docker engine DNS probe: gcr.io resolves inside a container"
    set -e
    return 0
  fi
  if docker run --rm --dns 8.8.8.8 --dns 8.8.4.4 alpine:3.19 nslookup gcr.io >/dev/null 2>&1; then
    echo -e "${YELLOW}[hub-pull]${NC}  Docker engine default DNS failed gcr.io, but a container with --dns 8.8.8.8 worked."
    echo -e "${YELLOW}[hub-pull]${NC}  Fix: Docker Desktop > Settings > Docker Engine > add: \"dns\": [\"8.8.8.8\", \"8.8.4.4\"]  then Apply & Restart."
  else
    echo -e "${YELLOW}[hub-pull]${NC}  Docker engine still cannot resolve gcr.io in a test container. Image refs are gcr.io/minio-demoforge/demoforge/... (see hub-push.sh); this is resolver/VPN/firewall, not a wrong image name."
  fi
  set -e
}
docker_engine_dns_probe

if command -v curl &>/dev/null; then
  if curl -sfI --connect-timeout 5 "https://gcr.io/v2/" >/dev/null; then
    log "  HTTPS to gcr.io/v2/ from host: ok"
  else
    echo -e "${YELLOW}[hub-pull]${NC}  HTTPS to gcr.io from host failed (proxy?). Docker may still pull if engine DNS works."
  fi
fi

echo -e "${CYAN}[hub-pull]${NC}  First pull target (sanity): ${GCR_HOST}/demoforge/demoforge-frontend:latest"
log "Each docker pull uses the registry manifest for this engine's CPU (amd64 vs arm64); no --platform flag needed."
echo ""

for repo in "${CRITICAL_IMAGES[@]}"; do
    if pull_image "$repo"; then ((++PULLED)); else ((++FAILED)); fi
done

echo -e "\n${GREEN}Pulled: ${PULLED}${NC}  ${RED}Failed: ${FAILED}${NC}"
[[ $FAILED -gt 0 ]] && exit 1
