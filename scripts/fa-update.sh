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

DEFAULT_HUB_URL="https://demoforge-gateway-64xwtiev6q-ww.a.run.app"

# ── Step 1: Load FA credentials ───────────────────────────────────────────────
FA_KEY=$(grep "^DEMOFORGE_API_KEY=" "$PROJECT_ROOT/.env.local" 2>/dev/null | cut -d= -f2- || echo "")
HUB_URL="$DEFAULT_HUB_URL"

if [[ -z "$FA_KEY" ]]; then
  warn "No FA key found in .env.local — skipping connectivity check."
  warn "Run 'make fa-setup' first if this is a fresh install."
else
  # ── Step 2: Verify hub connectivity ───────────────────────────────────────
  log "Checking hub connectivity..."
  _HEALTH_HTTP=$(curl -s --connect-timeout 5 -o /dev/null -w "%{http_code}" \
    "${HUB_URL}/health" 2>/dev/null || echo "000")
  if [[ "$_HEALTH_HTTP" != "200" ]]; then
    fail "Hub gateway unreachable (HTTP $_HEALTH_HTTP at ${HUB_URL}/health). Check your network connection."
  fi
  ok "Hub reachable"
  echo ""

  # ── Step 3: Version check ──────────────────────────────────────────────────
  _LOCAL_VER=$(curl -s "http://localhost:8080/api/version" --connect-timeout 3 2>/dev/null \
    | grep -o '"version":"[^"]*"' | cut -d'"' -f4 || echo "")
  _REMOTE_VER=$(curl -s "${HUB_URL}/version" --connect-timeout 5 2>/dev/null \
    | grep -o '"version":"[^"]*"' | cut -d'"' -f4 || echo "")
  if [[ -n "$_LOCAL_VER" && -n "$_REMOTE_VER" && "$_LOCAL_VER" != "$_REMOTE_VER" ]]; then
    warn "A newer version of DemoForge is available: $_REMOTE_VER (you have $_LOCAL_VER)"
    warn "Run 'make fa-update' again after updating to get the latest."
  elif [[ -n "$_LOCAL_VER" ]]; then
    ok "DemoForge is up to date ($_LOCAL_VER)"
  fi
  echo ""

  # ── Step 4: Pull core images from GCR ─────────────────────────────────────
  log "Pulling core images..."
  "$SCRIPT_DIR/hub-pull.sh" || warn "Some core images failed to pull (will use cached versions)"
  echo ""
fi

# ── Step 5: Ensure DEMOFORGE_MODE=fa is set ───────────────────────────────────
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

# ── Self-repair ────────────────────────────────────────────────────────────────
# Remove legacy hub-connector container (retired — FA traffic now goes direct to gateway)
if docker inspect hub-connector &>/dev/null 2>&1; then
  warn "Legacy hub-connector found — removing..."
  docker rm -f hub-connector 2>/dev/null || true
  ok "Legacy hub-connector removed"
fi

# Ensure DEMOFORGE_HUB_URL is set to the current gateway URL
_set_env "DEMOFORGE_HUB_URL" "$DEFAULT_HUB_URL"

# ── Step 6: Restart DemoForge services ────────────────────────────────────────
log "Restarting DemoForge..."
"$PROJECT_ROOT/demoforge.sh" restart
echo ""

# ── Step 7: Wait for backend to come up ───────────────────────────────────────
log "Waiting for DemoForge to start..."
_BACKEND_READY=0
for i in $(seq 1 12); do
  if curl -s "http://localhost:8080/api/health" --connect-timeout 3 2>/dev/null | grep -q '"status"'; then
    ok "DemoForge backend ready"
    _BACKEND_READY=1
    break
  fi
  [ "$i" -eq 12 ] && { warn "Backend not ready after 60s — skipping post-restart sync"; exit 0; }
  sleep 5
done
echo ""

# ── Step 8: Sync templates from hub ───────────────────────────────────────────
if [ "$_BACKEND_READY" -eq 1 ]; then
  log "Syncing templates from hub..."
  _SYNCED=0
  for i in $(seq 1 12); do
    _SYNC=$(curl -s -X POST "http://localhost:8080/api/templates/sync" \
      --connect-timeout 3 2>/dev/null | grep -c '"status"' || echo 0)
    if [ "$_SYNC" -gt 0 ]; then
      ok "Templates synced from hub"
      _SYNCED=1
      break
    fi
    sleep 5
  done
  [ "$_SYNCED" -eq 0 ] && warn "Template sync timed out — will retry on next fa-update"
  echo ""

  # ── Step 9: Cache license keys locally ──────────────────────────────────────
  log "Caching license keys..."
  curl -s "http://localhost:8080/api/fa/licenses/cache" --connect-timeout 5 2>/dev/null \
    | grep -q '"status"' \
    && ok "License keys cached" \
    || warn "License cache skipped — will use existing cache"
  echo ""
fi

ok "Update complete."
