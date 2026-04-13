#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
TEMPLATES_DIR="${PROJECT_ROOT}/demo-templates"
GCS_BUCKET="gs://demoforge-hub-templates"
GCS_PREFIX="templates"
GCS_MANIFEST="${GCS_BUCKET}/${GCS_PREFIX}/.seed-manifest.json"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
log()  { echo -e "${GREEN}[hub-seed]${NC} $*"; }
warn() { echo -e "${YELLOW}[hub-seed]${NC} $*"; }
err()  { echo -e "${RED}[hub-seed]${NC} $*" >&2; }

FORCE=false
for arg in "$@"; do [[ "$arg" == "--force" ]] && FORCE=true; done

log "Seeding templates → ${GCS_BUCKET}/${GCS_PREFIX}/"
[[ "$FORCE" == "true" ]] && warn "Force mode: skipping version comparison"

# ── Step 1: Fetch remote manifest (one API call) ────────────────────────────
TMP_MANIFEST=$(mktemp)
TMP_UPLOAD_LIST=$(mktemp)
TMP_NEW_MANIFEST=$(mktemp)
trap 'rm -f "$TMP_MANIFEST" "$TMP_UPLOAD_LIST" "$TMP_NEW_MANIFEST"' EXIT

if [[ "$FORCE" == "false" ]]; then
    gcloud storage cat "$GCS_MANIFEST" > "$TMP_MANIFEST" 2>/dev/null || echo "{}" > "$TMP_MANIFEST"
else
    echo "{}" > "$TMP_MANIFEST"
fi

# ── Step 2: Python decides which files to upload ────────────────────────────
python3 - "$TEMPLATES_DIR" "$TMP_MANIFEST" "$TMP_UPLOAD_LIST" <<'EOF'
import sys, json, yaml, os

templates_dir, manifest_path, upload_list_path = sys.argv[1:]

with open(manifest_path) as f:
    remote = json.load(f)

to_upload = []
skip_count = 0

for fname in sorted(os.listdir(templates_dir)):
    if not fname.endswith(".yaml"):
        continue
    if fname in ("CHANGELOG.yaml", "ORDER.yaml"):
        continue

    local_path = os.path.join(templates_dir, fname)
    try:
        with open(local_path) as f:
            data = yaml.safe_load(f) or {}
        local_date = data.get("_template", {}).get("updated_at", "") or ""
    except Exception:
        local_date = ""

    remote_entry = remote.get(fname, {})
    remote_date = (remote_entry.get("updated_at", "") if isinstance(remote_entry, dict) else str(remote_entry)) or ""

    # Skip only when remote is strictly newer
    if remote_date and local_date and remote_date > local_date:
        print(f"SKIP {fname} — GCS newer ({remote_date} > {local_date})", file=sys.stderr)
        skip_count += 1
        continue

    to_upload.append({"fname": fname, "local_date": local_date})

with open(upload_list_path, "w") as f:
    json.dump({"to_upload": to_upload, "skip_count": skip_count}, f)
EOF

# ── Step 3: Upload files flagged by Python ───────────────────────────────────
UPLOAD_INFO=$(cat "$TMP_UPLOAD_LIST")
NEWER_ON_GCS=$(python3 -c "import json,sys; print(json.loads('''$(cat "$TMP_UPLOAD_LIST")''')['skip_count'])")
TO_UPLOAD=$(python3 -c "import json,sys; [print(e['fname']) for e in json.loads('''$(cat "$TMP_UPLOAD_LIST")''')['to_upload']]")

UPLOADED=0; ERRORS=0
while IFS= read -r fname; do
    [[ -z "$fname" ]] && continue
    if gcloud storage cp "$TEMPLATES_DIR/$fname" "${GCS_BUCKET}/${GCS_PREFIX}/${fname}" 2>&1; then
        ((UPLOADED++))
    else
        err "Failed to upload $fname"
        ((ERRORS++))
    fi
done <<< "$TO_UPLOAD"

# ── Step 4: Delete GCS-only files ────────────────────────────────────────────
DELETED=0
GCS_FILES=$(gcloud storage ls "${GCS_BUCKET}/${GCS_PREFIX}/" 2>/dev/null | grep '\.yaml$' | sed 's|.*/||' || true)
for gcs_fname in $GCS_FILES; do
    [[ "$gcs_fname" == "CHANGELOG.yaml" || "$gcs_fname" == "ORDER.yaml" ]] && continue
    if [[ ! -f "$TEMPLATES_DIR/$gcs_fname" ]]; then
        gcloud storage rm "${GCS_BUCKET}/${GCS_PREFIX}/${gcs_fname}" 2>/dev/null && ((DELETED++)) || true
    fi
done

# ── Step 5: Update remote manifest ───────────────────────────────────────────
python3 - "$TEMPLATES_DIR" "$TMP_MANIFEST" "$TMP_NEW_MANIFEST" <<'EOF'
import sys, json, yaml, os

templates_dir, manifest_path, out_path = sys.argv[1:]

with open(manifest_path) as f:
    manifest = json.load(f)

for fname in os.listdir(templates_dir):
    if not fname.endswith(".yaml") or fname in ("CHANGELOG.yaml", "ORDER.yaml"):
        continue
    try:
        with open(os.path.join(templates_dir, fname)) as f:
            data = yaml.safe_load(f) or {}
        date = data.get("_template", {}).get("updated_at", "") or ""
    except Exception:
        date = ""
    manifest[fname] = {"updated_at": date}

with open(out_path, "w") as f:
    json.dump(manifest, f, indent=2, sort_keys=True)
EOF
gcloud storage cp "$TMP_NEW_MANIFEST" "$GCS_MANIFEST" 2>/dev/null || true

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
log "✓ Uploaded: ${UPLOADED}  Skipped (GCS newer): ${NEWER_ON_GCS}  Deleted: ${DELETED}  Errors: ${ERRORS}"
[[ "$NEWER_ON_GCS" -gt 0 ]] && warn "  ${NEWER_ON_GCS} file(s) on GCS are newer — git pull or use --force"
[[ $ERRORS -gt 0 ]] && err "  ${ERRORS} upload(s) failed" && exit 1

REMOTE_COUNT=$(gcloud storage ls "${GCS_BUCKET}/${GCS_PREFIX}/" 2>/dev/null | grep -c '\.yaml$' || echo "0")
log "✓ ${REMOTE_COUNT} templates on GCS"
