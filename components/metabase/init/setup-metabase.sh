#!/bin/sh
# Metabase auto-setup: creates admin user and adds Trino database connection
# Runs inside alpine:3.19 sidecar (has wget, grep, sed)

MB="http://${METABASE_HOST}:3000"

echo "Waiting 30 seconds for Metabase to initialize..."
sleep 30

# Helper: HTTP GET, returns body to stdout
http_get() {
  wget -q -O - --header="$2" "$1" 2>/dev/null
}

# Helper: HTTP POST with JSON body, returns body to stdout
http_post() {
  local url="$1" data="$2" extra_header="$3"
  if [ -n "$extra_header" ]; then
    wget -q -O - --header="Content-Type: application/json" --header="$extra_header" --post-data="$data" "$url" 2>/dev/null
  else
    wget -q -O - --header="Content-Type: application/json" --post-data="$data" "$url" 2>/dev/null
  fi
}

# --- Step 1: Wait for Metabase health ---
echo "Checking Metabase health..."
for attempt in $(seq 1 20); do
  HEALTH=$(http_get "$MB/api/health")
  if echo "$HEALTH" | grep -q '"status":"ok"'; then
    echo "Metabase is healthy."
    break
  fi
  echo "Metabase not ready yet (attempt $attempt/20)..."
  sleep 5
  if [ "$attempt" = "20" ]; then
    echo "ERROR: Metabase did not become healthy. Exiting."
    exit 1
  fi
done

# --- Step 2: Check if setup is already complete ---
echo "Checking setup status..."
PROPS=$(http_get "$MB/api/session/properties")
SETUP_TOKEN=$(echo "$PROPS" | grep -o '"setup-token":"[^"]*"' | sed 's/"setup-token":"//;s/"//')

if [ -z "$SETUP_TOKEN" ]; then
  echo "Setup already complete. Skipping first-run."
else
  # --- Step 3: Complete first-run setup ---
  echo "Running first-run setup..."
  SETUP_BODY="{\"token\":\"${SETUP_TOKEN}\",\"user\":{\"email\":\"admin@demoforge.local\",\"password\":\"DemoForge123!\",\"first_name\":\"Demo\",\"last_name\":\"Admin\",\"site_name\":\"DemoForge Analytics\"},\"prefs\":{\"site_name\":\"DemoForge Analytics\",\"allow_tracking\":false}}"
  RESULT=$(http_post "$MB/api/setup" "$SETUP_BODY")
  if echo "$RESULT" | grep -q '"id"'; then
    echo "First-run setup completed."
  else
    echo "WARNING: Setup may have failed or was already done."
  fi
fi

# --- Step 4: Login ---
echo "Logging in..."
for attempt in $(seq 1 5); do
  LOGIN=$(http_post "$MB/api/session" "{\"username\":\"admin@demoforge.local\",\"password\":\"DemoForge123!\"}")
  SESSION=$(echo "$LOGIN" | grep -o '"id":"[^"]*"' | head -1 | sed 's/"id":"//;s/"//')
  if [ -n "$SESSION" ]; then
    echo "Login successful."
    break
  fi
  echo "Login attempt $attempt/5 failed, retrying..."
  sleep 5
  if [ "$attempt" = "5" ]; then
    echo "ERROR: Could not log in. Exiting."
    exit 1
  fi
done

# --- Step 5: Add Trino database ---
echo "Checking for existing Trino connection..."
DB_LIST=$(http_get "$MB/api/database" "X-Metabase-Session: $SESSION")

if echo "$DB_LIST" | grep -q "Trino"; then
  echo "Trino connection already exists."
else
  echo "Adding Trino database connection (host: $TRINO_HOST, catalog: ${TRINO_CATALOG:-iceberg})..."
  DB_BODY="{\"name\":\"Trino - MinIO Lakehouse\",\"engine\":\"starburst\",\"details\":{\"host\":\"${TRINO_HOST}\",\"port\":8080,\"catalog\":\"${TRINO_CATALOG:-iceberg}\",\"schema\":\"${TRINO_SCHEMA:-analytics}\",\"user\":\"trino\",\"ssl\":false,\"tunnel-enabled\":false}}"
  DB_RESULT=$(http_post "$MB/api/database" "$DB_BODY" "X-Metabase-Session: $SESSION")
  if echo "$DB_RESULT" | grep -q '"id"'; then
    DB_ID=$(echo "$DB_RESULT" | grep -o '"id":[0-9]*' | head -1 | sed 's/"id"://')
    echo "Trino database added (id: $DB_ID)."

    # Trigger sync
    echo "Triggering schema sync..."
    http_post "$MB/api/database/$DB_ID/sync_schema" "{}" "X-Metabase-Session: $SESSION" > /dev/null 2>&1
    echo "Schema sync triggered."
  else
    echo "WARNING: Failed to add Trino database."
  fi
fi

# --- Step 7: Mark onboarding as complete ---
echo "Marking onboarding as complete..."
# Set site name and suppress welcome modals
http_post "$MB/api/setting/site-name" "{\"value\":\"DemoForge Analytics\"}" "X-Metabase-Session: $SESSION" > /dev/null 2>&1
http_post "$MB/api/setting/setup-license-active-at-setup" "{\"value\":true}" "X-Metabase-Session: $SESSION" > /dev/null 2>&1
http_post "$MB/api/setting/show-database-syncing-modal" "{\"value\":false}" "X-Metabase-Session: $SESSION" > /dev/null 2>&1

echo "Metabase setup complete. Login: admin@demoforge.local / DemoForge123!"
