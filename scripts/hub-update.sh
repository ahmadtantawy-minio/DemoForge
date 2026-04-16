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
    echo "Usage: $0 [--all | --gateway | --hub-api | --images | --licenses]"
    echo ""
    echo "  --all         Run all update steps (default)"
    echo "  --gateway     Rebuild and deploy Cloud Run gateway only"
    echo "  --hub-api     Redeploy hub-api Cloud Run only (~2 min)"
    echo "  --images      Build and push core images to GCR (frontend, backend, data-generator)"
    echo "  --images-all  Build and push ALL custom images to GCR"
    echo "  --licenses    Seed license keys to GCS (explicit opt-in — normally managed via the UI)"
    echo ""
    echo "  Note: templates are managed via the UI (publish/promote) or POST /api/templates/push-all-builtin"
    echo ""
    exit 0
}

MODE="${1:---all}"
case "$MODE" in
    --help|-h) usage ;;
    --all|--gateway|--hub-api|--images|--images-all|--licenses) ;;
    *) echo "Unknown flag: $MODE"; usage ;;
esac

echo -e "${CYAN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║  DemoForge Hub — Update                                 ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# ── hub-api only ──
if [[ "$MODE" == "--hub-api" ]]; then
    log "=== Redeploying hub-api Cloud Run ==="
    "$SCRIPT_DIR/minio-gcp.sh" --deploy-api
    echo ""
    exit 0
fi

# ── Gateway requires DIRECT_IP for Caddyfile generation ──
if [[ "$MODE" == "--all" || "$MODE" == "--gateway" ]]; then
    DIRECT_IP="${DEMOFORGE_DIRECT_IP:-}"
    if [[ -z "$DIRECT_IP" ]]; then
        err "DEMOFORGE_DIRECT_IP not set — required for gateway deploy. Configure .env.hub or .env.local."
        exit 1
    fi
    log "=== Updating Gateway ==="
    "$SCRIPT_DIR/minio-gcp.sh" --deploy-gateway
    echo ""
fi

# ── Images → GCR (no DIRECT_IP needed) ──
if [[ "$MODE" == "--all" || "$MODE" == "--images" ]]; then
    log "=== Building & Pushing Core Images (production frontend: hub-push uses Dockerfile --target prod) ==="
    "$SCRIPT_DIR/hub-push.sh"
    echo ""
fi

if [[ "$MODE" == "--images-all" ]]; then
    log "=== Building & Pushing All Custom Images ==="
    "$SCRIPT_DIR/hub-push.sh" --all
    echo ""
fi

# ── Licenses → GCS (explicit opt-in only — licenses are managed via the UI) ──
if [[ "$MODE" == "--licenses" ]]; then
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

"$SCRIPT_DIR/hub-status.sh" 2>/dev/null || true
