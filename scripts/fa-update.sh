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

# ── Step 1: Migrate stale config values ───────────────────────────────────
ENVFILE="$PROJECT_ROOT/.env.local"
if grep -q "^DEMOFORGE_REGISTRY_HOST=localhost:5000$" "$ENVFILE" 2>/dev/null; then
  sed -i.bak "s|^DEMOFORGE_REGISTRY_HOST=localhost:5000$|DEMOFORGE_REGISTRY_HOST=localhost:5050|" "$ENVFILE" && rm -f "${ENVFILE}.bak"
  ok "Migrated DEMOFORGE_REGISTRY_HOST → localhost:5050 (port 5000 is reserved by macOS AirPlay)"
fi

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
    fail "Bootstrap failed — hub unreachable or FA key invalid. Check your network or run 'make fa-setup'."
  else
    CONNECTOR_KEY=$(echo "$BOOTSTRAP_RESP" | python3 -c \
      "import sys,json; print(json.load(sys.stdin).get('connector_key',''))" 2>/dev/null || echo "")

    # Ensure sync is enabled (may have been disabled by an older fa-update version)
    if grep -q "^DEMOFORGE_SYNC_ENABLED=" "$PROJECT_ROOT/.env.local" 2>/dev/null; then
      sed -i.bak "s|^DEMOFORGE_SYNC_ENABLED=.*|DEMOFORGE_SYNC_ENABLED=true|" "$PROJECT_ROOT/.env.local" && rm -f "${ENVFILE}.bak"
    else
      echo "DEMOFORGE_SYNC_ENABLED=true" >> "$PROJECT_ROOT/.env.local"
    fi

    if [[ -z "$CONNECTOR_KEY" ]]; then
      fail "Hub returned no connector key. Run 'make fa-setup' to re-register."
    else
      # ── Step 4: Pull latest hub-connector image ──────────────────────────
      log "Pulling latest hub-connector image..."
      docker pull "${CONNECTOR_IMAGE}" || warn "Could not pull latest image — will use cached version."

      # ── Step 5: Restart connector with fresh key ─────────────────────────
      log "Restarting hub-connector..."
      docker rm -f hub-connector 2>/dev/null || true
      HUB_HOST="${HUB_URL#https://}"
      docker run -d \
        --name hub-connector \
        --restart=always \
        -p 9000:9000 \
        -p 5050:5000 \
        -p 9001:9001 \
        -p 8080:8080 \
        -e "HUB_URL=${HUB_URL}" \
        -e "HUB_HOST=${HUB_HOST}" \
        -e "API_KEY=${CONNECTOR_KEY}" \
        "${CONNECTOR_IMAGE}"

      CONNECTOR_OK=0
      for i in $(seq 1 20); do
        curl -sf "http://localhost:8080/health" &>/dev/null && CONNECTOR_OK=1 && break
        sleep 1
      done
      if [[ "$CONNECTOR_OK" -ne 1 ]]; then
        echo ""
        echo -e "${YELLOW}── hub-connector status ──${NC}"
        docker inspect hub-connector --format='State: {{.State.Status}}  RestartCount: {{.RestartCount}}' 2>/dev/null || echo "(container not found)"
        echo -e "${YELLOW}── hub-connector logs ──${NC}"
        docker logs --tail 50 hub-connector 2>&1 || true
        echo -e "${YELLOW}── verbose health probe ──${NC}"
        curl -v "http://localhost:8080/health" 2>&1 || true
        fail "hub-connector failed to start. See logs above."
      fi
      echo -e "${YELLOW}── connector health response ──${NC}"
      curl -sv "http://localhost:8080/health" 2>&1 | tail -20
      echo ""
      ok "hub-connector running"
    fi
  fi
  echo ""

  # ── Step 5: Pull core images from GCR ───────────────────────────────────
  log "Pulling core images..."
  "$SCRIPT_DIR/hub-pull.sh" || warn "Some core images failed to pull (will use cached versions)"
  echo ""
fi

# ── Step 7: Restart DemoForge services ────────────────────────────────────
log "Restarting DemoForge..."
"$PROJECT_ROOT/demoforge.sh" restart
echo ""
ok "Update complete."
