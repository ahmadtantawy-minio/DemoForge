#!/usr/bin/env bash
set -euo pipefail

# DemoForge Management Script
# Usage: ./demoforge.sh [command]
#
# Commands:
#   start       Build and start all services (kills existing first)
#   stop        Stop all services and clean up
#   restart     Stop then start
#   status      Show status of all services
#   logs        Tail logs from all services
#   logs:be     Tail backend logs only
#   logs:fe     Tail frontend logs only
#   build       Build all images without starting
#   clean       Stop everything, remove volumes, prune demo networks
#   nuke        Full clean + remove built images
#   dev:be      Run backend locally (no Docker) for development
#   dev:fe      Run frontend locally (no Docker) for development
#   help        Show this help

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PROJECT_NAME="demoforge"
BACKEND_PORT=9210  # overridden to 9211 for dev mode inside load_env()

# FA local instance config (same PC, isolated data under ./fa-data/)
# Uses 9212/3002 — distinct from FA (9210/3000) and dev (9211/3001)
FA_PROJECT_NAME="demoforge-fa"
FA_BACKEND_PORT=9212
FA_FRONTEND_PORT=3002
FA_DC_FLAGS=(-p "$FA_PROJECT_NAME" -f "docker-compose.fa-local.yml")

# Compose file list — populated by refresh_dc_flags (always run load_env first so mode/env match).
DC_FLAGS=(-f "$SCRIPT_DIR/docker-compose.yml")
FRONTEND_PORT=3000

# Recompute docker compose -f flags after load_env (mode, DEMOFORGE_HUB_LOCAL, paths).
refresh_dc_flags() {
    DC_FLAGS=(-f "$SCRIPT_DIR/docker-compose.yml")
    if [[ "${DEMOFORGE_MODE:-standard}" == "dev" && -f "$SCRIPT_DIR/docker-compose.dev.yml" ]]; then
        DC_FLAGS+=(-f "$SCRIPT_DIR/docker-compose.dev.yml")
    fi
    if [[ "${DEMOFORGE_HUB_LOCAL:-}" == "1" ]]; then
        DC_FLAGS+=("--profile" "local-hub")
    fi
}

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

log()   { echo -e "${BLUE}[DemoForge]${NC} $*"; }
ok()    { echo -e "${GREEN}[DemoForge]${NC} $*"; }
warn()  { echo -e "${YELLOW}[DemoForge]${NC} $*"; }
err()   { echo -e "${RED}[DemoForge]${NC} $*" >&2; }

# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

check_deps() {
    local missing=()
    command -v docker &>/dev/null || missing+=("docker")
    command -v docker compose version &>/dev/null 2>&1 || missing+=("docker-compose-v2")

    if [ ${#missing[@]} -gt 0 ]; then
        err "Missing dependencies: ${missing[*]}"
        err "Install Docker (Docker Desktop, OrbStack, or Docker Engine) with Compose v2 plugin."
        exit 1
    fi

    if ! docker info &>/dev/null 2>&1; then
        err "Docker daemon is not running. Start Docker Desktop, OrbStack, or the Docker service."
        exit 1
    fi
}

stop_services() {
    log "Stopping DemoForge services..."

    # Stop compose services gracefully
    docker compose "${DC_FLAGS[@]}" down --remove-orphans 2>/dev/null || true

    # Stop any orphaned demo containers (from deployed demos)
    local demo_containers
    demo_containers=$(docker ps -aq --filter "label=demoforge.demo" 2>/dev/null || true)
    if [ -n "$demo_containers" ]; then
        warn "Cleaning up orphaned demo containers..."
        echo "$demo_containers" | xargs docker stop 2>/dev/null || true
        echo "$demo_containers" | xargs docker rm 2>/dev/null || true
    fi

    # Stop stale demoforge containers, but spare sibling stacks: FA local (demoforge-fa-*)
    # and dev (demoforge-dev-*), which use different COMPOSE_PROJECT_NAME on the same host.
    local stale
    stale=$(docker ps -a --format "{{.ID}} {{.Names}}" 2>/dev/null \
        | awk '$2 ~ /^demoforge-/ && $2 !~ /^demoforge-fa-/ && $2 !~ /^demoforge-dev-/ {print $1}' || true)
    if [ -n "$stale" ]; then
        warn "Removing stale demoforge containers..."
        echo "$stale" | xargs docker stop 2>/dev/null || true
        echo "$stale" | xargs docker rm 2>/dev/null || true
    fi
}

clean_demo_networks() {
    log "Cleaning up demo networks..."
    # Skip sibling compose networks (dev / fa-local) so FA stop does not remove demoforge-dev_* / demoforge-fa_*.
    local nets
    nets=$(docker network ls --format "{{.ID}} {{.Name}}" 2>/dev/null \
        | awk '$2 ~ /^demoforge-/ && $2 !~ /demoforge-dev/ && $2 !~ /demoforge-fa/ {print $1}' || true)
    if [ -n "$nets" ]; then
        echo "$nets" | xargs docker network rm 2>/dev/null || true
        ok "Removed demo networks."
    fi
}

ensure_dirs() {
    mkdir -p demos data components
}

load_env() {
    # Capture any mode explicitly set by the caller (e.g. DEMOFORGE_MODE=dev from demoforge-dev.sh)
    # before sourcing .env files which might overwrite it.
    local _caller_mode="${DEMOFORGE_MODE:-}"

    # Load hub config first, then per-user local overrides (local wins for most keys)
    [[ -f "$SCRIPT_DIR/.env.hub" ]] && set -a && source "$SCRIPT_DIR/.env.hub" && set +a
    [[ -f "$SCRIPT_DIR/.env.local" ]] && set -a && source "$SCRIPT_DIR/.env.local" && set +a

    # Caller-specified mode always wins over .env.local (e.g. dev-start must stay dev).
    if [[ -n "$_caller_mode" ]]; then
        export DEMOFORGE_MODE="$_caller_mode"
    # Auto-promote to FA mode when FA identity is configured but mode is unset/standard.
    # This ensures 'make start' always runs in the right mode without manual .env.local edits.
    elif [[ "${DEMOFORGE_MODE:-standard}" == "standard" && -n "${DEMOFORGE_FA_ID:-}" ]]; then
        export DEMOFORGE_MODE="fa"
        if grep -q "^DEMOFORGE_MODE=" "$SCRIPT_DIR/.env.local" 2>/dev/null; then
            sed -i.bak "s|^DEMOFORGE_MODE=.*|DEMOFORGE_MODE=fa|" "$SCRIPT_DIR/.env.local" && rm -f "$SCRIPT_DIR/.env.local.bak"
        else
            echo "DEMOFORGE_MODE=fa" >> "$SCRIPT_DIR/.env.local"
        fi
    fi

    # Bake git version so the backend container can report it (no .git mount in Docker)
    export DEMOFORGE_VERSION="${DEMOFORGE_VERSION:-$(git -C "$SCRIPT_DIR" describe --tags --always 2>/dev/null || echo 'dev')}"
    # In GCP mode (DEMOFORGE_HUB_LOCAL not set), the .env.hub admin key is the GCP hub-api key.
    # Re-apply it after .env.local so the local dev key never wins in GCP mode.
    # fa_admin.py uses DEMOFORGE_HUB_API_URL (direct Cloud Run) with this key for FA Management.
    # If .env.hub has no admin key (old deployment), unset entirely — wrong local key is worse than none.
    if [[ "${DEMOFORGE_HUB_LOCAL:-}" != "1" && -f "$SCRIPT_DIR/.env.hub" ]]; then
        _hub_admin=$(grep "^DEMOFORGE_HUB_API_ADMIN_KEY=" "$SCRIPT_DIR/.env.hub" 2>/dev/null \
            | cut -d= -f2- || true)
        if [[ -n "$_hub_admin" ]]; then
            export DEMOFORGE_HUB_API_ADMIN_KEY="$_hub_admin"
        else
            unset DEMOFORGE_HUB_API_ADMIN_KEY 2>/dev/null || true
        fi
        unset _hub_admin
        # Gateway key: prefer explicit DEMOFORGE_GATEWAY_API_KEY from .env.hub,
        # fall back to DEMOFORGE_API_KEY. Always from .env.hub — never overridden locally.
        _gw_key=$(grep "^DEMOFORGE_GATEWAY_API_KEY=" "$SCRIPT_DIR/.env.hub" 2>/dev/null \
            | cut -d= -f2- || true)
        [[ -z "$_gw_key" ]] && _gw_key=$(grep "^DEMOFORGE_API_KEY=" "$SCRIPT_DIR/.env.hub" 2>/dev/null \
            | cut -d= -f2- || true)
        [[ -n "$_gw_key" ]] && export DEMOFORGE_GATEWAY_API_KEY="$_gw_key"
        unset _gw_key
    fi

    # Mode-specific ports: FA → 3000/9210, dev → 3001/9211 (non-overlapping host ports).
    # COMPOSE_PROJECT_NAME must always follow DEMOFORGE_MODE — not a stale value from .env.local
    # or the parent shell (e.g. COMPOSE_PROJECT_NAME=demoforge-dev + fa-update setting MODE=fa would
    # otherwise make `docker compose down` tear down the dev stack during FA restart).
    if [[ "${DEMOFORGE_MODE:-standard}" == "dev" ]]; then
        export BACKEND_PORT=9211
        export FRONTEND_PORT=3001
        export COMPOSE_PROJECT_NAME=demoforge-dev
    else
        export BACKEND_PORT=9210
        export FRONTEND_PORT=3000
        export COMPOSE_PROJECT_NAME=demoforge
    fi
    refresh_dc_flags
}

build_component_images() {
    # In FA mode (standard), images are pre-built and pulled via `make fa-setup`.
    # Building from source is dev-only — skip entirely for FAs.
    if [[ "${DEMOFORGE_MODE:-standard}" != "dev" ]]; then
        local missing=()
        for manifest in components/*/manifest.yaml; do
            [ -f "$manifest" ] || continue
            local build_ctx image
            build_ctx=$(grep -E '^build_context:' "$manifest" 2>/dev/null | sed 's/build_context:[[:space:]]*//' | tr -d '"' || true)
            [ -z "$build_ctx" ] && continue
            image=$(grep -E '^image:' "$manifest" 2>/dev/null | sed 's/image:[[:space:]]*//' | tr -d '"' || true)
            [ -z "$image" ] && continue
            if ! docker image inspect "$image" &>/dev/null; then
                missing+=("$image")
            fi
        done
        if [ ${#missing[@]} -gt 0 ]; then
            warn "Some component images are missing — run 'make fa-setup' to pull them:"
            for img in "${missing[@]}"; do warn "  $img"; done
        fi
        return
    fi

    # Dev mode: build from source only when source has changed since last build.
    # Marker files in .build-markers/ track the last successful build per image.
    local MARKER_DIR="$SCRIPT_DIR/.build-markers"
    mkdir -p "$MARKER_DIR"

    log "Checking for component images to build..."
    local count=0
    for manifest in components/*/manifest.yaml; do
        [ -f "$manifest" ] || continue
        local build_ctx
        build_ctx=$(grep -E '^build_context:' "$manifest" 2>/dev/null | sed 's/build_context:[[:space:]]*//' | tr -d '"' || true)
        [ -z "$build_ctx" ] && continue

        local comp_dir
        comp_dir=$(dirname "$manifest")
        local image
        image=$(grep -E '^image:' "$manifest" 2>/dev/null | sed 's/image:[[:space:]]*//' | tr -d '"' || true)
        [ -z "$image" ] && continue

        local build_path="$comp_dir/$build_ctx"
        if [ ! -d "$build_path" ]; then
            warn "Build context not found: $build_path (skipping)"
            continue
        fi

        # Derive a safe marker filename from the image name (replace / and : with _).
        local marker="$MARKER_DIR/$(echo "$image" | tr '/: ' '___').built"

        # Skip if image exists AND no source file is newer than the last build marker.
        if docker image inspect "$image" &>/dev/null && [[ -f "$marker" ]]; then
            if ! find "$build_path" -newer "$marker" -type f | grep -q .; then
                continue
            fi
        fi

        log "Building component image: $image from $build_path"
        if docker build -t "$image" "$build_path"; then
            touch "$marker"
            count=$((count + 1))
        else
            warn "Build failed for $image"
        fi
    done

    if [ $count -gt 0 ]; then
        ok "Built $count component image(s)."
    fi
}

wait_for_service() {
    local url=$1
    local name=$2
    local max_wait=${3:-60}
    local elapsed=0

    log "Waiting for $name at $url ..."
    while [ $elapsed -lt $max_wait ]; do
        if curl -sf "$url" &>/dev/null; then
            ok "$name is ready! ($elapsed s)"
            return 0
        fi
        sleep 2
        elapsed=$((elapsed + 2))
    done
    warn "$name did not respond within ${max_wait}s. Check logs with: ./demoforge.sh logs"
    return 1
}

# -------------------------------------------------------------------
# Commands
# -------------------------------------------------------------------

cmd_start() {
    check_deps
    log "Starting DemoForge..."

    load_env

    # FA identity check (non-dev mode only)
    if [[ "${DEMOFORGE_MODE:-standard}" != "dev" ]]; then
        if [[ -z "${DEMOFORGE_FA_ID:-}" ]]; then
            echo -e "${RED}✗ FA identity not configured.${NC}"
            echo -e "  Run: ${CYAN}make fa-setup${NC}"
            echo -e "  Or add manually: ${CYAN}echo 'DEMOFORGE_FA_ID=you@company.com' >> .env.local${NC}"
            exit 1
        fi
        echo -e "  FA: ${CYAN}${DEMOFORGE_FA_ID}${NC}"
    fi

    # Hub connectivity check (FA/standard mode only)
    if [[ "${DEMOFORGE_MODE:-standard}" != "dev" ]]; then
        log "Checking hub connectivity..."
        _DEFAULT_HUB_URL="https://demoforge-gateway-64xwtiev6q-ww.a.run.app"
        _HUB_URL="${DEMOFORGE_HUB_URL:-$_DEFAULT_HUB_URL}"
        _HEALTH_HTTP=$(curl -s --connect-timeout 5 -o /dev/null -w "%{http_code}" \
            "${_HUB_URL}/health" 2>/dev/null || echo "000")
        if [[ "$_HEALTH_HTTP" != "200" ]]; then
            warn "Hub gateway unreachable (HTTP $_HEALTH_HTTP) — FA management features may be limited."
        else
            ok "Hub connectivity verified"
        fi
    fi

    # Kill anything that's already running
    stop_services

    ensure_dirs

    # Build component images (custom Dockerfiles in components/)
    build_component_images

    if [[ "${DEMOFORGE_MODE:-standard}" == "dev" ]]; then
        # Dev mode: frontend must use Dockerfile stage `dev` (Vite HMR), not `prod` (nginx).
        # hub-update / hub-push use --target prod for GCR — keep that separate from this path.
        # Backend is single-stage; do not pass --target (would fail if set to dev).
        log "Building dev images (backend + frontend --target dev)..."
        docker compose "${DC_FLAGS[@]}" build backend
        docker compose "${DC_FLAGS[@]}" build --target dev frontend
        docker image prune -f --filter "until=1h" &>/dev/null || true
        log "Starting services..."
        docker compose "${DC_FLAGS[@]}" up -d --no-build
    else
        # FA mode: use pre-built images only — never build locally
        log "Starting services (using pre-built images)..."
        if ! docker compose "${DC_FLAGS[@]}" up -d --no-build 2>&1; then
            err "Required images not found. Run 'make fa-update' to pull the latest images."
            exit 1
        fi
    fi

    echo ""
    # Wait for services to be ready
    wait_for_service "http://localhost:${BACKEND_PORT}/docs" "Backend API" 60 || true
    wait_for_service "http://localhost:${FRONTEND_PORT}" "Frontend UI" 60 || true

    echo ""
    ok "========================================="
    ok " DemoForge is running!"
    ok "========================================="
    echo -e " ${CYAN}Frontend UI:${NC}  http://localhost:${FRONTEND_PORT}"
    echo -e " ${CYAN}Backend API:${NC}  http://localhost:${BACKEND_PORT}"
    echo -e " ${CYAN}API Docs:${NC}     http://localhost:${BACKEND_PORT}/docs"
    echo ""
    echo -e " ${YELLOW}Logs:${NC}         ./demoforge.sh logs"
    echo -e " ${YELLOW}Stop:${NC}         ./demoforge.sh stop"
    echo -e " ${YELLOW}Restart:${NC}      ./demoforge.sh restart"
    echo ""
}

cmd_stop() {
    log "Stopping DemoForge..."
    load_env
    stop_services
    clean_demo_networks
    ok "DemoForge stopped."
}

cmd_restart() {
    cmd_stop
    cmd_start
}

cmd_status() {
    load_env
    echo -e "${BLUE}=== DemoForge Status (${COMPOSE_PROJECT_NAME:-demoforge}) ===${NC}"
    echo ""

    # Compose services
    echo -e "${CYAN}Services:${NC}"
    docker compose "${DC_FLAGS[@]}" ps 2>/dev/null || echo "  No compose services running."
    echo ""

    # Demo containers
    echo -e "${CYAN}Demo Containers:${NC}"
    local demo_containers
    demo_containers=$(docker ps --filter "label=demoforge.demo" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || true)
    if [ -n "$demo_containers" ]; then
        echo "$demo_containers"
    else
        echo "  No demo containers running."
    fi
    echo ""

    # Demo networks
    echo -e "${CYAN}Demo Networks:${NC}"
    local nets
    nets=$(docker network ls --filter "name=demoforge-" --format "table {{.Name}}\t{{.Driver}}\t{{.Scope}}" 2>/dev/null || true)
    if [ -n "$nets" ]; then
        echo "$nets"
    else
        echo "  No demo networks."
    fi
    echo ""

    # Port usage
    echo -e "${CYAN}Ports:${NC}"
    for port in $BACKEND_PORT $FRONTEND_PORT; do
        local pid
        pid=$(lsof -ti :"$port" 2>/dev/null | head -1 || true)
        if [ -n "$pid" ]; then
            local pname
            pname=$(ps -p "$pid" -o comm= 2>/dev/null || echo "unknown")
            echo -e "  :${port} -> ${GREEN}in use${NC} (pid=$pid, $pname)"
        else
            echo -e "  :${port} -> ${YELLOW}free${NC}"
        fi
    done
}

cmd_logs() {
    load_env
    docker compose "${DC_FLAGS[@]}" logs -f --tail=100
}

cmd_logs_be() {
    load_env
    docker compose "${DC_FLAGS[@]}" logs -f --tail=100 backend
}

cmd_logs_fe() {
    load_env
    docker compose "${DC_FLAGS[@]}" logs -f --tail=100 frontend
}

cmd_build() {
    check_deps
    load_env
    log "Building DemoForge images..."
    build_component_images
    docker compose "${DC_FLAGS[@]}" build
    docker image prune -f --filter "until=1h" &>/dev/null || true
    ok "Build complete."
}

cmd_clean() {
    log "Full cleanup..."
    load_env
    stop_services
    clean_demo_networks

    # Remove volumes
    docker compose "${DC_FLAGS[@]}" down -v 2>/dev/null || true

    # Clean data directory
    if [ -d "data" ]; then
        rm -rf data/*
        log "Cleared data directory."
    fi

    ok "Clean complete."
}

cmd_nuke() {
    cmd_clean

    # Remove built images
    log "Removing DemoForge images..."
    docker compose "${DC_FLAGS[@]}" down --rmi local 2>/dev/null || true

    # Remove component-built images
    for manifest in components/*/manifest.yaml; do
        [ -f "$manifest" ] || continue
        local build_ctx
        build_ctx=$(grep -E '^build_context:' "$manifest" 2>/dev/null | sed 's/build_context:[[:space:]]*//' | tr -d '"' || true)
        [ -z "$build_ctx" ] && continue
        local image
        image=$(grep -E '^image:' "$manifest" 2>/dev/null | sed 's/image:[[:space:]]*//' | tr -d '"' || true)
        [ -n "$image" ] && docker rmi -f "$image" 2>/dev/null || true
    done

    # Remove any dangling demoforge images
    docker images --filter "reference=*demoforge*" -q 2>/dev/null | xargs docker rmi -f 2>/dev/null || true

    ok "Nuke complete. All DemoForge artifacts removed."
}

cmd_dev_be() {
    check_deps
    ensure_dirs

    log "Starting backend in dev mode (local Python)..."
    echo -e "${YELLOW}Tip: Install deps first: cd backend && pip install -r requirements.txt${NC}"
    echo ""

    load_env
    # Optional sim FA override — written by `make dev-as FA=...`, removed on exit
    if [[ -f "$SCRIPT_DIR/.env.sim" ]]; then
        set -a && source "$SCRIPT_DIR/.env.sim" && set +a
        echo -e "${YELLOW}Simulating FA: ${DEMOFORGE_FA_ID}${NC}"
    fi

    cd backend
    DEMOFORGE_COMPONENTS_DIR="$SCRIPT_DIR/components" \
    DEMOFORGE_DEMOS_DIR="$SCRIPT_DIR/demos" \
    DEMOFORGE_DATA_DIR="$SCRIPT_DIR/data" \
    DEMOFORGE_TEMPLATES_DIR="$SCRIPT_DIR/demo-templates" \
    DEMOFORGE_USER_TEMPLATES_DIR="$SCRIPT_DIR/user-templates" \
    DEMOFORGE_SYNCED_TEMPLATES_DIR="$SCRIPT_DIR/synced-templates" \
    DEMOFORGE_TEMPLATES_MODE="${DEMOFORGE_TEMPLATES_MODE:-all}" \
    DEMOFORGE_READINESS_CONFIG="$SCRIPT_DIR/component-readiness.yaml" \
    DEMOFORGE_HUB_API_ADMIN_KEY="${DEMOFORGE_HUB_API_ADMIN_KEY:-}" \
    uvicorn app.main:app --host 0.0.0.0 --port "$BACKEND_PORT" --reload
}

cmd_dev_fe() {
    log "Starting frontend in dev mode (local Node)..."
    echo -e "${YELLOW}Tip: Install deps first: cd frontend && npm install${NC}"
    echo ""

    cd frontend
    VITE_BACKEND_URL="http://localhost:${BACKEND_PORT}" \
    npm run dev -- --host 0.0.0.0 --port "$FRONTEND_PORT"
}

cmd_fa_ensure_dirs() {
    mkdir -p "$SCRIPT_DIR/fa-data"/{demos,data,user-templates,synced-templates}
    touch "$SCRIPT_DIR/fa-data/demos/.gitkeep" \
          "$SCRIPT_DIR/fa-data/data/.gitkeep" \
          "$SCRIPT_DIR/fa-data/user-templates/.gitkeep" \
          "$SCRIPT_DIR/fa-data/synced-templates/.gitkeep" 2>/dev/null || true
}

cmd_fa_start() {
    check_deps
    log "Starting DemoForge FA local instance (ports $FA_BACKEND_PORT/$FA_FRONTEND_PORT)..."
    load_env
    cmd_fa_ensure_dirs
    build_component_images
    docker compose "${FA_DC_FLAGS[@]}" up -d --remove-orphans
    wait_for_service "http://localhost:${FA_BACKEND_PORT}/docs" "FA Backend" 60 || true
    echo ""
    ok "DemoForge FA local instance running:"
    echo -e "  ${CYAN}Backend:${NC}   http://localhost:${FA_BACKEND_PORT}"
    echo -e "  ${CYAN}Frontend:${NC}  http://localhost:${FA_FRONTEND_PORT}"
    echo -e "  ${CYAN}Data:${NC}      ./fa-data/"
}

cmd_fa_stop() {
    log "Stopping DemoForge FA local instance..."
    docker compose "${FA_DC_FLAGS[@]}" down --remove-orphans 2>/dev/null || true
    ok "FA local instance stopped."
}

cmd_fa_restart() {
    cmd_fa_stop
    cmd_fa_start
}

cmd_fa_logs() {
    docker compose "${FA_DC_FLAGS[@]}" logs -f --tail=100
}

cmd_fa_status() {
    echo -e "${CYAN}FA Local Instance (port $FA_BACKEND_PORT):${NC}"
    docker compose "${FA_DC_FLAGS[@]}" ps 2>/dev/null || echo "  Not running."
}

cmd_fa_clean() {
    log "Cleaning FA local instance..."
    docker compose "${FA_DC_FLAGS[@]}" down -v --remove-orphans 2>/dev/null || true

    # Clear mutable FA data dirs (templates, licenses, demo state)
    for subdir in demos data user-templates synced-templates; do
        local dir="$SCRIPT_DIR/fa-data/$subdir"
        if [ -d "$dir" ]; then
            find "$dir" -mindepth 1 -not -name ".gitkeep" -delete 2>/dev/null || true
        fi
    done

    ok "FA local instance cleaned. Run './demoforge.sh fa:start' to restart fresh."
}

cmd_help() {
    echo -e "${BLUE}DemoForge Management Script${NC}"
    echo ""
    echo "Usage: ./demoforge.sh [command]"
    echo ""
    echo "Commands:"
    echo -e "  ${GREEN}start${NC}       Build and start all services (kills existing first)"
    echo -e "  ${GREEN}stop${NC}        Stop all services and clean up"
    echo -e "  ${GREEN}restart${NC}     Stop then start"
    echo -e "  ${GREEN}status${NC}      Show status of all services and demos"
    echo -e "  ${GREEN}logs${NC}        Tail logs from all services"
    echo -e "  ${GREEN}logs:be${NC}     Tail backend logs only"
    echo -e "  ${GREEN}logs:fe${NC}     Tail frontend logs only"
    echo -e "  ${GREEN}build${NC}       Build all images without starting"
    echo -e "  ${GREEN}clean${NC}       Stop everything, remove volumes and data"
    echo -e "  ${GREEN}nuke${NC}        Full clean + remove built images"
    echo -e "  ${GREEN}dev:be${NC}      Run backend locally (no Docker)"
    echo -e "  ${GREEN}dev:fe${NC}      Run frontend locally (no Docker)"
    echo -e "  ${GREEN}help${NC}        Show this help"
    echo ""
    echo -e "${BLUE}FA Local Testing (same PC, isolated on ports 9212/3002):${NC}"
    echo -e "  ${GREEN}fa:start${NC}    Start FA instance (./fa-data/ for templates/licenses)"
    echo -e "  ${GREEN}fa:stop${NC}     Stop FA instance"
    echo -e "  ${GREEN}fa:restart${NC}  Restart FA instance"
    echo -e "  ${GREEN}fa:logs${NC}     Tail FA instance logs"
    echo -e "  ${GREEN}fa:status${NC}   Show FA instance status"
    echo -e "  ${GREEN}fa:clean${NC}    Stop FA instance, remove volumes and clear fa-data/"
}

# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------

case "${1:-help}" in
    start)      cmd_start ;;
    stop)       cmd_stop ;;
    restart)    cmd_restart ;;
    status)     cmd_status ;;
    logs)       cmd_logs ;;
    logs:be)    cmd_logs_be ;;
    logs:fe)    cmd_logs_fe ;;
    build)      cmd_build ;;
    clean)      cmd_clean ;;
    nuke)       cmd_nuke ;;
    dev:be)     cmd_dev_be ;;
    dev:fe)     cmd_dev_fe ;;
    fa:start)   cmd_fa_start ;;
    fa:stop)    cmd_fa_stop ;;
    fa:restart) cmd_fa_restart ;;
    fa:logs)    cmd_fa_logs ;;
    fa:status)  cmd_fa_status ;;
    fa:clean)   cmd_fa_clean ;;
    help|--help|-h) cmd_help ;;
    *)
        err "Unknown command: $1"
        cmd_help
        exit 1
        ;;
esac
