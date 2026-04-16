# DemoForge: Restore Unified Tab Queries (Q8, Q9, Q10)

## Overview

During recent architecture discussions — Event Processor design, views over CSVs, medallion layering — the SQL Editor's Unified tab queries (Q8, Q9, Q10) fell out of the working spec set. Only the views and medallion discussions were forward-looking; the Unified queries were part of the committed baseline and should already be running. They're not. This spec restores them.

**Current live architecture (baseline):**
- Firewall External System: dual-write — CSV files to `raw-logs/firewall/` AND Iceberg table `soc.firewall_events` (via PyIceberg)
- Vulnerability Scanner External System: dual-write — CSV files to `raw-logs/vuln-scan/` AND Iceberg table `soc.vulnerability_scan`
- Threat Intel External System: writes STIX JSON objects to `threat-intel/feeds/stix/` + writes IOC Iceberg table `soc.threat_iocs` + drops malware binaries to `malware-vault/samples/`
- Event Processor (Spec 9): receives webhook when binary lands in `malware-vault/samples/`, generates JSON analysis report, writes the report to `malware-vault/reports/{sha256}.json`, AND writes an Iceberg row to `soc.malware_metadata` **including the `report_json` column** that holds the full JSON report as a string

So all four tables exist as real Iceberg tables. The `report_json` column on `soc.malware_metadata` is populated by the Event Processor as part of its malware-sandbox-analysis action scenario. Nothing speculative — this is the committed state.

The three Unified queries exercise this state:
- **Q8** — the CISO moment. 3-table join: firewall × IOCs × malware metadata. Proves correlated detection.
- **Q9** — the climax. All three data types in one query. Uses `json_extract_scalar` on IOC tags and `json_extract` on `report_json` for semi-structured access.
- **Q10** — the streaming proof. Run twice with a 30-60s gap. Count grows. Proves live ingestion.

---

## Agent Review, Validation & Testing Requirements

Same standards as all previous specs. Architect review at each phase gate. Playwright MCP E2E tests. No regression on other tabs.

---

## Phase 0 — Investigation

**Read-only. Do not modify any files.**

### 0.1 Current Tables and Columns

Connect to Trino in a deployed CPX instance (or equivalent) and run:

```sql
SHOW TABLES IN iceberg.soc;
DESCRIBE iceberg.soc.firewall_events;
DESCRIBE iceberg.soc.threat_iocs;
DESCRIBE iceberg.soc.vulnerability_scan;
DESCRIBE iceberg.soc.malware_metadata;
```

Verify:
1. All four tables exist
2. Column name for IOC value in `threat_iocs` — confirm whether it's `indicator_value`, `indicator`, or `ioc_value`
3. Column name for host IP in `vulnerability_scan` — confirm whether it's `host_ip`, `asset_ip`, `ip_address`, or `ip`
4. `threat_iocs.tags` exists and is a JSON string column
5. `malware_metadata.report_json` exists and is a JSON string column populated by the Event Processor
6. `malware_metadata.threat_actor` exists (used in Q8 join)
7. `firewall_events.event_timestamp` and `firewall_events.severity` exist

### 0.2 Current Saved Queries

Read the scenario YAML files that define saved queries:
- `components/external-system/scenarios/soc-firewall-events.yaml`
- `components/external-system/scenarios/soc-threat-intel.yaml`
- `components/external-system/scenarios/soc-vuln-scan.yaml`
- Any combined scenario file if it exists

Confirm:
1. Which queries currently exist (list by id or name)
2. What `tab` field values are in use (e.g., `overview`, `structured`, `semi-structured`, `unstructured`, `unified`)
3. Whether any Unified tab queries exist at all (likely none — that's why we're here)
4. Which scenario file owns the tab definitions in the `tabs:` section

### 0.3 SQL Editor Tab Registration

1. Is the `unified` tab already registered in the `tabs:` array of any scenario YAML?
2. If yes, what's its `order` value and description?
3. If no, what's the highest `order` value in use so we know where to place it?

### 0.4 Metabase Collection Structure

1. Does the `SOC Analyst Queries` collection exist?
2. Does a `Unified` sub-collection exist underneath it?
3. How does the Metabase provisioner create sub-collections from scenario YAML?

### 0.5 Streaming State

Confirm Q10 will work:
1. Is the firewall External System still streaming after initial seed?
2. What's the current rate (should be 25 events/sec per spec)?
3. Run `SELECT COUNT(*) FROM iceberg.soc.firewall_events` twice, 30s apart — does the count grow?

### 0.6 Report

Summary of:
1. Confirmed table names and column names (to substitute into the queries below)
2. Whether `report_json` column is present and populated
3. Current state of the `unified` tab (registered or not)
4. Current state of the Metabase `Unified` sub-collection
5. Streaming confirmed working (Q10 viable)

**STOP after report. Do not proceed without confirmation.**

**Architect review gate:** If any table is missing, any column name differs, or `report_json` isn't populated — raise it before proceeding. Don't silently adapt the queries; ask first.

---

## Phase 1 — Query Definitions

The queries below use the column names I believe are current. Phase 0 verifies them — substitute any actual name differences throughout before proceeding.

### 1.1 Q8 — Malware Linked to Firewall Actors

**Purpose:** 3-table join across all three data ingestion paths. Proves correlated detection works with plain SQL — the kind of query that usually requires a dedicated SIEM correlation rule.

**Demo talking point:** *"Here's the question every SOC analyst wants to answer in seconds but usually takes minutes: are we seeing traffic to destinations that match known-bad IOCs, AND do those IOCs' threat actors have malware we've analyzed in our sandbox? One query. Plain SQL. No correlation engine, no custom index."*

```sql
-- Q8: Malware actors active in our firewall traffic
-- Firewall events JOIN threat IOCs JOIN malware metadata
-- Finds traffic to IOCs whose threat actors have analyzed malware samples

SELECT 
  f.event_timestamp,
  f.src_ip,
  f.dst_ip,
  f.action,
  f.severity,
  t.indicator_value,
  t.threat_actor,
  t.confidence,
  m.malware_family,
  m.sandbox_verdict,
  m.sha256
FROM soc.firewall_events f
JOIN soc.threat_iocs t 
  ON f.dst_ip = t.indicator_value
JOIN soc.malware_metadata m 
  ON t.threat_actor = m.threat_actor
WHERE t.confidence > 70
  AND m.sandbox_verdict = 'malicious'
ORDER BY f.event_timestamp DESC
LIMIT 50
```

**Expected result:** 20-50 rows. Because the External System generators seed correlated data (~15% of firewall `dst_ip`s are in `threat_iocs`, and threat actors overlap between `threat_iocs` and `malware_metadata`), meaningful results are guaranteed.

### 1.2 Q9 — Full Threat Picture (All Three Data Types)

**Purpose:** The climax query. Touches every data type:
- Structured: `firewall_events`, `threat_iocs`, `malware_metadata`, `vulnerability_scan` (all Parquet Iceberg tables)
- Semi-structured: `json_extract_scalar` on `threat_iocs.tags`, `json_extract` on `malware_metadata.report_json`
- Unstructured provenance: sha256 → computed S3 path to the actual binary and JSON report

**Demo talking point:** *"Watch what we can do in a single SQL statement — correlate firewall traffic with threat intel, extract nested fields out of IOC tags, pull behavioral indicators and MITRE techniques out of the sandbox report JSON, add vulnerability context, AND tell you exactly where the binary sample and the full analysis report live in MinIO. One query. Three data types. Four tables plus two JSON columns."*

```sql
-- Q9: Full threat picture — unified query across all data types
-- Structured: firewall_events + threat_iocs + malware_metadata + vulnerability_scan
-- Semi-structured: json_extract_scalar on IOC tags, json_extract on report_json
-- Unstructured provenance: sha256 → binary location AND report JSON location

WITH active_threats AS (
  SELECT 
    t.indicator_value,
    t.threat_actor,
    t.confidence,
    json_extract_scalar(t.tags, '$.severity') AS ioc_severity,
    json_extract_scalar(t.tags, '$.campaign') AS campaign
  FROM soc.threat_iocs t
  WHERE t.confidence > 60
    AND json_extract_scalar(t.tags, '$.active') = 'true'
)
SELECT 
  f.event_timestamp,
  f.src_ip,
  f.dst_ip,
  f.action,
  at.threat_actor,
  at.confidence,
  at.ioc_severity,
  at.campaign,
  m.sha256,
  m.malware_family,
  m.sandbox_verdict,
  json_extract_scalar(m.report_json, '$.sandbox_engine')          AS sandbox_engine,
  json_extract(m.report_json, '$.behavioral_indicators')          AS behaviors,
  json_extract(m.report_json, '$.mitre_techniques')               AS mitre,
  json_extract(m.report_json, '$.network_indicators.dns_queries') AS c2_domains,
  CONCAT('s3://malware-vault/samples/', m.sha256)                 AS binary_location,
  CONCAT('s3://malware-vault/reports/', m.sha256, '.json')        AS report_location,
  v.cve_id,
  v.cvss_score,
  v.remediation_status
FROM soc.firewall_events f
JOIN active_threats at 
  ON f.dst_ip = at.indicator_value
LEFT JOIN soc.malware_metadata m 
  ON at.threat_actor = m.threat_actor
LEFT JOIN soc.vulnerability_scan v 
  ON f.src_ip = v.host_ip
WHERE f.event_timestamp > CURRENT_TIMESTAMP - INTERVAL '6' HOUR
ORDER BY at.confidence DESC, f.event_timestamp DESC
LIMIT 100
```

**Expected result:** 30-100 rows. Each row weaves structured fields, JSON-extracted nested fields, and binary-location pointers into a single record.

**Dependency on Event Processor:** The `json_extract` lines on `report_json` only return data if the Event Processor has been writing malware metadata. Phase 0 verifies this. If `report_json` exists and is populated (expected state), Q9 works. If not, Phase 0 flags it as a blocker — the Event Processor provisioning needs fixing, not the query.

### 1.3 Q10 — Streaming Proof

**Purpose:** Prove the firewall is continuously writing events into MinIO and Iceberg manifests expose new files to Trino without refresh or reindex.

**Demo cadence:** FA runs Q10 → reads the `total_events` count aloud → starts another query or topic → 45 seconds later says "let me run that streaming query one more time" → hits run → count has incremented by ~1000 (25 events/sec × 45s). Audience sees the lake is alive.

```sql
-- Q10: Streaming proof
-- Run twice with a 30-60 second gap. total_events grows, latest_event 
-- moves forward, events_last_minute stays non-zero.

SELECT 
  COUNT(*) AS total_events,
  MAX(event_timestamp) AS latest_event,
  CURRENT_TIMESTAMP AS query_time,
  DATE_DIFF('second', MAX(event_timestamp), CURRENT_TIMESTAMP) AS seconds_behind_live,
  COUNT(DISTINCT src_ip) AS unique_source_ips,
  COUNT(*) FILTER (WHERE severity = 'high') AS high_severity_count,
  COUNT(*) FILTER (
    WHERE event_timestamp > CURRENT_TIMESTAMP - INTERVAL '1' MINUTE
  ) AS events_last_minute
FROM soc.firewall_events
```

**Expected result:** A single row that changes on each run. `total_events` grows by ~1500 per minute when streaming is at 25 events/sec.

---

## Phase 2 — Scenario YAML Update

### 2.1 Owning Scenario File

Based on Phase 0, add the three queries to the scenario file that owns other tab queries. The recommended home is `components/external-system/scenarios/soc-firewall-events.yaml` because:
- Q10 depends specifically on firewall streaming
- Q8 and Q9 have firewall as the root table (driving table of the join)
- Keeps ownership aligned with the data producer

If Phase 0 found a combined scenario file owning all tabs, use that instead.

### 2.2 Query Definitions in YAML

Add to the `saved_queries:` section:

```yaml
saved_queries:
  # ... existing queries (overview, structured, semi-structured, unstructured) ...
  
  - id: q8-malware-firewall-correlation
    tab: unified
    order: 1
    name: "Q8. Malware actors in firewall traffic"
    description: "3-table join: firewall × IOCs × malware metadata"
    collection: "SOC Analyst Queries / Unified"
    sql: |
      SELECT 
        f.event_timestamp, f.src_ip, f.dst_ip, f.action, f.severity,
        t.indicator_value, t.threat_actor, t.confidence,
        m.malware_family, m.sandbox_verdict, m.sha256
      FROM soc.firewall_events f
      JOIN soc.threat_iocs t 
        ON f.dst_ip = t.indicator_value
      JOIN soc.malware_metadata m 
        ON t.threat_actor = m.threat_actor
      WHERE t.confidence > 70
        AND m.sandbox_verdict = 'malicious'
      ORDER BY f.event_timestamp DESC
      LIMIT 50

  - id: q9-full-threat-picture
    tab: unified
    order: 2
    name: "Q9. Full threat picture (all data types)"
    description: "Structured + semi-structured + unstructured provenance in one query"
    collection: "SOC Analyst Queries / Unified"
    sql: |
      WITH active_threats AS (
        SELECT 
          t.indicator_value, t.threat_actor, t.confidence,
          json_extract_scalar(t.tags, '$.severity') AS ioc_severity,
          json_extract_scalar(t.tags, '$.campaign') AS campaign
        FROM soc.threat_iocs t
        WHERE t.confidence > 60
          AND json_extract_scalar(t.tags, '$.active') = 'true'
      )
      SELECT 
        f.event_timestamp, f.src_ip, f.dst_ip, f.action,
        at.threat_actor, at.confidence, at.ioc_severity, at.campaign,
        m.sha256, m.malware_family, m.sandbox_verdict,
        json_extract_scalar(m.report_json, '$.sandbox_engine')          AS sandbox_engine,
        json_extract(m.report_json, '$.behavioral_indicators')          AS behaviors,
        json_extract(m.report_json, '$.mitre_techniques')               AS mitre,
        json_extract(m.report_json, '$.network_indicators.dns_queries') AS c2_domains,
        CONCAT('s3://malware-vault/samples/', m.sha256)                 AS binary_location,
        CONCAT('s3://malware-vault/reports/', m.sha256, '.json')        AS report_location,
        v.cve_id, v.cvss_score, v.remediation_status
      FROM soc.firewall_events f
      JOIN active_threats at 
        ON f.dst_ip = at.indicator_value
      LEFT JOIN soc.malware_metadata m 
        ON at.threat_actor = m.threat_actor
      LEFT JOIN soc.vulnerability_scan v 
        ON f.src_ip = v.host_ip
      WHERE f.event_timestamp > CURRENT_TIMESTAMP - INTERVAL '6' HOUR
      ORDER BY at.confidence DESC, f.event_timestamp DESC
      LIMIT 100

  - id: q10-streaming-proof
    tab: unified
    order: 3
    name: "Q10. Streaming proof (run twice)"
    description: "Run twice with a 30-60s gap. Counts grow. Proves live ingestion."
    collection: "SOC Analyst Queries / Unified"
    sql: |
      SELECT 
        COUNT(*) AS total_events,
        MAX(event_timestamp) AS latest_event,
        CURRENT_TIMESTAMP AS query_time,
        DATE_DIFF('second', MAX(event_timestamp), CURRENT_TIMESTAMP) AS seconds_behind_live,
        COUNT(DISTINCT src_ip) AS unique_source_ips,
        COUNT(*) FILTER (WHERE severity = 'high') AS high_severity_count,
        COUNT(*) FILTER (
          WHERE event_timestamp > CURRENT_TIMESTAMP - INTERVAL '1' MINUTE
        ) AS events_last_minute
      FROM soc.firewall_events
```

### 2.3 Tab Registration

If Phase 0 found the `unified` tab is NOT registered, add it to the `tabs:` array:

```yaml
tabs:
  # ... existing tabs ...
  
  - id: unified
    name: "Unified"
    order: 5
    description: "Queries that span all three data types — the climax of the demo"
    icon: layers
```

If the tab IS already registered, leave it alone.

### 2.4 Metabase Collection

Ensure the Metabase `Unified` sub-collection exists. If the provisioner auto-creates sub-collections from the `collection:` field on each saved query, no change needed. If sub-collections must be declared explicitly, add:

```yaml
metabase:
  collections:
    - name: "SOC Analyst Queries"
      sub_collections:
        - "Overview"
        - "Structured"
        - "Semi-structured"
        - "Unstructured"
        - "Unified"
```

### 2.5 Deliverables

1. Scenario YAML updated with Q8, Q9, Q10 under `tab: unified`
2. `unified` tab registered in the `tabs:` array (if Phase 0 found it missing)
3. Metabase `Unified` sub-collection ensured
4. Queries render in both the SQL Editor's Unified tab AND as Metabase saved questions

**STOP after Phase 2. Do not proceed without confirmation.**

**Architect review gate:**
- Queries use the column names verified in Phase 0
- `report_json` is populated (verified in Phase 0) so Q9's JSON extractions return real data
- No regression on existing queries in other tabs
- Streaming is active so Q10 demonstrates growth

---

## Phase 3 — Validation & E2E Testing

### 3.1 Query Execution

```
TEST 3.1: Q8 returns correlated rows
  1. Deploy the CPX template
  2. Wait for all containers healthy + initial seed complete (~90s)
  3. Wait an additional 10s for Event Processor to process seeded binaries 
     (malware-vault/samples/ webhook → soc.malware_metadata writes)
  4. Open SQL Editor → Unified tab
  5. Run Q8
  6. Verify: 20-50 rows returned
  7. Verify: every row has a non-null threat_actor AND non-null malware_family
  8. Screenshot

TEST 3.2: Q9 returns rows with JSON extraction working
  1. Same deploy as above
  2. Run Q9
  3. Verify: 20-100 rows returned
  4. Verify: ioc_severity column has values (not all nulls)
  5. Verify: behaviors column returns JSON arrays (e.g. ["creates_mutex","modifies_registry"])
  6. Verify: mitre column returns JSON arrays of technique IDs (e.g. ["T1059.001","T1486"])
  7. Verify: c2_domains column returns JSON arrays of domains
  8. Verify: binary_location column shows s3://malware-vault/samples/...
  9. Verify: report_location column shows s3://malware-vault/reports/....json
  10. Open one of the report_location URLs in MinIO Console — verify the JSON file exists
  11. Screenshot

TEST 3.3: Q10 streaming proof
  1. Same deploy
  2. Run Q10 → capture total_events (N1)
  3. Wait 45 seconds
  4. Run Q10 again → capture total_events (N2)
  5. Verify: N2 > N1 (approximately N1 + 1000)
  6. Verify: events_last_minute > 0
  7. Verify: seconds_behind_live < 10 (data is fresh)
  8. Screenshot both runs side by side
```

### 3.2 Event Processor Dependency Verification

```
TEST 3.4: Verify malware_metadata is Event-Processor-populated
  1. Query: SELECT COUNT(*) FROM soc.malware_metadata
  2. Verify count matches approximately the number of binaries in malware-vault/samples/
  3. Query: SELECT COUNT(*) FROM soc.malware_metadata WHERE report_json IS NULL
  4. Verify: 0 (every row should have report_json populated)
  5. Query: SELECT json_extract_scalar(report_json, '$.sandbox_engine') AS engine, COUNT(*)
           FROM soc.malware_metadata GROUP BY 1
  6. Verify: returns multiple sandbox engine names with counts
  7. Screenshot
```

### 3.3 Metabase Provisioning

```
TEST 3.5: Metabase Unified collection exists with all three queries
  1. Open Metabase → Collections → SOC Analyst Queries
  2. Verify Unified sub-collection exists
  3. Open Unified
  4. Verify Q8, Q9, Q10 all present as saved questions
  5. Click each, verify it renders with the expected result set
  6. Screenshot the collection listing and one rendered query
```

### 3.4 Demo Dress Rehearsal

```
TEST 3.6: Full Unified tab walkthrough (timed)
  1. Fresh deploy
  2. Start timer
  3. Open SQL Editor → Unified tab
  4. Run Q8 → read results aloud for 30s
  5. Run Q9 → scroll horizontally to show all columns, pause on behaviors/mitre/binary_location
  6. Run Q10 → capture count
  7. Spend 45s on another query or topic (Structured tab, Q1)
  8. Return to Unified → Run Q10 → show incremented count
  9. Stop timer
  10. Verify: total time under 4 minutes
  11. Screenshot at each step
```

### 3.5 Regression

```
TEST 3.7: Other tabs unaffected
  1. Verify Overview tab queries still return results
  2. Verify Structured tab Q1-Q3 still return results
  3. Verify Semi-structured tab Q4-Q5 still return results
  4. Verify Unstructured tab Q6-Q7 still return results
  5. Screenshot each tab showing queries and result counts
```

---

## Deliverables

1. Updated scenario YAML with Q8, Q9, Q10 under `tab: unified`
2. Metabase `Unified` sub-collection with all three queries provisioned
3. SQL Editor shows the Unified tab with three queries, in order
4. All Playwright tests pass — including the dress rehearsal completing under 4 minutes
5. No regression on existing tabs

## Out of Scope

- Gold-layer views that abstract Q8/Q9 as simpler view queries (belongs in a future medallion spec)
- Views-over-CSV architecture changes (not live yet)
- New queries beyond the original three
- Changes to the Event Processor or External System data generation

This spec restores three queries that should already be running. Nothing more.
