#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
COMPONENTS_DIR="$PROJECT_ROOT/components"

[[ -f "$PROJECT_ROOT/.env.hub" ]] && source "$PROJECT_ROOT/.env.hub"
[[ -f "$PROJECT_ROOT/.env.local" ]] && source "$PROJECT_ROOT/.env.local"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${GREEN}[hub-push]${NC} $*"; }
err()  { echo -e "${RED}[hub-push]${NC} $*" >&2; }

GCR_HOST="gcr.io/minio-demoforge"
REGISTRY_PREFIX="demoforge"

COMPONENTS=(); DOCKERFILES=()
while IFS= read -r df; do
    COMPONENTS+=("$(basename "$(dirname "$df")")")
    DOCKERFILES+=("$df")
done < <(find "$COMPONENTS_DIR" -name "Dockerfile" -type f | sort)

[[ -f "$PROJECT_ROOT/backend/Dockerfile" ]] && { COMPONENTS+=("demoforge-backend"); DOCKERFILES+=("$PROJECT_ROOT/backend/Dockerfile"); }
[[ -f "$PROJECT_ROOT/frontend/Dockerfile" ]] && { COMPONENTS+=("demoforge-frontend"); DOCKERFILES+=("$PROJECT_ROOT/frontend/Dockerfile"); }

[[ ${#COMPONENTS[@]} -eq 0 ]] && { echo "No Dockerfiles found."; exit 0; }

# Parse flags
PUSH_ALL=false
for arg in "$@"; do
  [[ "$arg" == "--all" ]] && PUSH_ALL=true
done

CORE_IMAGES=("demoforge-frontend" "demoforge-backend" "data-generator")

echo -e "\n${CYAN}Found ${#COMPONENTS[@]} images to build:${NC}"
for i in "${!COMPONENTS[@]}"; do echo "  ${COMPONENTS[$i]} ← ${DOCKERFILES[$i]#$PROJECT_ROOT/}"; done
echo ""

if [[ "$PUSH_ALL" == "false" ]]; then
    echo -e "${YELLOW}Mode: core only (frontend, backend, data-generator). Use --all to push all images.${NC}"
fi

FILTER="${1:-}"
# If the first positional arg is --all, don't treat it as a component filter
[[ "$FILTER" == "--all" ]] && FILTER=""

BUILT=0; FAILED=0

TOTAL=0
for i in "${!COMPONENTS[@]}"; do
    comp="${COMPONENTS[$i]}"
    if [[ "$PUSH_ALL" == "false" ]]; then
        is_core=false
        for core in "${CORE_IMAGES[@]}"; do
            [[ "$comp" == "$core" ]] && is_core=true && break
        done
        [[ "$is_core" == "false" ]] && continue
    fi
    [[ -n "$FILTER" && "$comp" != "$FILTER" ]] && continue
    ((TOTAL++))
done
CURRENT=0

GIT_HASH=$(git rev-parse --short HEAD 2>/dev/null || echo "")

for i in "${!COMPONENTS[@]}"; do
    comp="${COMPONENTS[$i]}"; dockerfile="${DOCKERFILES[$i]}"; context=$(dirname "$dockerfile")

    # Skip non-core images unless --all is passed
    if [[ "$PUSH_ALL" == "false" ]]; then
        is_core=false
        for core in "${CORE_IMAGES[@]}"; do
            [[ "$comp" == "$core" ]] && is_core=true && break
        done
        [[ "$is_core" == "false" ]] && continue
    fi

    # Optional single-image filter (existing behaviour)
    [[ -n "$FILTER" && "$comp" != "$FILTER" ]] && continue

    ((CURRENT++))

    GCR_IMAGE="${GCR_HOST}/${REGISTRY_PREFIX}/${comp}:latest"
    echo ""
    echo -e "${CYAN}━━━ [${CURRENT}/${TOTAL}] ${comp} ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    log "Building ${comp}..."
    log "  Dockerfile: ${dockerfile#$PROJECT_ROOT/}"
    log "  Context:    ${context#$PROJECT_ROOT/}"
    log "  Tag:        ${GCR_IMAGE}"
    echo ""

    BUILD_START=$SECONDS
    if docker build -t "$GCR_IMAGE" -f "$dockerfile" "$context" 2>&1; then
        BUILD_ELAPSED=$(( SECONDS - BUILD_START ))
        log "  ✓ Built in ${BUILD_ELAPSED}s: $GCR_IMAGE"
    else
        BUILD_ELAPSED=$(( SECONDS - BUILD_START ))
        err "  ✗ Build failed after ${BUILD_ELAPSED}s: $comp"; ((FAILED++)); continue
    fi

    PUSH_START=$SECONDS
    if docker push "$GCR_IMAGE" 2>&1; then
        PUSH_ELAPSED=$(( SECONDS - PUSH_START ))
        IMG_SIZE=$(docker image inspect "$GCR_IMAGE" --format '{{.Size}}' 2>/dev/null || echo "0")
        IMG_SIZE_MB=$(( IMG_SIZE / 1000000 ))
        log "  ✓ Pushed in ${PUSH_ELAPSED}s (${IMG_SIZE_MB} MB): $GCR_IMAGE"; ((BUILT++))
    else
        PUSH_ELAPSED=$(( SECONDS - PUSH_START ))
        err "  ✗ Push failed after ${PUSH_ELAPSED}s: $comp"
        echo -e "${YELLOW}[hub-push]  Run: gcloud auth configure-docker gcr.io${NC}"
        ((FAILED++)); continue
    fi

    if [[ -n "$GIT_HASH" ]]; then
        GCR_GIT="${GCR_HOST}/${REGISTRY_PREFIX}/${comp}:${GIT_HASH}"
        docker tag "$GCR_IMAGE" "$GCR_GIT"
        docker push "$GCR_GIT" 2>/dev/null || true
        log "  ✓ Also tagged: ${GIT_HASH}"
    fi
done

echo ""
echo -e "${GREEN}══════════════════════════════════════════════════════════${NC}"
echo -e "  Built & pushed: ${GREEN}${BUILT}/${TOTAL}${NC}"
[[ $FAILED -gt 0 ]] && echo -e "  Failed:         ${RED}${FAILED}${NC}"
echo -e "${GREEN}══════════════════════════════════════════════════════════${NC}"

exit $FAILED
