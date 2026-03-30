#!/usr/bin/env bash
set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'

echo -e "${CYAN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║  DemoForge — Field Architect Setup                                   ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# ── Pre-flight ──
if ! command -v docker &>/dev/null; then
    echo -e "${RED}Docker not found. Install OrbStack: https://orbstack.dev${NC}"
    exit 1
fi

# ── Get config from user (or .env.hub) ──
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

if [[ -f "$PROJECT_ROOT/.env.hub" ]]; then
    source "$PROJECT_ROOT/.env.hub"
    echo -e "${GREEN}✓ Loaded config from .env.hub${NC}"
else
    echo "Enter the Hub URL (from your team lead):"
    read -rp "  HUB_URL: " DEMOFORGE_HUB_URL
    echo "Enter your API key:"
    read -rsp "  API_KEY: " DEMOFORGE_API_KEY
    echo ""
fi

HUB_URL="${DEMOFORGE_HUB_URL:?Missing HUB_URL}"
API_KEY="${DEMOFORGE_API_KEY:?Missing API_KEY}"

# ── Verify gateway ──
echo -e "\n${CYAN}Checking hub connectivity...${NC}"
if curl -sf "${HUB_URL}/health" &>/dev/null; then
    echo -e "${GREEN}✓ Hub gateway reachable${NC}"
else
    echo -e "${RED}✗ Cannot reach ${HUB_URL}. Check your network.${NC}"
    exit 1
fi

# ── Stop existing connector ──
docker rm -f hub-connector 2>/dev/null || true

# ── Start hub connector ──
echo -e "\n${CYAN}Starting hub connector...${NC}"
CONNECTOR_IMAGE="gcr.io/minio-demoforge/demoforge-hub-connector:latest"
docker pull "${CONNECTOR_IMAGE}" 2>/dev/null || true

docker run -d \
    --name hub-connector \
    --restart=always \
    -p 9000:9000 \
    -p 5000:5000 \
    -p 9001:9001 \
    -p 8080:8080 \
    -e "HUB_URL=${HUB_URL}" \
    -e "API_KEY=${API_KEY}" \
    "${CONNECTOR_IMAGE}"

# Wait
for i in $(seq 1 10); do
    curl -sf "http://localhost:8080/health" &>/dev/null && break
    sleep 1
done

echo -e "${GREEN}✓ Hub connector running${NC}"

# ── Write .env.local ──
cat > "$PROJECT_ROOT/.env.local" <<EOF
DEMOFORGE_SYNC_ENABLED=true
DEMOFORGE_SYNC_ENDPOINT=http://localhost:9000
DEMOFORGE_SYNC_BUCKET=demoforge-templates
DEMOFORGE_SYNC_PREFIX=templates/
DEMOFORGE_SYNC_ACCESS_KEY=demoforge-sync
DEMOFORGE_SYNC_SECRET_KEY=${DEMOFORGE_SYNC_SECRET_KEY:-change-me}
DEMOFORGE_REGISTRY_HOST=localhost:5000
EOF

echo -e "${GREEN}✓ Wrote .env.local${NC}"

# ── Pull custom images ──
echo -e "\n${CYAN}Pulling custom DemoForge images...${NC}"
CATALOG=$(curl -sf "http://localhost:5000/v2/_catalog" 2>/dev/null || echo '{"repositories":[]}')
REPOS=$(echo "$CATALOG" | python3 -c "import sys,json; [print(r) for r in json.load(sys.stdin).get('repositories',[])]" 2>/dev/null || true)

if [[ -n "$REPOS" ]]; then
    while IFS= read -r repo; do
        [[ -z "$repo" ]] && continue
        echo "  Pulling localhost:5000/${repo}:latest..."
        docker pull "localhost:5000/${repo}:latest" 2>&1 | tail -1
    done <<< "$REPOS"
    echo -e "${GREEN}✓ Custom images pulled${NC}"
else
    echo -e "${YELLOW}No custom images in registry yet.${NC}"
fi

# ── Done ──
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  Setup complete!                                        ║${NC}"
echo -e "${GREEN}╠══════════════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║  Hub connector: running (auto-restarts)                 ║${NC}"
echo -e "${GREEN}║  Templates:     sync on next 'make start'              ║${NC}"
echo -e "${GREEN}║  Images:        pulled from registry                    ║${NC}"
echo -e "${GREEN}║  Console:       http://localhost:9001                   ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "Next: ${CYAN}make start${NC} to launch DemoForge"
