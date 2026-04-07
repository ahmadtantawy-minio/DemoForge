#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}⚠${NC}  $*"; }

cd "$PROJECT_ROOT"

# ── Step 1: Pull latest scripts ────────────────────────────────────────────
echo -e "${GREEN}▶${NC} Pulling latest scripts and configs..."
_GIT_BEFORE=$(git rev-parse HEAD)
git pull
_GIT_AFTER=$(git rev-parse HEAD)
echo ""

if [[ "$_GIT_BEFORE" != "$_GIT_AFTER" ]]; then
  ok "Scripts updated — re-running with latest version..."
  echo ""
  exec "$SCRIPT_DIR/demoforge-update.sh"
fi

# ── Step 2: Run fa-update with the latest scripts ─────────────────────────
exec "$SCRIPT_DIR/fa-update.sh"
