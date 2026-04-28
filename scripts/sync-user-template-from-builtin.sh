#!/usr/bin/env bash
# Copy demo-templates/<template_id>.yaml → user-templates/<template_id>.yaml
# Hub loads user templates before builtins (see backend/app/api/templates.py).
# Usage: ./scripts/sync-user-template-from-builtin.sh experience-stx-inference
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ID="${1:?usage: $0 <template-id>   example: $0 experience-stx-inference}"
SRC="$ROOT/demo-templates/${ID}.yaml"
DST="$ROOT/user-templates/${ID}.yaml"
if [[ ! -f "$SRC" ]]; then
  echo "error: missing builtin template: $SRC" >&2
  exit 1
fi
mkdir -p "$ROOT/user-templates"
cp "$SRC" "$DST"
echo "Updated $DST from builtin. Restart hub-api (or refresh templates) if it is already running."
