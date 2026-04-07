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

CONNECTOR_IMAGE="gcr.io/minio-demoforge/demoforge-hub-connector:latest"
DEFAULT_HUB_URL="https://demoforge-gateway-64xwtiev6q-ww.a.run.app"

# ── Step 1: Pull latest scripts / configs ──────────────────────────────────
log "Pulling latest scripts and configs..."
git pull
echo ""

# ── Step 2: Load FA key ────────────────────────────────────────────────────
FA_KEY=$(grep "^DEMOFORGE_API_KEY=" "$PROJECT_ROOT/.env.local" 2>/dev/null | cut -d= -f2- || echo "")
HUB_URL=$(grep "^DEMOFORGE_HUB_URL=" "$PROJECT_ROOT/.env.local" 2>/dev/null | cut -d= -f2- || echo "$DEFAULT_HUB_URL")
[[ -z "$HUB_URL" ]] && HUB_URL="$DEFAULT_HUB_URL"

if [[ -z "$FA_KEY" ]]; then
  warn "No FA key found in .env.local — skipping hub-connector update."
  warn "Run 'make fa-setup' first if this is a fresh install."
else
  # ── Step 3: Re-bootstrap to get connector key ────────────────────────────
  log "Refreshing connector config from hub..."
  BOOTSTRAP_RESP=$(curl -sf "${HUB_URL}/api/hub/fa/bootstrap" \
    -H "X-Api-Key: ${FA_KEY}" 2>/dev/null || echo "")

  if [[ -z "$BOOTSTRAP_RESP" ]]; then
    warn "Bootstrap failed (hub unreachable or FA key invalid) — restarting existing connector."
    docker restart hub-connector 2>/dev/null || warn "hub-connector not found. Run 'make fa-setup'."
  else
    CONNECTOR_KEY=$(echo "$BOOTSTRAP_RESP" | python3 -c \
      "import sys,json; print(json.load(sys.stdin).get('connector_key',''))" 2>/dev/null || echo "")

    if [[ -z "$CONNECTOR_KEY" ]]; then
      warn "Hub returned no connector key — restarting existing connector."
      docker restart hub-connector 2>/dev/null || warn "hub-connector not found. Run 'make fa-setup'."
    else
      # ── Step 4: Pull latest hub-connector image ──────────────────────────
      log "Pulling latest hub-connector image..."
      docker pull "${CONNECTOR_IMAGE}" || warn "Could not pull latest image — will use cached version."

      # ── Step 5: Restart connector with fresh key ─────────────────────────
      log "Restarting hub-connector..."
      docker rm -f hub-connector 2>/dev/null || true
      docker run -d \
        --name hub-connector \
        --restart=always \
        -p 9000:9000 \
        -p 5000:5000 \
        -p 9001:9001 \
        -p 8080:8080 \
        -e "HUB_URL=${HUB_URL}" \
        -e "API_KEY=${CONNECTOR_KEY}" \
        "${CONNECTOR_IMAGE}"

      for i in $(seq 1 15); do
        curl -sf "http://localhost:8080/health" &>/dev/null && break
        sleep 1
      done
      ok "hub-connector running"
    fi
  fi
  echo ""

  # ── Step 6: Pull latest custom images via connector ──────────────────────
  log "Pulling latest images from registry..."
  if curl -sf --connect-timeout 5 --max-time 8 "http://localhost:5000/v2/" &>/dev/null; then
    "$SCRIPT_DIR/hub-pull.sh" || warn "Some images failed to pull (will use cached versions)"
  else
    warn "Registry still unreachable — skipping image pull."
  fi
  echo ""
fi

# ── Step 7: Restart DemoForge services ────────────────────────────────────
log "Restarting DemoForge..."
"$PROJECT_ROOT/demoforge.sh" restart
echo ""
ok "Update complete."
