# DemoForge: Event Processor Component

## Overview

The Event Processor is a generic, scenario-driven component that receives MinIO bucket notifications (webhooks), optionally processes events (generates data, transforms content, extracts metadata), and optionally writes results back to MinIO or Iceberg tables.

On the canvas it sits in the **tooling** category. It connects to MinIO in both directions: incoming webhooks (MinIO → Event Processor) and outgoing writes (Event Processor → MinIO). All S3 configuration — endpoints, credentials, catalog URI, warehouse — is **auto-injected from the connected edges**. The FA never configures connection details manually.

The only things the FA configures in the properties panel are:
1. **Action Scenario** — picked from a dropdown, just like the External System's scenario picker
2. **Processing Mode** — observe (log only) or process (log + execute)

---

## Agent Review, Validation & Testing Requirements

Same standards as all previous specs.

---

## Phase 0 — Investigation

**Read-only. Do not modify any files.**

### 0.1 MinIO Webhook Configuration

1. How does MinIO configure webhook targets? Environment variables on the MinIO container (`MINIO_NOTIFY_WEBHOOK_ENABLE_*`, `MINIO_NOTIFY_WEBHOOK_ENDPOINT_*`)?
2. How are bucket-level notification rules set? (Must use `mc event add` after startup, or can they be set via env vars?)
3. What is the exact webhook payload JSON schema?
4. Can the Event Processor self-register its webhook via the MinIO API or `mc` after both containers are healthy?

### 0.2 Existing Edge Auto-Configuration

1. How does the compose generator currently resolve S3 credentials from edges? Show the exact code path for `s3` and `aistor-tables` edge types.
2. How does the External System component receive `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `ICEBERG_CATALOG_URI`, `ICEBERG_WAREHOUSE` — all via edge auto-configuration?
3. Confirm: NO connection details appear in the External System's properties panel. All injected from edges.

### 0.3 External System Scenario Picker

1. How does the External System's scenario dropdown work? Where are scenarios loaded from?
2. How does the selected scenario map to the `ES_SCENARIO` env var?
3. How are scenario YAML files discovered and listed in the dropdown?
4. Can we reuse the same pattern for Action Scenarios?

### 0.4 Connection Handles & Bidirectional Edges

1. Can two nodes have edges in both directions simultaneously?
2. How are connection handles (ports) positioned on nodes?
3. What happens visually when Node A → Node B AND Node B → Node A exist?

### 0.5 Report

All findings. Key question: can we replicate the External System's auto-config pattern exactly, so the Event Processor gets all connection details from edges with zero manual config?

**STOP after report. Do not proceed without confirmation.**

---

## Phase 1 — Component Manifest & Connection Types

### 1.1 New Connection Type: `webhook`

**Direction:** MinIO provides → Event Processor accepts.

Add to MinIO manifest `connections.provides`:
```yaml
- type: webhook
  port: 0
  description: "Bucket event notifications"
  config_schema:
    - key: webhook_bucket
      label: "Bucket"
      type: string
      default: ""
      description: "Bucket to watch (empty = all buckets)"
    - key: webhook_prefix
      label: "Prefix"
      type: string
      default: ""
      description: "Object key prefix filter"
    - key: webhook_suffix
      label: "Suffix"
      type: string
      default: ""
      description: "Object key suffix filter"
    - key: webhook_events
      label: "Events"
      type: select
      options:
        - "s3:ObjectCreated:*"
        - "s3:ObjectRemoved:*"
        - "s3:ObjectCreated:Put"
        - "s3:ObjectCreated:CompleteMultipartUpload"
      default: "s3:ObjectCreated:*"
```

The bucket/prefix/suffix/events config lives on the **edge properties**, not on the Event Processor node properties. This is consistent with how other edge configs work (e.g., target_bucket on s3 edges).

### 1.2 Event Processor Manifest

```yaml
id: event-processor
name: Event Processor
category: tooling
icon: zap
version: "1.0"
image: demoforge/event-processor:latest
build_context: .
description: "Receives MinIO bucket webhooks and runs configurable action scenarios — observe events, generate data, transform content, write results back."

resources:
  memory: "256m"
  cpu: 0.25

ports:
  - name: webhook
    container: 8090
    protocol: tcp
  - name: web-ui
    container: 8091
    protocol: tcp

environment:
  # === Auto-injected from edges — NOT shown in properties panel ===
  # These are resolved by the compose generator from connected edges.
  # The FA never sees or configures these.
  S3_ENDPOINT: ""
  S3_ACCESS_KEY: ""
  S3_SECRET_KEY: ""
  ICEBERG_CATALOG_URI: ""
  ICEBERG_WAREHOUSE: ""
  EP_WEBHOOK_ENDPOINT: ""          # Set by compose generator: self URL for MinIO to call
  EP_WEBHOOK_BUCKET: ""            # From webhook edge config
  EP_WEBHOOK_PREFIX: ""            # From webhook edge config
  EP_WEBHOOK_SUFFIX: ""            # From webhook edge config
  EP_WEBHOOK_EVENTS: ""            # From webhook edge config

  # === FA-configurable via properties panel ===
  EP_ACTION_SCENARIO: ""           # Action scenario ID (from dropdown picker)
  EP_MODE: "process"               # "observe" or "process"

secrets:
  - key: S3_ACCESS_KEY
    label: S3 Access Key
    default: minioadmin
  - key: S3_SECRET_KEY
    label: S3 Secret Key
    default: minioadmin

web_ui:
  - name: events
    port: 8091
    path: "/"
    description: "Live event log — incoming webhooks, matched rules, processing results"

terminal:
  shell: /bin/sh
  welcome_message: "Event Processor container."
  quick_actions:
    - label: "Recent events"
      command: "curl -s http://localhost:8091/api/events?limit=10 | python3 -m json.tool"
    - label: "View loaded scenario"
      command: "cat /app/scenarios/$EP_ACTION_SCENARIO.yaml"
    - label: "Health check"
      command: "curl -s http://localhost:8090/health"
    - label: "Event stats"
      command: "curl -s http://localhost:8091/api/stats | python3 -m json.tool"

connections:
  provides:
    - type: s3
      port: 0
      description: "Writes processing results to MinIO (S3 PUT)"
      config_schema: []
    - type: aistor-tables
      port: 0
      description: "Writes structured rows to Iceberg tables"
      config_schema:
        - key: warehouse
          label: "Warehouse"
          type: string
          default: "analytics"
  accepts:
    - type: webhook
      config_schema:
        - key: webhook_bucket
          label: "Bucket"
          type: string
          default: ""
        - key: webhook_prefix
          label: "Prefix"
          type: string
          default: ""
        - key: webhook_suffix
          label: "Suffix"
          type: string
          default: ""
        - key: webhook_events
          label: "Events"
          type: select
          options: ["s3:ObjectCreated:*", "s3:ObjectRemoved:*", "s3:ObjectCreated:Put"]
          default: "s3:ObjectCreated:*"
    - type: s3
      config_schema: []

health_check:
  endpoint: /health
  port: 8090
  interval: 10s
  timeout: 5s

volumes: []

static_mounts: []

init_scripts:
  - command: "/app/register-webhook.sh"
    wait_for_healthy: true
    timeout: 30
    order: 10
    description: "Register webhook target with MinIO"

log_commands:
  - name: "Recent events"
    command: "curl -s http://localhost:8091/api/events?limit=20 | python3 -m json.tool"
    description: "Last 20 processed events"
  - name: "Event stats"
    command: "curl -s http://localhost:8091/api/stats | python3 -m json.tool"
    description: "Rule match counts and processing stats"

resource_weight: light
```

### 1.3 What the FA Sees in the Properties Panel

**Only two fields:**

| Field | Label | Type | Notes |
|-------|-------|------|-------|
| `EP_ACTION_SCENARIO` | Action scenario | select | Dropdown populated from `scenarios/` directory. Options: "Malware sandbox analysis", "CSV to Iceberg ingestion", "STIX feed processing", "Observe only", etc. |
| `EP_MODE` | Processing mode | select | "observe" (log events only) / "process" (log + execute actions) |

That's it. No S3 endpoint, no credentials, no bucket names, no catalog URI. All of that comes from the edges.

The bucket/prefix/suffix/events filtering is configured on the **webhook edge** properties (when the FA clicks the amber edge between MinIO and Event Processor), not on the Event Processor node itself.

### 1.4 Compose Generator: Auto-Configuration

**When a `webhook` edge exists (MinIO → Event Processor):**

On the **MinIO container**, inject:
```yaml
MINIO_NOTIFY_WEBHOOK_ENABLE_{target_id}: "on"
MINIO_NOTIFY_WEBHOOK_ENDPOINT_{target_id}: "http://{project}-{ep_node_id}:8090/webhook"
MINIO_NOTIFY_WEBHOOK_QUEUE_DIR_{target_id}: "/tmp/.minio/events/{target_id}"
MINIO_NOTIFY_WEBHOOK_QUEUE_LIMIT_{target_id}: "10000"
```

On the **Event Processor container**, inject:
```yaml
EP_WEBHOOK_BUCKET: "{edge.connection_config.webhook_bucket}"
EP_WEBHOOK_PREFIX: "{edge.connection_config.webhook_prefix}"
EP_WEBHOOK_SUFFIX: "{edge.connection_config.webhook_suffix}"
EP_WEBHOOK_EVENTS: "{edge.connection_config.webhook_events}"
```

**When an `s3` edge exists (Event Processor → MinIO):**

On the **Event Processor container**, inject (same as any s3 edge):
```yaml
S3_ENDPOINT: "http://{project}-{minio_node_id}:9000"
S3_ACCESS_KEY: "{minio_root_user}"
S3_SECRET_KEY: "{minio_root_password}"
```

**When an `aistor-tables` edge exists (Event Processor → MinIO):**

On the **Event Processor container**, inject (same as any aistor-tables edge):
```yaml
ICEBERG_CATALOG_URI: "http://{project}-{minio_node_id}:9000/_iceberg"
ICEBERG_WAREHOUSE: "{edge.connection_config.warehouse}"
S3_ENDPOINT: "http://{project}-{minio_node_id}:9000"
S3_ACCESS_KEY: "{minio_root_user}"
S3_SECRET_KEY: "{minio_root_password}"
```

**Webhook registration init script:**

The Event Processor registers the bucket notification rule after both containers are healthy. Generated script `register-webhook.sh`:

```bash
#!/bin/sh
# Auto-generated by compose generator
# Downloads mc, configures alias, registers bucket event notification

MC_URL="https://dl.min.io/client/mc/release/linux-amd64/mc"
curl -sL "$MC_URL" -o /usr/local/bin/mc && chmod +x /usr/local/bin/mc

mc alias set minio "$S3_ENDPOINT" "$S3_ACCESS_KEY" "$S3_SECRET_KEY" --api S3v4

# Create bucket if it doesn't exist (for the case where the bucket is specified)
if [ -n "$EP_WEBHOOK_BUCKET" ]; then
  mc mb --ignore-existing "minio/$EP_WEBHOOK_BUCKET"
fi

# Register event notification
BUCKET="${EP_WEBHOOK_BUCKET:-*}"
mc event add "minio/$BUCKET" "arn:minio:sqs::_:webhook" \
  ${EP_WEBHOOK_PREFIX:+--prefix "$EP_WEBHOOK_PREFIX"} \
  ${EP_WEBHOOK_SUFFIX:+--suffix "$EP_WEBHOOK_SUFFIX"} \
  --event "${EP_WEBHOOK_EVENTS:-s3:ObjectCreated:*}"

echo "Webhook registered: bucket=$BUCKET prefix=$EP_WEBHOOK_PREFIX events=$EP_WEBHOOK_EVENTS"
```

This script is generated by the compose generator as a template mount, not hardcoded. The edge config values flow through.

### 1.5 Connection Type Metadata

Add to `connectionMeta.ts`:
```typescript
webhook: {
  color: "#EF9F27",
  label: "Webhook",
  description: "MinIO bucket event notification"
}
```

Add `"webhook"` to the `ConnectionType` union.

### 1.6 Deliverables

1. `components/event-processor/manifest.yaml`
2. `webhook` connection type: added to MinIO manifest, frontend types, connectionMeta
3. Compose generator: webhook edge → MinIO env vars + Event Processor env vars + init script generation
4. Properties panel: only Action Scenario + Processing Mode visible
5. Verified: all S3/Iceberg config auto-injected from edges (no manual entry)
6. Verified: webhook fires from MinIO to Event Processor on object create

**STOP after Phase 1. Do not proceed without confirmation.**

**Architect review gate:**
- Event Processor properties panel shows ONLY scenario picker + mode toggle (no connection details)
- All S3/Iceberg env vars are injected from edges (grep the generated docker-compose.yml to confirm)
- MinIO webhook env vars render correctly (the `{target_id}` suffix must be valid for MinIO's env var parser)
- Init script successfully registers the bucket notification
- Webhook delivery confirmed (check Event Processor logs)
- Existing MinIO edges (s3, aistor-tables to other components) not affected

**Playwright MCP E2E tests:**

```
TEST 1.1: Event Processor in palette
  1. Open component palette → tooling
  2. Verify "Event Processor" with zap icon
  3. Screenshot

TEST 1.2: Properties panel shows only scenario + mode
  1. Place Event Processor on canvas
  2. Open properties panel
  3. Verify: Action Scenario dropdown visible
  4. Verify: Processing Mode toggle visible
  5. Verify: NO fields for S3 endpoint, access key, secret key, catalog URI
  6. Screenshot: clean properties panel

TEST 1.3: Webhook edge auto-configures
  1. Place MinIO + Event Processor
  2. Draw webhook edge: MinIO → Event Processor
  3. Click edge → verify bucket/prefix/suffix/events fields on the EDGE (not the node)
  4. Draw s3 edge: Event Processor → MinIO
  5. Deploy
  6. Inspect generated docker-compose.yml:
     - MinIO has MINIO_NOTIFY_WEBHOOK_* env vars
     - Event Processor has S3_ENDPOINT, S3_ACCESS_KEY, S3_SECRET_KEY from the s3 edge
  7. Screenshot: generated compose env vars

TEST 1.4: Webhook delivery
  1. Deploy MinIO + Event Processor with webhook edge (bucket: "test")
  2. Create bucket "test" via MinIO Console
  3. Upload a file
  4. Open Event Processor Web UI
  5. Verify event logged
  6. Screenshot: event in Web UI

TEST 1.5: Existing edges unaffected (REGRESSION)
  1. Deploy template with MinIO + Trino + Metabase (no Event Processor)
  2. Verify it works correctly
  3. Screenshot
```

---

## Phase 2 — Action Scenarios & Rule Engine

### 2.1 Action Scenario = Scenario Picker (same pattern as External System)

Action Scenarios live in `components/event-processor/scenarios/`:

```
components/event-processor/scenarios/
├── malware-sandbox-analysis.yaml
├── csv-to-iceberg.yaml
├── stix-feed-processing.yaml
├── cpx-combined.yaml              # All-in-one for the CPX demo
├── observe-only.yaml
└── _schema.md                     # Schema documentation
```

The dropdown in the properties panel is populated from this directory — exactly like the External System's scenario picker. The selected scenario ID maps to `EP_ACTION_SCENARIO` env var. The container loads `/app/scenarios/{EP_ACTION_SCENARIO}.yaml` at startup.

### 2.2 Action Scenario YAML Schema

```yaml
scenario:
  id: string
  name: string                      # Shown in the dropdown
  description: string
  category: string                  # "cybersecurity", "analytics", "iot", etc.
  version: string

# What this scenario does when events arrive
rules:
  - id: string
    name: string                    # Shown in the Web UI per event
    description: string
    enabled: boolean

    match:
      bucket: string                # Exact match or "*"
      prefix: string                # Key prefix filter
      suffix: string                # Key suffix filter
      events: list[string]          # S3 event types
      content_type: string          # Optional: match on object content-type
      min_size: integer             # Optional: minimum object size bytes
      max_size: integer             # Optional: maximum object size bytes

    steps:
      - id: string
        action: string              # Action type (see below)
        params: dict                # Action-specific parameters
        output: string              # Variable name for results
        on_error: "skip" | "abort" | "log"

    outputs:
      - id: string
        action: "write_object" | "write_iceberg" | "write_iceberg_batch"
        params: dict
```

### 2.3 Action Types

| Action | What it does | Params | Output |
|--------|-------------|--------|--------|
| `read_object_metadata` | HEAD request on trigger object | — | `{size, content_type, etag, tags}` |
| `read_object` | GET full object content | — | `{content, size, content_type}` |
| `read_csv` | GET + parse CSV file | `{has_header: true}` | `{rows: [...], count: N}` |
| `read_json` | GET + parse JSON object | — | parsed dict |
| `generate` | Produce data using generator library | `{schema: [...]}` | generated dict |
| `extract` | Extract/rename fields from prior output | `{fields: {new: "old.nested"}}` | flat dict |
| `delay` | Pause N seconds (simulate processing) | `{seconds: N, message: "..."}` | — |
| `log` | Write custom message to event log | `{message: "template {var}"}` | — |
| `write_object` | PUT object to MinIO | `{bucket, key, content_type, body}` | confirmation |
| `write_iceberg` | Write single row to Iceberg table | `{namespace, table_name, columns}` | confirmation |
| `write_iceberg_batch` | Write rows from read_csv output | `{namespace, table_name, source}` | confirmation |

The `generate` action reuses the **same generator library** as the External System — `weighted_choice`, `distribution`, `ioc`, `json_object`, `pattern`, etc. No code duplication.

### 2.4 Action Scenario: Malware Sandbox Analysis

`components/event-processor/scenarios/malware-sandbox-analysis.yaml`:

```yaml
scenario:
  id: malware-sandbox-analysis
  name: "Malware sandbox analysis"
  description: "Simulates sandbox analysis of binary samples — generates JSON reports and writes Iceberg metadata"
  category: cybersecurity
  version: "1.0"

rules:
  - id: analyze-sample
    name: "Analyze malware sample"
    description: "Binary arrives → simulate sandbox analysis → write JSON report → write Iceberg row"
    enabled: true

    match:
      bucket: malware-vault
      prefix: "samples/"
      events: ["s3:ObjectCreated:*"]

    steps:
      - id: get-metadata
        action: read_object_metadata
        output: sample

      - id: simulate-analysis
        action: delay
        params:
          seconds: 2
          message: "Analyzing sample {trigger.key}..."

      - id: generate-report
        action: generate
        params:
          schema:
            - name: sha256
              source: trigger.key_basename
            - name: file_size_bytes
              source: sample.size
            - name: file_type
              generator: weighted_choice
              params:
                choices:
                  "application/x-executable": 0.35
                  "application/x-dosexec": 0.30
                  "application/pdf": 0.15
                  "application/javascript": 0.10
                  "application/vnd.ms-office": 0.10
            - name: sandbox_verdict
              generator: weighted_choice
              params:
                choices: { malicious: 0.65, suspicious: 0.20, clean: 0.10, unknown: 0.05 }
            - name: confidence
              generator: distribution
              params: { type: uniform, min: 40, max: 99 }
            - name: threat_actor
              generator: weighted_choice
              params:
                choices: { APT33: 0.12, APT35: 0.10, LockBit: 0.20, RansomHub: 0.08, unknown: 0.50 }
            - name: malware_family
              generator: weighted_choice
              params:
                choices: { Shamoon: 0.12, Triton: 0.08, LockerGoga: 0.18, BlackCat: 0.10, unknown: 0.45 }
            - name: behavioral_indicators
              generator: json_object
              params:
                type: array
                sample_from: [creates_mutex, modifies_registry, contacts_c2_domain, attempts_privilege_escalation, disables_security_tools, encrypts_files, exfiltrates_data, installs_backdoor]
                min_items: 2
                max_items: 6
            - name: network_indicators
              generator: json_object
              params:
                fields:
                  - name: dns_queries
                    generator: ioc
                    params: { ioc_type: domain, count: 2 }
                  - name: http_connections
                    generator: ioc
                    params: { ioc_type: ipv4, count: 2 }
            - name: mitre_techniques
              generator: json_object
              params:
                type: array
                sample_from: ["T1059.001", "T1547.001", "T1071.001", "T1486", "T1021.002", "T1055", "T1027"]
                min_items: 1
                max_items: 4
            - name: analysis_timestamp
              source: now
            - name: sandbox_engine
              generator: weighted_choice
              params:
                choices: { "CrowdStrike Falcon Sandbox": 0.40, "Joe Sandbox": 0.30, "Cuckoo Sandbox": 0.20, "ANY.RUN": 0.10 }
            - name: analysis_duration_seconds
              generator: distribution
              params: { type: uniform, min: 60, max: 300 }
        output: report

    outputs:
      - id: json-report
        action: write_object
        params:
          bucket: malware-vault
          key: "reports/{report.sha256}.json"
          content_type: "application/json"
          body: report

      - id: iceberg-row
        action: write_iceberg
        params:
          namespace: soc
          table_name: malware_metadata
          columns:
            sha256: "{report.sha256}"
            file_size_bytes: "{report.file_size_bytes}"
            file_type: "{report.file_type}"
            sandbox_verdict: "{report.sandbox_verdict}"
            confidence: "{report.confidence}"
            threat_actor: "{report.threat_actor}"
            malware_family: "{report.malware_family}"
            analysis_timestamp: "{report.analysis_timestamp}"
            sandbox_engine: "{report.sandbox_engine}"
            analysis_duration_seconds: "{report.analysis_duration_seconds}"
            report_json: "{report}"
```

### 2.5 Action Scenario: CSV to Iceberg

`components/event-processor/scenarios/csv-to-iceberg.yaml`:

```yaml
scenario:
  id: csv-to-iceberg
  name: "CSV to Iceberg ingestion"
  description: "Parses CSV files from MinIO and writes rows to Iceberg tables"
  category: analytics
  version: "1.0"

rules:
  - id: firewall-csv
    name: "Firewall CSV → Iceberg"
    description: "Parse firewall CSV logs into soc.firewall_events"
    enabled: true
    match:
      bucket: raw-logs
      prefix: "firewall/"
      suffix: ".csv"
      events: ["s3:ObjectCreated:*"]
    steps:
      - id: parse
        action: read_csv
        params: { has_header: true }
        output: rows
      - id: count
        action: log
        params: { message: "Parsed {rows.count} rows from {trigger.key}" }
    outputs:
      - id: write
        action: write_iceberg_batch
        params:
          namespace: soc
          table_name: firewall_events
          source: rows

  - id: vulnscan-csv
    name: "Vuln scan CSV → Iceberg"
    description: "Parse vulnerability scan CSV into soc.vulnerability_scan"
    enabled: true
    match:
      bucket: raw-logs
      prefix: "vuln-scan/"
      suffix: ".csv"
      events: ["s3:ObjectCreated:*"]
    steps:
      - id: parse
        action: read_csv
        params: { has_header: true }
        output: rows
    outputs:
      - id: write
        action: write_iceberg_batch
        params:
          namespace: soc
          table_name: vulnerability_scan
          source: rows
```

### 2.6 Action Scenario: CPX Combined

`components/event-processor/scenarios/cpx-combined.yaml`:

```yaml
scenario:
  id: cpx-combined
  name: "CPX SOC — combined pipeline"
  description: "Handles all CPX demo event flows: firewall CSV ingestion, vuln scan CSV ingestion, and malware sandbox analysis"
  category: cybersecurity
  version: "1.0"

rules:
  # Include all rules from csv-to-iceberg AND malware-sandbox-analysis
  - id: firewall-csv
    name: "Firewall CSV → Iceberg"
    # ... same as csv-to-iceberg.yaml firewall rule

  - id: vulnscan-csv
    name: "Vuln scan CSV → Iceberg"
    # ... same as csv-to-iceberg.yaml vulnscan rule

  - id: malware-sandbox
    name: "Malware sandbox analysis"
    # ... same as malware-sandbox-analysis.yaml analyze-sample rule
```

### 2.7 Action Scenario: Observe Only

`components/event-processor/scenarios/observe-only.yaml`:

```yaml
scenario:
  id: observe-only
  name: "Observe only"
  description: "Logs all incoming events without processing — no writes, no generation"
  category: general
  version: "1.0"

rules:
  - id: log-all
    name: "Log all events"
    description: "Captures and displays every webhook event"
    enabled: true
    match:
      bucket: "*"
      events: ["*"]
    steps:
      - id: log
        action: log
        params: { message: "Event received: {trigger.event} on {trigger.bucket}/{trigger.key}" }
    outputs: []
```

### 2.8 Container Structure

```
components/event-processor/
├── manifest.yaml
├── Dockerfile
├── requirements.txt
├── scenarios/
│   ├── _schema.md
│   ├── malware-sandbox-analysis.yaml
│   ├── csv-to-iceberg.yaml
│   ├── cpx-combined.yaml
│   └── observe-only.yaml
├── templates/
│   └── register-webhook.sh.j2
└── src/
    ├── __init__.py
    ├── main.py                    # FastAPI: webhook endpoint (8090) + web UI (8091)
    ├── webhook_handler.py         # Receives MinIO payloads, matches rules
    ├── rule_engine.py             # Loads scenario, executes step pipelines
    ├── actions/
    │   ├── __init__.py
    │   ├── read.py                # read_object_metadata, read_object, read_csv, read_json
    │   ├── generate.py            # generate — reuses External System generator library
    │   ├── transform.py           # extract, delay, log
    │   └── write.py               # write_object, write_iceberg, write_iceberg_batch
    ├── web_ui/
    │   └── index.html             # Single-page event log UI
    └── event_store.py             # In-memory ring buffer (capped at 1000 events)
```

### 2.9 Web UI

Single-page app served on port 8091. Vanilla HTML/JS, no build step.

**Header bar:**
- Component name + scenario name
- Mode badge: "Processing" (green) or "Observe" (blue)
- Event count + events/minute rate
- Uptime

**Event log (scrolling, newest on top):**

Each event row:
```
[10:23:15] s3:ObjectCreated:Put  malware-vault/samples/a1b2c3...
           → Malware sandbox analysis
           → Analyzing... (2s) → Report written → Iceberg row written
           [Processed ✓]
```

Expandable on click:
- Full webhook payload JSON
- Step execution log with timing: `read_object_metadata (12ms) → delay (2000ms) → generate (8ms) → write_object (45ms) → write_iceberg (120ms)`
- Output details: what was written, where, row count

**API endpoints:**
- `GET /api/events?limit=N` — recent events
- `GET /api/events/{id}` — full event detail
- `GET /api/stats` — counts, rates, errors
- `GET /api/scenario` — loaded scenario info
- `GET /health` — health check

### 2.10 Deliverables

1. All scenario YAML files
2. Container: Dockerfile, source code, requirements
3. Web UI: index.html
4. Verified: malware analysis scenario triggers on binary upload
5. Verified: CSV-to-Iceberg scenario triggers on CSV upload
6. Verified: observe-only mode logs without acting
7. Verified: Web UI shows real-time event stream

**STOP after Phase 2. Do not proceed without confirmation.**

**Architect review gate:**
- `generate` action reuses External System's generator library (shared code, not copied)
- Error handling: what happens if Iceberg write fails? (should log error, mark event as failed, continue processing next events)
- Ring buffer doesn't grow unbounded
- The `delay` action is visible in the Web UI as a progress state
- Write-back to `malware-vault/reports/` does NOT re-trigger the rule (prefix mismatch: rule watches `samples/`, writes to `reports/`)
- No connection details are hardcoded in scenario YAMLs — all resolved from env vars at runtime

**Playwright MCP E2E tests:**

```
TEST 2.1: Scenario picker populated
  1. Place Event Processor on canvas
  2. Open properties panel
  3. Verify dropdown shows: "Malware sandbox analysis", "CSV to Iceberg", "CPX SOC — combined", "Observe only"
  4. Screenshot: scenario dropdown

TEST 2.2: Malware analysis pipeline
  1. Deploy MinIO + Event Processor (scenario: malware-sandbox-analysis)
  2. Create malware-vault bucket, upload binary to samples/test123
  3. Open Web UI — verify event appears with "Malware sandbox analysis" rule
  4. Verify "Analyzing..." step visible with 2s delay
  5. Verify malware-vault/reports/test123.json exists and is valid JSON
  6. Query Trino: SELECT * FROM soc.malware_metadata WHERE sha256 = 'test123'
  7. Verify row exists with report_json column
  8. Screenshot: Web UI + JSON report + Trino result

TEST 2.3: CSV ingestion pipeline
  1. Deploy MinIO + Event Processor (scenario: csv-to-iceberg)
  2. Create raw-logs bucket, upload test CSV to firewall/test.csv (10 rows)
  3. Open Web UI — verify event + "Firewall CSV → Iceberg" rule match
  4. Query Trino: verify 10 new rows in soc.firewall_events
  5. Screenshot: Web UI + Trino count

TEST 2.4: Observe-only mode
  1. Deploy with scenario: observe-only, mode: observe
  2. Upload file to any bucket
  3. Verify Web UI shows event with "Observe" badge (blue)
  4. Verify NO writes occurred
  5. Screenshot

TEST 2.5: No infinite webhook loop
  1. Deploy malware analysis scenario
  2. Upload binary to samples/
  3. Verify report written to reports/
  4. Wait 10 seconds — verify event count stays at 1
  5. Screenshot: stable event count

TEST 2.6: Web UI event detail expansion
  1. After TEST 2.2, click the event row in Web UI
  2. Verify expanded detail shows step timing breakdown
  3. Verify output section shows bucket/key of written objects
  4. Screenshot: expanded event
```

---

## Phase 3 — CPX Demo Integration

### 3.1 Updated Data Flow

With the Event Processor, the External Systems simplify to raw-data-only writers:

| External System | Before | After |
|----------------|--------|-------|
| Perimeter Firewall | Writes CSV + Iceberg table | Writes CSV only → Event Processor handles Iceberg |
| Threat Intel | Writes STIX JSON + IOC table + binaries + reports + Iceberg | Writes STIX JSON + IOC table + binaries only → Event Processor handles reports + Iceberg metadata |
| Vuln Scanner | Writes CSV + Iceberg table | Writes CSV only → Event Processor handles Iceberg |

The IOC Iceberg table (`soc.threat_iocs`) is still written directly by the External System — it's extracted from STIX feeds, not triggered by a file drop. Only the malware and CSV flows go through the Event Processor.

### 3.2 Template Update

Add Event Processor node and edges:

```yaml
nodes:
  # ... existing nodes unchanged

  - id: event-proc
    component: event-processor
    position: { x: 100, y: 350 }
    display_name: "Event Processor"
    config:
      EP_ACTION_SCENARIO: cpx-combined
      EP_MODE: process

edges:
  # ... existing source → MinIO edges (simplified: raw data only)

  # Webhook: MinIO → Event Processor (all buckets, rules filter internally)
  - id: e-webhook
    source: minio-1
    target: event-proc
    connection_type: webhook
    network: default
    auto_configure: true
    label: "Bucket events"
    connection_config:
      webhook_events: "s3:ObjectCreated:*"

  # Write-back: Event Processor → MinIO
  - id: e-ep-s3
    source: event-proc
    target: minio-1
    connection_type: s3
    network: default
    auto_configure: true
    label: "Reports + results"

  - id: e-ep-iceberg
    source: event-proc
    target: minio-1
    connection_type: aistor-tables
    network: default
    auto_configure: true
    label: "Iceberg writes"
    connection_config:
      warehouse: analytics
```

### 3.3 Updated External System Scenarios

**`soc-firewall-events.yaml`:**
- Remove `raw_landing` (if implemented from Spec 8) — the External System now writes ONLY CSV files as its primary output, NOT Iceberg
- Change `target: table` to `target: object` with `object_format: csv`
- Keep dashboards and saved queries (provisioned to Metabase as before)

**`soc-vuln-scan.yaml`:**
- Same change — CSV-only output

**`soc-threat-intel.yaml`:**
- IOC table: unchanged (still writes via PyIceberg — this is extracted from STIX, not file-triggered)
- STIX JSON: unchanged (raw objects)
- Malware: writes ONLY binary blobs to `samples/`. Removes report generation and Iceberg metadata writing — Event Processor handles those

### 3.4 Sticky Notes

**Customer-facing:**
```yaml
- id: sn-ep-customer
  title: "Event-driven ingestion"
  content: "MinIO bucket notifications trigger automated processing. CSV logs are parsed into Iceberg tables. Malware binaries are analyzed with sandbox reports generated automatically. No polling, no batch scheduling."
  visibility: customer
```

**FA internal:**
```yaml
- id: sn-ep-fa
  title: "Demo highlight"
  content: "Open the Event Processor Web UI during seeding — the audience watches events streaming in real-time. Each event shows what arrived, which rule matched, and what was generated. For the 'wow' moment: manually drag a file into MinIO Console and watch the pipeline trigger live."
  visibility: internal
```

### 3.5 Deliverables

1. Updated template YAML with Event Processor node + edges
2. Updated External System scenarios (simplified to raw-only)
3. cpx-combined action scenario
4. Sticky notes for Event Processor
5. Full end-to-end test: raw data → webhooks → Event Processor → Iceberg → dashboards + queries

**STOP after Phase 3. Review with Ahmad.**

**Architect review gate:**
- Full pipeline works: External System → raw files → MinIO → webhook → Event Processor → Iceberg
- All dashboards and saved queries return data (same tables, different ingestion path)
- Event Processor Web UI shows clear event flow during seeding
- The manual file drop demo works (upload binary via Console → analysis report + Iceberg row appear)
- Total container count is now 8 (3 External Systems + MinIO + Trino + Metabase + Event Processor + network)
- Memory estimate: ~9GB (adding ~512MB for Event Processor)
- Template deploys within 2 minutes

**Playwright MCP E2E — FULL PIPELINE:**

```
TEST 3.1: Full CPX demo
  1. Load updated template
  2. Deploy — all 8 containers healthy
  3. Open Event Processor Web UI — events streaming
  4. Open MinIO Console — raw CSVs + STIX JSON + binaries + reports + Iceberg tables
  5. Open Metabase — all dashboards render
  6. Run all saved queries — all return results
  7. Run Q9 (unified) — spans all data types
  8. Screenshot at every step

TEST 3.2: Manual file drop
  1. Stack running, open Event Processor Web UI side by side with MinIO Console
  2. Upload a binary to malware-vault/samples/demo-drop via Console
  3. Watch Event Processor: event appears → "Analyzing..." → report written → Iceberg row written
  4. Open malware-vault/reports/demo-drop.json in Console — verify valid
  5. Run: SELECT * FROM soc.malware_metadata WHERE sha256 = 'demo-drop'
  6. Verify row exists with report_json
  7. Screenshot: the complete visible pipeline

TEST 3.3: Existing templates unaffected (REGRESSION)
  1. Load any template that doesn't use Event Processor
  2. Deploy — works correctly
  3. Screenshot
```
