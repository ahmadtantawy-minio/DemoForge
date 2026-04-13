#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${GREEN}[seed-licenses]${NC} $*"; }
warn() { echo -e "${YELLOW}[seed-licenses]${NC} $*"; }
err()  { echo -e "${RED}[seed-licenses]${NC} $*" >&2; }

echo -e "${CYAN}Seeding licenses to GCS...${NC}"

LICENSES_FILE="${PROJECT_ROOT}/data/licenses.yaml"
GCS_BUCKET="gs://demoforge-hub-licenses"

if [[ ! -f "$LICENSES_FILE" ]]; then
    err "No licenses.yaml found at ${LICENSES_FILE}"
    exit 1
fi

# Parse YAML and upload each license as JSON to GCS
python3 -c "
import yaml, json, sys, subprocess, os

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
    dest = f'${GCS_BUCKET}/{lid}.json'
    result = subprocess.run(
        ['gcloud', 'storage', 'cp', fname, dest],
        capture_output=True, text=True
    )
    os.unlink(fname)
    if result.returncode == 0:
        print(f'✓ Uploaded: {lid}')
    else:
        print(f'✗ Failed: {lid} — {result.stderr.strip()}', file=sys.stderr)
"

log "Licenses seeded to ${GCS_BUCKET}"
gcloud storage ls "${GCS_BUCKET}/" 2>/dev/null | grep '\.json$' || warn "No license files found in bucket"
