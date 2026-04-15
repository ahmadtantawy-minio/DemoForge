# DemoForge: SOC Demo Queries — Data Type Categorization & Statistics Overview

## Overview

This spec redesigns the 10 pre-configured demo queries to clearly demonstrate structured, semi-structured, and unstructured data querying — and adds a **Statistics Overview** dashboard that shows all tables, row counts, freshness, and data types in a single view.

**Problem:** The original 10 queries are almost entirely structured-on-structured joins. Only one uses `json_extract_scalar`, and nothing makes the "unified data types" story visible. The audience sees 10 SQL queries against tables and has no reason to believe this is different from any other SQL database.

**Fix:**
1. Reorganize queries into **sub-collections by data type** so the folder structure tells the story
2. Replace redundant structured queries with purpose-built semi-structured and unstructured queries
3. Add two "unified" queries that explicitly JOIN across data types in one SQL statement
4. Add a **Statistics Overview** dashboard — the first thing the FA opens, showing all tables, row counts, latest timestamps, and data type badges at a glance

**Dependencies:** This spec updates deliverables from `claude-code-cpx-demo-completion-spec.md` (Spec 3). It modifies the `saved_queries` section of `soc-firewall-events.yaml` and adds a new dashboard. No changes to the generator engine, compose generator, or component manifests.

---

## Agent Review, Validation & Testing Requirements

Same standards as previous specs. Architect review, Playwright MCP E2E tests, regression checks.

---

## Phase 0 — Read-Only Investigation

**DO NOT write any code. Only read and report.**

### 0.1 Metabase Sub-Collections API

Research:
- Can Metabase collections be nested? (`POST /api/collection` with `parent_id`)
- How does the Metabase UI display nested collections? (folder tree? breadcrumbs?)
- Can a Question be moved between collections via API?
- Maximum nesting depth supported?

### 0.2 Metabase Dashboard Tabs

Research:
- Does Metabase support tabs within a single dashboard? (recent versions added "dashboard tabs")
- If yes: `PUT /api/dashboard/{id}` with `tabs` parameter — what's the schema?
- Can different cards be assigned to different tabs?
- If tabs aren't supported: we use separate dashboards instead

### 0.3 Current Saved Queries Implementation

- Verify the provisioner from Spec 3 creates Metabase Questions correctly
- How are Questions currently organized (flat collection or already sub-collections)?
- What visualization types are supported in the provisioner?

### 0.4 Trino JSON Functions

Verify these Trino functions work against AIStor Iceberg tables:
- `json_extract_scalar(column, '$.field')` — returns string
- `json_extract(column, '$.field')` — returns JSON
- `CAST(json_extract_scalar(...) AS BOOLEAN)` — type coercion from JSON
- `json_array_length()` — if we store JSON arrays

### 0.5 Report

1. Sub-collection API details and UI behavior
2. Dashboard tabs support (yes/no, API schema)
3. Current provisioner state
4. Trino JSON function compatibility confirmation

**STOP after report. Do not proceed without confirmation.**

**Architect review gate:** Confirm sub-collections work in the Metabase version we're using. If tabs exist, confirm the API schema.

---

## Phase 1 — Redesigned Query Collection

### 1.1 Collection Structure

```
SOC Demo Queries/
├── 1 — Structured (Iceberg tables)/
│   ├── Q1. Total firewall events ingested
│   ├── Q2. All tables in the data lake
│   └── Q3. Connections to known C2 infrastructure
├── 2 — Semi-structured (JSON fields)/
│   ├── Q4. Active IOCs by threat actor (JSON filter)
│   └── Q5. IOC review status breakdown (JSON aggregation)
├── 3 — Unstructured origin (mirror tables from raw objects)/
│   ├── Q6. Malware samples by verdict and threat actor
│   └── Q7. Malware file type distribution
├── 4 — Unified (cross-type joins)/
│   ├── Q8. Malware linked to firewall threat actors
│   └── Q9. Full threat picture — all three data types
└── Q10. Live data — run twice to prove streaming
```

The sub-collection names have numeric prefixes so they sort in presentation order. Q10 sits in the root collection — it's a utility query, not a data type demonstration.

### 1.2 Provisioner Updates

Update the `saved_queries` section of the scenario YAML schema to support sub-collections:

```yaml
saved_queries:
  collection: "SOC Demo Queries"

  subcollections:
    - id: sc-structured
      name: "1 — Structured (Iceberg tables)"
      description: "Standard SQL against Parquet-backed Iceberg tables"

    - id: sc-semi
      name: "2 — Semi-structured (JSON fields)"
      description: "JSON extraction functions on fields stored within Iceberg tables"

    - id: sc-unstructured
      name: "3 — Unstructured origin (mirror tables)"
      description: "Querying metadata extracted from raw S3 objects (binaries, files)"

    - id: sc-unified
      name: "4 — Unified (cross-type joins)"
      description: "Single queries spanning structured tables, JSON fields, and object-origin metadata"

  queries:
    - id: q-event-count
      subcollection: sc-structured    # NEW: assigns to sub-collection
      title: "Q1. Total firewall events ingested"
      # ...
```

The provisioner sequence:
1. Create root collection "SOC Demo Queries"
2. Create sub-collections as children of root (using `parent_id`)
3. Create each Question with `collection_id` pointing to its sub-collection
4. Q10 gets `collection_id` = root (no sub-collection)

### 1.3 The 10 Queries

#### Sub-collection: Structured (Iceberg tables)

```yaml
- id: q-event-count
  subcollection: sc-structured
  title: "Q1. Total firewall events ingested"
  description: "Pure structured query — count rows in a Parquet-backed Iceberg table"
  order: 1
  visualization: number
  query: |
    SELECT count(*) as total_events
    FROM soc.firewall_events

- id: q-all-tables
  subcollection: sc-structured
  title: "Q2. All tables in the data lake"
  description: "Lists every Iceberg table registered in the AIStor catalog"
  order: 2
  visualization: table
  query: |
    SELECT table_schema as namespace,
           table_name,
           table_type
    FROM information_schema.tables
    WHERE table_schema = 'soc'
    ORDER BY table_name

- id: q-c2-hits
  subcollection: sc-structured
  title: "Q3. Connections to known C2 infrastructure"
  description: "JOINs two structured Iceberg tables — firewall logs with threat IOCs"
  order: 3
  visualization: table
  query: |
    SELECT
      f.event_timestamp,
      f.src_ip,
      f.dst_ip,
      t.threat_actor,
      t.confidence,
      f.action,
      f.severity,
      f.mitre_tactic
    FROM soc.firewall_events f
    JOIN soc.threat_iocs t
      ON f.dst_ip = t.indicator
      AND t.ioc_type = 'ipv4'
    WHERE t.confidence > 60
    ORDER BY f.event_timestamp DESC
    LIMIT 50
```

#### Sub-collection: Semi-structured (JSON fields)

```yaml
- id: q-active-iocs-json
  subcollection: sc-semi
  title: "Q4. Active IOCs by threat actor (JSON filter)"
  description: "Filters on a JSON field inside an Iceberg table using json_extract_scalar — the 'tags' column stores {active, reviewed} as JSON"
  order: 4
  visualization: bar
  query: |
    -- The 'tags' column is a JSON string: {"active": true, "reviewed": false}
    -- json_extract_scalar parses it at query time — no pre-processing needed
    SELECT
      threat_actor,
      count(*) as active_iocs,
      round(avg(confidence), 0) as avg_confidence,
      round(avg(severity_score), 1) as avg_severity
    FROM soc.threat_iocs
    WHERE json_extract_scalar(tags, '$.active') = 'true'
    GROUP BY 1
    ORDER BY 2 DESC

- id: q-review-status-json
  subcollection: sc-semi
  title: "Q5. IOC review status breakdown (JSON aggregation)"
  description: "Aggregates over two JSON fields — demonstrates semi-structured analytics at scale across 8K IOC records"
  order: 5
  visualization: table
  query: |
    -- Extracting multiple fields from the same JSON column
    -- and using them as GROUP BY dimensions
    SELECT
      json_extract_scalar(tags, '$.active') as is_active,
      json_extract_scalar(tags, '$.reviewed') as is_reviewed,
      count(*) as ioc_count,
      round(avg(confidence), 0) as avg_confidence,
      count(DISTINCT threat_actor) as distinct_actors,
      count(DISTINCT source_feed) as distinct_feeds
    FROM soc.threat_iocs
    GROUP BY 1, 2
    ORDER BY 3 DESC
```

#### Sub-collection: Unstructured origin (mirror tables)

```yaml
- id: q-malware-verdict
  subcollection: sc-unstructured
  title: "Q6. Malware samples by verdict and threat actor"
  description: "Queries soc.malware_metadata — an Iceberg table mirrored from raw binary objects stored in s3://malware-vault/samples/. The original files are opaque binaries; this table contains extracted metadata."
  order: 6
  visualization: bar
  query: |
    -- soc.malware_metadata is a mirror table
    -- Source: 200 raw binary files in s3://malware-vault/samples/
    -- Each file is 10-500KB of opaque binary data
    -- Metadata (sha256, file_type, verdict) was extracted during ingestion
    -- and written as an Iceberg table for queryability
    SELECT
      threat_actor,
      sandbox_verdict,
      count(*) as samples,
      round(avg(file_size_bytes) / 1024, 1) as avg_size_kb
    FROM soc.malware_metadata
    GROUP BY 1, 2
    ORDER BY 3 DESC

- id: q-malware-filetypes
  subcollection: sc-unstructured
  title: "Q7. Malware file type distribution"
  description: "File format analysis from binary object metadata — shows how unstructured binaries become queryable through mirror tables"
  order: 7
  visualization: bar
  query: |
    -- What types of malicious files are we seeing?
    -- These were raw binaries — now queryable as structured data
    SELECT
      file_type,
      sandbox_verdict,
      count(*) as sample_count,
      round(min(file_size_bytes) / 1024, 1) as min_kb,
      round(avg(file_size_bytes) / 1024, 1) as avg_kb,
      round(max(file_size_bytes) / 1024, 1) as max_kb
    FROM soc.malware_metadata
    GROUP BY 1, 2
    ORDER BY 3 DESC
```

#### Sub-collection: Unified (cross-type joins)

```yaml
- id: q-malware-firewall-link
  subcollection: sc-unified
  title: "Q8. Malware linked to firewall threat actors"
  description: "JOINs structured firewall logs → structured IOCs → unstructured-origin malware metadata. Three tables, two data types, one SQL query."
  order: 8
  visualization: table
  query: |
    -- This query spans TWO data types:
    --   Structured: soc.firewall_events (Iceberg table from Parquet)
    --   Structured: soc.threat_iocs (Iceberg table from Parquet)
    --   Unstructured-origin: soc.malware_metadata (mirror of raw binaries)
    SELECT
      m.threat_actor,
      m.sandbox_verdict,
      count(DISTINCT m.sha256) as malware_variants,
      count(DISTINCT f.src_ip) as targeted_internal_hosts,
      count(*) as total_firewall_hits,
      sum(CASE WHEN f.action IN ('deny','drop','reset') THEN 1 ELSE 0 END) as blocked
    FROM soc.malware_metadata m
    JOIN soc.threat_iocs t
      ON m.threat_actor = t.threat_actor
      AND t.ioc_type = 'ipv4'
    JOIN soc.firewall_events f
      ON f.dst_ip = t.indicator
    GROUP BY 1, 2
    ORDER BY 5 DESC

- id: q-full-threat-picture
  subcollection: sc-unified
  title: "Q9. Full threat picture — all three data types in one query"
  description: "The demo closer. Structured firewall logs + semi-structured JSON fields (json_extract_scalar) + unstructured-origin malware metadata. One query, all three data types, one platform."
  order: 9
  visualization: table
  query: |
    -- ALL THREE DATA TYPES IN ONE QUERY:
    --   Structured:        soc.firewall_events (Iceberg, from Parquet)
    --   Semi-structured:   soc.threat_iocs.tags (JSON field, json_extract_scalar)
    --   Unstructured-origin: soc.malware_metadata (mirror of raw binary objects)
    SELECT
      t.threat_actor,
      count(DISTINCT f.dst_ip) as c2_connections,
      count(DISTINCT f.src_ip) as internal_hosts_affected,
      count(DISTINCT m.sha256) as malware_variants,
      round(avg(t.confidence), 0) as avg_ioc_confidence,
      sum(CASE
        WHEN json_extract_scalar(t.tags, '$.reviewed') = 'true'
        THEN 1 ELSE 0
      END) as reviewed_iocs,
      sum(CASE
        WHEN json_extract_scalar(t.tags, '$.active') = 'true'
        THEN 1 ELSE 0
      END) as active_iocs,
      sum(CASE
        WHEN f.action IN ('deny','drop','reset')
        THEN 1 ELSE 0
      END) as blocked_connections
    FROM soc.threat_iocs t
    JOIN soc.firewall_events f
      ON f.dst_ip = t.indicator
      AND t.ioc_type = 'ipv4'
    LEFT JOIN soc.malware_metadata m
      ON t.threat_actor = m.threat_actor
    GROUP BY 1
    ORDER BY 2 DESC
```

#### Root collection (no sub-collection)

```yaml
- id: q-streaming
  title: "Q10. Live data — run twice to prove streaming"
  description: "Count increases between runs — proves continuous ingestion"
  order: 10
  visualization: number
  query: |
    SELECT
      count(*) as total_events,
      max(event_timestamp) as latest_event,
      date_diff('second',
        min(event_timestamp),
        max(event_timestamp)) as time_span_seconds
    FROM soc.firewall_events
```

### 1.4 SQL Comments as Narrative

Notice the SQL comments in Q6-Q9. These are intentional — when the FA runs a query in Metabase's SQL editor, the comments are visible above the query. They serve as inline narration:

```sql
-- ALL THREE DATA TYPES IN ONE QUERY:
--   Structured:          soc.firewall_events
--   Semi-structured:     soc.threat_iocs.tags (JSON)
--   Unstructured-origin: soc.malware_metadata (mirror of binaries)
```

The audience reads these before the results load. The comments DO the explaining so the FA doesn't have to narrate every line.

### 1.5 Deliverables

1. Updated `soc-firewall-events.yaml` with new `saved_queries` section (sub-collections + 10 queries)
2. Updated provisioner to create sub-collections via Metabase API
3. Verified: all 10 queries execute without error against generated data
4. Verified: sub-collections display correctly in Metabase UI
5. Verified: SQL comments are visible in the query editor view

**STOP after Phase 1. Do not proceed without confirmation.**

**Architect review gate:**
- Every query returns non-empty results (especially Q8 and Q9 which depend on cross-table correlations)
- SQL comments don't break Trino parsing
- Sub-collection ordering is correct (1, 2, 3, 4 then Q10)
- Query descriptions are accurate (data type labels match what the SQL actually does)

**Playwright MCP E2E tests:**

```
TEST 1.1: Sub-collections exist in correct order
  1. Deploy full stack, wait for provisioning
  2. Open Metabase → Collections → SOC Demo Queries
  3. Verify 4 sub-collections appear: Structured, Semi-structured, Unstructured, Unified
  4. Verify Q10 is in root collection
  5. Screenshot: collection tree

TEST 1.2: Structured queries return results
  1. Open Q1 — verify count > 0
  2. Open Q2 — verify 4+ tables listed
  3. Open Q3 — verify non-empty join results
  4. Screenshot: each result

TEST 1.3: Semi-structured queries use JSON functions
  1. Open Q4 — verify json_extract_scalar is visible in query
  2. Verify results show threat actors with active IOC counts
  3. Open Q5 — verify grouped JSON aggregation results
  4. Screenshot: query editor showing JSON functions + results

TEST 1.4: Unstructured-origin queries reference mirror tables
  1. Open Q6 — verify results include sandbox_verdict, file_size
  2. Open Q7 — verify file_type distribution
  3. Verify SQL comments mention "mirror of raw binary objects"
  4. Screenshot: query with comments visible

TEST 1.5: Unified queries span data types
  1. Open Q8 — verify three-table join returns results
  2. Open Q9 — verify results include json_extract_scalar AND malware_metadata columns
  3. Verify SQL comments list all three data types
  4. Screenshot: Q9 query + results (the demo closer)

TEST 1.6: Streaming proof
  1. Run Q10, note count
  2. Wait 45 seconds
  3. Re-run Q10
  4. Verify count increased
  5. Screenshot: both results
```

---

## Phase 2 — Statistics Overview Dashboard

A dashboard that shows the health and shape of the entire data lake at a glance. This is the FIRST thing the FA opens after deployment — before diving into specific queries or dashboards.

### 2.1 Purpose

The Statistics Overview answers: "What's in the data lake right now?" in one screen. It shows:
- Every table, its row count, and when it was last written to
- Every object bucket, its object count
- Data type badges (structured / semi-structured / unstructured)
- Freshness indicators (how recent is the latest record)
- Streaming status (is data still arriving)

This dashboard is NOT about analytics — it's about data observability. It's the "control panel" the FA checks to confirm everything is working before presenting the analytical dashboards.

### 2.2 Dashboard: "Data Lake Overview"

This is provisioned as a separate Metabase dashboard (not in the saved queries collection). It should be the first dashboard in the Metabase sidebar.

**Dashboard layout (single page, no tabs needed):**

#### Row 1: Summary cards (4 number cards)

```yaml
- id: stat-total-tables
  title: "Iceberg tables"
  type: number
  query: |
    SELECT count(*) as tables
    FROM information_schema.tables
    WHERE table_schema = 'soc'
  position: { row: 0, col: 0, width: 6, height: 4 }

- id: stat-total-rows
  title: "Total rows (all tables)"
  type: number
  query: |
    SELECT
      (SELECT count(*) FROM soc.firewall_events) +
      (SELECT count(*) FROM soc.threat_iocs) +
      (SELECT count(*) FROM soc.vulnerability_scan) +
      (SELECT count(*) FROM soc.malware_metadata) as total_rows
  position: { row: 0, col: 6, width: 6, height: 4 }

- id: stat-latest-event
  title: "Latest event"
  type: number
  query: |
    SELECT max(event_timestamp) as latest
    FROM soc.firewall_events
  position: { row: 0, col: 12, width: 6, height: 4 }
  settings:
    number_format: datetime

- id: stat-streaming-rate
  title: "Events / minute (last 5 min)"
  type: number
  query: |
    SELECT round(count(*) / 5.0, 0) as events_per_minute
    FROM soc.firewall_events
    WHERE event_timestamp > current_timestamp - interval '5' minute
  position: { row: 0, col: 18, width: 6, height: 4 }
```

#### Row 2: Table inventory (full-width table)

```yaml
- id: stat-table-inventory
  title: "Table inventory"
  type: table
  query: |
    SELECT
      'firewall_events' as table_name,
      'Structured' as data_type,
      'Parquet → Iceberg' as format,
      (SELECT count(*) FROM soc.firewall_events) as row_count,
      (SELECT max(event_timestamp) FROM soc.firewall_events) as latest_record,
      (SELECT min(event_timestamp) FROM soc.firewall_events) as earliest_record,
      'Streaming (25/s)' as ingestion_mode
    UNION ALL
    SELECT
      'threat_iocs',
      'Structured + Semi-structured (JSON)',
      'Parquet → Iceberg',
      (SELECT count(*) FROM soc.threat_iocs),
      (SELECT max(last_seen) FROM soc.threat_iocs),
      (SELECT min(first_seen) FROM soc.threat_iocs),
      'Batch (one-time seed)'
    UNION ALL
    SELECT
      'vulnerability_scan',
      'Structured',
      'Parquet → Iceberg',
      (SELECT count(*) FROM soc.vulnerability_scan),
      (SELECT max(scan_timestamp) FROM soc.vulnerability_scan),
      (SELECT min(scan_timestamp) FROM soc.vulnerability_scan),
      'Batch (periodic scans)'
    UNION ALL
    SELECT
      'malware_metadata',
      'Unstructured origin (mirror)',
      'Binary objects → Iceberg metadata',
      (SELECT count(*) FROM soc.malware_metadata),
      CAST(NULL AS timestamp),
      CAST(NULL AS timestamp),
      'Batch (mirror of raw objects)'
  position: { row: 1, col: 0, width: 24, height: 10 }
```

#### Row 3: Data type distribution + freshness

```yaml
- id: stat-data-type-split
  title: "Rows by data type"
  type: pie
  query: |
    SELECT 'Structured (firewall)' as data_type,
           (SELECT count(*) FROM soc.firewall_events) as rows
    UNION ALL
    SELECT 'Structured (vulns)',
           (SELECT count(*) FROM soc.vulnerability_scan)
    UNION ALL
    SELECT 'Semi-structured (IOCs w/ JSON)',
           (SELECT count(*) FROM soc.threat_iocs)
    UNION ALL
    SELECT 'Unstructured origin (malware)',
           (SELECT count(*) FROM soc.malware_metadata)
  position: { row: 2, col: 0, width: 10, height: 8 }

- id: stat-event-timeline
  title: "Event ingestion timeline (last hour)"
  type: time_series
  query: |
    SELECT
      date_trunc('minute', event_timestamp) as minute,
      count(*) as events
    FROM soc.firewall_events
    WHERE event_timestamp > current_timestamp - interval '1' hour
    GROUP BY 1
    ORDER BY 1
  position: { row: 2, col: 10, width: 14, height: 8 }
  settings:
    x_axis: minute
    y_axis: events
```

#### Row 4: Object bucket inventory

```yaml
- id: stat-object-summary
  title: "S3 object buckets (unstructured data)"
  type: table
  query: |
    -- This query shows the mirror table metadata as a proxy
    -- for the actual object buckets. The raw objects are in
    -- s3://threat-intel/feeds/stix/ and s3://malware-vault/samples/
    -- MinIO Console shows the actual object counts.
    SELECT
      'threat-intel/feeds/stix/' as bucket_path,
      'STIX 2.1 JSON bundles' as content_type,
      '~500 objects' as estimated_count,
      'Semi-structured (JSON)' as data_type
    UNION ALL
    SELECT
      'malware-vault/samples/',
      'Binary malware samples',
      '~200 objects',
      'Unstructured (binary)'
  position: { row: 3, col: 0, width: 24, height: 6 }
```

#### Row 5: Cross-table correlation health

```yaml
- id: stat-correlation-health
  title: "Cross-table correlation status"
  type: table
  query: |
    SELECT
      'Firewall → IOC (dst_ip = indicator)' as correlation,
      (SELECT count(DISTINCT f.dst_ip)
       FROM soc.firewall_events f
       JOIN soc.threat_iocs t ON f.dst_ip = t.indicator
       WHERE t.ioc_type = 'ipv4') as matching_ips,
      (SELECT count(*) FROM soc.firewall_events) as total_firewall_events,
      round(100.0 *
        (SELECT count(*)
         FROM soc.firewall_events f
         JOIN soc.threat_iocs t ON f.dst_ip = t.indicator
         WHERE t.ioc_type = 'ipv4')
        / NULLIF((SELECT count(*) FROM soc.firewall_events), 0), 2)
      as match_rate_pct
    UNION ALL
    SELECT
      'Firewall → Vuln (src_ip = host_ip)',
      (SELECT count(DISTINCT f.src_ip)
       FROM soc.firewall_events f
       JOIN soc.vulnerability_scan v ON f.src_ip = v.host_ip),
      (SELECT count(*) FROM soc.firewall_events),
      round(100.0 *
        (SELECT count(DISTINCT f.src_ip)
         FROM soc.firewall_events f
         JOIN soc.vulnerability_scan v ON f.src_ip = v.host_ip)
        / NULLIF((SELECT count(DISTINCT src_ip) FROM soc.firewall_events), 0), 2)
    UNION ALL
    SELECT
      'Malware → IOC (threat_actor match)',
      (SELECT count(DISTINCT m.sha256)
       FROM soc.malware_metadata m
       JOIN soc.threat_iocs t ON m.threat_actor = t.threat_actor),
      (SELECT count(*) FROM soc.malware_metadata),
      round(100.0 *
        (SELECT count(DISTINCT m.sha256)
         FROM soc.malware_metadata m
         JOIN soc.threat_iocs t ON m.threat_actor = t.threat_actor)
        / NULLIF((SELECT count(*) FROM soc.malware_metadata), 0), 2)
  position: { row: 4, col: 0, width: 24, height: 8 }
```

### 2.3 How This Dashboard Is Used in the Demo

The Statistics Overview is NOT part of the main demo narrative — it's a "pre-flight check" the FA opens immediately after deployment to confirm:

1. All 4 tables exist with expected row counts
2. Streaming is active (events/minute > 0, latest event is recent)
3. Correlations are working (match rates are non-zero)
4. Object buckets have data

The FA can also show it to the audience as a "data platform observability" view: "Before we dive into the analytics, let me show you what's in the data lake right now."

It's also useful if something goes wrong during the demo — the FA can quickly check whether data seeded correctly, whether streaming stopped, or whether correlations broke.

### 2.4 Provisioning

This dashboard is provisioned by the **firewall External System** (since it starts last and has the `saved_queries` section). Add it to the scenario YAML as a separate dashboard alongside the SOC Overview:

```yaml
dashboards:
  # Existing: SOC Overview, Threat Intel, Vuln Posture
  # NEW: Statistics Overview
  - id: data-lake-overview
    title: "Data Lake Overview"
    description: "Table inventory, row counts, freshness, data types, and correlation health"
    layout: auto
    charts:
      # All charts from 2.2 above
```

### 2.5 Dashboard Order in Metabase

After provisioning, the Metabase sidebar should show dashboards in this order:

1. **Data Lake Overview** (pre-flight check)
2. **SOC Overview** (main demo dashboard)
3. **Threat Intelligence** (IOC-focused)
4. **Vulnerability Posture** (vuln-focused)

Plus the "SOC Demo Queries" collection with sub-collections.

The provisioner can control order by creating dashboards in sequence (Metabase sorts by creation time by default) or by pinning them to a collection.

### 2.6 Deliverables

1. Data Lake Overview dashboard definition in scenario YAML
2. Updated provisioner to create the dashboard with all charts
3. Verified: all statistics queries execute correctly
4. Verified: correlation health shows non-zero match rates
5. Verified: streaming rate shows active ingestion

**STOP after Phase 2. Do not proceed without confirmation.**

**Architect review gate:**
- The UNION ALL queries don't have type mismatches (all columns align across union branches)
- The subquery-heavy statistics queries don't timeout (acceptable performance on 500K rows)
- Dashboard renders within 5 seconds of opening
- Correlation health percentages match the expected ratios from the scenario config (3% IOC correlation, 80% vuln correlation)

**Playwright MCP E2E tests:**

```
TEST 2.1: Data Lake Overview dashboard exists
  1. Deploy full stack, wait for provisioning
  2. Open Metabase
  3. Verify "Data Lake Overview" dashboard exists
  4. Screenshot: dashboard in sidebar

TEST 2.2: Summary cards show correct data
  1. Open Data Lake Overview
  2. Verify "Iceberg tables" = 4
  3. Verify "Total rows" > 500K (firewall 500K + IOCs 8K + vulns 15K + malware 200)
  4. Verify "Latest event" is within last few minutes
  5. Verify "Events/minute" > 0 (streaming active)
  6. Screenshot: summary cards

TEST 2.3: Table inventory is complete
  1. Verify table inventory shows all 4 tables
  2. Verify data_type column shows: Structured, Semi-structured, Unstructured origin
  3. Verify row counts match expected values
  4. Screenshot: table inventory

TEST 2.4: Correlation health is non-zero
  1. Scroll to correlation health table
  2. Verify Firewall→IOC match rate is ~3%
  3. Verify Firewall→Vuln match rate is high (~80% of distinct src_ips)
  4. Verify Malware→IOC match rate > 0%
  5. Screenshot: correlation health

TEST 2.5: Event timeline shows ingestion
  1. Verify event ingestion timeline chart renders
  2. Verify it shows data points in the last hour
  3. Verify the line trends upward or is steady (not flat/zero)
  4. Screenshot: timeline chart

TEST 2.6: Dashboard loads within 5 seconds
  1. Open Data Lake Overview
  2. Time from click to all charts rendered
  3. Verify < 5 seconds
  4. If > 5 seconds, flag for query optimization
```

---

## Summary

**Phase 1** reorganizes 10 queries into 4 sub-collections by data type, replaces redundant structured queries with purpose-built semi-structured (JSON) and unstructured (mirror table) queries, and adds two "unified" queries (Q8 + Q9) that JOIN across data types. SQL comments embedded in the queries serve as inline narration.

**Phase 2** adds a Data Lake Overview dashboard that shows table inventory, row counts, freshness, streaming status, data type distribution, and cross-table correlation health in a single view.

**Files changed:**
- `components/external-system/scenarios/soc-firewall-events.yaml` — updated `saved_queries` + new dashboard
- External System provisioner — sub-collection creation logic
- No component manifest changes, no compose generator changes, no frontend changes

**Demo flow update:**
The FA's presentation order becomes:
1. Deploy → show log viewer during seeding
2. Open MinIO Console → show tables + objects (the "unified" story)
3. Open **Data Lake Overview** → "Here's what's in the data lake" (pre-flight + audience context)
4. Open **SOC Overview** → main analytical dashboard
5. Click through **SOC Demo Queries** sub-collections → structured → semi-structured → unstructured → unified
6. Q9 (full threat picture) is the climax
7. Q10 (streaming proof) is the encore
