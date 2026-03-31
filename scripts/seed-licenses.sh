#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'

echo -e "${CYAN}Seeding licenses to MinIO...${NC}"

# Source env
[[ -f "$PROJECT_ROOT/.env.hub" ]] && source "$PROJECT_ROOT/.env.hub"
[[ -f "$PROJECT_ROOT/.env.local" ]] && source "$PROJECT_ROOT/.env.local"

LICENSES_FILE="$PROJECT_ROOT/data/licenses.yaml"
BUCKET="demoforge-licenses"

if [[ ! -f "$LICENSES_FILE" ]]; then
    echo -e "${RED}No licenses.yaml found at ${LICENSES_FILE}${NC}"
    exit 1
fi

# Use mc with the hub alias
MC_ALIAS="demoforge-hub"
ENDPOINT="${DEMOFORGE_SYNC_ENDPOINT:-http://localhost:9000}"
ACCESS_KEY="${DEMOFORGE_SYNC_ACCESS_KEY:-}"
SECRET_KEY="${DEMOFORGE_SYNC_SECRET_KEY:-}"

if [[ -z "$ACCESS_KEY" || -z "$SECRET_KEY" ]]; then
    echo -e "${RED}Sync credentials not configured. Set DEMOFORGE_SYNC_ACCESS_KEY and DEMOFORGE_SYNC_SECRET_KEY.${NC}"
    exit 1
fi

# Set mc alias
mc alias set "${MC_ALIAS}" "${ENDPOINT}" "${ACCESS_KEY}" "${SECRET_KEY}" --api S3v4 2>/dev/null || {
    echo -e "${RED}Cannot connect to MinIO at ${ENDPOINT}${NC}"
    exit 1
}

# Create bucket if needed
mc mb "${MC_ALIAS}/${BUCKET}" --ignore-existing 2>/dev/null
echo -e "${GREEN}✓ Bucket ${BUCKET} ready${NC}"

# Parse YAML and upload each license as JSON
python3 -c "
import yaml, json, sys

with open('${LICENSES_FILE}') as f:
    data = yaml.safe_load(f)

if not data:
    print('No licenses found')
    sys.exit(0)

for lid, info in data.items():
    entry = {
        'license_id': lid,
        'value': info.get('value', ''),
        'label': info.get('label', ''),
        'created_at': info.get('created_at', ''),
    }
    fname = f'/tmp/license-{lid}.json'
    with open(fname, 'w') as f:
        json.dump(entry, f)
    print(f'Prepared: {lid}')
"

# Upload each license JSON
for f in /tmp/license-*.json; do
    [[ ! -f "$f" ]] && continue
    lid=$(basename "$f" .json | sed 's/^license-//')
    mc cp "$f" "${MC_ALIAS}/${BUCKET}/${lid}.json" 2>/dev/null
    echo -e "${GREEN}✓ Uploaded: ${lid}${NC}"
    rm -f "$f"
done

echo -e "\n${GREEN}Licenses seeded to ${BUCKET}${NC}"
mc ls "${MC_ALIAS}/${BUCKET}/"
