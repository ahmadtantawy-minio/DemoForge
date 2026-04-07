#!/usr/bin/env bash
set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'

echo -e "${CYAN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║  DemoForge — Field Architect Setup                       ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# ── Pre-flight ──
if ! command -v docker &>/dev/null; then
    echo -e "${RED}Docker not found. Install OrbStack: https://orbstack.dev${NC}"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DEFAULT_HUB_URL="https://demoforge-gateway-64xwtiev6q-ww.a.run.app"

# ── Load or prompt for FA key ──
FA_KEY=""
HUB_URL="${DEFAULT_HUB_URL}"

# Check for existing key
if [[ -f "$PROJECT_ROOT/.env.local" ]]; then
    _EXISTING_KEY=$(grep "^DEMOFORGE_API_KEY=" "$PROJECT_ROOT/.env.local" 2>/dev/null | cut -d= -f2- || echo "")
    if [[ -n "$_EXISTING_KEY" ]]; then
        FA_KEY="$_EXISTING_KEY"
        echo -e "${GREEN}✓ Loaded existing FA key from .env.local${NC}"
    fi
fi

if [[ -z "$FA_KEY" ]]; then
    echo -e "${CYAN}Enter your FA key (provided by your DemoForge admin):${NC}"
    read -rsp "  FA Key: " FA_KEY
    echo ""
fi

if [[ -z "$FA_KEY" ]]; then
    echo -e "${RED}FA key is required. Ask your DemoForge admin to create an account for you.${NC}"
    exit 1
fi

# ── Verify gateway reachable ──
echo -e "\n${CYAN}Checking hub gateway...${NC}"
if ! curl -sf "${HUB_URL}/health" &>/dev/null; then
    echo -e "${RED}✗ Cannot reach ${HUB_URL}. Check your network.${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Hub gateway reachable${NC}"

# ── Bootstrap: validate FA key and get connector config ──
echo -e "\n${CYAN}Validating FA key with hub...${NC}"
BOOTSTRAP_RESP=$(curl -sf "${HUB_URL}/api/hub/fa/bootstrap" \
    -H "X-Api-Key: ${FA_KEY}" \
    2>/dev/null || echo "")

if [[ -z "$BOOTSTRAP_RESP" ]]; then
    echo -e "${RED}✗ FA key validation failed. Check your key is correct, or ask your admin to verify your account.${NC}"
    exit 1
fi

# Parse bootstrap response
_FA_ID_FROM_HUB=$(echo "$BOOTSTRAP_RESP" | python3 -c \
    "import sys,json; d=json.load(sys.stdin); print(d.get('fa_id',''))" 2>/dev/null || echo "")
_IS_ACTIVE=$(echo "$BOOTSTRAP_RESP" | python3 -c \
    "import sys,json; d=json.load(sys.stdin); print(str(d.get('is_active',True)).lower())" 2>/dev/null || echo "true")
CONNECTOR_KEY=$(echo "$BOOTSTRAP_RESP" | python3 -c \
    "import sys,json; d=json.load(sys.stdin); print(d.get('connector_key',''))" 2>/dev/null || echo "")
SYNC_SECRET=$(echo "$BOOTSTRAP_RESP" | python3 -c \
    "import sys,json; d=json.load(sys.stdin); print(d.get('sync_secret_key',''))" 2>/dev/null || echo "")

if [[ "$_IS_ACTIVE" != "true" ]]; then
    echo -e "${RED}✗ Your account is deactivated. Contact your DemoForge admin.${NC}"
    exit 1
fi

if [[ -z "$CONNECTOR_KEY" ]]; then
    echo -e "${RED}✗ Hub did not return connector configuration. Contact your admin — hub-api may need updating.${NC}"
    exit 1
fi

echo -e "${GREEN}✓ FA key validated${NC}"
[[ -n "$_FA_ID_FROM_HUB" ]] && echo -e "  Identity: ${CYAN}${_FA_ID_FROM_HUB}${NC}"

# ── Stop existing connector ──
docker rm -f hub-connector 2>/dev/null || true

# ── Start hub connector ──
echo -e "\n${CYAN}Starting hub connector...${NC}"
CONNECTOR_IMAGE="gcr.io/minio-demoforge/demoforge-hub-connector:latest"
docker pull "${CONNECTOR_IMAGE}" 2>/dev/null || true

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

# Wait for connector
for i in $(seq 1 15); do
    curl -sf "http://localhost:8080/health" &>/dev/null && break
    sleep 1
done

echo -e "${GREEN}✓ Hub connector running${NC}"

# ─── Detect FA identity ──────────────────────────────────────────────
echo -e "\n${CYAN}Confirming your identity...${NC}"

FA_ID="${_FA_ID_FROM_HUB}"

# If hub didn't return an FA_ID (first-time registration), auto-detect
if [[ -z "$FA_ID" ]]; then
    if command -v git &>/dev/null; then
        FA_ID=$(git config user.email 2>/dev/null || echo "")
    fi
    if [[ -z "$FA_ID" ]] && command -v gh &>/dev/null; then
        FA_ID=$(gh api user --jq '.login // empty' 2>/dev/null || echo "")
    fi
    if [[ -z "$FA_ID" ]] && [[ -f "$PROJECT_ROOT/.env.local" ]]; then
        FA_ID=$(grep "^DEMOFORGE_FA_ID=" "$PROJECT_ROOT/.env.local" 2>/dev/null | cut -d= -f2 || echo "")
    fi
fi

if [[ -n "$FA_ID" ]]; then
    echo -e "  Identity: ${CYAN}${FA_ID}${NC}"
    read -rp "  Press Enter to confirm, or type a different email/username: " FA_OVERRIDE
    [[ -n "$FA_OVERRIDE" ]] && FA_ID="$FA_OVERRIDE"
else
    echo -e "${YELLOW}Could not auto-detect your identity.${NC}"
    echo -e "  ${CYAN}Enter your email or username (e.g., ahmad@min.io or ahmad.tantawy).${NC}"
    read -rp "  Your identity: " FA_ID
fi

if [[ -z "$FA_ID" ]]; then
    echo -e "${RED}FA identity is required.${NC}"
    exit 1
fi
echo -e "${GREEN}✓ FA identity: ${FA_ID}${NC}"

# ── Register with Hub API (now via connector) ──
echo ""
echo -e "${CYAN}Registering with DemoForge Hub API...${NC}"
_FA_NAME="$(git config user.name 2>/dev/null || echo "$FA_ID")"
_REGISTER_RESP=$(curl -sf -X POST http://localhost:8080/api/hub/fa/register \
    -H "Content-Type: application/json" \
    -d "{\"fa_id\": \"$FA_ID\", \"fa_name\": \"$_FA_NAME\", \"api_key\": \"$FA_KEY\"}" \
    2>/dev/null || echo "")

if echo "$_REGISTER_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d.get('fa_id')" 2>/dev/null; then
    echo -e "  ${GREEN}✓${NC} Registered as: $FA_ID"
else
    echo -e "  ${YELLOW}⚠${NC}  Hub registration response unexpected (non-blocking). Check connectivity page after starting."
fi

# ── Write .env.local ──
ENVFILE="$PROJECT_ROOT/.env.local"
touch "$ENVFILE"

_set_env() {
    local key="$1" val="$2"
    if grep -q "^${key}=" "$ENVFILE" 2>/dev/null; then
        sed -i.bak "s|^${key}=.*|${key}=${val}|" "$ENVFILE" && rm -f "${ENVFILE}.bak"
    else
        printf '%s=%s\n' "$key" "$val" >> "$ENVFILE"
    fi
}

_set_env "DEMOFORGE_FA_ID"           "${FA_ID}"
_set_env "DEMOFORGE_API_KEY"         "${FA_KEY}"
_set_env "DEMOFORGE_REGISTRY_HOST"   "localhost:5050"

if [[ -n "$SYNC_SECRET" ]]; then
    _set_env "DEMOFORGE_SYNC_ENABLED"    "true"
    _set_env "DEMOFORGE_SYNC_ENDPOINT"   "http://host.docker.internal:9000"
    _set_env "DEMOFORGE_SYNC_BUCKET"     "demoforge-templates"
    _set_env "DEMOFORGE_SYNC_PREFIX"     "templates/"
    _set_env "DEMOFORGE_SYNC_ACCESS_KEY" "demoforge-sync"
    _set_env "DEMOFORGE_SYNC_SECRET_KEY" "${SYNC_SECRET}"
else
    _set_env "DEMOFORGE_SYNC_ENABLED"    "false"
    echo -e "  ${YELLOW}⚠${NC}  Hub did not return sync credentials — template sync disabled."
fi

echo -e "${GREEN}✓ Updated .env.local${NC}"

# ── Pull custom images ──
echo -e "\n${CYAN}Pulling custom DemoForge images...${NC}"
CATALOG=$(curl -sf "http://localhost:5050/v2/_catalog" 2>/dev/null || echo '{"repositories":[]}')
REPOS=$(echo "$CATALOG" | python3 -c "import sys,json; [print(r) for r in json.load(sys.stdin).get('repositories',[])]" 2>/dev/null || true)

if [[ -n "$REPOS" ]]; then
    while IFS= read -r repo; do
        [[ -z "$repo" ]] && continue
        echo "  Pulling localhost:5050/${repo}:latest..."
        docker pull "localhost:5050/${repo}:latest" 2>&1 | tail -1
        docker tag "localhost:5050/${repo}:latest" "${repo}:latest" 2>/dev/null && echo "  ↳ tagged ${repo}:latest"
    done <<< "$REPOS"
    echo -e "${GREEN}✓ Custom images pulled and tagged${NC}"
else
    echo -e "${YELLOW}No custom images in registry yet.${NC}"
fi

# ── Done ──
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  Setup complete!                                         ║${NC}"
echo -e "${GREEN}╠══════════════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║  FA identity:   ${FA_ID}${NC}"
echo -e "${GREEN}║  Hub connector: running (auto-restarts)                  ║${NC}"
echo -e "${GREEN}║  Templates:     sync on next 'make start'               ║${NC}"
echo -e "${GREEN}║  Images:        pulled from registry                     ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "Next: ${CYAN}make start${NC} to launch DemoForge"
