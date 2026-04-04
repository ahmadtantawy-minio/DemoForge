#!/bin/bash
set -e

echo "[superset-init] Initializing Superset database..."
superset db upgrade

echo "[superset-init] Creating admin user..."
superset fab create-admin \
  --username admin \
  --firstname DemoForge \
  --lastname Admin \
  --email admin@demoforge.local \
  --password admin \
  2>/dev/null || true

echo "[superset-init] Initializing roles and permissions..."
superset init

echo "[superset-init] Starting Superset server..."
exec superset run \
  --host 0.0.0.0 \
  --port 8088 \
  --with-threads \
  --reload
