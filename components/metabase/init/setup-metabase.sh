#!/bin/sh
set -eu
# Metabase auto-setup: creates admin user, Trino DB, pre-seeded dashboard, suppresses onboarding UI.
# Sidecar: alpine:3.19 or python:3.11-alpine — install curl+jq for correct PUT /api/setting and JSON parsing.

MB="http://${METABASE_HOST}:3000"

echo "Installing curl and jq for Metabase API (PUT settings, JSON parse)..."
apk add --no-cache curl jq >/dev/null 2>&1 || true
if ! command -v curl >/dev/null 2>&1 || ! command -v jq >/dev/null 2>&1; then
  echo "ERROR: curl and jq are required. apk add failed."
  exit 1
fi

# Offline JSONL for Integrations UI (backend tails /tmp/demoforge_integration.jsonl in metabase-init)
INTEG_LOG="${METABASE_INTEGRATION_LOG:-/tmp/demoforge_integration.jsonl}"
log_integ() {
  _lvl="$1"
  _kind="$2"
  _msg="$3"
  _det="${4:-}"
  _ts=$(( $(date +%s) * 1000 ))
  _id="mbs-$(date +%s)-$$"
  jq -nc \
    --arg id "$_id" \
    --argjson ts_ms "$_ts" \
    --arg level "$_lvl" \
    --arg kind "$_kind" \
    --arg message "$_msg" \
    --arg details "$_det" \
    --arg node_id "${INTEGRATION_NODE_ID:-metabase-init}" \
    --arg source "metabase-init" \
    '{id: $id, ts_ms: $ts_ms, level: $level, kind: $kind, message: $message, details: $details, node_id: $node_id, source: $source}' \
    >> "$INTEG_LOG" 2>/dev/null || true
}

log_integ "info" "metabase_setup" "setup-metabase.sh started" "mb=${METABASE_HOST:-} trino=${TRINO_HOST:-}"

# GET with optional session header: http_get_auth URL "X-Metabase-Session: sid"
http_get_auth() {
  if [ -n "${2:-}" ]; then
    curl -sS -H "Content-Type: application/json" -H "$2" "$1" 2>/dev/null || true
  else
    curl -sS -H "Content-Type: application/json" "$1" 2>/dev/null || true
  fi
}

http_post() {
  _url="$1"
  _data="$2"
  _hdr="${3-}"
  if [ -n "$_hdr" ]; then
    curl -sS -X POST -H "Content-Type: application/json" -H "$_hdr" --data "$_data" "$_url" 2>/dev/null || true
  else
    curl -sS -X POST -H "Content-Type: application/json" --data "$_data" "$_url" 2>/dev/null || true
  fi
}

# Metabase expects PUT /api/setting/:key with body {"value": ...} (POST is ignored / wrong)
http_put_setting() {
  curl -sS -o /dev/null -w "%{http_code}" -X PUT -H "Content-Type: application/json" -H "X-Metabase-Session: $SESSION" \
    --data "$2" "$MB/api/setting/$1" 2>/dev/null || echo "000"
}

echo "Waiting for Metabase JVM (initial pause)..."
log_integ "info" "metabase_setup" "Waiting before health checks" "sleep=15s"
sleep 15

# --- Step 1: Wait for Metabase health ---
echo "Checking Metabase health..."
HEALTHY=0
for attempt in $(seq 1 20); do
  HEALTH=$(http_get_auth "$MB/api/health")
  if echo "$HEALTH" | jq -e '.status == "ok"' >/dev/null 2>&1; then
    echo "Metabase is healthy."
    log_integ "info" "metabase_setup" "Metabase /api/health ok" "attempt=$attempt"
    HEALTHY=1
    break
  fi
  echo "Metabase not ready yet (attempt $attempt/20)..."
  if [ "$attempt" -eq 1 ] || [ "$attempt" -eq 5 ] || [ "$attempt" -eq 10 ] || [ "$attempt" -eq 15 ]; then
    log_integ "warn" "metabase_setup" "Metabase not healthy yet" "attempt=$attempt/20"
  fi
  sleep 5
done
if [ "$HEALTHY" = "0" ]; then
  log_integ "error" "metabase_setup" "Metabase health check failed" "attempts=20"
  echo "ERROR: Metabase did not become healthy after 20 attempts. Exiting."
  exit 1
fi

# --- Step 2: Check if setup is already complete ---
echo "Checking setup status..."
PROPS=$(http_get_auth "$MB/api/session/properties")
SETUP_TOKEN=$(echo "$PROPS" | jq -r '."setup-token" // empty' 2>/dev/null || true)

if [ -z "$SETUP_TOKEN" ] || [ "$SETUP_TOKEN" = "null" ]; then
  echo "Setup already complete. Skipping first-run."
  log_integ "info" "metabase_setup" "First-run setup already done" ""
else
  # --- Step 3: Complete first-run setup ---
  echo "Running first-run setup..."
  log_integ "info" "metabase_setup" "Running Metabase first-run setup" ""
  SETUP_BODY="{\"token\":\"${SETUP_TOKEN}\",\"user\":{\"email\":\"admin@demoforge.local\",\"password\":\"DemoForge123!\",\"first_name\":\"Demo\",\"last_name\":\"Admin\",\"site_name\":\"DemoForge Analytics\"},\"prefs\":{\"site_name\":\"DemoForge Analytics\",\"allow_tracking\":false}}"
  RESULT=$(http_post "$MB/api/setup" "$SETUP_BODY")
  if echo "$RESULT" | jq -e '.id' >/dev/null 2>&1; then
    echo "First-run setup completed."
    log_integ "info" "metabase_setup" "First-run setup API returned session" ""
  else
    log_integ "warn" "metabase_setup" "First-run setup uncertain" "$(echo "$RESULT" | head -c 400)"
    echo "WARNING: Setup may have failed or was already done. Response: $(echo "$RESULT" | head -c 400)"
  fi
fi

# --- Step 4: Login ---
echo "Logging in..."
SESSION=""
for attempt in $(seq 1 5); do
  LOGIN=$(http_post "$MB/api/session" "{\"username\":\"admin@demoforge.local\",\"password\":\"DemoForge123!\"}")
  SESSION=$(echo "$LOGIN" | jq -r '.id // empty' 2>/dev/null || true)
  if [ -n "$SESSION" ] && [ "$SESSION" != "null" ]; then
    echo "Login successful."
    log_integ "info" "metabase_setup" "Admin login ok" "attempt=$attempt"
    break
  fi
  echo "Login attempt $attempt/5 failed, retrying..."
  sleep 5
  if [ "$attempt" = "5" ]; then
    log_integ "error" "metabase_setup" "Admin login failed" "attempts=5"
    echo "ERROR: Could not log in. Exiting."
    exit 1
  fi
done

# --- Step 5: Add Trino database ---
echo "Checking for existing Trino connection..."
DB_LIST=$(http_get_auth "$MB/api/database" "X-Metabase-Session: $SESSION")

DB_ID=$(echo "$DB_LIST" | jq -r '
  (if type == "array" then . elif .data then .data else [] end)
  | map(select(.name | type == "string" and (test("trino|presto"; "i"))))
  | .[0].id // empty
' 2>/dev/null || true)

if [ -n "$DB_ID" ] && [ "$DB_ID" != "null" ]; then
  echo "Trino connection already exists. DB id: $DB_ID"
  log_integ "info" "metabase_setup" "Trino DB already in Metabase" "db_id=$DB_ID"
else
  echo "Adding Trino database connection (host: $TRINO_HOST, catalog: ${TRINO_CATALOG:-iceberg})..."
  log_integ "info" "metabase_setup" "Adding Trino connection" "host=${TRINO_HOST} catalog=${TRINO_CATALOG:-iceberg}"
  DB_BODY="{\"name\":\"Trino - MinIO Lakehouse\",\"engine\":\"presto\",\"details\":{\"host\":\"${TRINO_HOST}\",\"port\":8080,\"catalog\":\"${TRINO_CATALOG:-iceberg}\",\"schema-filters-type\":\"all\",\"user\":\"trino\",\"ssl\":false,\"tunnel-enabled\":false}}"
  DB_RESULT=$(http_post "$MB/api/database" "$DB_BODY" "X-Metabase-Session: $SESSION")
  if echo "$DB_RESULT" | jq -e '.id' >/dev/null 2>&1; then
    DB_ID=$(echo "$DB_RESULT" | jq -r '.id')
    echo "Trino database added (id: $DB_ID)."

    echo "Triggering schema sync..."
    http_post "$MB/api/database/$DB_ID/sync_schema" "{}" "X-Metabase-Session: $SESSION" >/dev/null 2>&1
    echo "Schema sync triggered."
    log_integ "info" "metabase_setup" "Trino DB added and sync triggered" "db_id=$DB_ID"
  else
    log_integ "error" "metabase_setup" "Failed to add Trino database" "$(echo "$DB_RESULT" | head -c 500)"
    echo "ERROR: Failed to add Trino database. Response: $DB_RESULT"
    exit 1
  fi
fi

# --- Step 6: Create pre-seeded dashboard ---
echo "Creating pre-seeded dashboard..."
DASH_ID=""

if [ -z "$DB_ID" ] || [ "$DB_ID" = "null" ]; then
  log_integ "warn" "metabase_setup" "No DB_ID — skipping seed dashboard" ""
  echo "WARNING: DB_ID not set, skipping dashboard creation."
else
  DASH_LIST=$(http_get_auth "$MB/api/dashboard" "X-Metabase-Session: $SESSION")
  DASH_ID=$(echo "$DASH_LIST" | jq -r '
    (if type == "array" then . elif .data then .data else [] end)
    | map(select(.name == "Live Orders Analytics"))
    | .[0].id // empty
  ' 2>/dev/null || true)

  if [ -n "$DASH_ID" ] && [ "$DASH_ID" != "null" ]; then
    echo "Dashboard 'Live Orders Analytics' already exists (id: $DASH_ID). Skipping card creation."
    log_integ "info" "metabase_setup" "Seed dashboard already exists" "dash_id=$DASH_ID"
  else
    sleep 10

    DASH_RESULT=$(http_post "$MB/api/dashboard" '{"name":"Live Orders Analytics","description":"Real-time analytics on MinIO data via Trino"}' "X-Metabase-Session: $SESSION")
    if ! echo "$DASH_RESULT" | jq -e '.id' >/dev/null 2>&1; then
      log_integ "error" "metabase_setup" "Could not create seed dashboard" "$(echo "$DASH_RESULT" | head -c 500)"
      echo "ERROR: Could not create dashboard. Response: $DASH_RESULT"
      exit 1
    fi
    DASH_ID=$(echo "$DASH_RESULT" | jq -r '.id')
    echo "Dashboard created (id: $DASH_ID)."

    CARD1=$(http_post "$MB/api/card" "{\"name\":\"Table Count\",\"display\":\"scalar\",\"visualization_settings\":{},\"dataset_query\":{\"type\":\"native\",\"native\":{\"query\":\"SELECT count(*) AS table_count FROM system.information_schema.tables WHERE table_schema != 'information_schema'\"},\"database\":$DB_ID}}" "X-Metabase-Session: $SESSION")
    C1ID=$(echo "$CARD1" | jq -r '.id // empty')

    CARD2=$(http_post "$MB/api/card" "{\"name\":\"Tables by Schema\",\"display\":\"bar\",\"visualization_settings\":{},\"dataset_query\":{\"type\":\"native\",\"native\":{\"query\":\"SELECT table_schema, count(*) AS tables FROM system.information_schema.tables GROUP BY table_schema ORDER BY tables DESC\"},\"database\":$DB_ID}}" "X-Metabase-Session: $SESSION")
    C2ID=$(echo "$CARD2" | jq -r '.id // empty')

    CARD3=$(http_post "$MB/api/card" "{\"name\":\"All Tables\",\"display\":\"table\",\"visualization_settings\":{},\"dataset_query\":{\"type\":\"native\",\"native\":{\"query\":\"SELECT table_catalog, table_schema, table_name FROM system.information_schema.tables WHERE table_schema != 'information_schema' ORDER BY table_schema, table_name\"},\"database\":$DB_ID}}" "X-Metabase-Session: $SESSION")
    C3ID=$(echo "$CARD3" | jq -r '.id // empty')

    CARD4=$(http_post "$MB/api/card" "{\"name\":\"Trino Version\",\"display\":\"scalar\",\"visualization_settings\":{},\"dataset_query\":{\"type\":\"native\",\"native\":{\"query\":\"SELECT node_version FROM system.runtime.nodes LIMIT 1\"},\"database\":$DB_ID}}" "X-Metabase-Session: $SESSION")
    C4ID=$(echo "$CARD4" | jq -r '.id // empty')

    for CID in $C1ID $C2ID $C3ID $C4ID; do
      if [ -n "$CID" ] && [ "$CID" != "null" ]; then
        http_post "$MB/api/dashboard/$DASH_ID/cards" "{\"cardId\":$CID}" "X-Metabase-Session: $SESSION" >/dev/null 2>&1
      fi
    done
    echo "Dashboard cards created and added."
    log_integ "info" "metabase_setup" "Seed dashboard and cards ready" "dash_id=$DASH_ID"
  fi
fi

# --- Step 7: Pin demo dashboard as homepage (so it is obvious in the UI) ---
if [ -n "$DASH_ID" ] && [ "$DASH_ID" != "null" ]; then
  echo "Setting custom homepage to dashboard id $DASH_ID..."
  http_put_setting "custom-homepage" "{\"value\":true}" >/dev/null
  http_put_setting "custom-homepage-dashboard" "{\"value\":$DASH_ID}" >/dev/null
fi

# --- Step 8: Mark onboarding / modals suppressed (PUT required by Metabase API) ---
echo "Applying settings to skip onboarding modals and product tips..."
http_put_setting "site-name" "{\"value\":\"DemoForge Analytics\"}" >/dev/null
http_put_setting "setup-license-active-at-setup" "{\"value\":true}" >/dev/null
http_put_setting "show-database-syncing-modal" "{\"value\":false}" >/dev/null
http_put_setting "show-homepage-xrays" "{\"value\":false}" >/dev/null
http_put_setting "show-homepage-pin-message" "{\"value\":false}" >/dev/null
http_put_setting "show-homepage-data" "{\"value\":true}" >/dev/null
http_put_setting "embedding-homepage" "{\"value\":\"hidden\"}" >/dev/null
http_put_setting "check-for-updates" "{\"value\":false}" >/dev/null
http_put_setting "anon-tracking-enabled" "{\"value\":false}" >/dev/null

log_integ "info" "metabase_setup" "Metabase setup script finished" "homepage_dash=${DASH_ID:-none}"
echo "Metabase setup complete. Login: admin@demoforge.local / DemoForge123!"
