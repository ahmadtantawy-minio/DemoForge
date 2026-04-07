#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${GREEN}[hub-update]${NC} $*"; }
warn() { echo -e "${YELLOW}[hub-update]${NC} $*"; }
err()  { echo -e "${RED}[hub-update]${NC} $*" >&2; }

# Source env
[[ -f "$PROJECT_ROOT/.env.hub" ]] && source "$PROJECT_ROOT/.env.hub"
[[ -f "$PROJECT_ROOT/.env.local" ]] && source "$PROJECT_ROOT/.env.local"

usage() {
    echo "Usage: $0 [--all | --gateway | --templates | --images | --licenses]"
    echo ""
    echo "  --all         Run all update steps (default)"
    echo "  --gateway     Rebuild and deploy Cloud Run gateway only"
    echo "  --templates   Seed base templates to MinIO hub"
    echo "  --images      Build and push custom images to registry"
    echo "  --licenses    Seed license keys to MinIO"
    echo ""
    echo "Requires dev mode (direct MinIO access) for push operations."
    exit 0
}

MODE="${1:---all}"
case "$MODE" in
    --help|-h) usage ;;
    --all|--gateway|--templates|--images|--licenses) ;;
    *) echo "Unknown flag: $MODE"; usage ;;
esac

echo -e "${CYAN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║  DemoForge Hub — Update                                 ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# ── Pre-flight checks ──
DIRECT_IP="${DEMOFORGE_DIRECT_IP:-}"
if [[ -z "$DIRECT_IP" ]]; then
    err "DEMOFORGE_DIRECT_IP not set. Configure .env.hub or .env.local first."
    exit 1
fi

log "Hub: ${DEMOFORGE_HUB_URL:-not set}"
log "Direct IP: ${DIRECT_IP}"
echo ""

# ── Step 1: Gateway ──
if [[ "$MODE" == "--all" || "$MODE" == "--gateway" ]]; then
    log "=== Updating Gateway ==="
    "$SCRIPT_DIR/minio-gcp.sh" --deploy-gateway
    echo ""
fi

# ── Step 2: Templates ──
if [[ "$MODE" == "--all" || "$MODE" == "--templates" ]]; then
    log "=== Seeding Templates ==="
    "$SCRIPT_DIR/hub-seed.sh"
    echo ""
fi

# ── Step 3: Images ──
if [[ "$MODE" == "--all" || "$MODE" == "--images" ]]; then
    log "=== Building & Pushing Custom Images ==="
    "$SCRIPT_DIR/hub-push.sh"
    echo ""
fi

# ── Step 4: Licenses ──
if [[ "$MODE" == "--all" || "$MODE" == "--licenses" ]]; then
    log "=== Seeding Licenses ==="
    "$SCRIPT_DIR/seed-licenses.sh"
    echo ""
fi

# ── Summary ──
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  Hub Update Complete                                    ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# Show status
"$SCRIPT_DIR/hub-status.sh" 2>/dev/null || true
