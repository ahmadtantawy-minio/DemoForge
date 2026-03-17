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
COMPOSE_FILE="docker-compose.yml"
BACKEND_PORT=9210
FRONTEND_PORT=3000

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
    docker compose -f "$COMPOSE_FILE" down --remove-orphans 2>/dev/null || true

    # Stop any orphaned demo containers (from deployed demos)
    local demo_containers
    demo_containers=$(docker ps -aq --filter "label=demoforge.demo" 2>/dev/null || true)
    if [ -n "$demo_containers" ]; then
        warn "Cleaning up orphaned demo containers..."
        echo "$demo_containers" | xargs docker stop 2>/dev/null || true
        echo "$demo_containers" | xargs docker rm 2>/dev/null || true
    fi

    # Stop any containers matching demoforge naming convention
    local stale
    stale=$(docker ps -aq --filter "name=demoforge-" 2>/dev/null || true)
    if [ -n "$stale" ]; then
        warn "Removing stale demoforge containers..."
        echo "$stale" | xargs docker stop 2>/dev/null || true
        echo "$stale" | xargs docker rm 2>/dev/null || true
    fi
}

clean_demo_networks() {
    log "Cleaning up demo networks..."
    local nets
    nets=$(docker network ls --filter "name=demoforge-" -q 2>/dev/null || true)
    if [ -n "$nets" ]; then
        echo "$nets" | xargs docker network rm 2>/dev/null || true
        ok "Removed demo networks."
    fi
}

ensure_dirs() {
    mkdir -p demos data components
}

build_component_images() {
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

        log "Building component image: $image from $build_path"
        docker build -t "$image" "$build_path"
        count=$((count + 1))
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

    # Kill anything that's already running
    stop_services

    ensure_dirs

    # Build component images (custom Dockerfiles in components/)
    build_component_images

    # Build and start
    log "Building images..."
    docker compose -f "$COMPOSE_FILE" build
    docker image prune -f --filter "until=1h" &>/dev/null || true

    log "Starting services..."
    docker compose -f "$COMPOSE_FILE" up -d

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
    stop_services
    clean_demo_networks
    ok "DemoForge stopped."
}

cmd_restart() {
    cmd_stop
    cmd_start
}

cmd_status() {
    echo -e "${BLUE}=== DemoForge Status ===${NC}"
    echo ""

    # Compose services
    echo -e "${CYAN}Services:${NC}"
    docker compose -f "$COMPOSE_FILE" ps 2>/dev/null || echo "  No compose services running."
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
    docker compose -f "$COMPOSE_FILE" logs -f --tail=100
}

cmd_logs_be() {
    docker compose -f "$COMPOSE_FILE" logs -f --tail=100 backend
}

cmd_logs_fe() {
    docker compose -f "$COMPOSE_FILE" logs -f --tail=100 frontend
}

cmd_build() {
    check_deps
    log "Building DemoForge images..."
    build_component_images
    docker compose -f "$COMPOSE_FILE" build
    docker image prune -f --filter "until=1h" &>/dev/null || true
    ok "Build complete."
}

cmd_clean() {
    log "Full cleanup..."
    stop_services
    clean_demo_networks

    # Remove volumes
    docker compose -f "$COMPOSE_FILE" down -v 2>/dev/null || true

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
    docker compose -f "$COMPOSE_FILE" down --rmi local 2>/dev/null || true

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

    cd backend
    DEMOFORGE_COMPONENTS_DIR="$SCRIPT_DIR/components" \
    DEMOFORGE_DEMOS_DIR="$SCRIPT_DIR/demos" \
    DEMOFORGE_DATA_DIR="$SCRIPT_DIR/data" \
    uvicorn app.main:app --host 0.0.0.0 --port "$BACKEND_PORT" --reload
}

cmd_dev_fe() {
    log "Starting frontend in dev mode (local Node)..."
    echo -e "${YELLOW}Tip: Install deps first: cd frontend && npm install${NC}"
    echo ""

    cd frontend
    VITE_API_URL="http://localhost:${BACKEND_PORT}" \
    npm run dev -- --host 0.0.0.0 --port "$FRONTEND_PORT"
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
    help|--help|-h) cmd_help ;;
    *)
        err "Unknown command: $1"
        cmd_help
        exit 1
        ;;
esac
