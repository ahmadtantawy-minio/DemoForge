# DemoForge: External System Component & Scenario Engine

## Overview

This spec introduces an **External System** component and a **Scenario YAML schema** that together allow Field Architects to represent customer source systems on the canvas and generate realistic, scenario-specific data into MinIO AIStor.

The External System is a real container (the "scenario engine") that reads a declarative YAML file describing what data to generate, how to generate it, and what dashboards to provision in the connected visualization tool. FAs drag it onto the canvas, rename it to match the customer's reality (e.g., "Perimeter Firewall," "IoT Gateway," "Trading Platform"), select a scenario profile, and deploy. The container handles everything: schema creation, data seeding, optional streaming, and dashboard provisioning.

**Key principle:** Adding a new demo scenario requires ONLY a new YAML file. No code changes, no new containers, no DemoForge modifications.

---

## Agent Review, Validation & Testing Requirements

**These requirements apply to ALL phases and are non-negotiable.**

### Architect & Senior Agent Review

Every phase of this spec MUST be reviewed by the **architect agent** and/or a **senior agent** before marking the phase as complete. The reviewing agent's responsibilities are:

1. **Fit review:** Verify that every change — manifest, compose generator, frontend types, Python code — integrates cleanly with the existing DemoForge architecture. No pattern violations, no inconsistencies with how other components work.

2. **Non-breakage review:** Before any code is committed, the reviewing agent MUST verify that existing functionality is not broken. Specifically:
   - The existing `data-generator` component still works unchanged
   - The existing `bi-dashboard-lakehouse` template still loads, generates valid compose YAML, and deploys correctly
   - All existing connection types still resolve properly in the compose generator
   - The frontend builds without errors (`npm run build` must pass)
   - The backend starts without errors and all existing API endpoints still respond correctly
   - No existing component manifests are modified (unless explicitly called for in this spec)

3. **Code quality review:** The reviewing agent checks for:
   - Proper error handling (no silent failures, clear error messages)
   - Consistent coding style with the existing codebase (naming conventions, file structure, import patterns)
   - No hardcoded values that should be configurable
   - No security issues (credentials handling, input validation)
   - Type safety (TypeScript strict mode compliance, Python type hints)

4. **Regression check:** After each phase, the reviewing agent runs the existing test suite (if any) and confirms all tests pass. If no formal test suite exists, the agent manually validates the scenarios described in the non-breakage review above.

### End-to-End Testing with Playwright MCP

Every phase that produces deployable artifacts (Phase 2 onward) MUST include **end-to-end validation tests executed via Playwright MCP**. These are not optional smoke tests — they are the acceptance criteria for the phase.

#### Test Infrastructure

- Tests run against a live DemoForge instance (dev mode: `make dev`)
- Use Playwright MCP to drive the browser — navigate, click, fill forms, assert
- Tests must be repeatable: they should clean up after themselves (delete test demos)
- Screenshots should be captured at key validation points as evidence

#### Required E2E Test Scenarios

**Phase 2 — Component & Compose Validation:**

```
TEST 2.1: External System appears in component palette
  1. Open DemoForge canvas
  2. Open component palette
  3. Verify "External System" appears under the "sources" category
  4. Verify icon renders correctly
  5. Screenshot: component in palette

TEST 2.2: External System can be dragged onto canvas
  1. Drag External System onto canvas
  2. Verify node renders with default display name
  3. Open properties panel
  4. Verify scenario dropdown is populated with available scenarios
  5. Select "SOC Firewall & Threat Intel" scenario
  6. Verify display name updates (if auto-name is implemented)
  7. Screenshot: node on canvas with properties panel open

TEST 2.3: External System connects to MinIO
  1. Place External System and MinIO nodes on canvas
  2. Draw edge from External System to MinIO
  3. Verify connection type picker shows valid options (s3, aistor-tables)
  4. Select aistor-tables
  5. Verify edge renders with correct color and label
  6. Screenshot: connected nodes

TEST 2.4: External System connects to Metabase (dashboard-provision)
  1. Place External System and Metabase on canvas
  2. Draw edge from External System to Metabase
  3. Verify dashboard-provision connection type is available
  4. Verify edge renders with violet color
  5. Screenshot: connected nodes

TEST 2.5: Full topology composes correctly
  1. Create topology: External System → MinIO → Trino → Metabase, External System → Metabase
  2. Deploy (or trigger compose generation)
  3. Verify no errors in compose generation
  4. If deploy is possible: verify all containers start
  5. Screenshot: deployed topology with all nodes green

TEST 2.6: Existing templates still work (REGRESSION)
  1. Load bi-dashboard-lakehouse template
  2. Verify it loads without errors
  3. Deploy it
  4. Verify all containers start and go healthy
  5. Screenshot: deployed existing template
  6. Destroy the demo
```

**Phase 3 — Data Generation & Dashboard Provisioning:**

```
TEST 3.1: Data seeding completes
  1. Deploy sovereign-cyber-data-lake template
  2. Wait for External System container logs to show "Seeded X rows"
  3. Open MinIO Console
  4. Verify Iceberg table data exists (navigate buckets, check objects)
  5. Screenshot: MinIO Console showing data

TEST 3.2: Trino can query Iceberg tables
  1. Open Trino UI
  2. Run: SELECT count(*) FROM soc.firewall_events
  3. Verify returns non-zero count matching seed_rows
  4. Run: SELECT count(*) FROM soc.threat_iocs
  5. Run: SELECT count(*) FROM soc.vulnerability_scan
  6. Screenshot: Trino query results

TEST 3.3: Cross-table join works (correlation validation)
  1. Open Trino UI
  2. Run the IOC-firewall join query from the dashboard spec:
     SELECT f.src_ip, f.dst_ip, t.threat_actor, t.confidence
     FROM soc.firewall_events f
     JOIN soc.threat_iocs t ON f.dst_ip = t.indicator AND t.ioc_type = 'ipv4'
     LIMIT 10
  3. Verify results are non-empty (correlation engine worked)
  4. Screenshot: join query results

TEST 3.4: Metabase dashboards are provisioned
  1. Open Metabase UI
  2. Verify Trino data source exists in Admin > Databases
  3. Navigate to dashboards
  4. Verify "SOC Overview" dashboard exists and loads
  5. Verify "Threat Intelligence" dashboard exists and loads
  6. Verify "Vulnerability Posture" dashboard exists and loads
  7. Verify charts render with actual data (not empty)
  8. Screenshot: each dashboard

TEST 3.5: Streaming generates new data
  1. After seeding completes, wait 60 seconds
  2. Query Trino: SELECT count(*) FROM soc.firewall_events
  3. Wait 30 more seconds
  4. Query again
  5. Verify count has increased (streaming is working)
  6. Screenshot: two query results showing growth

TEST 3.6: E-commerce scenario works too
  1. Create new demo with External System using ecommerce-orders scenario
  2. Deploy
  3. Verify data seeds correctly
  4. Verify Trino queries work
  5. Destroy the demo
```

**Phase 4 — Template & Full Integration:**

```
TEST 4.1: Template loads from gallery
  1. Open DemoForge
  2. Navigate to template gallery
  3. Find "Sovereign Cyber Data Lake" template
  4. Verify metadata displays correctly (name, description, tags, tier)
  5. Click to create demo from template
  6. Verify canvas loads with correct topology
  7. Screenshot: template in gallery + loaded canvas

TEST 4.2: Full end-to-end deployment
  1. Deploy the template
  2. Wait for all containers to be healthy
  3. Validate all TEST 3.x scenarios pass against this deployment
  4. Screenshot: fully deployed and functional

TEST 4.3: Template SE guide renders
  1. Open the template details / SE guide
  2. Verify talking points, demo flow steps, and common Q&A render
  3. Screenshot: SE guide

TEST 4.4: Cleanup works
  1. Stop the demo
  2. Verify all containers stop
  3. Destroy the demo
  4. Verify all volumes are removed
  5. Verify canvas returns to not_deployed state
  6. Screenshot: clean state
```

#### Test Execution Protocol

1. **Before running tests:** Start DemoForge in dev mode (`make dev`), confirm it's healthy
2. **During tests:** Capture screenshots at every assertion point. If a test fails, capture the error state screenshot AND the browser console logs AND the container logs
3. **After tests:** Produce a test report summarizing pass/fail for each test, with screenshot links
4. **On failure:** Do NOT proceed to the next phase. Fix the failure, re-run the failing test and all regression tests, then proceed only when all pass

#### Test File Organization

If Playwright test files are created (for future CI/CD), place them at:
```
tests/e2e/external-system/
├── phase2-component.spec.ts
├── phase3-data-generation.spec.ts
├── phase4-template.spec.ts
└── regression/
    └── existing-templates.spec.ts
```

---

## Phase 0 — Read-Only Investigation

**DO NOT write any code in this phase. Only read and report.**

Before implementing anything, investigate the following and present findings for review:

### 0.1 Existing Data Generator Analysis

Read the existing `data-generator` component thoroughly:
- `components/data-generator/manifest.yaml` — full contents
- `components/data-generator/` — all source files (Dockerfile, Python code, any config)
- How does `DG_SCENARIO` currently work? What scenarios exist? How is data generated?
- What image does it use? Is there a Dockerfile or is it pre-built?
- How does the Iceberg write mode (`DG_WRITE_MODE: iceberg`) work? What library writes Iceberg tables?

### 0.2 Metabase Component Analysis

Read the existing `metabase` component:
- `components/metabase/manifest.yaml` — full contents
- Any templates, static mounts, init scripts
- How does it currently connect to Trino? Does it auto-configure?
- Does it have any dashboard provisioning mechanism?

### 0.3 Trino Component Analysis

Read the existing `trino` component:
- `components/trino/manifest.yaml` — full contents
- `components/trino/templates/iceberg.properties.j2` — how is the Iceberg connector configured?
- `components/trino/templates/aistor-iceberg.properties.j2` — same
- How does the connection to MinIO get resolved (S3 endpoint, credentials)?

### 0.4 Connection Type: aistor-tables

- Search `compose_generator.py` for how the `aistor-tables` connection type is handled
- Search `connectionMeta.ts` for its color/label/description
- How does the edge auto-configuration work for this type?

### 0.5 Existing Template: bi-dashboard-lakehouse

- Read `demo-templates/bi-dashboard-lakehouse.yaml` completely
- Understand how data-generator → MinIO → Trino → Metabase are wired
- What edge types and connection configs are used?

### 0.6 Canvas Node Display

- In the frontend, how does a node display its `display_name` vs component `name`?
- Can a node show a subtitle or secondary label? (e.g., "Perimeter Firewall" as name, "Palo Alto PA-5400" as subtitle)
- How is the component icon rendered? Can a node override the icon?

### 0.7 Report Format

Produce a single report with:
1. Full source code of the data-generator container (Python files)
2. Full source code of the Metabase manifest and any provisioning logic
3. Full Trino Iceberg template files
4. How `aistor-tables` is resolved in compose generation
5. The complete bi-dashboard-lakehouse template YAML
6. Findings on node display name / subtitle / icon behavior
7. A list of ALL `DG_SCENARIO` values currently supported and what each generates
8. Whether the data-generator already uses pyiceberg or another Iceberg library

**STOP after producing this report. Do not proceed to Phase 1 without explicit confirmation.**

**Architect review gate:** The architect agent must review the Phase 0 report for completeness before Phase 1 begins. Specifically: are there any existing patterns, utilities, or code in the codebase that the spec doesn't account for? Are there any assumptions in this spec that conflict with how the codebase actually works? The architect should flag anything that would require spec amendments before implementation begins.

---

## Phase 1 — Scenario YAML Schema

Create the scenario YAML schema definition and 1-2 example scenario files. No component changes yet.

### 1.1 Schema Location

```
components/external-system/scenarios/
├── _schema.md              # Human-readable schema documentation
├── soc-firewall-logs.yaml  # Example: cybersecurity scenario
└── ecommerce-orders.yaml   # Example: migrated from existing data-generator
```

### 1.2 Scenario YAML Schema

```yaml
# ============================================================
# Scenario Profile Schema — v1.0
# ============================================================
# A single YAML file that fully describes:
#   1. What this external system looks like on the canvas
#   2. What data it generates (schemas + generation rules)
#   3. What dashboards to provision in the visualization tool
# ============================================================

scenario:
  id: string                    # Unique identifier, kebab-case (e.g., "soc-firewall-logs")
  name: string                  # Human-readable name shown in scenario picker
  description: string           # One-line description
  category: string              # Grouping: "cybersecurity", "analytics", "iot", "fintech", etc.
  icon: string                  # Icon name from the DemoForge icon set (optional, defaults to "database")
  version: string               # Scenario version (e.g., "1.0")
  tags: list[string]            # Searchable tags

# What this system looks like on the canvas
display:
  default_name: string          # Default node display name (FA can override)
  default_subtitle: string      # Secondary label shown below name (optional)
  
# ============================================================
# DATASETS — What data this system produces
# ============================================================
# Each dataset is either:
#   - target: "table"  → Iceberg table (structured/semi-structured, queryable via Trino)
#   - target: "object" → Raw objects in MinIO bucket (unstructured/binary)
# ============================================================

datasets:
  - id: string                  # Unique within this scenario
    target: "table" | "object"
    
    # --- For target: "table" ---
    namespace: string            # Iceberg namespace (maps to Trino schema)
    table_name: string           # Iceberg table name
    format: "parquet"            # Data file format (parquet only for Iceberg tables)
    partition_by: list[string]   # Optional partition columns (e.g., ["event_date"])
    
    # --- For target: "object" ---
    bucket: string               # MinIO bucket name
    prefix: string               # Object key prefix (e.g., "feeds/stix/")
    object_format: string        # "json" | "csv" | "binary" | "text"
    
    # --- Schema: defines columns/fields ---
    schema:
      - name: string             # Column/field name
        type: string             # "string" | "integer" | "long" | "float" | "double" 
                                 #   | "boolean" | "timestamp" | "date" | "decimal" | "binary"
        nullable: bool           # Default: true
        generator: string        # Generator function name (see Generator Library below)
        params: dict             # Generator-specific parameters
    
    # --- Optional: mirror objects to a queryable table ---
    # Only valid when target: "object"
    # Creates a parallel Iceberg table with extracted metadata fields
    mirror_to_table:
      namespace: string
      table_name: string
      fields: list[string]       # Which schema fields to include in the table
    
    # --- Generation behavior ---
    generation:
      mode: "batch" | "stream" | "batch_then_stream"
      seed_rows: int             # For batch: how many rows to generate initially
      seed_count: int            # For objects: how many objects to generate
      stream_rate: string        # For stream: rate expression (e.g., "50/s", "10/m")
      stream_duration: string    # Optional: stop after duration (e.g., "30m", "forever")
      batch_files: int           # Optional: split batch across N files (default: auto based on seed_rows)

# ============================================================
# REFERENCE DATA — Static lookup tables used by generators
# ============================================================
# Small datasets that generators reference (e.g., known-bad IPs,
# product catalogs, employee lists). Loaded once, used by generators.
# ============================================================

reference_data:
  - id: string                   # Referenced by generators as "ref:{id}"
    description: string
    format: "inline" | "csv"     # inline = defined here; csv = file in scenarios/data/
    
    # For format: "inline"
    columns: list[string]
    rows: list[list[any]]
    
    # For format: "csv"
    file: string                 # Path relative to scenarios/data/ directory
    
# ============================================================
# CORRELATIONS — Cross-dataset relationships
# ============================================================
# Define how datasets reference each other for realistic data.
# E.g., 3% of firewall dst_ips should match threat intel IOCs.
# ============================================================

correlations:
  - name: string                 # Human-readable description
    source_dataset: string       # Dataset ID that produces values
    source_field: string         # Field in source dataset
    target_dataset: string       # Dataset ID that consumes values
    target_field: string         # Field in target dataset
    ratio: float                 # 0.0-1.0: fraction of target rows that should match

# ============================================================
# DASHBOARDS — Visualization definitions
# ============================================================
# Each dashboard maps to a Metabase dashboard (or Superset in future).
# Charts are defined as SQL queries against the Iceberg tables.
# The provisioner translates these into the visualization tool's API.
# ============================================================

dashboards:
  - id: string                   # Unique dashboard identifier
    title: string                # Dashboard title shown in UI
    description: string          # Optional description
    
    # Grid layout hint (Metabase uses a 24-column grid)
    # If omitted, charts stack vertically
    layout: "auto" | "2-column" | "3-column"
    
    charts:
      - id: string               # Unique chart identifier within dashboard
        title: string            # Chart title
        type: string             # "time_series" | "bar" | "horizontal_bar" | "pie" | "donut"
                                 #   | "number" | "table" | "area" | "scatter" | "gauge" | "map"
        description: string      # Optional subtitle/description
        
        query: |                 # SQL query (Trino-compatible)
          SELECT ...             # Use {namespace}.{table_name} to reference tables
          FROM ...               # The provisioner resolves these to the actual Trino connection
          
        # Layout hint (row, col within the grid; optional)
        position:
          row: int               # 0-indexed row
          col: int               # 0-indexed column (0-23 for Metabase)
          width: int             # Column span (1-24 for Metabase, default: 12)
          height: int            # Row span (default: 6)
        
        # Chart-specific settings
        settings:
          x_axis: string         # Column name for X axis (time_series, bar, scatter)
          y_axis: string | list  # Column name(s) for Y axis
          group_by: string       # Column to group/color by (optional)
          sort: "asc" | "desc"   # Sort direction (optional)
          limit: int             # Row limit for table charts (optional)
          number_format: string  # For number charts: "decimal" | "percent" | "currency"
          color: string          # Hex color override (optional)
```

### 1.3 Generator Library

These are the built-in generator functions available in `generator` fields.
Each generator is a Python function that returns a value given the `params` dict.

| Generator | Description | Key Params |
|-----------|-------------|------------|
| `uuid` | UUID v4 string | — |
| `auto_increment` | Sequential integer | `start`, `step` |
| `timestamp` / `time_series` | Timestamps with realistic patterns | `start`, `end`, `pattern` ("uniform", "business_hours", "realistic") |
| `date` | Date values | `start`, `end` |
| `ip_address` | IPv4 addresses | `ranges` (CIDR list), `known_bad_ratio` (float) |
| `weighted_choice` | Pick from weighted options | `choices` (dict of value→weight) |
| `uniform_choice` | Pick uniformly from list | `values` (list) |
| `pattern` | String from template | `format` (template string with `{seq}`, `{category}`, `{random_hex}`, etc.), `categories` (list) |
| `distribution` | Numeric from statistical distribution | `type` ("normal", "lognormal", "uniform", "exponential"), `mean`, `sigma`, `min`, `max` |
| `faker` | Delegates to Faker library | `method` (any Faker method name), `locale` |
| `ref_lookup` | Value from reference data | `ref` (reference data ID), `column`, `distribution` ("uniform", "weighted") |
| `ref_sample` | Random row from reference data | `ref` (reference data ID) |
| `ioc` | Cybersecurity IOC (IP, domain, hash, URL) | `ioc_type` ("ipv4", "domain", "sha256", "md5", "url") |
| `constant` | Fixed value | `value` |
| `nullable` | Wraps another generator, returns null at a rate | `generator`, `params`, `null_ratio` |
| `conditional` | Value depends on another field in same row | `field`, `conditions` (list of {when, generator, params}) |
| `sequence_from` | Cycles through a list | `values` |
| `json_object` | Generates a nested JSON string | `fields` (list of name/generator/params, same as schema fields) |
| `correlation` | Pulls from correlated dataset | Handled automatically via `correlations` section |
| `text_block` | Lorem-ipsum-like text blocks | `min_words`, `max_words`, `language` |
| `geo_coordinate` | Lat/lon coordinates | `region` ("global", "uae", "us", "eu", custom bbox) |
| `mac_address` | MAC address string | `prefix` (optional OUI prefix) |
| `enum` | Strict enum values (no weighting) | `values` |

### 1.4 Example Scenario: SOC Firewall Logs

Create this file at `components/external-system/scenarios/soc-firewall-logs.yaml`:

```yaml
scenario:
  id: soc-firewall-logs
  name: "SOC Firewall & Threat Intel"
  description: "Simulates enterprise firewall event streams with correlated threat intelligence"
  category: cybersecurity
  icon: shield-alert
  version: "1.0"
  tags: [cybersecurity, soc, firewall, siem, threat-intelligence, ids]

display:
  default_name: "Perimeter Firewall"
  default_subtitle: "Enterprise IDS/IPS"

reference_data:
  - id: known_c2_ips
    description: "Known command-and-control IP addresses"
    format: inline
    columns: [ip, threat_actor, first_seen]
    rows:
      - ["198.51.100.10", "APT33", "2025-06-15"]
      - ["203.0.113.42", "APT35", "2025-08-22"]
      - ["192.0.2.88", "LockBit", "2025-11-03"]
      - ["198.51.100.55", "RansomHub", "2026-01-10"]
      - ["203.0.113.99", "APT33", "2025-09-18"]
      - ["192.0.2.200", "DarkVault", "2026-02-05"]
      - ["198.51.100.77", "Muddy Water", "2025-07-30"]
      - ["203.0.113.15", "Pulsar Kitten", "2025-12-12"]
      - ["192.0.2.33", "LockBit", "2025-10-25"]
      - ["198.51.100.120", "APT35", "2026-03-01"]

  - id: mitre_tactics
    description: "MITRE ATT&CK tactics with typical ports"
    format: inline
    columns: [tactic, technique_id, name, typical_ports]
    rows:
      - ["initial-access", "T1190", "Exploit Public-Facing Application", [80, 443, 8080]]
      - ["execution", "T1059", "Command and Scripting Interpreter", [445, 5985, 22]]
      - ["lateral-movement", "T1021", "Remote Services", [3389, 22, 445, 5985]]
      - ["exfiltration", "T1041", "Exfiltration Over C2 Channel", [443, 53, 8443]]
      - ["command-and-control", "T1071", "Application Layer Protocol", [443, 80, 53, 8080]]
      - ["discovery", "T1046", "Network Service Discovery", [0]]
      - ["credential-access", "T1110", "Brute Force", [22, 3389, 445]]
      - ["persistence", "T1078", "Valid Accounts", [22, 3389, 443]]

datasets:
  - id: firewall_events
    target: table
    namespace: soc
    table_name: firewall_events
    format: parquet
    partition_by: [event_date]

    schema:
      - name: event_id
        type: string
        generator: uuid

      - name: event_timestamp
        type: timestamp
        generator: time_series
        params:
          pattern: realistic         # Clusters during business hours, dips at night
          timezone: "Asia/Dubai"     # UAE timezone

      - name: event_date
        type: date
        generator: conditional
        params:
          field: event_timestamp
          conditions:
            - when: "*"
              generator: date
              params: { from_field: "event_timestamp" }

      - name: src_ip
        type: string
        generator: ip_address
        params:
          ranges: ["10.0.0.0/8", "172.16.0.0/12"]

      - name: src_port
        type: integer
        generator: distribution
        params:
          type: uniform
          min: 1024
          max: 65535

      - name: dst_ip
        type: string
        generator: ip_address
        params:
          ranges: ["0.0.0.0/0"]

      - name: dst_port
        type: integer
        generator: weighted_choice
        params:
          choices:
            443: 0.40
            80: 0.18
            53: 0.12
            8080: 0.06
            22: 0.04
            3389: 0.03
            445: 0.02
            8443: 0.02
            25: 0.01
          # Remaining 12% = random high ports
          random_high_port_ratio: 0.12

      - name: protocol
        type: string
        generator: weighted_choice
        params:
          choices: { TCP: 0.78, UDP: 0.18, ICMP: 0.04 }

      - name: action
        type: string
        generator: weighted_choice
        params:
          choices: { allow: 0.91, deny: 0.055, drop: 0.025, reset: 0.01 }

      - name: severity
        type: string
        generator: weighted_choice
        params:
          choices: { info: 0.68, low: 0.16, medium: 0.10, high: 0.045, critical: 0.015 }

      - name: rule_id
        type: string
        generator: pattern
        params:
          format: "FW-{category}-{seq:04d}"
          categories: [INGRESS, EGRESS, LATERAL, DNS, MALWARE, SCAN, BRUTE]

      - name: bytes_sent
        type: long
        generator: distribution
        params:
          type: lognormal
          mean: 1200
          sigma: 2.5

      - name: bytes_received
        type: long
        generator: distribution
        params:
          type: lognormal
          mean: 3500
          sigma: 2.0

      - name: session_duration_ms
        type: long
        generator: distribution
        params:
          type: lognormal
          mean: 500
          sigma: 3.0

      - name: mitre_tactic
        type: string
        nullable: true
        generator: nullable
        params:
          null_ratio: 0.82
          generator: ref_lookup
          params:
            ref: mitre_tactics
            column: tactic
            distribution: weighted

      - name: mitre_technique_id
        type: string
        nullable: true
        generator: conditional
        params:
          field: mitre_tactic
          conditions:
            - when: null
              generator: constant
              params: { value: null }
            - when: "*"
              generator: ref_lookup
              params:
                ref: mitre_tactics
                column: technique_id
                match_field: tactic
                match_value_from: mitre_tactic

      - name: geo_country
        type: string
        generator: weighted_choice
        params:
          choices:
            AE: 0.35
            US: 0.12
            CN: 0.08
            RU: 0.06
            IR: 0.05
            DE: 0.04
            GB: 0.04
            IN: 0.03
            SA: 0.03
            KR: 0.02
            OTHER: 0.18

      - name: device_hostname
        type: string
        generator: pattern
        params:
          format: "{category}-{seq:02d}.corp.local"
          categories: [fw, ids, ips, waf]

    generation:
      mode: batch_then_stream
      seed_rows: 500000
      stream_rate: "25/s"
      stream_duration: forever

  - id: threat_intel_iocs
    target: table
    namespace: soc
    table_name: threat_iocs
    format: parquet

    schema:
      - name: ioc_id
        type: string
        generator: uuid

      - name: ioc_type
        type: string
        generator: weighted_choice
        params:
          choices: { ipv4: 0.40, domain: 0.25, sha256: 0.20, url: 0.10, md5: 0.05 }

      - name: indicator
        type: string
        generator: ioc
        params:
          type_field: ioc_type    # Uses the value of ioc_type to determine IOC format

      - name: confidence
        type: integer
        generator: distribution
        params:
          type: uniform
          min: 25
          max: 100

      - name: threat_actor
        type: string
        generator: weighted_choice
        params:
          choices:
            APT33: 0.14
            APT35: 0.12
            LockBit: 0.18
            RansomHub: 0.10
            DarkVault: 0.08
            Muddy Water: 0.06
            Pulsar Kitten: 0.05
            unknown: 0.27

      - name: severity_score
        type: float
        generator: distribution
        params:
          type: normal
          mean: 6.5
          sigma: 2.0
          min: 1.0
          max: 10.0

      - name: first_seen
        type: timestamp
        generator: time_series
        params:
          start: "2025-01-01T00:00:00Z"
          end: "2026-04-01T00:00:00Z"
          pattern: uniform

      - name: last_seen
        type: timestamp
        generator: time_series
        params:
          start: "2026-01-01T00:00:00Z"
          end: "2026-04-14T00:00:00Z"
          pattern: uniform

      - name: source_feed
        type: string
        generator: weighted_choice
        params:
          choices:
            OSINT: 0.35
            commercial: 0.25
            government: 0.20
            internal: 0.15
            dark_web: 0.05

      - name: mitre_tactic
        type: string
        nullable: true
        generator: weighted_choice
        params:
          choices:
            initial-access: 0.15
            command-and-control: 0.25
            exfiltration: 0.15
            lateral-movement: 0.12
            execution: 0.10
            credential-access: 0.08
            persistence: 0.05
            null: 0.10

      - name: tags
        type: string
        generator: json_object
        params:
          fields:
            - name: active
              generator: weighted_choice
              params:
                choices: { true: 0.70, false: 0.30 }
            - name: reviewed
              generator: weighted_choice
              params:
                choices: { true: 0.45, false: 0.55 }

    generation:
      mode: batch
      seed_rows: 8000

  - id: vulnerability_scan
    target: table
    namespace: soc
    table_name: vulnerability_scan
    format: parquet

    schema:
      - name: vuln_id
        type: string
        generator: uuid

      - name: scan_timestamp
        type: timestamp
        generator: time_series
        params:
          start: "2026-03-01T00:00:00Z"
          end: "2026-04-14T00:00:00Z"
          pattern: uniform

      - name: host_ip
        type: string
        generator: ip_address
        params:
          ranges: ["10.0.0.0/8"]

      - name: hostname
        type: string
        generator: pattern
        params:
          format: "{category}-{seq:03d}.corp.local"
          categories: [srv, ws, db, app, web, dns, mail, dc]

      - name: cve_id
        type: string
        generator: pattern
        params:
          format: "CVE-{year}-{seq:05d}"
          categories: ["2024", "2025", "2026"]

      - name: cvss_score
        type: float
        generator: distribution
        params:
          type: normal
          mean: 5.5
          sigma: 2.5
          min: 0.0
          max: 10.0

      - name: severity
        type: string
        generator: conditional
        params:
          field: cvss_score
          conditions:
            - when: ">=9.0"
              generator: constant
              params: { value: "critical" }
            - when: ">=7.0"
              generator: constant
              params: { value: "high" }
            - when: ">=4.0"
              generator: constant
              params: { value: "medium" }
            - when: ">=0.1"
              generator: constant
              params: { value: "low" }
            - when: "*"
              generator: constant
              params: { value: "info" }

      - name: remediation_status
        type: string
        generator: weighted_choice
        params:
          choices: { open: 0.45, in_progress: 0.25, remediated: 0.20, accepted_risk: 0.07, false_positive: 0.03 }

      - name: business_unit
        type: string
        generator: weighted_choice
        params:
          choices:
            IT Operations: 0.25
            Engineering: 0.20
            Finance: 0.15
            HR: 0.10
            Executive: 0.08
            Customer Service: 0.12
            Legal: 0.05
            Facilities: 0.05

      - name: os
        type: string
        generator: weighted_choice
        params:
          choices:
            "Ubuntu 22.04": 0.30
            "RHEL 9": 0.25
            "Windows Server 2022": 0.20
            "Windows 11": 0.10
            "CentOS Stream 9": 0.08
            "macOS 14": 0.07

    generation:
      mode: batch
      seed_rows: 15000

correlations:
  - name: "Firewall hits on known C2 IPs"
    source_dataset: threat_intel_iocs
    source_field: indicator
    target_dataset: firewall_events
    target_field: dst_ip
    ratio: 0.03                  # 3% of firewall dst_ips are known IOCs

  - name: "Vuln scan hosts appear in firewall logs"
    source_dataset: vulnerability_scan
    source_field: host_ip
    target_dataset: firewall_events
    target_field: src_ip
    ratio: 0.80                  # 80% of firewall src_ips are known internal hosts

dashboards:
  - id: soc-overview
    title: "SOC Overview"
    description: "Real-time security operations overview"
    layout: 3-column

    charts:
      - id: total-events-24h
        title: "Events (24h)"
        type: number
        query: |
          SELECT count(*) as total_events
          FROM soc.firewall_events
          WHERE event_timestamp > current_timestamp - interval '24' hour
        position: { row: 0, col: 0, width: 6, height: 4 }
        settings:
          number_format: decimal

      - id: critical-events-24h
        title: "Critical/High Alerts (24h)"
        type: number
        query: |
          SELECT count(*) as critical_alerts
          FROM soc.firewall_events
          WHERE severity IN ('critical', 'high')
            AND event_timestamp > current_timestamp - interval '24' hour
        position: { row: 0, col: 6, width: 6, height: 4 }
        settings:
          number_format: decimal
          color: "#ef4444"

      - id: blocked-events-24h
        title: "Blocked (24h)"
        type: number
        query: |
          SELECT count(*) as blocked
          FROM soc.firewall_events
          WHERE action IN ('deny', 'drop', 'reset')
            AND event_timestamp > current_timestamp - interval '24' hour
        position: { row: 0, col: 12, width: 6, height: 4 }
        settings:
          number_format: decimal
          color: "#f97316"

      - id: active-iocs
        title: "Active IOCs"
        type: number
        query: |
          SELECT count(*) as active_iocs
          FROM soc.threat_iocs
          WHERE json_extract_scalar(tags, '$.active') = 'true'
        position: { row: 0, col: 18, width: 6, height: 4 }
        settings:
          number_format: decimal

      - id: event-volume-timeline
        title: "Event Volume (Hourly)"
        type: time_series
        query: |
          SELECT date_trunc('hour', event_timestamp) as hour,
                 count(*) as events,
                 sum(case when severity IN ('high', 'critical') then 1 else 0 end) as high_severity
          FROM soc.firewall_events
          WHERE event_timestamp > current_timestamp - interval '24' hour
          GROUP BY 1 ORDER BY 1
        position: { row: 1, col: 0, width: 16, height: 8 }
        settings:
          x_axis: hour
          y_axis: [events, high_severity]

      - id: severity-breakdown
        title: "Severity Distribution"
        type: donut
        query: |
          SELECT severity, count(*) as count
          FROM soc.firewall_events
          WHERE event_timestamp > current_timestamp - interval '24' hour
          GROUP BY 1
        position: { row: 1, col: 16, width: 8, height: 8 }
        settings:
          group_by: severity

      - id: top-blocked-destinations
        title: "Top 15 Blocked Destinations"
        type: horizontal_bar
        query: |
          SELECT dst_ip, count(*) as blocks
          FROM soc.firewall_events
          WHERE action IN ('deny', 'drop', 'reset')
          GROUP BY 1 ORDER BY 2 DESC LIMIT 15
        position: { row: 2, col: 0, width: 12, height: 8 }
        settings:
          x_axis: blocks
          y_axis: dst_ip

      - id: mitre-coverage
        title: "MITRE ATT&CK Tactic Hits"
        type: bar
        query: |
          SELECT mitre_tactic, count(*) as hits
          FROM soc.firewall_events
          WHERE mitre_tactic IS NOT NULL
          GROUP BY 1 ORDER BY 2 DESC
        position: { row: 2, col: 12, width: 12, height: 8 }
        settings:
          x_axis: mitre_tactic
          y_axis: hits

      - id: geo-distribution
        title: "Events by Country"
        type: bar
        query: |
          SELECT geo_country, count(*) as events,
                 sum(case when action IN ('deny','drop','reset') then 1 else 0 end) as blocked
          FROM soc.firewall_events
          GROUP BY 1 ORDER BY 2 DESC LIMIT 12
        position: { row: 3, col: 0, width: 12, height: 8 }
        settings:
          x_axis: geo_country
          y_axis: [events, blocked]

      - id: protocol-distribution
        title: "Protocol Split"
        type: pie
        query: |
          SELECT protocol, count(*) as count
          FROM soc.firewall_events
          GROUP BY 1
        position: { row: 3, col: 12, width: 6, height: 8 }

      - id: action-distribution
        title: "Action Breakdown"
        type: pie
        query: |
          SELECT action, count(*) as count
          FROM soc.firewall_events
          GROUP BY 1
        position: { row: 3, col: 18, width: 6, height: 8 }

  - id: threat-intelligence
    title: "Threat Intelligence"
    description: "IOC analysis and threat actor tracking"
    layout: 2-column

    charts:
      - id: threat-actor-breakdown
        title: "IOCs by Threat Actor"
        type: bar
        query: |
          SELECT threat_actor, count(*) as ioc_count,
                 round(avg(confidence), 1) as avg_confidence
          FROM soc.threat_iocs
          GROUP BY 1 ORDER BY 2 DESC
        position: { row: 0, col: 0, width: 12, height: 8 }
        settings:
          x_axis: threat_actor
          y_axis: ioc_count

      - id: ioc-type-split
        title: "IOC Types"
        type: donut
        query: |
          SELECT ioc_type, count(*) as count
          FROM soc.threat_iocs
          GROUP BY 1
        position: { row: 0, col: 12, width: 12, height: 8 }

      - id: firewall-ioc-hits
        title: "Firewall Events Matching Known IOCs"
        type: table
        query: |
          SELECT f.event_timestamp, f.src_ip, f.dst_ip,
                 t.threat_actor, t.confidence, t.ioc_type,
                 f.action, f.severity, f.mitre_tactic
          FROM soc.firewall_events f
          JOIN soc.threat_iocs t
            ON f.dst_ip = t.indicator AND t.ioc_type = 'ipv4'
          ORDER BY f.event_timestamp DESC
          LIMIT 100
        position: { row: 1, col: 0, width: 24, height: 10 }
        settings:
          limit: 100

      - id: source-feed-distribution
        title: "Intelligence Sources"
        type: pie
        query: |
          SELECT source_feed, count(*) as count
          FROM soc.threat_iocs
          GROUP BY 1
        position: { row: 2, col: 0, width: 8, height: 8 }

      - id: ioc-severity-distribution
        title: "IOC Severity Score Distribution"
        type: bar
        query: |
          SELECT
            CASE
              WHEN severity_score >= 9 THEN 'Critical (9-10)'
              WHEN severity_score >= 7 THEN 'High (7-9)'
              WHEN severity_score >= 4 THEN 'Medium (4-7)'
              ELSE 'Low (0-4)'
            END as severity_band,
            count(*) as count
          FROM soc.threat_iocs
          GROUP BY 1
          ORDER BY min(severity_score) DESC
        position: { row: 2, col: 8, width: 8, height: 8 }

      - id: mitre-tactic-intel
        title: "IOCs by MITRE Tactic"
        type: bar
        query: |
          SELECT mitre_tactic, count(*) as count
          FROM soc.threat_iocs
          WHERE mitre_tactic IS NOT NULL
          GROUP BY 1 ORDER BY 2 DESC
        position: { row: 2, col: 16, width: 8, height: 8 }

  - id: vulnerability-posture
    title: "Vulnerability Posture"
    description: "Vulnerability assessment and remediation tracking"
    layout: 3-column

    charts:
      - id: open-criticals
        title: "Open Critical Vulns"
        type: number
        query: |
          SELECT count(*) as open_critical
          FROM soc.vulnerability_scan
          WHERE severity = 'critical' AND remediation_status = 'open'
        position: { row: 0, col: 0, width: 8, height: 4 }
        settings:
          color: "#ef4444"

      - id: open-highs
        title: "Open High Vulns"
        type: number
        query: |
          SELECT count(*) as open_high
          FROM soc.vulnerability_scan
          WHERE severity = 'high' AND remediation_status = 'open'
        position: { row: 0, col: 8, width: 8, height: 4 }
        settings:
          color: "#f97316"

      - id: remediation-rate
        title: "Remediation Rate"
        type: number
        query: |
          SELECT round(
            100.0 * count(case when remediation_status = 'remediated' then 1 end) / count(*), 1
          ) as remediation_pct
          FROM soc.vulnerability_scan
        position: { row: 0, col: 16, width: 8, height: 4 }
        settings:
          number_format: percent

      - id: vuln-by-severity
        title: "Vulnerabilities by Severity"
        type: bar
        query: |
          SELECT severity,
                 count(*) as total,
                 sum(case when remediation_status = 'open' then 1 else 0 end) as open_count,
                 sum(case when remediation_status = 'remediated' then 1 else 0 end) as remediated
          FROM soc.vulnerability_scan
          GROUP BY 1
          ORDER BY CASE severity
            WHEN 'critical' THEN 1
            WHEN 'high' THEN 2
            WHEN 'medium' THEN 3
            WHEN 'low' THEN 4
            ELSE 5 END
        position: { row: 1, col: 0, width: 12, height: 8 }
        settings:
          x_axis: severity
          y_axis: [total, open_count, remediated]

      - id: vuln-by-business-unit
        title: "Open Vulns by Business Unit"
        type: horizontal_bar
        query: |
          SELECT business_unit,
                 count(*) as open_vulns,
                 round(avg(cvss_score), 1) as avg_cvss
          FROM soc.vulnerability_scan
          WHERE remediation_status IN ('open', 'in_progress')
          GROUP BY 1 ORDER BY 2 DESC
        position: { row: 1, col: 12, width: 12, height: 8 }
        settings:
          x_axis: open_vulns
          y_axis: business_unit

      - id: remediation-status
        title: "Remediation Status"
        type: donut
        query: |
          SELECT remediation_status, count(*) as count
          FROM soc.vulnerability_scan
          GROUP BY 1
        position: { row: 2, col: 0, width: 8, height: 8 }

      - id: top-cves
        title: "Most Common CVEs"
        type: table
        query: |
          SELECT cve_id,
                 count(*) as affected_hosts,
                 round(max(cvss_score), 1) as max_cvss,
                 max(severity) as severity
          FROM soc.vulnerability_scan
          WHERE remediation_status = 'open'
          GROUP BY 1
          ORDER BY max(cvss_score) DESC, count(*) DESC
          LIMIT 20
        position: { row: 2, col: 8, width: 16, height: 8 }

      - id: os-exposure
        title: "Vulnerabilities by OS"
        type: bar
        query: |
          SELECT os, count(*) as vuln_count,
                 round(avg(cvss_score), 1) as avg_cvss
          FROM soc.vulnerability_scan
          WHERE remediation_status IN ('open', 'in_progress')
          GROUP BY 1 ORDER BY 2 DESC
        position: { row: 3, col: 0, width: 24, height: 8 }
        settings:
          x_axis: os
          y_axis: [vuln_count]
```

### 1.5 Example Scenario: E-commerce Orders (Migration)

Create `components/external-system/scenarios/ecommerce-orders.yaml` by migrating the logic from the existing data-generator into the new YAML format. This validates that the schema can express what the existing generator already does.

Use the Phase 0 investigation findings to produce this file. The schema, generation parameters, and any existing dashboards from the bi-dashboard-lakehouse template should be captured in the YAML.

### 1.6 Schema Validation Script

Create `components/external-system/scenarios/validate_scenario.py`:
- Reads a scenario YAML file
- Validates against the schema (required fields, valid types, valid generator names)
- Checks that correlations reference existing datasets/fields
- Checks that dashboard queries reference tables that exist in the datasets
- Reports all errors with file/line references
- Exit 0 if valid, exit 1 if errors

This does NOT require the generator engine to run — it's a static validation tool that can be used during scenario authoring.

### 1.7 Deliverables

1. `components/external-system/scenarios/_schema.md` — human-readable documentation of the full schema
2. `components/external-system/scenarios/soc-firewall-logs.yaml` — cybersecurity scenario (from above, adapt based on Phase 0 findings)
3. `components/external-system/scenarios/ecommerce-orders.yaml` — migrated from existing data-generator
4. `components/external-system/scenarios/validate_scenario.py` — validation script
5. Run the validation script against both scenario files, confirm both pass

**STOP after Phase 1 deliverables. Do not proceed to Phase 2 without explicit confirmation.**

**Architect review gate:** The architect agent reviews:
- Scenario YAML schema completeness — can it express the existing data-generator's ecommerce-orders scenario without loss of functionality?
- Generator library coverage — are there gaps that would block the SOC scenario?
- Dashboard schema — can the SQL queries be reliably translated to Metabase API calls?
- Validation script correctness — run it against both scenario files, confirm it catches intentional errors (introduce a few and verify)
- Schema documentation (`_schema.md`) accuracy and completeness

---

## Phase 2 — External System Component Manifest

Create the manifest and supporting files for the External System component.

### 2.1 Manifest Design Decisions

Based on Phase 0 findings, the External System component:

- **IS a real container** using image `demoforge/external-system:latest` with `build_context: .` for dev mode
- **Category:** `sources` (new category — represents external data sources)
- **Has NO web UI** (it's a background data generator)
- **Provides:** `s3` and `structured-data` and `aistor-tables` connection types (pushes data to MinIO)
- **Accepts:** nothing (it's a source, not a sink)
- **Key environment variables:**
  - `ES_SCENARIO` — scenario profile ID (maps to YAML file)
  - `ES_MODE` — `"seed"` (batch only, exit when done) | `"seed_and_stream"` (batch then continuous) | `"stream"` (streaming only)
  - `ES_SEED_MULTIPLIER` — scale factor for seed_rows (e.g., 0.1 for quick demo, 1.0 for normal, 5.0 for large)
  - `ES_STREAM_RATE_MULTIPLIER` — scale factor for stream rates
  - `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY` — auto-configured from edge to MinIO
  - `ICEBERG_CATALOG_URI` — auto-configured from edge (for aistor-tables)
  - `METABASE_URL` — auto-configured from edge to Metabase (if connected)
  - `TRINO_HOST`, `TRINO_PORT` — auto-configured from edge to Trino (for dashboard provisioning)

### 2.2 Properties Panel Fields

Exposed through `connections.provides[*].config_schema`:

| Field | Label | Type | Default | Notes |
|-------|-------|------|---------|-------|
| `scenario` | Scenario | select | (first available) | Populated from scenario YAML files |
| `seed_multiplier` | Data Volume | select | "1.0" | Options: "0.1" (Quick), "0.5" (Light), "1.0" (Normal), "3.0" (Heavy), "5.0" (Massive) |
| `stream_mode` | After Seeding | select | "stream" | Options: "stop" (seed only), "stream" (continue generating) |

### 2.3 Connection Configuration

When connected to MinIO (s3/aistor-tables edge):
- The compose generator auto-resolves `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`
- If the edge type is `aistor-tables`, also resolve `ICEBERG_CATALOG_URI`

When connected to Metabase (new edge type `dashboard-provision`):
- Resolve `METABASE_URL` as `http://{project_name}-{metabase_node_id}:3000`
- The External System container will call Metabase API after seeding to create dashboards

When connected to Trino (new edge type or reuse `sql-query`):
- Resolve `TRINO_HOST` and `TRINO_PORT`
- Needed for dashboard provisioning (Metabase needs a Trino data source)

**Important:** The dashboard provisioning connection (External System → Metabase) is optional. If not connected, the container just generates data and skips dashboard creation. The FA can always manually create dashboards.

### 2.4 New Connection Type: `dashboard-provision`

- **Color:** `#8b5cf6` (violet)
- **Label:** "Dashboard"
- **Description:** "Provisions pre-built dashboards and data sources"
- **Direction:** External System → Metabase (or Superset in future)

Add to:
- `ConnectionType` union in `frontend/src/types/index.ts`
- `connectionColors` in `frontend/src/lib/connectionMeta.ts`
- `_edge_env_map` in `compose_generator.py` (no additional env mapping needed beyond METABASE_URL)
- Handle in compose generator's auto-configuration section

### 2.5 New Component Category: `sources`

- **Color/theme:** Use a distinct color in the node renderer that differentiates from existing categories
- **Icon default:** `database-zap` or similar from lucide
- **Position in component palette:** Before "tooling"

### 2.6 Node Display

The External System node should show:
- **Primary label:** The FA's custom `display_name` (defaults to `display.default_name` from scenario YAML)
- **Secondary label/subtitle:** `display.default_subtitle` from scenario YAML
- **Badge:** Scenario name (e.g., "SOC Firewall & Threat Intel")

Check Phase 0 findings for how node display currently works and whether subtitle rendering exists. If it doesn't, note it as a UI enhancement but DO NOT implement it in this phase — just use the existing display_name field.

### 2.7 Manifest File

Create `components/external-system/manifest.yaml` following the patterns found in Phase 0. Use the existing `data-generator` manifest as the closest reference.

### 2.8 Compose Generator Changes

Modify `compose_generator.py` to handle:
1. The `dashboard-provision` edge type — resolve `METABASE_URL`
2. Ensure `ES_SCENARIO` env var is passed through from node config
3. Mount the `scenarios/` directory into the container (static mount from `components/external-system/scenarios/` → `/app/scenarios/`)
4. Add `dashboard-provision` to `_edge_env_map` if needed

### 2.9 Frontend Changes

1. Add `"dashboard-provision"` to `ConnectionType` 
2. Add color/label in `connectionMeta.ts`
3. Add `"sources"` category if it doesn't exist
4. Verify that the scenario dropdown populates from the manifest's config_schema options

### 2.10 Deliverables

1. `components/external-system/manifest.yaml`
2. `compose_generator.py` changes (minimal, targeted)
3. Frontend type/color additions
4. Verify: create a test template YAML that wires External System → MinIO → Trino → Metabase. Confirm compose generation produces valid YAML (test via the existing compose generation test path if one exists, otherwise manual validation).

**STOP after Phase 2 deliverables. Do not proceed to Phase 3 without explicit confirmation.**

**Architect review gate:** The architect/senior agent reviews:
- Manifest follows existing patterns exactly (compare field-by-field with data-generator and nginx manifests)
- Compose generator changes are minimal and surgical — no refactoring of existing logic
- Frontend changes compile cleanly (`npm run build`)
- Backend starts without errors
- New connection type `dashboard-provision` doesn't interfere with existing connection resolution

**Playwright MCP E2E tests:** Execute TEST 2.1 through TEST 2.6 as defined in the "Agent Review, Validation & Testing Requirements" section. ALL tests must pass. TEST 2.6 (regression on existing templates) is especially critical — if it fails, something broke and must be fixed before proceeding.

---

## Phase 3 — Generator Engine (Container)

Build the Python container that reads scenario YAMLs and generates data.

### 3.1 Container Structure

```
components/external-system/
├── manifest.yaml
├── Dockerfile
├── requirements.txt
├── scenarios/
│   ├── _schema.md
│   ├── soc-firewall-logs.yaml
│   ├── ecommerce-orders.yaml
│   └── validate_scenario.py
├── src/
│   ├── __init__.py
│   ├── main.py              # Entry point
│   ├── scenario_loader.py   # YAML parsing + validation
│   ├── generators/
│   │   ├── __init__.py
│   │   ├── base.py          # Generator protocol/base class
│   │   ├── basic.py         # uuid, constant, auto_increment, enum
│   │   ├── choice.py        # weighted_choice, uniform_choice, sequence_from
│   │   ├── distribution.py  # distribution (normal, lognormal, etc.)
│   │   ├── temporal.py      # timestamp, time_series, date
│   │   ├── network.py       # ip_address, mac_address, ioc
│   │   ├── text.py          # pattern, text_block, faker
│   │   ├── reference.py     # ref_lookup, ref_sample
│   │   ├── compound.py      # nullable, conditional, json_object, correlation
│   │   └── geo.py           # geo_coordinate
│   ├── writers/
│   │   ├── __init__.py
│   │   ├── iceberg_writer.py   # Write to AIStor via pyiceberg
│   │   └── object_writer.py    # Write raw objects to MinIO via minio SDK
│   ├── provisioners/
│   │   ├── __init__.py
│   │   └── metabase.py      # Metabase API dashboard provisioner
│   └── correlation_engine.py   # Pre-compute correlation pools from reference data
```

### 3.2 Entry Point Logic (`main.py`)

```
1. Load scenario YAML from /app/scenarios/{ES_SCENARIO}.yaml
2. Validate scenario (fail fast with clear error)
3. Wait for MinIO to be healthy (retry loop on S3_ENDPOINT)
4. Load reference data into memory
5. Pre-compute correlation pools (sample from reference data based on ratios)
6. For each dataset with mode "batch" or "batch_then_stream":
   a. Create Iceberg namespace if needed
   b. Create Iceberg table if needed (from schema)
   c. Generate seed_rows * ES_SEED_MULTIPLIER rows
   d. Write in batches (configurable batch size, default 10000 rows)
   e. Log progress: "[firewall_events] Seeded 500,000 rows in 45s"
7. If METABASE_URL is set and dashboards exist in scenario:
   a. Wait for Metabase to be healthy
   b. Wait for Trino to be healthy
   c. Create Trino data source in Metabase
   d. Create dashboards and charts via Metabase API
   e. Log: "[dashboards] Created 3 dashboards with 25 charts"
8. If stream mode is active:
   a. Start streaming threads per dataset (where mode includes "stream")
   b. Generate rows at stream_rate * ES_STREAM_RATE_MULTIPLIER
   c. Run until container is stopped
9. If seed-only mode: exit 0
```

### 3.3 Key Libraries

```
pyiceberg>=0.9.0          # Iceberg table operations
pyarrow>=15.0.0           # Parquet/Arrow data
minio>=7.2.0              # MinIO object operations  
pyyaml>=6.0               # YAML parsing
faker>=28.0.0             # Faker generator delegate
requests>=2.31.0          # Metabase API calls
```

### 3.4 Generator Protocol

```python
class Generator(Protocol):
    def setup(self, params: dict, context: GeneratorContext) -> None: ...
    def generate(self) -> Any: ...
    def generate_batch(self, n: int) -> list[Any]: ...  # Optional optimization
```

`GeneratorContext` provides access to:
- Reference data (loaded from scenario)
- Correlation pools (pre-computed)
- Other field values in the current row (for conditional/correlation generators)
- Row index (for auto_increment, sequence_from)

### 3.5 Writer: Iceberg

Use `pyiceberg` REST catalog client pointing at `ICEBERG_CATALOG_URI`:
- Create namespace via catalog API
- Create table from schema (convert scenario types to Iceberg types)
- Write batches as PyArrow RecordBatches → Parquet data files

Type mapping:
| Scenario Type | Iceberg Type | PyArrow Type |
|---------------|-------------|--------------|
| string | StringType | pa.string() |
| integer | IntegerType | pa.int32() |
| long | LongType | pa.int64() |
| float | FloatType | pa.float32() |
| double | DoubleType | pa.float64() |
| boolean | BooleanType | pa.bool_() |
| timestamp | TimestampType (μs, UTC) | pa.timestamp('us', tz='UTC') |
| date | DateType | pa.date32() |
| decimal | DecimalType(38,10) | pa.decimal128(38, 10) |
| binary | BinaryType | pa.binary() |

### 3.6 Writer: Object

Use `minio` Python SDK:
- Create bucket if not exists
- Write objects with prefix from scenario
- For JSON: serialize dict to JSON bytes
- For CSV: write row as CSV line
- For binary: generate random bytes of configured size
- Set content-type metadata appropriately

### 3.7 Provisioner: Metabase

Metabase API sequence:
1. `POST /api/session` — authenticate (default admin: email `admin@demoforge.local`, password from env or default)
2. Wait for setup: `GET /api/session/properties` — check if setup is complete; if not, run initial setup via `POST /api/setup`
3. `POST /api/database` — create Trino database connection (engine: `starburst`, host, port, user from env)
4. `POST /api/database/{id}/sync_schema` — trigger schema sync, poll until complete
5. For each dashboard:
   a. `POST /api/dashboard` — create empty dashboard
   b. For each chart:
      - `POST /api/dataset` — test query (optional, validates SQL)
      - `POST /api/card` — create "question" (native query) with visualization settings
      - `PUT /api/dashboard/{id}` — add cards to dashboard with positions
6. Log dashboard URLs for FA reference

### 3.8 Deliverables

1. `components/external-system/Dockerfile`
2. `components/external-system/requirements.txt`
3. `components/external-system/src/` — all Python source files
4. Working: `docker build` succeeds
5. Working: container starts with `ES_SCENARIO=soc-firewall-logs` and:
   - Creates Iceberg tables via REST catalog
   - Seeds data
   - Provisions Metabase dashboards (if METABASE_URL set)
   - Streams data (if mode = seed_and_stream)
6. Test with the ecommerce-orders scenario as well

**STOP after Phase 3 deliverables. Do not proceed to Phase 4 without explicit confirmation.**

**Architect review gate:** The architect/senior agent reviews:
- Generator engine architecture — clean separation of concerns, no monolithic functions
- Error handling in all writers — what happens when MinIO is slow? When Metabase isn't ready? When a query fails?
- Memory management — generating 500K rows shouldn't OOM the container; verify batch processing works
- Correlation engine correctness — verify the 3% IOC hit ratio actually produces ~3% in the generated data
- Dockerfile follows best practices (multi-stage build if appropriate, minimal image size, non-root user)
- All Python code has type hints and docstrings on public functions

**Playwright MCP E2E tests:** Execute TEST 3.1 through TEST 3.6 as defined in the "Agent Review, Validation & Testing Requirements" section. ALL tests must pass. Key validations:
- TEST 3.3 (cross-table join) validates that the correlation engine works — if this returns empty results, the correlation logic is broken
- TEST 3.4 (Metabase dashboards) validates end-to-end provisioning — every chart must render with data, not just exist as an empty container
- TEST 3.5 (streaming) validates the long-running behavior — the container must continue generating without memory leaks or connection exhaustion

**Also re-run all Phase 2 tests** to confirm nothing regressed during Phase 3 implementation.

---

## Phase 4 — Template & Integration Testing

### 4.1 Demo Template: Sovereign Cyber Data Lake

Create `demo-templates/sovereign-cyber-data-lake.yaml`:

```yaml
_template:
  name: Sovereign Cyber Data Lake
  tier: advanced
  category: cybersecurity
  tags: [cybersecurity, soc, siem, threat-intelligence, iceberg, trino, metabase, aistor-tables]
  description: "Security operations data lake with firewall logs, threat intelligence, and vulnerability data — unified in MinIO AIStor with Iceberg tables and interactive dashboards"
  objective: "Show how MinIO AIStor Tables unifies structured security logs, semi-structured threat intel, and enables real-time SOC analytics — all sovereign, on-prem, no hyperscaler dependency"
  minio_value: "MinIO AIStor is the single sovereign data store for ALL security telemetry — structured Iceberg tables for logs and alerts, objects for threat feeds and malware samples — queryable through standard SQL, visualized in real-time dashboards"
  estimated_resources:
    memory: 6GB
    cpu: 6
    containers: 5
  external_dependencies: []
  walkthrough:
    - step: Deploy the stack
      description: "Click Deploy to start MinIO AIStor, Trino, Metabase, and the External System data generators"
    - step: Watch data flow
      description: "The External System nodes generate realistic SOC data and push it into MinIO AIStor as Iceberg tables"
    - step: Open Metabase dashboards
      description: "Pre-built SOC Overview, Threat Intelligence, and Vulnerability Posture dashboards are automatically provisioned"
    - step: Run ad-hoc queries
      description: "Open Trino UI and run cross-table queries: join firewall logs with threat IOCs to find compromised hosts"
    - step: Show the unified story
      description: "Open MinIO Console to show structured Iceberg tables AND raw threat feed objects in the same namespace"
  se_guide:
    pitch: "Cybersecurity teams drown in fragmented data — logs in SIEM, IOCs in TIP, vulns in scanners, reports in SharePoint. AIStor Tables unifies it all in one sovereign platform."
    audience: "CISOs, SOC managers, security architects, data platform leads"
    talking_points:
      - "SIEM vendors charge per GB ingested — at national SOC scale that's millions per year. MinIO + Trino + Metabase is 10-50x cheaper."
      - "UAE PDPL requires data sovereignty — this runs entirely on-prem, zero hyperscaler dependency."
      - "Iceberg V3 REST catalog is built into AIStor — no separate Hive metastore, no Polaris, no catalog tax."
      - "Same data feeds dashboards AND ML models — no ETL to a separate feature store."
      - "Open standards: swap Trino for Spark, Metabase for Superset, add DuckDB for analyst notebooks — all against the same data."
    demo_flow:
      - step: 1
        action: "Click Deploy, wait for all containers to go green"
        say: "We're spinning up a complete sovereign security data lake — MinIO as the data store, Trino as the query engine, Metabase for dashboards."
      - step: 2
        action: "Point to the External System nodes on canvas"
        say: "These represent your existing security systems — firewall, threat intel feeds, vulnerability scanners. They're pushing data into MinIO in real-time."
      - step: 3
        action: "Open Metabase, show SOC Overview dashboard"
        say: "These dashboards were auto-provisioned. Event volume, severity breakdown, MITRE ATT&CK coverage, geographic distribution — all queryable in real-time."
      - step: 4
        action: "Click into Threat Intelligence dashboard, show the IOC-firewall join table"
        say: "This is the power of unified data — we're joining firewall logs with threat intelligence IOCs in a single SQL query. Try doing that when your logs are in Splunk and your IOCs are in a separate TIP."
      - step: 5
        action: "Open MinIO Console, show the Iceberg tables and raw objects"
        say: "Everything lives here — structured tables, semi-structured feeds, unstructured artifacts. One platform, one security model, one set of encryption keys. Full sovereignty."
    common_questions:
      - q: "How does this compare to Splunk or Microsoft Sentinel?"
        a: "Splunk/Sentinel charge per GB ingested and lock you into their query language. This stack uses open SQL, open Iceberg format, and costs a fraction. You own the data and the infrastructure."
      - q: "Can this handle our data volumes?"
        a: "MinIO AIStor scales to exabytes. The same architecture runs at Fortune 100 scale."
      - q: "What about real-time alerting?"
        a: "This demo focuses on analytics. For real-time alerting, you'd add a streaming layer (Kafka/Redpanda) — DemoForge has those components too."
  fa_ready: true
  updated_at: "2026-04-14"

id: template-sovereign-cyber-data-lake
name: "Sovereign Cyber Data Lake"
description: "Security data lake: External Systems → MinIO AIStor → Trino → Metabase dashboards"

networks:
  - name: default
    subnet: 172.20.0.0/16
    driver: bridge

nodes:
  - id: fw-gen
    component: external-system
    position: { x: -300, y: 0 }
    display_name: "Perimeter Firewall"
    config:
      ES_SCENARIO: soc-firewall-logs
      ES_SEED_MULTIPLIER: "1.0"

  - id: minio-1
    component: minio
    position: { x: 100, y: 100 }
    display_name: "MinIO AIStor"
    config:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin

  - id: trino
    component: trino
    position: { x: 400, y: 100 }
    display_name: "Trino"
    config: {}

  - id: metabase
    component: metabase
    position: { x: 700, y: 100 }
    display_name: "Metabase"
    config: {}

clusters: []

edges:
  - id: e-fw-minio
    source: fw-gen
    target: minio-1
    connection_type: aistor-tables
    network: default
    auto_configure: true
    label: "Firewall + IOC + Vuln data"
    connection_config: {}

  - id: e-trino-minio
    source: trino
    target: minio-1
    connection_type: aistor-tables
    network: default
    auto_configure: true
    label: "Iceberg catalog"
    connection_config: {}

  - id: e-metabase-trino
    source: metabase
    target: trino
    connection_type: sql-query
    network: default
    auto_configure: true
    label: "SQL queries"
    connection_config: {}

  - id: e-fw-metabase
    source: fw-gen
    target: metabase
    connection_type: dashboard-provision
    network: default
    auto_configure: true
    label: "Dashboard provisioning"
    connection_config: {}

groups: []
sticky_notes: []

resources:
  default_memory: 512m
  default_cpu: 0.5
  max_memory: 3g
  max_cpu: 2.0
  total_memory: 10g
  total_cpu: 8.0
```

### 4.2 Integration Test

1. Load the template via the DemoForge API
2. Verify compose generation produces valid Docker Compose YAML
3. Deploy locally (if environment allows)
4. Verify:
   - External System container starts, reads scenario, creates tables
   - Data appears in MinIO (check via mc or Console)
   - Trino can query the Iceberg tables
   - Metabase dashboards are provisioned and show data
   - Streaming generates new data over time

### 4.3 Second Template: E-commerce Lakehouse (Migration)

Optionally create a variant of `bi-dashboard-lakehouse` that uses the External System component instead of the existing data-generator, proving backward compatibility.

### 4.4 Deliverables

1. `demo-templates/sovereign-cyber-data-lake.yaml`
2. Integration test results (compose generation, deployment, data flow)
3. (Optional) Migrated bi-dashboard-lakehouse template

**STOP after Phase 4. Review with Ahmad before any further work.**

**Architect review gate — FINAL:** The architect/senior agent conducts a comprehensive final review:
- Full codebase diff review: every file changed or added across all phases
- Verify no unintended side effects on any existing component
- Review the template YAML for correctness (all node IDs, edge references, config keys)
- Review SE guide content for accuracy (talking points, common questions)
- Confirm all new files follow the project's naming conventions and directory structure

**Playwright MCP E2E tests — FULL SUITE:** Execute ALL tests from all phases:
- TEST 2.1–2.6 (component and compose validation + regression)
- TEST 3.1–3.6 (data generation and dashboard provisioning)
- TEST 4.1–4.4 (template gallery, full deployment, SE guide, cleanup)

**All tests must pass in a single clean run.** If any test fails, fix and re-run the entire suite — not just the failing test. The final test report (with screenshots) is a required deliverable for Phase 4.

**Produce a final summary document** listing:
1. All files created (with paths)
2. All files modified (with paths and summary of changes)
3. All new dependencies introduced
4. Any known limitations or future work items
5. The complete Playwright test report with pass/fail status and screenshot evidence
