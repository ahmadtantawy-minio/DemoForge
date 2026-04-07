#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
COMPONENTS_DIR="$PROJECT_ROOT/components"

[[ -f "$PROJECT_ROOT/.env.hub" ]] && source "$PROJECT_ROOT/.env.hub"
[[ -f "$PROJECT_ROOT/.env.local" ]] && source "$PROJECT_ROOT/.env.local"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'

REGISTRY_HOST="${DEMOFORGE_REGISTRY_HOST:-localhost:5000}"
REGISTRY_PREFIX="demoforge"

TUNNEL_PID=""

# --direct flag: bypass Cloud Run gateway and push directly to VM registry
# Auto-uses IAP tunnel when VM has no public IP (avoids Cloud Run 32MB body limit)
if [[ "${1:-}" == "--direct" ]]; then
    shift
    DIRECT_IP=$(grep "^DEMOFORGE_DIRECT_IP=" "$PROJECT_ROOT/.env.hub" 2>/dev/null | cut -d= -f2 || echo "")
    VM_NAME=$(grep "^DEMOFORGE_VM_NAME=" "$PROJECT_ROOT/.env.hub" 2>/dev/null | cut -d= -f2 || echo "")
    ZONE=$(grep "^DEMOFORGE_ZONE=" "$PROJECT_ROOT/.env.hub" 2>/dev/null | cut -d= -f2 || echo "")
    PROJECT_ID=$(grep "^DEMOFORGE_PROJECT_ID=" "$PROJECT_ROOT/.env.hub" 2>/dev/null | cut -d= -f2 || echo "")

    # Check if IP is reachable directly (public IP case)
    if [[ -n "$DIRECT_IP" ]] && curl -sf --connect-timeout 3 "http://${DIRECT_IP}:5000/v2/" &>/dev/null; then
        REGISTRY_HOST="${DIRECT_IP}:5000"
        echo -e "${YELLOW}[hub-push] Using direct access: ${REGISTRY_HOST}${NC}"
    elif [[ -n "$VM_NAME" && -n "$ZONE" && -n "$PROJECT_ID" ]]; then
        # VM has no public IP — use IAP tunnel
        IAP_PORT=15000
        echo -e "${YELLOW}[hub-push] VM has no public IP — setting up IAP tunnel on localhost:${IAP_PORT}...${NC}"
        gcloud compute start-iap-tunnel "${VM_NAME}" 5000 \
            --local-host-port="localhost:${IAP_PORT}" \
            --zone="${ZONE}" --project="${PROJECT_ID}" &>/dev/null &
        TUNNEL_PID=$!
        trap 'kill "$TUNNEL_PID" 2>/dev/null; exit' EXIT INT TERM
        # Wait for tunnel to be ready
        for i in $(seq 1 15); do
            curl -sf --connect-timeout 2 "http://localhost:${IAP_PORT}/v2/" &>/dev/null && break
            sleep 1
        done
        REGISTRY_HOST="localhost:${IAP_PORT}"
        echo -e "${YELLOW}[hub-push] IAP tunnel ready — pushing via localhost:${IAP_PORT}${NC}"
    else
        echo -e "${RED}[hub-push] --direct: DIRECT_IP unreachable and VM_NAME/ZONE/PROJECT_ID not set in .env.hub${NC}"
        echo -e "${YELLOW}[hub-push] Run 'make hub-update-gateway' to regenerate .env.hub, then retry.${NC}"
        exit 1
    fi
fi
log()  { echo -e "${GREEN}[hub-push]${NC} $*"; }
err()  { echo -e "${RED}[hub-push]${NC} $*" >&2; }

log "Checking registry at ${REGISTRY_HOST}..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 --max-time 10 "http://${REGISTRY_HOST}/v2/" 2>/dev/null || echo "000")
# 200=ok, 401/403=auth required but reachable — all acceptable
if [[ "$HTTP_CODE" == "000" ]]; then
    err "Registry unreachable at http://${REGISTRY_HOST}"; exit 1
fi
log "✓ Registry reachable (HTTP ${HTTP_CODE})"

COMPONENTS=(); DOCKERFILES=()
while IFS= read -r df; do
    COMPONENTS+=("$(basename "$(dirname "$df")")")
    DOCKERFILES+=("$df")
done < <(find "$COMPONENTS_DIR" -name "Dockerfile" -type f | sort)

[[ -f "$PROJECT_ROOT/backend/Dockerfile" ]] && { COMPONENTS+=("demoforge-backend"); DOCKERFILES+=("$PROJECT_ROOT/backend/Dockerfile"); }
[[ -f "$PROJECT_ROOT/frontend/Dockerfile" ]] && { COMPONENTS+=("demoforge-frontend"); DOCKERFILES+=("$PROJECT_ROOT/frontend/Dockerfile"); }

[[ ${#COMPONENTS[@]} -eq 0 ]] && { echo "No Dockerfiles found."; exit 0; }

echo -e "\n${CYAN}Found ${#COMPONENTS[@]} images to build:${NC}"
for i in "${!COMPONENTS[@]}"; do echo "  ${COMPONENTS[$i]} ← ${DOCKERFILES[$i]#$PROJECT_ROOT/}"; done
echo ""

FILTER="${1:-}"
BUILT=0; FAILED=0; SKIPPED=0

# Count how many will actually be processed
TOTAL=0
for i in "${!COMPONENTS[@]}"; do
    [[ -n "$FILTER" && "${COMPONENTS[$i]}" != "$FILTER" ]] && continue
    ((TOTAL++))
done
CURRENT=0

for i in "${!COMPONENTS[@]}"; do
    comp="${COMPONENTS[$i]}"; dockerfile="${DOCKERFILES[$i]}"; context=$(dirname "$dockerfile")
    [[ -n "$FILTER" && "$comp" != "$FILTER" ]] && continue
    ((CURRENT++))

    IMAGE_TAG="${REGISTRY_HOST}/${REGISTRY_PREFIX}/${comp}:latest"
    echo ""
    echo -e "${CYAN}━━━ [${CURRENT}/${TOTAL}] ${comp} ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    log "Building ${comp}..."
    log "  Dockerfile: ${dockerfile#$PROJECT_ROOT/}"
    log "  Context:    ${context#$PROJECT_ROOT/}"
    log "  Tag:        ${IMAGE_TAG}"
    echo ""

    BUILD_START=$SECONDS
    if docker build -t "$IMAGE_TAG" -f "$dockerfile" "$context" 2>&1; then
        BUILD_ELAPSED=$(( SECONDS - BUILD_START ))
        log "  ✓ Built in ${BUILD_ELAPSED}s: $IMAGE_TAG"
    else
        BUILD_ELAPSED=$(( SECONDS - BUILD_START ))
        err "  ✗ Build failed after ${BUILD_ELAPSED}s: $comp"; ((FAILED++)); continue
    fi

    log "  Pushing to ${REGISTRY_HOST}..."
    PUSH_START=$SECONDS
    if docker push "$IMAGE_TAG" 2>&1; then
        PUSH_ELAPSED=$(( SECONDS - PUSH_START ))
        # Get image size
        IMG_SIZE=$(docker image inspect "$IMAGE_TAG" --format '{{.Size}}' 2>/dev/null || echo "0")
        IMG_SIZE_MB=$(( IMG_SIZE / 1000000 ))
        log "  ✓ Pushed in ${PUSH_ELAPSED}s (${IMG_SIZE_MB} MB): $IMAGE_TAG"; ((BUILT++))
    else
        PUSH_ELAPSED=$(( SECONDS - PUSH_START ))
        err "  ✗ Push failed after ${PUSH_ELAPSED}s: $comp"; ((FAILED++))
    fi

    # Git hash tag
    if command -v git &>/dev/null && git rev-parse --short HEAD &>/dev/null 2>&1; then
        GIT_TAG="${REGISTRY_HOST}/${REGISTRY_PREFIX}/${comp}:$(git rev-parse --short HEAD)"
        docker tag "$IMAGE_TAG" "$GIT_TAG"; docker push "$GIT_TAG" 2>/dev/null || true
        log "  ✓ Also tagged: $(git rev-parse --short HEAD)"
    fi
done

echo ""
echo -e "${GREEN}══════════════════════════════════════════════════════════${NC}"
echo -e "  Built & pushed: ${GREEN}${BUILT}/${TOTAL}${NC}"
[[ $FAILED -gt 0 ]] && echo -e "  Failed:         ${RED}${FAILED}${NC}"
echo -e "${GREEN}══════════════════════════════════════════════════════════${NC}"

log "Registry contents:"
CATALOG=$(curl -sf "http://${REGISTRY_HOST}/v2/_catalog" 2>/dev/null || echo '{"repositories":[]}')
for repo in $(echo "$CATALOG" | python3 -c "import sys,json; [print(r) for r in json.load(sys.stdin).get('repositories',[])]" 2>/dev/null); do
    TAGS=$(curl -sf "http://${REGISTRY_HOST}/v2/${repo}/tags/list" 2>/dev/null \
      | python3 -c "import sys,json; print(', '.join(json.load(sys.stdin).get('tags',[])))" 2>/dev/null || echo "?")
    echo -e "  ${repo}: ${CYAN}${TAGS}${NC}"
done
exit $FAILED
