# Test Plan: Analytics Enrichment

## Overview

This plan covers the four new analytics templates and their supporting components:
`streaming-lakehouse`, `dremio-lakehouse`, `versioned-data-lake`, and `complete-analytics`.
New components under test: Dremio, Redpanda, Redpanda Console, Kafka Connect S3, and Nessie.
New edge types under test: `kafka`, `schema-registry`, `dremio-sql`, `kafka-connect`, plus
`iceberg-catalog`, `structured-data`, and `metrics` introduced by these templates.

---

## Prerequisites

### System Resources

| Template | Memory | CPU | Containers |
|---|---|---|---|
| Versioned Data Lake | 5 GB | 5 | 5 |
| Dremio Lakehouse | 6 GB | 6 | 6 |
| Real-time Streaming Lakehouse | 6 GB | 7 | 7 |
| Complete Analytics Platform | 10 GB | 11 | 11 |

Minimum host machine requirement for running all templates sequentially: 10 GB RAM available
to Docker. Confirm with `docker info | grep -i memory` before beginning.

### Ports Required (host-mapped)

The following container ports must be free on the host before each test run:

- `9047` — Dremio web console
- `31010` — Dremio JDBC/ODBC client
- `32010` — Dremio Arrow Flight
- `9092` / `19092` — Redpanda Kafka broker (internal/external)
- `8081` / `18081` — Redpanda Schema Registry
- `8082` / `18082` — Redpanda Pandaproxy
- `9644` — Redpanda admin API
- `8080` — Redpanda Console web UI
- `8083` — Kafka Connect REST API
- `19120` — Nessie REST API

### Build Requirements

- `demoforge/kafka-connect-s3:latest` Docker image must be built locally before testing
  (`build_context: "."` is set in the manifest — no published image exists). Confirm with
  `docker image inspect demoforge/kafka-connect-s3:latest`.
- All other component images pull from public registries; pre-pull on slow connections:
  - `docker.redpanda.com/redpandadata/redpanda:latest`
  - `docker.redpanda.com/redpandadata/console:latest`
  - `dremio/dremio-oss:latest`
  - `ghcr.io/projectnessie/nessie:latest`

### Application State

- DemoForge backend running at `http://localhost:8000`
- DemoForge frontend running at `http://localhost:3000`
- No leftover containers from a previous test run (verify with `docker ps -a`)

---

## Test Suite 1: Component Health

Run each component in isolation (standalone deploy via the canvas, single-node diagram).
All health checks poll the endpoint defined in the manifest until the container reports
healthy or the timeout is exceeded.

### 1.1 Dremio

**Deploy:** Single `dremio` node, `default` variant.

**Health check:**
- Endpoint: `GET /apiv2/server_status` on port `9047`
- Start period: 90 seconds (Dremio JVM startup — do not fail before this window)
- Poll interval: 30 seconds, timeout per request: 15 seconds
- Expected response: HTTP 200 with body containing `"status":"OK"`

**Web UI:**
- Navigate to `http://localhost:<host_port>` (DemoForge-assigned port for container 9047)
- Expected: Dremio login page loads; title contains "Dremio"
- First-run setup wizard appears; username/password form is present

**Terminal quick actions (via DemoForge terminal panel):**
- "Check server status" → `curl -s http://localhost:9047/apiv2/server_status`
  - Expected output: JSON with `"status":"OK"`
- "Tail server logs" → `tail -f /opt/dremio/log/server.log`
  - Expected: log stream begins, no `ERROR` or `FATAL` lines in the first 30 lines

**Teardown:** Remove the single-node demo before proceeding.

---

### 1.2 Redpanda

**Deploy:** Single `redpanda` node, `default` variant.

**Health check:**
- Endpoint: `GET /v1/status/ready` on port `9644` (admin API)
- Poll interval: 10 seconds, timeout: 5 seconds
- Expected response: HTTP 200

**No web UI** (Redpanda has no built-in UI; that is Redpanda Console's role).

**Terminal quick actions:**
- "rpk topic list" → `rpk topic list`
  - Expected: command exits 0; output may be empty (no topics yet) or list headers
- "rpk cluster info" → `rpk cluster info`
  - Expected: cluster info block showing node ID 0, broker `redpanda:9092`
- "Create topic" → `rpk topic create demo-topic --partitions 3 --replicas 1`
  - Expected: `Created topic "demo-topic"`
- "rpk topic describe demo-topic" → `rpk topic describe demo-topic`
  - Expected: partition summary showing 3 partitions, leader assigned

**Teardown:** Remove before proceeding.

---

### 1.3 Redpanda Console

**Deploy:** Two-node diagram — `redpanda` + `redpanda-console`, connected via a `kafka` edge.

**Health check:**
- Endpoint: `GET /api/health` on port `8080`
- Poll interval: 10 seconds, timeout: 5 seconds
- Expected response: HTTP 200

**Web UI:**
- Navigate to `http://localhost:<host_port>` (DemoForge-assigned port for container 8080)
- Expected: Redpanda Console dashboard loads; sidebar shows "Topics", "Consumer Groups",
  "Schema Registry", "Brokers"
- Topics page: at minimum shows the Kafka internal topics or an empty state message

**Terminal quick actions:**
- "Check health" → `wget -qO- http://localhost:8080/api/health`
  - Expected: JSON response with a status field indicating healthy

**Environment variables injected by edge resolution (verify in container env):**
- `KAFKA_BROKERS` must be set to `redpanda:9092`
- `KAFKA_SCHEMAREGISTRY_URLS` must be set to `http://redpanda:8081`

**Teardown:** Remove before proceeding.

---

### 1.4 Kafka Connect S3

**Deploy:** Two-node diagram — `redpanda` + `kafka-connect-s3`, connected via a `kafka` edge.

**Health check:**
- Endpoint: `GET /connectors` on port `8083`
- Poll interval: 15 seconds, timeout: 10 seconds
- Expected response: HTTP 200, body is a JSON array (empty `[]` is valid at startup)

**No web UI** (API-only component).

**Terminal quick actions:**
- "List connectors" → `curl -s http://localhost:8083/connectors | jq .`
  - Expected: `[]` (no connectors registered yet)
- "List plugins" → `curl -s http://localhost:8083/connector-plugins | jq .[].class`
  - Expected: output includes `"io.aiven.kafka.connect.s3.AivenKafkaConnectS3SinkConnector"`
    (or equivalent Aiven S3 sink class name)
- "Connector status" → `curl -s http://localhost:8083/connectors/s3-sink/status | jq .`
  - Expected: message `"No s3-sink connector deployed"` (connector not yet registered)

**Environment variable injected by edge resolution (verify in container env):**
- `CONNECT_BOOTSTRAP_SERVERS` must be set to `redpanda:9092`

**Teardown:** Remove before proceeding.

---

### 1.5 Nessie

**Deploy:** Single `nessie` node, `default` variant.

**Health check:**
- Endpoint: `GET /api/v2/config` on port `19120`
- Poll interval: 10 seconds, timeout: 5 seconds
- Expected response: HTTP 200 with JSON body containing `"defaultBranch":"main"`

**No web UI** (API-only component in this manifest).

**Terminal quick actions:**
- "List branches" → `wget -qO- http://localhost:19120/api/v2/trees | grep -o '"name":"[^"]*"'`
  - Expected: output contains `"name":"main"`
- "Get default branch" → `wget -qO- http://localhost:19120/api/v2/trees/main`
  - Expected: JSON response with `"name":"main"` and a `"hash"` field
- "Check config" → `wget -qO- http://localhost:19120/api/v2/config`
  - Expected: JSON with `"defaultBranch":"main"` and `"specVersion"` field

**Teardown:** Remove before proceeding.

---

## Test Suite 2: Edge Resolution

For each edge type, build a minimal two-node diagram, deploy it, then verify that environment
variables are injected correctly into both containers and that the connection is functional.

### 2.1 Edge Type: `kafka`

**Diagram:** `redpanda` (source) ← `kafka` edge → `redpanda-console` (target)

**Expected env vars in `redpanda-console` container:**
- `KAFKA_BROKERS=redpanda:9092`
- `KAFKA_SCHEMAREGISTRY_URLS=http://redpanda:8081`

**Connectivity check:**
- Open Redpanda Console UI at port 8080
- Navigate to "Topics" — page loads without a "connection failed" error banner
- Open Redpanda terminal → `rpk topic create edge-test --partitions 1 --replicas 1`
- Refresh Redpanda Console Topics page — `edge-test` topic appears in the list

**Edge label shown in UI:** "Manage" or "Produce events" (depends on template usage)

---

### 2.2 Edge Type: `schema-registry`

**Diagram:** `redpanda` (source, provides `schema-registry` on port 8081) ← `schema-registry` edge → `redpanda-console` (target)

**Expected env var in `redpanda-console` container:**
- `KAFKA_SCHEMAREGISTRY_URLS=http://redpanda:8081`
- `KAFKA_SCHEMAREGISTRY_ENABLED=true`

**Connectivity check:**
- Hit schema registry directly: `curl -s http://redpanda:8081/subjects`
  - Expected: `[]` (no schemas registered yet)
- In Redpanda Console UI, navigate to "Schema Registry" tab — page loads without error

---

### 2.3 Edge Type: `dremio-sql`

**Diagram:** `dremio` (source, provides `dremio-sql` on port 31010) ← `dremio-sql` edge → `metabase` (target)

**Expected env vars in `metabase` container:**
- `MB_DREMIO_HOST=dremio`
- `MB_DREMIO_PORT=31010` (or equivalent Dremio JDBC config injected by auto_configure)

**Connectivity check (after Dremio is healthy, ~90s):**
- Open Metabase UI, navigate to Admin → Databases
- A Dremio database entry should be present (auto-configured)
- Run a test connection — expected: "Successfully connected"

**Edge label shown in UI:** "Dremio SQL"

---

### 2.4 Edge Type: `kafka-connect`

**Diagram:** `kafka-connect-s3` (source, provides `kafka-connect` on port 8083) — represents the REST API endpoint provided to orchestrating services.

**Minimal test:** Deploy `kafka-connect-s3` + `redpanda` with a `kafka` edge (kafka-connect accepts `kafka`). Verify `CONNECT_BOOTSTRAP_SERVERS` is set to `redpanda:9092` in the Kafka Connect container.

**Additional edge types observed in templates (not in user-specified list but present):**

- `structured-data` (data-generator → minio): injected env should include `AWS_S3_BUCKET`
  pointing to the configured `target_bucket`
- `iceberg-catalog` (dremio/trino → iceberg-rest or nessie): injected env should include
  the catalog URI (e.g. `NESSIE_URI=http://nessie-1:19120/api/v1`)
- `s3` (kafka-connect/trino/dremio → minio): `AWS_ENDPOINT_URL`, `AWS_ACCESS_KEY_ID`,
  `AWS_SECRET_ACCESS_KEY` injected into the consuming container
- `metrics` (minio → prometheus): Prometheus scrape target config injected with MinIO
  metrics endpoint

---

## Test Suite 3: Kafka Producer Mode

Tests the data generator running with `DG_FORMAT=kafka` and `DG_SCENARIO=clickstream`.

### 3.1 Setup

Deploy a two-node diagram: `data-generator` + `redpanda`, connected via a `kafka` edge
with `connection_config.topic=clickstream`.

Required environment variables on the `data-generator` container (verify before starting):
- `DG_FORMAT=kafka`
- `DG_SCENARIO=clickstream`
- `KAFKA_BOOTSTRAP_SERVERS=redpanda:9092`  (injected by edge auto_configure)
- `KAFKA_TOPIC=clickstream`  (injected from edge connection_config.topic)

### 3.2 Topic Auto-Creation

Before starting generation, confirm the `clickstream` topic does not yet exist:
```
rpk topic list   # should show no clickstream topic
```

Start the data generator (right-click → "Start Generating" in DemoForge UI).

Within 10 seconds, verify topic creation:
```
rpk topic list
```
Expected: `clickstream` appears in the topic list with 1 partition, replication factor 1.

The `KafkaWriter._ensure_topic()` method creates the topic via `KafkaAdminClient`. If the
topic already exists, `TopicAlreadyExistsError` is silently swallowed — no error logged.

### 3.3 Message Production

After 30 seconds of generation, check message count:
```
rpk topic describe clickstream
```
Expected: `High Watermark` is greater than 0.

Consume a sample of messages to verify schema:
```
rpk topic consume clickstream --num 5 --format json
```

### 3.4 Message Schema Verification

Each Kafka message must be a JSON object with exactly these 10 keys (from clickstream.yaml):

| Field | Type | Expected values/range |
|---|---|---|
| `event_id` | string (UUID) | UUID v4 format |
| `event_ts` | string (ISO 8601) | timestamp within ~5 minutes of now |
| `session_id` | string | pattern `sess-NNNNNN`, range 000001–005000 |
| `user_id` | string | pattern `user-NNNN`, range 0001–0500 |
| `page_url` | string | one of 9 values (`/`, `/products`, `/products/detail`, `/cart`, `/checkout`, `/search`, `/account`, `/about`, `/blog`) |
| `event_type` | string | one of: `page_view`, `click`, `scroll`, `add_to_cart`, `purchase`, `search` |
| `referrer` | string | one of: `direct`, `google`, `social`, `email`, `paid_ad`, `affiliate` |
| `device_type` | string | one of: `mobile`, `desktop`, `tablet` |
| `country` | string | one of: `US`, `UK`, `DE`, `FR`, `JP`, `IN`, `BR`, `CA`, `AU`, `Other` |
| `duration_sec` | integer | range 1–600 (lognormal distribution) |

No additional keys should be present. The `_serialize_value` function converts `datetime`
objects to ISO 8601 strings, so `event_ts` must be a string in the message, not a numeric
epoch.

### 3.5 Volume Profile

At the default volume profile (200 rows/batch, 30 batches/minute):
- Expected throughput: ~6,000 messages/minute
- After 1 minute, `rpk topic describe clickstream` High Watermark should be >= 5,000
  (allowing for the 10-second ramp-up period)

---

## Test Suite 4: Template Deployments (Playwright MCP)

Each sub-suite follows this base flow before component-specific steps:
1. Navigate to the DemoForge UI
2. Open the Template Gallery
3. Select the target template
4. Create the demo
5. Deploy and wait for all nodes to go green
6. Run component-specific verification steps

### 4.1 Real-time Streaming Lakehouse

**Expected nodes (7):** Data Generator, Redpanda, Redpanda Console, Kafka Connect S3, MinIO, Trino, Metabase

**Expected edges (6) with labels:**
- Data Generator → Redpanda: "Produce events"
- Redpanda Console → Redpanda: "Manage"
- Kafka Connect S3 → Redpanda: "Consume"
- Kafka Connect S3 → MinIO: "S3 Sink"
- Trino → MinIO: "S3 query"
- Metabase → Trino: "SQL"

**Playwright MCP steps:**

```
browser_navigate → http://localhost:3000

browser_snapshot
  Verify: Page title or heading contains "DemoForge"
  Verify: "Template Gallery" button or nav item is visible

browser_click → ref: "Template Gallery" button

browser_snapshot
  Verify: Gallery panel/modal is open
  Verify: Card with title "Real-time Streaming Lakehouse" is visible
  Verify: Card shows tags including "streaming", "redpanda"

browser_click → ref: "Real-time Streaming Lakehouse" card

browser_snapshot
  Verify: Template detail view shows description containing "Kafka Connect S3 Sink"
  Verify: "Create Demo" or "Use Template" button is present

browser_click → ref: "Create Demo" button

browser_snapshot
  Verify: Canvas view loads with 7 nodes placed on it
  Verify: Node labels: "Data Generator", "Redpanda", "Redpanda Console",
          "Kafka Connect S3", "MinIO", "Trino", "Metabase"
  Verify: 6 edges are drawn connecting the nodes

browser_click → ref: "Deploy" button

browser_wait_for → condition: all 7 node status badges show green/healthy
  Timeout: 180 seconds (Metabase startup can take ~120s)

browser_snapshot
  Verify: All 7 nodes show green health indicator
  Verify: No node shows red/error status badge
  Verify: Edge labels are visible: "Produce events", "Manage", "Consume",
          "S3 Sink", "S3 query", "SQL"
```

**Component-specific: Streaming data flow**

```
browser_click → ref: "Data Generator" node (right-click context menu)
browser_click → ref: "Start Generating" menu item

browser_wait_for → condition: Data Generator node shows "generating" or active state
  Timeout: 15 seconds

# Check Redpanda Console for messages
browser_click → ref: "Redpanda Console" node → "Open Console" or web UI link

browser_navigate → http://localhost:<rp-console-port>
browser_snapshot
  Verify: Redpanda Console UI loads (heading or sidebar present)

browser_click → ref: "Topics" in sidebar
browser_snapshot
  Verify: "clickstream" topic appears in the topic list

browser_click → ref: "clickstream" topic row
browser_snapshot
  Verify: Message count is greater than 0
  Verify: Message preview panel shows JSON with "event_id", "event_type" fields

# Check MinIO for files from Kafka Connect
browser_navigate → http://localhost:<minio-console-port>
browser_snapshot
  Verify: MinIO Console login or dashboard loads

# If login required:
browser_fill_form → username: "minioadmin", password: "minioadmin"
browser_click → ref: Login/Submit button

browser_click → ref: "streaming-data" bucket
browser_snapshot
  Verify: One or more objects/files are present in the bucket
  Verify: Object keys follow the Kafka Connect S3 path pattern (topic/partition/offset)
```

**Wait condition for Kafka Connect → MinIO:** Kafka Connect uses a flush interval; allow
up to 60 seconds after data generation starts before expecting objects in MinIO.

---

### 4.2 Dremio Lakehouse

**Expected nodes (6):** Data Generator, MinIO, Iceberg REST Catalog, Dremio, Trino, Metabase

**Expected edges (8) with labels:**
- Data Generator → MinIO: "Parquet"
- MinIO → Iceberg REST: "S3 warehouse"
- Dremio → MinIO: "S3"
- Dremio → Iceberg REST: "Iceberg catalog"
- Trino → MinIO: "S3"
- Trino → Iceberg REST: "Iceberg catalog"
- Metabase → Dremio: "Dremio SQL"
- Metabase → Trino: "SQL"

**Playwright MCP steps:**

```
browser_navigate → http://localhost:3000
browser_click → ref: "Template Gallery"
browser_click → ref: "Dremio Lakehouse" card

browser_snapshot
  Verify: Template detail shows tags including "dremio", "iceberg", "trino"
  Verify: Description mentions "two query engines, one data layer"

browser_click → ref: "Create Demo"
browser_snapshot
  Verify: Canvas shows 6 nodes
  Verify: Node labels: "Data Generator", "MinIO", "Iceberg REST Catalog",
          "Dremio", "Trino", "Metabase"

browser_click → ref: "Deploy"
browser_wait_for → condition: all 6 nodes green
  Timeout: 210 seconds (Dremio 90s start_period + buffer)

browser_snapshot
  Verify: All 6 nodes green
  Verify: Edge labels visible: "Parquet", "S3 warehouse", "S3", "Iceberg catalog",
          "Dremio SQL", "SQL"
```

**Component-specific: Dremio console loads**

```
# Start data generation first
browser_click → ref: "Data Generator" node → right-click → "Start Generating"
browser_wait_for → condition: Data Generator active
  Timeout: 15 seconds

# Open Dremio UI
browser_navigate → http://localhost:<dremio-port>
browser_snapshot
  Verify: Dremio login page loads
  Verify: Page contains input fields for username and password
  Verify: Title contains "Dremio"
```

---

### 4.3 Versioned Data Lake

**Expected nodes (5):** Data Generator, MinIO, Project Nessie, Dremio, Metabase

**Expected edges (4) with labels:**
- Data Generator → MinIO: "Structured data"
- Dremio → MinIO: "S3"
- Dremio → Nessie: "Nessie catalog"
- Metabase → Dremio: "Dremio SQL"

**Playwright MCP steps:**

```
browser_navigate → http://localhost:3000
browser_click → ref: "Template Gallery"
browser_click → ref: "Versioned Data Lake" card

browser_snapshot
  Verify: Tags include "nessie", "dremio", "branching"
  Verify: Description mentions "Git-like"

browser_click → ref: "Create Demo"
browser_snapshot
  Verify: Canvas shows 5 nodes
  Verify: Node labels: "Data Generator", "MinIO", "Project Nessie", "Dremio", "Metabase"

browser_click → ref: "Deploy"
browser_wait_for → condition: all 5 nodes green
  Timeout: 210 seconds

browser_snapshot
  Verify: All 5 nodes green
  Verify: Edge labels: "Structured data", "S3", "Nessie catalog", "Dremio SQL"
```

**Component-specific: Nessie API branches**

```
# Nessie has no web UI; verify via terminal or direct API
# In Nessie terminal (via DemoForge terminal panel):
#   quick action "List branches" → verify output contains "main"
#   quick action "Get default branch" → verify JSON response with "name":"main"

# Alternatively via host HTTP (if port is mapped):
browser_navigate → http://localhost:<nessie-port>/api/v2/trees
browser_snapshot
  Verify: JSON response body contains an entry with "name":"main"
  Verify: The main branch has a non-null "hash" field
```

---

### 4.4 Complete Analytics Platform

**Expected nodes (11):** Data Generator (Batch), Data Generator (Stream), Redpanda,
Redpanda Console, Kafka Connect S3, MinIO, Project Nessie, Dremio, Trino, Metabase, Prometheus

**Expected edges (11) with labels:**
- Data Generator (Batch) → MinIO: "Parquet batch"
- Data Generator (Stream) → Redpanda: "Produce events"
- Redpanda Console → Redpanda: "Manage"
- Kafka Connect S3 → Redpanda: "Consume"
- Kafka Connect S3 → MinIO: "S3 Sink"
- Dremio → MinIO: "S3"
- Dremio → Nessie: "Nessie catalog"
- Trino → MinIO: "S3 query"
- Metabase → Dremio: "Dremio SQL"
- Metabase → Trino: "SQL"
- MinIO → Prometheus: "Metrics"

**Resource requirement note:** This template requires 10 GB RAM and 11 containers. Confirm
available memory before deploying.

**Playwright MCP steps:**

```
browser_navigate → http://localhost:3000
browser_click → ref: "Template Gallery"
browser_click → ref: "Complete Analytics Platform" card

browser_snapshot
  Verify: Tags include "streaming", "batch", "nessie", "dremio", "full-stack"
  Verify: Estimated resources section mentions "10GB"

browser_click → ref: "Create Demo"
browser_snapshot
  Verify: Canvas shows 11 nodes
  Verify: Two "Data Generator" nodes with display names "Data Generator (Batch)"
          and "Data Generator (Stream)"
  Verify: "Prometheus" node is present

browser_click → ref: "Deploy"
browser_wait_for → condition: all 11 nodes green
  Timeout: 300 seconds (Dremio + Metabase both need extended startup time)

browser_snapshot
  Verify: All 11 nodes show green health indicator
  Verify: "Metrics" edge label is visible on MinIO → Prometheus edge
```

**Component-specific: Both generators running + all dashboards**

```
# Start batch generator
browser_click → ref: "Data Generator (Batch)" node → right-click → "Start Generating"
browser_wait_for → condition: batch generator active, Timeout: 15s

# Start stream generator
browser_click → ref: "Data Generator (Stream)" node → right-click → "Start Generating"
browser_wait_for → condition: stream generator active, Timeout: 15s

browser_snapshot
  Verify: Both Data Generator nodes show active/generating state

# Verify Redpanda Console shows streaming events
browser_navigate → http://localhost:<rp-console-port>
browser_click → ref: "Topics"
browser_snapshot
  Verify: "clickstream" topic present with message count > 0

# Verify MinIO has both data types
browser_navigate → http://localhost:<minio-console-port>
# Login if needed: minioadmin / minioadmin
browser_snapshot
  Verify: "raw-data" bucket exists (from batch generator, DG_SCENARIO=ecommerce-orders)
  Verify: "streaming-data" bucket exists (from Kafka Connect S3 sink)
  Verify: Both buckets have object count > 0

# Verify Prometheus is collecting MinIO metrics
browser_navigate → http://localhost:<prometheus-port>
browser_snapshot
  Verify: Prometheus UI loads (heading "Prometheus" visible)

browser_fill_form → query input: "minio_bucket_usage_object_total"
browser_click → ref: "Execute" button
browser_snapshot
  Verify: Graph or table shows data points (non-empty result)
  Verify: Series labels include bucket names "raw-data" and/or "streaming-data"
```

---

## Test Suite 5: Clickstream Dataset

Tests the clickstream scenario end-to-end: schema correctness, all 10 columns present,
and all 5 defined SQL queries producing valid results.

### 5.1 Deploy Setup

Use the Real-time Streaming Lakehouse template (has `DG_SCENARIO=clickstream` and
`DG_FORMAT=kafka` pre-configured). Wait for all nodes healthy. Start data generation.
Allow 2 minutes of data accumulation before running queries.

### 5.2 Column Presence Verification

Connect to the data store appropriate to the format being written. For Kafka (streaming):
consume a sample message and verify the exact key set. For Parquet (batch scenarios):
use Trino or Dremio to inspect the table schema.

Expected column set — all 10 must be present, no extras:

```
event_id       VARCHAR   (UUID)
event_ts       TIMESTAMP
session_id     VARCHAR
user_id        VARCHAR
page_url       VARCHAR
event_type     VARCHAR
referrer       VARCHAR
device_type    VARCHAR
country        VARCHAR
duration_sec   INTEGER
```

For Kafka messages, verify via `rpk topic consume clickstream --num 1 --format json`
and parse the JSON keys.

For Parquet/Iceberg, verify via Trino:
```sql
DESCRIBE minio.clickstream_parquet.clickstream;
-- or
DESCRIBE iceberg.demo.clickstream;
```

### 5.3 SQL Query Execution

Run all 5 queries defined in `clickstream.yaml` against the appropriate catalog. Replace
`{catalog}` and `{namespace}` with the deployed values (e.g., `minio` and `streaming_data`
for Trino against the streaming bucket, or `iceberg` and `demo` for Iceberg-backed storage).

**Query 1: Events per minute** (`events_per_minute`)
```sql
SELECT date_trunc('minute', event_ts) AS minute,
       COUNT(*) AS events
FROM {catalog}.{namespace}.clickstream
WHERE event_ts > current_timestamp - interval '30' minute
GROUP BY 1 ORDER BY 1
```
Expected result: one or more rows with `minute` (truncated timestamp) and `events` (integer > 0).
Expected chart type: line chart.

**Query 2: Top pages** (`top_pages`)
```sql
SELECT page_url, COUNT(*) AS views
FROM {catalog}.{namespace}.clickstream
GROUP BY page_url ORDER BY views DESC
```
Expected result: up to 9 rows, one per page URL. `/products` should rank near the top
(20% weight). `page_url` values must only be from the defined set.
Expected chart type: horizontal bar.

**Query 3: Conversion funnel** (`conversion_funnel`)
```sql
SELECT event_type,
       COUNT(*) AS count
FROM {catalog}.{namespace}.clickstream
WHERE event_type IN ('page_view', 'click', 'add_to_cart', 'purchase')
GROUP BY event_type
```
Expected result: 4 rows. `page_view` count should be the highest (~50% of total).
`purchase` count should be the lowest (~3% of total).
Expected chart type: bar.

**Query 4: Device breakdown** (`device_breakdown`)
```sql
SELECT device_type, COUNT(*) AS count
FROM {catalog}.{namespace}.clickstream
GROUP BY device_type
```
Expected result: 3 rows: `mobile` (~55%), `desktop` (~35%), `tablet` (~10%).
Expected chart type: donut.

**Query 5: Clickstream KPIs** (`kpis`)
```sql
SELECT COUNT(*) AS total_events,
       COUNT(DISTINCT session_id) AS sessions,
       COUNT(DISTINCT user_id) AS users,
       SUM(CASE WHEN event_type = 'purchase' THEN 1 ELSE 0 END) AS purchases
FROM {catalog}.{namespace}.clickstream
```
Expected result: single row with 4 scalar values.
- `total_events`: matches sum from other queries
- `sessions`: integer between 1 and 5000 (seq_range ceiling)
- `users`: integer between 1 and 500 (seq_range ceiling)
- `purchases`: integer > 0 (approximately 3% of total_events)
Expected chart type: scalar/KPI display.

### 5.4 Data Distribution Spot-Check

After at least 10,000 messages, sample 1,000 rows and verify approximate statistical
distribution matches the `weighted_enum` weights in the schema:

- `page_view` events: expect 45–55% of total
- `mobile` device: expect 50–60% of total
- `direct` referrer: expect 25–35% of total

Tolerance: ±5 percentage points from the defined weight (sampling variation).

---

## Test Suite 6: Integration

End-to-end tests verifying cross-component data flows and multi-engine query parity.

### 6.1 Multi-Engine Query: Same Data from Trino and Dremio

**Template:** Dremio Lakehouse (has both Dremio and Trino connected to the same Iceberg
REST catalog and MinIO storage).

**Steps:**
1. Deploy Dremio Lakehouse template. Wait for all 6 nodes green.
2. Start data generator (Parquet format, writes to `raw-data` bucket).
3. Wait 60 seconds for data accumulation.
4. Run a count query via Trino terminal:
   ```sql
   SELECT COUNT(*) FROM iceberg.raw.events;
   ```
5. Run the equivalent query via Dremio SQL editor (via web UI):
   ```sql
   SELECT COUNT(*) FROM iceberg.raw.events;
   ```

**Expected outcome:** Both engines return the same row count (± rows added between the
two queries). The result must be non-zero.

**Failure mode to catch:** If Iceberg catalog registration is incomplete for either engine,
the query will fail with a "catalog not found" or "table not found" error.

---

### 6.2 Streaming End-to-End: Data Generator → Redpanda → Kafka Connect → MinIO → Trino Query

**Template:** Real-time Streaming Lakehouse.

**Steps:**
1. Deploy template. All 7 nodes healthy.
2. Verify Kafka Connect has the S3 sink connector registered:
   - In Kafka Connect terminal: `curl -s http://localhost:8083/connectors | jq .`
   - Expected: `["s3-sink"]` (connector auto-registered on deploy or via init script)
3. Start data generator → "Start Generating".
4. Wait 90 seconds (allow Kafka Connect flush interval to write to MinIO).
5. Verify objects in MinIO `streaming-data` bucket via MinIO Console.
6. Open Trino terminal and run:
   ```sql
   SELECT COUNT(*) FROM minio.streaming_data.clickstream;
   ```
   Expected: row count > 0.
7. Run a structured query to confirm data integrity:
   ```sql
   SELECT event_type, COUNT(*) AS cnt
   FROM minio.streaming_data.clickstream
   GROUP BY event_type
   ORDER BY cnt DESC;
   ```
   Expected: results include `page_view` as the top event type.

**Timing note:** Kafka Connect S3 sink uses batch flushing. If query returns 0 rows,
wait an additional 60 seconds and retry before marking as a failure.

---

### 6.3 Metabase with Dual Sources: Dremio + Trino Catalogs

**Template:** Dremio Lakehouse (Metabase has both `dremio-sql` and `sql-query` edges).

**Steps:**
1. Deploy Dremio Lakehouse template. All 6 nodes green.
2. Open Metabase UI.
3. Navigate to Admin → Databases.
4. Verify two database entries are present:
   - A Dremio database (configured via `dremio-sql` edge, port 31010)
   - A Trino database (configured via `sql-query` edge)
5. For each database, click "Test Connection":
   - Expected for both: "Successfully connected" (or equivalent success message)
6. Navigate to "New Question".
7. Select the Dremio database → browse available schemas → confirm data is visible.
8. Create a second question selecting the Trino database → browse available schemas →
   confirm same underlying data is visible.

**Expected outcome:** Metabase shows both databases as configured and connectable. Data
from the same Iceberg tables is accessible through both query engines within the same
Metabase instance.

---

## Test Suite 7: Regression Checks

Quick checks to ensure the new components do not break existing functionality.

### 7.1 Existing Templates Still Deploy

After adding the new component manifests and templates, verify that at least one
pre-existing template still deploys and reaches healthy state:

- Deploy a minimal pre-existing template (e.g., MinIO single-node or any template
  present before this enrichment).
- Verify all nodes go green.
- Verify no port conflicts with the new components (all new components use distinct ports).

### 7.2 No Port Collisions Between Templates

Confirm that deploying two templates simultaneously (or in rapid succession without
teardown) does not cause host port binding failures. The DemoForge port mapper should
assign distinct host ports for each demo. Verify in Docker:

```
docker ps --format "table {{.Names}}\t{{.Ports}}" | sort
```

Each container should have a unique host-side port binding. No two containers should
share a host port.

### 7.3 Data Generator Without Kafka Env Vars

Deploy a data generator node without connecting a `kafka` edge (i.e., `DG_FORMAT` not
set to `kafka`). Verify the container starts and runs without errors related to missing
`KAFKA_BOOTSTRAP_SERVERS`. The `KafkaWriter` is only instantiated when `write_batch` is
called with `DG_FORMAT=kafka`; default operation should use the S3/Parquet writer.

---

## Appendix A: Port Reference

| Component | Container Port | Purpose |
|---|---|---|
| Dremio | 9047 | Web console + health check |
| Dremio | 31010 | JDBC/ODBC (dremio-sql endpoint) |
| Dremio | 32010 | Arrow Flight |
| Redpanda | 9092 | Kafka broker (internal) |
| Redpanda | 19092 | Kafka broker (external) |
| Redpanda | 8081 / 18081 | Schema Registry |
| Redpanda | 8082 / 18082 | Pandaproxy |
| Redpanda | 9644 | Admin API (health check) |
| Redpanda Console | 8080 | Web UI + health check |
| Kafka Connect S3 | 8083 | REST API + health check |
| Nessie | 19120 | REST API + health check |

---

## Appendix B: Health Check Summary

| Component | Endpoint | Port | Expected Response | Start Period |
|---|---|---|---|---|
| Dremio | `/apiv2/server_status` | 9047 | `{"status":"OK"}` | 90 seconds |
| Redpanda | `/v1/status/ready` | 9644 | HTTP 200 | none specified |
| Redpanda Console | `/api/health` | 8080 | HTTP 200 JSON | none specified |
| Kafka Connect S3 | `/connectors` | 8083 | HTTP 200, JSON array | none specified |
| Nessie | `/api/v2/config` | 19120 | `{"defaultBranch":"main"}` | none specified |

**Note on Dremio timing:** The 90-second start period means DemoForge must not mark
Dremio as unhealthy during the first 90 seconds of startup. Test assertions that wait
for "all nodes green" must use a timeout of at least 180 seconds for any template
containing Dremio, and at least 210 seconds when Metabase is also present.

---

## Appendix C: Known Kafka Writer Behavior

The `KafkaWriter` class (in `components/data-generator/src/writers/kafka_writer.py`)
creates a new `KafkaAdminClient` and `KafkaProducer` instance on every call to the
module-level `write_batch()` function. There is no persistent connection pool across
batches. This means:

- Topic creation is attempted on every batch (silently skipped if topic exists).
- A new producer is created per `KafkaWriter` instantiation per batch.
- Under high throughput (60 batches/minute at high profile), this may cause elevated
  connection churn. If message production stops unexpectedly, check for connection
  exhaustion errors in data generator logs.
- `producer.flush()` is called after each batch, ensuring no messages are silently
  buffered and lost on generator stop.
