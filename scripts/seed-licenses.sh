#!/usr/bin/env bash
# seed-licenses.sh — Upload license keys to hub via gateway (GCS write path).
# GCS is the source of truth. No gcloud CLI required — auth via admin key.
#
# Usage:
#   scripts/seed-licenses.sh                    # uses .env.hub for HUB_URL + admin key
#   HUB_URL=https://... ADMIN_KEY=... scripts/seed-licenses.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
log()  { echo -e "${GREEN}[seed-licenses]${NC} $*"; }
warn() { echo -e "${YELLOW}[seed-licenses]${NC} $*"; }
err()  { echo -e "${RED}[seed-licenses]${NC} $*" >&2; }

# Load env
[[ -f "$PROJECT_ROOT/.env.hub" ]]   && source "$PROJECT_ROOT/.env.hub"
[[ -f "$PROJECT_ROOT/.env.local" ]] && source "$PROJECT_ROOT/.env.local"

HUB_URL="${DEMOFORGE_HUB_URL:-}"
ADMIN_KEY="${DEMOFORGE_HUB_API_ADMIN_KEY:-}"
LICENSES_FILE="${PROJECT_ROOT}/data/licenses.yaml"

[[ -z "$HUB_URL" ]]   && { err "DEMOFORGE_HUB_URL not set"; exit 1; }
[[ -z "$ADMIN_KEY" ]] && { err "DEMOFORGE_HUB_API_ADMIN_KEY not set"; exit 1; }
[[ -f "$LICENSES_FILE" ]] || { err "No licenses.yaml found at ${LICENSES_FILE}"; exit 1; }

log "Seeding licenses → ${HUB_URL}/api/hub/licenses (via gateway → GCS)"

python3 - "$LICENSES_FILE" "$HUB_URL" "$ADMIN_KEY" <<'EOF'
import yaml, json, sys, urllib.request, urllib.error

licenses_file, hub_url, admin_key = sys.argv[1:]

with open(licenses_file) as f:
    data = yaml.safe_load(f)

if not data:
    print("No licenses found in licenses.yaml")
    sys.exit(0)

ok = failed = 0
for lid, info in data.items():
    entry = {
        "license_id": lid,
        "value": info.get("value", ""),
        "label": info.get("label", ""),
        "created_at": info.get("created_at", ""),
    }
    url = f"{hub_url}/api/hub/licenses/{lid}.json"
    payload = json.dumps(entry).encode()
    req = urllib.request.Request(
        url, data=payload, method="PUT",
        headers={"X-Hub-Admin-Key": admin_key, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            print(f"✓ Uploaded: {lid}")
            ok += 1
    except urllib.error.HTTPError as e:
        print(f"✗ Failed: {lid} — HTTP {e.code}: {e.read().decode()[:120]}", file=sys.stderr)
        failed += 1
    except Exception as e:
        print(f"✗ Failed: {lid} — {e}", file=sys.stderr)
        failed += 1

print(f"\nDone: {ok} uploaded, {failed} failed")
if failed:
    sys.exit(1)
EOF
