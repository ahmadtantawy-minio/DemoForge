#!/usr/bin/env bash
# Push DemoForge images to GCR. Frontend is always built with --target prod (nginx + Vite dist).
# Local dev (make dev-start / dev-start-gcp) uses Dockerfile --target dev via demoforge-dev + docker compose — not this script.
#
# Multi-arch: by default builds/pushes a manifest list for linux/amd64 + linux/arm64 so Windows/Linux
# (amd64) and Apple Silicon (arm64) FAs each get a matching image on plain "docker pull" (no --platform).
# Override: DEMOFORGE_HUB_PLATFORMS=linux/amd64  DEMOFORGE_HUB_BUILDX_BUILDER=mybuilder
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

CORE_IMAGES=("demoforge-frontend" "demoforge-backend" "data-generator" "event-processor" "external-system" "spark-etl-job" "iceberg-browser" "inference-sim" "inference-client")

echo -e "\n${CYAN}Found ${#COMPONENTS[@]} images to build:${NC}"
for i in "${!COMPONENTS[@]}"; do echo "  ${COMPONENTS[$i]} ← ${DOCKERFILES[$i]#$PROJECT_ROOT/}"; done
echo ""

if [[ "$PUSH_ALL" == "false" ]]; then
    echo -e "${YELLOW}Mode: core only (frontend, backend, data-generator, event-processor, external-system, spark-etl-job, iceberg-browser, inference-sim, inference-client). Use --all to push all images.${NC}"
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
# Same semantics as backend GET /api/version (git describe) — baked into the SPA at Vite build time.
RELEASE_VERSION=$(git -C "$PROJECT_ROOT" describe --tags --always --dirty 2>/dev/null || echo "unknown")

HUB_PLATFORMS="${DEMOFORGE_HUB_PLATFORMS:-linux/amd64,linux/arm64}"
HUB_BUILDER="${DEMOFORGE_HUB_BUILDX_BUILDER:-demoforge-hub}"

prepare_buildx() {
  command -v docker >/dev/null || { err "docker not found"; return 1; }
  if ! docker buildx version >/dev/null 2>&1; then
    err "docker buildx is required for hub-push (multi-arch). Install a current Docker CLI / Docker Desktop."
    return 1
  fi
  # Single platform: use default builder (no dedicated builder needed).
  if [[ "$HUB_PLATFORMS" != *","* ]]; then
    docker buildx use default >/dev/null 2>&1 || true
    log "Single-platform push: ${HUB_PLATFORMS}"
    return 0
  fi
  if docker buildx inspect "$HUB_BUILDER" >/dev/null 2>&1; then
    docker buildx use "$HUB_BUILDER"
    return 0
  fi
  log "Creating buildx builder \"${HUB_BUILDER}\" (docker-container driver) for ${HUB_PLATFORMS}..."
  docker buildx create --name "$HUB_BUILDER" --driver docker-container --use
  docker buildx inspect "$HUB_BUILDER" --bootstrap >/dev/null
}

prepare_buildx || exit 1
log "Platforms: ${HUB_PLATFORMS} (hub-pull / FA machines: plain docker pull selects the host arch)"

for i in "${!COMPONENTS[@]}"; do
    comp="${COMPONENTS[$i]}"; dockerfile="${DOCKERFILES[$i]}"; context=$(dirname "$dockerfile")
    # external-system bundles Data Generator scenario YAML + writers (same S3 layout as data-generator)
    if [[ "$comp" == "external-system" ]]; then
        context="$COMPONENTS_DIR"
        dockerfile="$COMPONENTS_DIR/external-system/Dockerfile"
    fi

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
    if [[ "$comp" == "demoforge-frontend" ]]; then
        log "  Mode:       production (vite build → nginx static, --target prod)"
        log "  UI version: VITE_DEMOFORGE_RELEASE_VERSION=${RELEASE_VERSION} (same as backend /api/version when built from this tree)"
    fi
    echo ""

    # Frontend: explicit production image (nginx + Vite dist). Dockerfile ends with AS prod;
    # --target documents intent if stages are reordered later.
    BUILD_FLAGS=(-f "$dockerfile")
    if [[ "$comp" == "demoforge-frontend" ]]; then
        BUILD_FLAGS+=(--target prod)
        BUILD_FLAGS+=(--build-arg "VITE_DEMOFORGE_RELEASE_VERSION=${RELEASE_VERSION}")
    fi

    TAG_ARGS=(-t "$GCR_IMAGE")
    if [[ -n "$GIT_HASH" ]]; then
        TAG_ARGS+=(-t "${GCR_HOST}/${REGISTRY_PREFIX}/${comp}:${GIT_HASH}")
    fi

    BUILD_START=$SECONDS
    if docker buildx build \
        --platform "$HUB_PLATFORMS" \
        "${BUILD_FLAGS[@]}" \
        "${TAG_ARGS[@]}" \
        --push \
        "$context" 2>&1; then
        BUILD_ELAPSED=$(( SECONDS - BUILD_START ))
        log "  ✓ Built + pushed in ${BUILD_ELAPSED}s (manifest: ${HUB_PLATFORMS}): $GCR_IMAGE"
        [[ -n "$GIT_HASH" ]] && log "  ✓ Same digest also tagged: ${GIT_HASH}"
        ((BUILT++))
    else
        BUILD_ELAPSED=$(( SECONDS - BUILD_START ))
        err "  ✗ buildx build/push failed after ${BUILD_ELAPSED}s: $comp"
        echo -e "${YELLOW}[hub-push]  Run: gcloud auth configure-docker gcr.io${NC}"
        echo -e "${YELLOW}[hub-push]  Multi-arch needs QEMU/binfmt (Docker Desktop includes it). Try DEMOFORGE_HUB_PLATFORMS=linux/amd64 for a single-arch push.${NC}"
        ((FAILED++)); continue
    fi
done

echo ""
echo -e "${GREEN}══════════════════════════════════════════════════════════${NC}"
echo -e "  Built & pushed: ${GREEN}${BUILT}/${TOTAL}${NC}"
[[ $FAILED -gt 0 ]] && echo -e "  Failed:         ${RED}${FAILED}${NC}"
echo -e "${GREEN}══════════════════════════════════════════════════════════${NC}"

exit $FAILED
