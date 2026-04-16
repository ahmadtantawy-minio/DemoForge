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

# Human-readable schedule line for integration logs (Debug / Integrations UI)
_next_retry_detail() {
  _sec="$1"
  if command -v python3 >/dev/null 2>&1; then
    _na=$(python3 -c "import time; print(time.strftime('%H:%M:%S', time.localtime(time.time()+float('$_sec'))))" 2>/dev/null || echo "?")
    echo "next_retry_in_s=${_sec} next_retry_at_local=${_na}"
  else
    echo "next_retry_in_s=${_sec}"
  fi
}

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
HEALTH_SLEEP=5
for attempt in $(seq 1 20); do
  HEALTH=$(http_get_auth "$MB/api/health")
  if echo "$HEALTH" | jq -e '.status == "ok"' >/dev/null 2>&1; then
    echo "Metabase is healthy."
    log_integ "info" "metabase_setup" "Metabase /api/health ok" "attempt=$attempt/20"
    HEALTHY=1
    break
  fi
  echo "Metabase not ready yet (attempt $attempt/20)..."
  if [ "$attempt" -lt 20 ]; then
    log_integ "warn" "metabase_setup" "Metabase not healthy yet" "attempt=$attempt/20 $(_next_retry_detail "$HEALTH_SLEEP")"
    sleep "$HEALTH_SLEEP"
  else
    log_integ "warn" "metabase_setup" "Metabase /api/health not ok — giving up after final attempt" "attempt=$attempt/20"
  fi
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

log_integ "info" "metabase_setup" "First-run block complete — next: settle, admin login, Trino (if configured), DB + built-in dashboard seed" ""

# Session API can lag behind /api/health right after first-run — avoid failing the login loop too early.
echo "Waiting for session API to accept logins..."
log_integ "info" "metabase_setup" "Post-setup settle before login" "sleep=10s"
sleep 10

log_integ "info" "metabase_setup" "Starting admin API login (for Trino DB + dashboard injection)" ""

# --- Step 4: Login ---
echo "Logging in..."
SESSION=""
LOGIN_MAX=20
LOGIN_SLEEP=5
for attempt in $(seq 1 "$LOGIN_MAX"); do
  LOGIN=$(http_post "$MB/api/session" "{\"username\":\"admin@demoforge.local\",\"password\":\"DemoForge123!\"}")
  SESSION=$(echo "$LOGIN" | jq -r '.id // empty' 2>/dev/null || true)
  if [ -n "$SESSION" ] && [ "$SESSION" != "null" ]; then
    echo "Login successful."
    log_integ "info" "metabase_setup" "Admin login ok" "attempt=$attempt/$LOGIN_MAX"
    break
  fi
  echo "Login attempt $attempt/$LOGIN_MAX failed, retrying..."
  if [ "$attempt" -lt "$LOGIN_MAX" ]; then
    log_integ "warn" "metabase_setup" "Admin login not ready yet" "attempt=$attempt/$LOGIN_MAX $(_next_retry_detail "$LOGIN_SLEEP") body=$(echo "$LOGIN" | head -c 200)"
    sleep "$LOGIN_SLEEP"
  else
    log_integ "error" "metabase_setup" "Admin login failed after final attempt" "attempt=$attempt/$LOGIN_MAX body=$(echo "$LOGIN" | head -c 200)"
    echo "ERROR: Could not log in. Exiting."
    exit 1
  fi
done

log_integ "info" "metabase_setup" "Admin API session acquired — proceeding to Trino wait / database registration / dashboards" ""

# Trino→Metabase: TRINO_* is injected by compose from diagram edges (sql-query Trino→Metabase, catalog/schema on edge).
# Edge status in the UI = deploy automation; this log = actual values applied to Metabase /api/database.
if [ -n "${TRINO_HOST:-}" ]; then
  log_integ "info" "trino_metabase_seed" "Effective Trino data source for Metabase (compose / diagram edges)" "TRINO_HOST=${TRINO_HOST} TRINO_CATALOG=${TRINO_CATALOG:-iceberg} TRINO_SCHEMA=${TRINO_SCHEMA:-} metabase_engine=presto port=8080"
else
  log_integ "info" "trino_metabase_seed" "No Trino wiring for Metabase (TRINO_HOST empty — add Trino + sql-query edge to Metabase)" ""
fi

# --- Step 4b: Wait for Trino HTTP (compose ordering is not enough on slow cold start) ---
if [ -n "${TRINO_HOST:-}" ]; then
  echo "Waiting for Trino at http://${TRINO_HOST}:8080/v1/info ..."
  log_integ "info" "metabase_setup" "Waiting for Trino HTTP" "host=${TRINO_HOST}"
  TRINO_OK=0
  TRINO_SLEEP=3
  for attempt in $(seq 1 40); do
    if curl -sf "http://${TRINO_HOST}:8080/v1/info" >/dev/null 2>&1; then
      echo "Trino is reachable."
      log_integ "info" "metabase_setup" "Trino HTTP ok" "attempt=$attempt/40"
      TRINO_OK=1
      break
    fi
    echo "Trino not ready yet ($attempt/40)..."
    if [ "$attempt" -lt 40 ]; then
      log_integ "warn" "metabase_setup" "Trino HTTP not ready yet" "attempt=$attempt/40 $(_next_retry_detail "$TRINO_SLEEP") host=${TRINO_HOST}"
      sleep "$TRINO_SLEEP"
    else
      log_integ "warn" "metabase_setup" "Trino HTTP not reachable — final attempt" "attempt=$attempt/40 host=${TRINO_HOST}"
    fi
  done
  if [ "$TRINO_OK" = "0" ]; then
    log_integ "error" "metabase_setup" "Trino not reachable after wait" "host=${TRINO_HOST}"
    echo "ERROR: Trino did not become reachable. Cannot add database connection."
    exit 1
  fi
fi

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
  log_integ "info" "trino_metabase_seed" "Trino connection already present in Metabase (reuse, no new /api/database)" "db_id=$DB_ID catalog=${TRINO_CATALOG:-iceberg} host=${TRINO_HOST}"
elif [ -z "${TRINO_HOST:-}" ]; then
  log_integ "warn" "metabase_setup" "TRINO_HOST empty — no Trino in this demo; skipping DB and lakehouse seed" ""
  echo "WARNING: TRINO_HOST is not set; skipping Trino database and seed dashboard."
else
  echo "Adding Trino database connection (host: $TRINO_HOST, catalog: ${TRINO_CATALOG:-iceberg})..."
  log_integ "info" "metabase_setup" "POST /api/database — registering Trino with Metabase" "host=${TRINO_HOST} catalog=${TRINO_CATALOG:-iceberg}"
  log_integ "info" "trino_metabase_seed" "Applying Trino→Metabase connection via Metabase API" "engine=presto host=${TRINO_HOST} port=8080 catalog=${TRINO_CATALOG:-iceberg}"
  DB_BODY="{\"name\":\"Trino - MinIO Lakehouse\",\"engine\":\"presto\",\"details\":{\"host\":\"${TRINO_HOST}\",\"port\":8080,\"catalog\":\"${TRINO_CATALOG:-iceberg}\",\"schema-filters-type\":\"all\",\"user\":\"trino\",\"ssl\":false,\"tunnel-enabled\":false}}"
  DB_RESULT=$(http_post "$MB/api/database" "$DB_BODY" "X-Metabase-Session: $SESSION")
  if echo "$DB_RESULT" | jq -e '.id' >/dev/null 2>&1; then
    DB_ID=$(echo "$DB_RESULT" | jq -r '.id')
    echo "Trino database added (id: $DB_ID)."

    echo "Triggering schema sync..."
    http_post "$MB/api/database/$DB_ID/sync_schema" "{}" "X-Metabase-Session: $SESSION" >/dev/null 2>&1
    echo "Schema sync triggered."
    log_integ "info" "metabase_setup" "Trino DB added and sync triggered" "db_id=$DB_ID"
    log_integ "info" "trino_metabase_seed" "Trino registered in Metabase; schema sync triggered" "db_id=$DB_ID catalog=${TRINO_CATALOG:-iceberg} host=${TRINO_HOST}"
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
  log_integ "warn" "metabase_setup" "No DB_ID — skipping built-in seed dashboard" ""
  echo "WARNING: DB_ID not set, skipping dashboard creation."
else
  log_integ "info" "metabase_setup" "Starting built-in dashboard seed (Live Orders Analytics)" "db_id=$DB_ID"
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
    log_integ "info" "metabase_setup" "Creating Metabase dashboard shell + native questions (4 cards)" "wait_before_create_s=10"
    sleep 10

    DASH_RESULT=$(http_post "$MB/api/dashboard" '{"name":"Live Orders Analytics","description":"Real-time analytics on MinIO data via Trino"}' "X-Metabase-Session: $SESSION")
    if ! echo "$DASH_RESULT" | jq -e '.id' >/dev/null 2>&1; then
      log_integ "error" "metabase_setup" "Could not create seed dashboard" "$(echo "$DASH_RESULT" | head -c 500)"
      echo "ERROR: Could not create dashboard. Response: $DASH_RESULT"
      exit 1
    fi
    DASH_ID=$(echo "$DASH_RESULT" | jq -r '.id')
    echo "Dashboard created (id: $DASH_ID)."
    log_integ "info" "metabase_setup" "Seed dashboard shell created" "dash_id=$DASH_ID"

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
    log_integ "info" "metabase_setup" "Seed dashboard cards added to dashboard" "dash_id=$DASH_ID cards=${C1ID:-x},${C2ID:-x},${C3ID:-x},${C4ID:-x}"
  fi
fi

# --- Step 7: Pin demo dashboard as homepage (so it is obvious in the UI) ---
if [ -n "$DASH_ID" ] && [ "$DASH_ID" != "null" ]; then
  echo "Setting custom homepage to dashboard id $DASH_ID..."
  http_put_setting "custom-homepage" "{\"value\":true}" >/dev/null
  http_put_setting "custom-homepage-dashboard" "{\"value\":$DASH_ID}" >/dev/null
  log_integ "info" "metabase_setup" "Homepage pinned to seed dashboard" "dash_id=$DASH_ID"
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
