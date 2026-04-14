#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${GREEN}▶${NC} $*"; }
warn() { echo -e "${YELLOW}⚠${NC}  $*"; }
ok()   { echo -e "${GREEN}✓${NC} $*"; }
fail() { echo -e "${RED}✗${NC} $*" >&2; exit 1; }

cd "$PROJECT_ROOT"

# ── Step 2b: Pull latest DemoForge code ────────────────────────────────────
log "Pulling latest DemoForge code..."
if git -C "$PROJECT_ROOT" pull --ff-only 2>/dev/null; then
  ok "DemoForge code updated"
else
  warn "git pull failed or not a clean repo — skipping code update (will use current version)"
fi

DEFAULT_HUB_URL="https://demoforge-gateway-64xwtiev6q-ww.a.run.app"

# ── Step 2: Load FA credentials ───────────────────────────────────────────
FA_KEY=$(grep "^DEMOFORGE_API_KEY=" "$PROJECT_ROOT/.env.local" 2>/dev/null | cut -d= -f2- || echo "")
HUB_URL=$(grep "^DEMOFORGE_HUB_URL=" "$PROJECT_ROOT/.env.local" 2>/dev/null | cut -d= -f2- || echo "$DEFAULT_HUB_URL")
[[ -z "$HUB_URL" ]] && HUB_URL="$DEFAULT_HUB_URL"

if [[ -z "$FA_KEY" ]]; then
  warn "No FA key found in .env.local — skipping connectivity check."
  warn "Run 'make fa-setup' first if this is a fresh install."
else
  # ── Step 3: Verify cloud connectivity ─────────────────────────────────
  log "Checking hub connectivity..."
  _HEALTH_HTTP=$(curl -s --connect-timeout 5 -o /dev/null -w "%{http_code}" \
    "${HUB_URL}/health" 2>/dev/null || echo "000")
  if [[ "$_HEALTH_HTTP" != "200" ]]; then
    fail "Hub gateway unreachable (HTTP $_HEALTH_HTTP at ${HUB_URL}/health). Check your network connection."
  fi
  ok "Hub reachable"
  echo ""

  # ── Step 4: Pull core images from GCR ─────────────────────────────────
  log "Pulling core images..."
  "$SCRIPT_DIR/hub-pull.sh" || warn "Some core images failed to pull (will use cached versions)"
  echo ""
fi

# ── Step 6: Ensure DEMOFORGE_MODE=fa is set ──────────────────────────────
ENVFILE="$PROJECT_ROOT/.env.local"
_set_env() {
    local key="$1" val="$2"
    if grep -q "^${key}=" "$ENVFILE" 2>/dev/null; then
        sed -i.bak "s|^${key}=.*|${key}=${val}|" "$ENVFILE" && rm -f "${ENVFILE}.bak"
    else
        printf '%s=%s\n' "$key" "$val" >> "$ENVFILE"
    fi
}
_set_env "DEMOFORGE_MODE" "fa"

# ── Step 7: Restart DemoForge services ────────────────────────────────────
log "Restarting DemoForge..."
"$PROJECT_ROOT/demoforge.sh" restart
echo ""
ok "Update complete."
