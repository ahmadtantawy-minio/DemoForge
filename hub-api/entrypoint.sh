#!/bin/sh
set -e

DB_PATH="${HUB_API_DATABASE_PATH:-/data/hub-api/demoforge-hub.db}"
mkdir -p "$(dirname "$DB_PATH")"

if [ ! -f "$DB_PATH" ]; then
  echo "[entrypoint] No local DB found. Attempting Litestream restore from gs://${LITESTREAM_BUCKET}..."
  if litestream restore -if-replica-exists -config /etc/litestream.yml "$DB_PATH"; then
    if [ -f "$DB_PATH" ]; then
      echo "[entrypoint] Restore complete."
    else
      echo "[entrypoint] No replica found in GCS — starting with a fresh DB (first boot)."
    fi
  else
    echo "[entrypoint] Restore failed." >&2
    exit 1
  fi
else
  echo "[entrypoint] Existing DB found at ${DB_PATH} — skipping restore."
fi

echo "[entrypoint] Starting hub-api under Litestream replication..."
exec litestream replicate -config /etc/litestream.yml \
  -exec "uvicorn hub_api.main:app --host 0.0.0.0 --port 8000 --log-level info"
