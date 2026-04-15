# DemoForge: CPX Demo — Analytics Scenario & Demo Queries

## Overview

This is the third spec for the CPX Sovereign Cyber Data Lake demo. It focuses exclusively on **Act 1: Data Analytics** — the production-ready demo. AI/ML (Act 2) is documented as an experimental appendix but is NOT built or tested in this spec.

**Prerequisites:** `claude-code-external-system-spec.md` (External System + Scenario Engine) and `claude-code-aistor-pipeline-spec.md` (AIStor Tables + Metabase + Canvas Image) are implemented.

**What this spec adds:**
1. Split SOC scenario into 3 separate scenario YAMLs for 3 canvas nodes
2. Unstructured data generation (threat feed objects + malware samples alongside Iceberg tables)
3. Pre-configured demo queries — saved Metabase "Questions" the FA clicks through live
4. Data flow visualization strategy — how the audience sees data arriving
5. Complete Analytics-only demo template
6. Demo script for the CPX session (Analytics focus, ~25 minutes)

---

## Agent Review, Validation & Testing Requirements

Same standards as the previous two specs: architect review at every gate, Playwright MCP E2E tests, regression checks, no proceeding on failure.

---

## Phase 0 — Read-Only Investigation

**DO NOT write any code. Only read and report.**

### 0.1 Existing SOC Scenario

- Verify `soc-firewall-logs.yaml` from Spec 1 is implemented and working
- Check the generator engine: does `target: "object"` mode work? Can it write raw JSON/binary objects to MinIO?
- Check if `mirror_to_table` is implemented (creates an Iceberg metadata table for objects)
- How does the dashboard provisioner create Metabase "Questions" (saved queries) vs dashboard charts? Are they the same API endpoint or different?

### 0.2 Metabase Saved Questions API

Research:
- `POST /api/card` — this creates a "Question" (saved query). Is it the same call used for dashboard charts?
- Can a Question exist independently of a dashboard (visible from Metabase home / collection)?
- Can a Question be organized into a "Collection" (folder) in Metabase?
- Can a Question's SQL be pre-filled and the result visualization type set (table, chart)?
- What's the difference between a "Question" on a dashboard vs a standalone "Question"?

### 0.3 Metabase Auto-Refresh & Presentation Mode

- Does Metabase support auto-refresh on dashboards? What's the minimum interval?
- Can auto-refresh be configured via the API during provisioning?
- Is there a "full-screen" or "presentation mode" for dashboards?

### 0.4 S3 File Browser Component

- `components/s3-file-browser/manifest.yaml` — full contents
- What does it show? Bucket listing? File preview?
- Would it be useful as a "data is landing" visual during seeding?

### 0.5 Report

Key questions to answer:
1. Can the provisioner create standalone Metabase Questions (not just dashboard charts)?
2. Can those Questions be organized into a named Collection?
3. Does Metabase presentation mode exist and can it be linked directly?

**STOP after report. Do not proceed without confirmation.**

**Architect review gate:** Confirm that the Metabase API supports everything the saved queries feature needs.

---

## Phase 1 — Split SOC Scenarios + Unstructured Data

Split the single SOC scenario into 3 focused scenario files and add unstructured data generation to the threat intel scenario.

### 1.1 Scenario: SOC Firewall Events

Create `components/external-system/scenarios/soc-firewall-events.yaml`:

- **ID:** `soc-firewall-events`
- **Display:** default_name "Perimeter Firewall", subtitle "Enterprise IDS/IPS"
- **Datasets:** `firewall_events` Iceberg table — same schema as original spec
- **Generation:** 500K seed rows, streaming at 25/s after seed
- **Dashboards:** SOC Overview dashboard (event volume, severity, MITRE, geo, top blocked, protocol, action)
- **Saved queries:** All 10 demo queries (see Phase 2) — this scenario provisions the query collection since it starts last and all correlated data is available
- **Reference data:** known_c2_ips, mitre_tactics
- **Correlations:**
  - 3% of dst_ips match threat_iocs.indicator (resolved cross-scenario at runtime)
  - 80% of src_ips match vulnerability_scan.host_ip (resolved cross-scenario at runtime)
- **Startup delay:** `ES_STARTUP_DELAY=30` — waits 30s for other scenarios to seed correlation data

### 1.2 Scenario: SOC Threat Intelligence

Create `components/external-system/scenarios/soc-threat-intel.yaml`:

- **ID:** `soc-threat-intel`
- **Display:** default_name "Threat Intel Feeds", subtitle "STIX/TAXII + OSINT"
- **Datasets:**
  - `threat_iocs` Iceberg table — structured IOC records (8K rows, batch)
  - `threat_feeds_raw` objects — raw STIX 2.1 JSON bundles in `threat-intel/feeds/stix/` (500 objects, batch)
  - `malware_samples` objects — synthetic binary blobs in `malware-vault/samples/` (200 objects, batch)
    - Each object has metadata set via MinIO object tags: sha256, file_type, sandbox_verdict, threat_actor
    - `mirror_to_table` creates `soc.malware_metadata` Iceberg table with extracted fields
- **Generation:** All batch, no streaming
- **Dashboards:** Threat Intelligence dashboard (actor breakdown, IOC types, source feeds, severity bands, MITRE by tactic)

**Unstructured data — what the audience sees:**

The STIX JSON objects are realistic STIX 2.1 bundles. When the FA opens MinIO Console and navigates to `threat-intel/feeds/stix/`, they see hundreds of JSON files. Clicking one shows a structured STIX bundle — the "semi-structured" story.

The malware samples in `malware-vault/samples/` are synthetic binary blobs (random bytes, 10KB-500KB). The FA shows the bucket listing — "unstructured binaries coexist with structured tables." The `malware_metadata` Iceberg table makes metadata queryable without accessing raw files.

### 1.3 Scenario: SOC Vulnerability Scanner

Create `components/external-system/scenarios/soc-vuln-scan.yaml`:

- **ID:** `soc-vuln-scan`
- **Display:** default_name "Vulnerability Scanner", subtitle "Qualys / Nessus"
- **Datasets:** `vulnerability_scan` Iceberg table — same schema as original spec (15K rows, batch)
- **Generation:** Batch only
- **Dashboards:** Vulnerability Posture dashboard

### 1.4 Cross-Scenario Correlation

The firewall generator checks if `soc.threat_iocs` and `soc.vulnerability_scan` tables exist and samples from them for correlation. Falls back to reference data if tables don't exist yet.

**Startup ordering:** The firewall External System has `ES_STARTUP_DELAY=30`, giving threat intel and vuln scan containers time to seed first. This ensures correlation tables are populated when the firewall generator needs them.

### 1.5 Deliverables

1. `components/external-system/scenarios/soc-firewall-events.yaml`
2. `components/external-system/scenarios/soc-threat-intel.yaml`
3. `components/external-system/scenarios/soc-vuln-scan.yaml`
4. Cross-scenario correlation logic verified
5. Object generation verified: STIX JSON + malware binaries appear in MinIO
6. `mirror_to_table` verified: `soc.malware_metadata` queryable via Trino

**STOP after Phase 1. Do not proceed without confirmation.**

**Architect review gate:** Verify 3 External System containers coexist without namespace/bucket collisions. Correlation produces meaningful join results.

**Playwright MCP E2E tests:**

```
TEST 1.1: Three External Systems deploy to one MinIO
  1. Create canvas: 3 External System nodes + MinIO AIStor + Trino
  2. Configure each with its scenario
  3. Connect all to MinIO (aistor-tables), connect Trino to MinIO
  4. Deploy and wait for healthy
  5. Open MinIO Console
  6. Verify: Iceberg tables exist (firewall_events, threat_iocs, vulnerability_scan, malware_metadata)
  7. Verify: Object buckets exist (threat-intel, malware-vault)
  8. Screenshot: MinIO Console

TEST 1.2: Unstructured data coexists with tables
  1. In MinIO Console, navigate to threat-intel/feeds/stix/
  2. Verify JSON objects exist (click one, verify valid STIX structure)
  3. Navigate to malware-vault/samples/
  4. Verify binary objects exist with metadata tags
  5. Query Trino: SELECT count(*) FROM soc.malware_metadata
  6. Verify mirror table has rows
  7. Screenshot: objects + mirror table query

TEST 1.3: Cross-scenario correlation produces results
  1. After all seeding completes, run in Trino:
     SELECT f.dst_ip, t.threat_actor FROM soc.firewall_events f
     JOIN soc.threat_iocs t ON f.dst_ip = t.indicator WHERE t.ioc_type = 'ipv4' LIMIT 10
  2. Verify non-empty results
  3. Screenshot: join results
```

---

## Phase 2 — Pre-Configured Demo Queries & Data Flow Visibility

### 2.1 Saved Queries — The Concept

During the live demo, the FA needs "ready-to-run" queries the audience watches them click through. These are provisioned in Metabase as **standalone Questions** in a **Collection** called "CPX Demo Queries." The FA opens Metabase, navigates to this collection, and clicks through them in presentation order. Each query name IS the talking point.

### 2.2 Scenario YAML Extension: saved_queries

Add a `saved_queries` section to the scenario YAML schema:

```yaml
saved_queries:
  collection: string              # Metabase Collection name
  queries:
    - id: string
      title: string               # Display name — this IS the talking point
      description: string         # Brief context shown below the query
      query: |                    # Trino-compatible SQL
        SELECT ...
      visualization: string       # "table" | "bar" | "line" | "number" | "pie"
      order: int                  # Display order in collection
```

### 2.3 The 10 Demo Queries

Added to `soc-firewall-events.yaml` under `saved_queries.collection: "CPX Demo Queries"`:

```yaml
saved_queries:
  collection: "CPX Demo Queries"
  queries:
    - id: q-event-count
      title: "1. Total firewall events ingested"
      description: "Confirms data volume"
      order: 1
      visualization: number
      query: |
        SELECT count(*) as total_events FROM soc.firewall_events

    - id: q-all-tables
      title: "2. All tables in the data lake"
      description: "Everything queryable via Iceberg catalog"
      order: 2
      visualization: table
      query: |
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_schema = 'soc'
        ORDER BY table_name

    - id: q-ioc-hits
      title: "3. Connections to known C2 infrastructure"
      description: "Joins firewall logs with threat IOCs — the unified data story"
      order: 3
      visualization: table
      query: |
        SELECT f.event_timestamp, f.src_ip, f.dst_ip,
               t.threat_actor, t.confidence, f.action, f.severity, f.mitre_tactic
        FROM soc.firewall_events f
        JOIN soc.threat_iocs t ON f.dst_ip = t.indicator AND t.ioc_type = 'ipv4'
        WHERE t.confidence > 60
        ORDER BY f.event_timestamp DESC LIMIT 50

    - id: q-actor-activity
      title: "4. Threat actor activity summary"
      description: "Which actors are most active against the network?"
      order: 4
      visualization: bar
      query: |
        SELECT t.threat_actor,
               count(*) as attempts,
               count(DISTINCT f.src_ip) as targeted_hosts,
               sum(case when f.action IN ('deny','drop','reset') then 1 else 0 end) as blocked
        FROM soc.firewall_events f
        JOIN soc.threat_iocs t ON f.dst_ip = t.indicator AND t.ioc_type = 'ipv4'
        GROUP BY 1 ORDER BY 2 DESC

    - id: q-mitre
      title: "5. MITRE ATT&CK tactic detections"
      description: "What techniques are we detecting and blocking?"
      order: 5
      visualization: bar
      query: |
        SELECT mitre_tactic, count(*) as detections,
               round(100.0 * sum(case when action IN ('deny','drop') then 1 else 0 end) / count(*), 1) as block_rate_pct
        FROM soc.firewall_events
        WHERE mitre_tactic IS NOT NULL
        GROUP BY 1 ORDER BY 2 DESC

    - id: q-exposed-hosts
      title: "6. Highest-risk hosts: unpatched + suspicious traffic"
      description: "Cross-correlates vulns with firewall activity — the priority list"
      order: 6
      visualization: table
      query: |
        SELECT v.hostname, v.host_ip, v.business_unit,
               count(DISTINCT v.cve_id) as open_vulns,
               max(v.cvss_score) as max_cvss,
               sum(case when f.action IN ('deny','drop') then 1 else 0 end) as blocked_connections
        FROM soc.vulnerability_scan v
        JOIN soc.firewall_events f ON v.host_ip = f.src_ip
        WHERE v.remediation_status = 'open' AND v.severity IN ('critical', 'high')
        GROUP BY 1, 2, 3
        HAVING blocked_connections > 0
        ORDER BY max_cvss DESC, blocked_connections DESC LIMIT 20

    - id: q-lateral
      title: "7. Lateral movement patterns"
      description: "Internal-to-internal traffic on suspicious ports"
      order: 7
      visualization: table
      query: |
        SELECT f.src_ip, f.dst_ip, f.dst_port, f.protocol,
               count(*) as events,
               min(f.event_timestamp) as first_seen,
               max(f.event_timestamp) as last_seen
        FROM soc.firewall_events f
        WHERE f.mitre_tactic = 'lateral-movement'
          AND f.src_ip LIKE '10.%' AND f.dst_ip LIKE '10.%'
        GROUP BY 1, 2, 3, 4
        ORDER BY 5 DESC LIMIT 20

    - id: q-malware
      title: "8. Malware samples by verdict and actor"
      description: "Structured metadata from unstructured binary objects"
      order: 8
      visualization: bar
      query: |
        SELECT threat_actor, sandbox_verdict, count(*) as samples,
               round(avg(file_size_bytes) / 1024, 1) as avg_size_kb
        FROM soc.malware_metadata
        GROUP BY 1, 2 ORDER BY 3 DESC

    - id: q-intel-freshness
      title: "9. Threat intelligence freshness by source"
      description: "How current is the intel?"
      order: 9
      visualization: table
      query: |
        SELECT source_feed, count(*) as total_iocs,
               count(case when json_extract_scalar(tags, '$.active') = 'true' then 1 end) as active,
               max(last_seen) as most_recent,
               round(avg(confidence), 0) as avg_confidence
        FROM soc.threat_iocs
        GROUP BY 1 ORDER BY 2 DESC

    - id: q-streaming
      title: "10. Live data — run this twice to see growth"
      description: "Proves streaming is active"
      order: 10
      visualization: number
      query: |
        SELECT count(*) as total_events,
               max(event_timestamp) as latest_event
        FROM soc.firewall_events
```

### 2.4 Provisioner Update

Extend the External System provisioner to handle `saved_queries`:

1. Create a Metabase Collection: `POST /api/collection` with name from YAML
2. For each query: `POST /api/card` with:
   - `dataset_query.type = "native"`, `dataset_query.native.query = {sql}`
   - `display` = visualization type
   - `collection_id` = created collection ID
   - `description` = query description
3. Log: "Created collection 'CPX Demo Queries' with 10 saved queries"

### 2.5 Data Flow Visibility Strategy

**During deployment + seeding (60-90 seconds):**

- FA narrates: "The source systems are pushing data into MinIO AIStor right now."
- Open DemoForge **log viewer** on the firewall External System — show progress: `[firewall_events] Seeding: 100,000/500,000 rows (20%)`
- Functional, shows control — the FA isn't waiting blindly

**Immediately after seeding:**

- Open **MinIO Console** → analytics warehouse bucket → show Iceberg metadata + Parquet files
- Navigate to `threat-intel/feeds/stix/` → show JSON objects
- Navigate to `malware-vault/samples/` → show binary objects
- "Structured tables AND raw objects. Same system. Same security model."

**During dashboards:**

- Metabase dashboards with auto-refresh (FA clicks refresh or sets 30s auto-refresh in UI)
- SOC Overview time series chart shows data accumulating
- Number cards tick up with each refresh

**During saved queries:**

- FA opens "CPX Demo Queries" collection, clicks through in order
- Each query result IS the demo — no typing, no errors, no syntax fumbling
- Query 10 is the streaming proof: run, wait 30 seconds, run again, count increases

### 2.6 Deliverables

1. Updated `soc-firewall-events.yaml` with `saved_queries` section
2. Updated provisioner to handle `saved_queries` → Metabase Collection + Questions
3. Verified: Metabase has "CPX Demo Queries" collection with 10 clickable queries
4. Verified: each query returns non-empty, meaningful results
5. FA data flow visibility instructions documented

**STOP after Phase 2. Do not proceed without confirmation.**

**Architect review gate:** Every query executes without error. Cross-table joins return results. Collection is navigable.

**Playwright MCP E2E tests:**

```
TEST 2.1: Saved queries collection exists in Metabase
  1. Deploy full Analytics stack
  2. Wait for seeding to complete
  3. Open Metabase → Collections
  4. Verify "CPX Demo Queries" exists with 10 queries
  5. Screenshot: collection

TEST 2.2: Each query returns results
  1. Click each of the 10 queries in order
  2. Verify each executes without error and returns rows
  3. Especially: Query 3 (IOC correlation), Query 6 (vuln cross-ref), Query 8 (malware metadata)
  4. Screenshot: each result

TEST 2.3: Streaming proof
  1. Run Query 10, note count
  2. Wait 45 seconds
  3. Re-run Query 10
  4. Verify count increased
  5. Screenshot: both results

TEST 2.4: Dashboards render with data
  1. Open SOC Overview dashboard — all charts have data
  2. Open Threat Intelligence dashboard — IOC charts populated
  3. Open Vulnerability Posture dashboard — vuln charts populated
  4. Screenshot: each dashboard
```

---

## Phase 3 — Analytics Demo Template & Script

### 3.1 Template YAML

Create `demo-templates/sovereign-cyber-data-lake.yaml` with:
- 3 External System nodes (Firewall, Threat Intel, Vuln Scanner)
- MinIO AIStor (Tables enabled)
- Trino
- Metabase
- Canvas images (AIStor Tables logo backdrop, zone labels)
- Full SE guide with 12-step demo flow
- 7 containers total, ~8GB RAM

Node positions follow the architecture diagram from the previous conversation.

### 3.2 Demo Script Summary (25 minutes)

| Time | Scene | Action | Talking Point |
|------|-------|--------|---------------|
| 0:00 | Canvas | Show topology before deploy | "Three source systems → one sovereign data platform" |
| 1:00 | Deploy | Click Deploy, show log viewer | "Watch the data flow — 500K events being ingested" |
| 2:30 | MinIO Console | Show tables + objects | "Structured AND unstructured in one system" |
| 4:30 | Metabase | SOC Overview dashboard | "Auto-provisioned. Real-time. No manual setup." |
| 7:30 | Metabase | Threat Intelligence dashboard | "IOCs correlated across feeds" |
| 9:30 | Metabase | Vulnerability Posture dashboard | "Your CISO's board report" |
| 11:30 | Demo Queries | Query 3: IOC hits | "Firewall logs joined with threat intel — try this in Splunk" |
| 14:00 | Demo Queries | Query 4+5: Actor + MITRE | "Who's attacking and how?" |
| 16:00 | Demo Queries | Query 6: Exposed hosts | "The money query — unpatched AND suspicious traffic" |
| 19:00 | Demo Queries | Query 8: Malware metadata | "Unstructured binaries → queryable metadata" |
| 21:00 | Demo Queries | Query 10: Streaming proof | "Run twice — count goes up. It's live." |
| 23:00 | MinIO Console | AIStor Tables differentiator | "Built-in Iceberg V3 catalog. No metastore. Sovereign. Fraction of SIEM cost." |
| 25:00 | Close | Recap | "One platform. Tables + objects. SQL + dashboards. Sovereign. Open." |

### 3.3 Deliverables

1. Complete template YAML: `demo-templates/sovereign-cyber-data-lake.yaml`
2. Demo script: `demo-templates/guides/cpx-demo-script.md`
3. Full end-to-end deployment test
4. All Playwright tests pass in a single clean run

**STOP after Phase 3. Review with Ahmad before the CPX session.**

**Architect review gate — FINAL:**
- Template deploys on FA MacBook (OrbStack, 16GB RAM) within 90 seconds
- All 3 dashboards render with data
- All 10 queries return meaningful results
- Streaming visibly active
- Demo completable in ~25 minutes
- Canvas images render correctly
- No hardcoded credentials

**Playwright MCP E2E — FULL SUITE:**

All tests from Phase 1, Phase 2, plus:

```
FULL PIPELINE TEST:
  1. Load template from gallery
  2. Verify canvas topology + canvas images
  3. Deploy → all 7 containers healthy
  4. MinIO Console: tables + objects present
  5. Metabase: 3 dashboards + 10 saved queries all render
  6. Run all 10 queries — all return results
  7. Streaming proof (query 10 twice)
  8. Stop → Destroy → clean state
  9. Screenshot at every step
```

**Resource estimate:**
- Containers: 7
- Memory: ~8GB
- CPU: 6 cores
- Startup: ~90 seconds

---

## Appendix A — Experimental: AI/ML Extension (NOT for implementation)

Documented for future reference only. Not built or tested in this spec.

### A.1 Planned Components

JupyterLab + Ollama (mistral:7b) + Qdrant + RAG App → adds 4 containers, +6-7GB RAM.

### A.2 Planned Notebooks

1. Anomaly detection (Isolation Forest on firewall features)
2. IOC enrichment (LLM reads STIX, enriches with context)
3. Natural language threat hunting (English → SQL → Trino)
4. RAG on incident reports (vectorize DFIR reports, search via NL)

### A.3 Additional Scenario

`soc-incident-reports.yaml` — 50 synthetic DFIR reports as text objects for RAG ingestion.

### A.4 When to Build

After Analytics demo is stable and presented at least once. AI extension adds value but also failure surface. Get Analytics right first.
