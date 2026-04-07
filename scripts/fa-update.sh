#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${GREEN}▶${NC} $*"; }
warn() { echo -e "${YELLOW}⚠${NC}  $*"; }
ok()   { echo -e "${GREEN}✓${NC} $*"; }

cd "$PROJECT_ROOT"

# ── Step 1: Pull latest scripts / configs ──────────────────────────────────
log "Pulling latest changes..."
git pull
echo ""

# ── Step 2: Pull latest images via hub-connector ───────────────────────────
log "Checking hub-connector registry (localhost:5000)..."
if curl -sf --connect-timeout 3 --max-time 5 "http://localhost:5000/v2/" &>/dev/null; then
    ok "Registry reachable — pulling latest images..."
    "$SCRIPT_DIR/hub-pull.sh" || warn "Some images failed to pull (will use cached versions)"
else
    warn "Registry unreachable at localhost:5000"
    warn "Is hub-connector running? Run 'make fa-setup' if not set up yet."
    warn "Skipping image pull — restarting with currently cached images."
fi
echo ""

# ── Step 3: Restart services ───────────────────────────────────────────────
log "Restarting DemoForge..."
"$PROJECT_ROOT/demoforge.sh" restart
echo ""
ok "Update complete."
