# DemoForge: Sticky Note Visibility & CPX Demo Annotations

## Overview

This spec adds a **visibility mode** to DemoForge sticky notes: notes can be either **customer-facing** (always visible) or **FA internal** (visible only when a toggle is enabled). A global toggle in the canvas toolbar controls whether internal notes are shown.

This solves a real problem: FAs need coaching notes, talking points, and technical reminders on the canvas during design and rehearsal, but those notes must disappear instantly when presenting to a customer. Today, FAs would have to manually delete or move notes before a demo — error-prone and stressful.

**Also included:** All sticky note content for the CPX Sovereign Cyber Data Lake demo, in both customer-facing and FA internal flavors.

---

## Agent Review, Validation & Testing Requirements

Same standards as previous specs. Architect review at every gate, Playwright MCP E2E tests, regression checks.

---

## Phase 0 — Read-Only Investigation

**DO NOT write any code. Only read and report.**

### 0.1 Existing Sticky Notes

- How are sticky notes currently defined in the frontend types? (check `types/index.ts`)
- How are they rendered on the React Flow canvas?
- What properties do they currently have? (position, content, color, size?)
- How are they persisted in the demo state and template YAML?
- Can they be selected, moved, resized, deleted?
- Do they have a properties panel when selected?
- What colors are available?

### 0.2 Canvas Toolbar

- Where is the toolbar located (top of canvas)?
- What buttons/controls currently exist?
- Is there a pattern for toggle buttons in the toolbar?
- How is toolbar state persisted (session-only or saved with demo)?

### 0.3 React Flow Custom Node Types

- How does DemoForge register custom node types with React Flow?
- Could sticky notes be rendered as a custom node type with conditional visibility?
- Is there a z-index / layer system for rendering notes behind or in front of components?

### 0.4 Report

1. Complete StickyNote type definition
2. Rendering code for sticky notes
3. Properties panel for sticky notes (if exists)
4. Toolbar code and existing toggle patterns
5. Template YAML sticky_notes section examples (if any exist with content)

**STOP after report. Do not proceed without confirmation.**

**Architect review gate:** Confirm the sticky note system exists and identify the minimal changes needed.

---

## Phase 1 — Sticky Note Visibility System

### 1.1 Data Model Changes

Extend the sticky note type with a `visibility` field:

```typescript
export interface StickyNote {
  id: string;
  position: { x: number; y: number };
  size?: { width: number; height: number };
  content: string;
  title?: string;              // NEW: optional title line (bold, above content)
  color?: string;              // Existing: note background color
  visibility: "customer" | "internal";  // NEW: default "customer"
}
```

**Backward compatibility:** Existing sticky notes that don't have a `visibility` field default to `"customer"` — no migration needed.

### 1.2 Visual Differentiation

**Customer-facing notes:**
- Standard appearance (current behavior, unchanged)
- No badge or indicator
- Always visible regardless of toggle state

**FA internal notes:**
- Left border accent: 3px solid amber (#EF9F27 light / #854F0B dark)
- Background tinted amber: #FAEEDA light / #412402 dark (using existing amber ramp)
- "FA only" badge: small pill in top-right corner of the note
  - Text: "FA only" with an eye icon (lucide `eye` icon, 10px)
  - Background: amber-50, border: amber-400, text: amber-600
  - Always visible when the note is visible (the badge IS the indicator)
- Hidden when the FA notes toggle is OFF
- Transition: fade out with 200ms opacity transition (not instant disappear)

### 1.3 Global Toggle: "FA notes"

**Location:** Top-right area of the canvas toolbar, grouped with other view controls.

**UI:**
- Toggle switch (same style as existing DemoForge toggles)
- Label: "FA notes" with a small eye icon
- ON state: blue track, internal notes visible
- OFF state: gray track, internal notes hidden (opacity: 0, pointer-events: none)

**State management:**
- Toggle state stored in the Zustand canvas store (NOT persisted to demo/template — it's a view preference)
- Default: ON during design time
- Default: OFF when a demo is in "running" state (auto-hides when deployed, auto-shows when stopped/destroyed)
- The FA can manually override in any state

**Auto-hide behavior:**
- When the FA clicks "Deploy," the toggle automatically switches to OFF
- When the FA clicks "Stop" or "Destroy," the toggle automatically switches to ON
- This ensures internal notes disappear during live demos without the FA remembering to toggle manually
- The FA can always manually toggle back ON during a running demo if they need their notes

### 1.4 Properties Panel Update

When a sticky note is selected, the properties panel should show:

1. **Title** — text input (new field, optional)
2. **Content** — textarea (existing)
3. **Visibility** — segmented control with two options:
   - "Customer" (default) — standard note
   - "FA internal" — amber-styled, toggle-controlled
4. **Color** — color picker (existing, but disabled/locked to amber when visibility = "internal")

When the FA switches visibility to "internal," the color automatically changes to amber and the color picker is disabled. When they switch back to "customer," the color picker re-enables and reverts to the previous color.

### 1.5 Template YAML Schema

```yaml
sticky_notes:
  - id: sn-data-flow
    position: { x: -100, y: -20 }
    size: { width: 260, height: 80 }
    title: "Data flow"
    content: "500K firewall events as Iceberg tables, streaming at 25/s"
    color: "gray"
    visibility: "customer"        # Always visible

  - id: sn-talking-point-1
    position: { x: -100, y: 70 }
    size: { width: 260, height: 100 }
    title: "Talking point"
    content: "Ask CPX about current SIEM costs. Splunk is $150+/GB. This stack replaces it."
    color: "amber"
    visibility: "internal"        # FA toggle controls this
```

### 1.6 Compose Generator: Ignore Visibility

The compose generator already ignores sticky notes. Verify that the new `visibility` and `title` fields don't cause parsing errors.

### 1.7 Deliverables

1. Updated `StickyNote` type with `visibility` and `title` fields
2. Visual rendering: amber style for internal notes with "FA only" badge
3. Global toggle in canvas toolbar with auto-hide on deploy
4. Properties panel: visibility segmented control
5. Backward compatibility: existing notes default to "customer"

**STOP after Phase 1. Do not proceed without confirmation.**

**Architect review gate:**
- Existing sticky notes (in any template) still render correctly without `visibility` field
- Toggle auto-hide on deploy works
- Internal notes are completely invisible when toggle is OFF (no residual hover targets, no phantom space)
- The "FA only" badge is visually clear at all zoom levels

**Playwright MCP E2E tests:**

```
TEST 1.1: Create customer-facing note
  1. Right-click canvas → Add sticky note
  2. Type content
  3. Verify default visibility is "Customer"
  4. Verify standard appearance (no badge, no amber)
  5. Screenshot: customer note

TEST 1.2: Create internal note
  1. Create a sticky note
  2. Open properties panel
  3. Switch visibility to "FA internal"
  4. Verify amber border + "FA only" badge appear
  5. Verify color picker is disabled/locked to amber
  6. Screenshot: internal note with badge

TEST 1.3: Toggle hides/shows internal notes
  1. Place both customer and internal notes on canvas
  2. Verify both visible (toggle ON by default)
  3. Click FA notes toggle → OFF
  4. Verify internal note fades out
  5. Verify customer note is still visible
  6. Click toggle → ON
  7. Verify internal note reappears
  8. Screenshot: before and after toggle

TEST 1.4: Auto-hide on deploy
  1. Place internal notes on canvas with components
  2. Deploy
  3. Verify toggle automatically switches to OFF
  4. Verify internal notes are hidden
  5. Stop the demo
  6. Verify toggle switches back to ON
  7. Verify internal notes reappear
  8. Screenshot: during deploy (hidden) and after stop (visible)

TEST 1.5: Backward compatibility (REGRESSION)
  1. Load an existing template that has sticky_notes without visibility field
  2. Verify notes render normally (default to "customer")
  3. Verify no console errors
  4. Screenshot: old template loaded cleanly

TEST 1.6: Template save/load with mixed notes
  1. Create demo with both customer and internal notes
  2. Save as template
  3. Load template into new demo
  4. Verify both note types appear correctly
  5. Verify visibility settings preserved
  6. Screenshot: loaded template
```

---

## Phase 2 — CPX Demo Annotations

All sticky note content for the Sovereign Cyber Data Lake template. Each note has both a customer-facing and FA internal version where appropriate.

### 2.1 Source Systems Zone

**Customer note (near Perimeter Firewall):**
```yaml
- id: sn-fw-data
  position: { x: -260, y: -60 }   # Above/beside the firewall node
  size: { width: 280, height: 90 }
  title: "Firewall event stream"
  content: "500K events as Iceberg tables (Parquet). 20 columns: IPs, ports, protocol, action, severity, MITRE ATT&CK tactic. Streaming at 25 events/sec after initial seed."
  color: "gray"
  visibility: "customer"
```

**FA internal note (near Perimeter Firewall):**
```yaml
- id: sn-fw-fa
  position: { x: -260, y: 40 }
  size: { width: 280, height: 100 }
  title: "Demo tip"
  content: "Seeding takes ~30s. Show DemoForge log viewer during seeding — audience sees progress bar. After seed, open MinIO Console to show Parquet files landing. 3% of dst_ips correlate with IOCs — the join query WILL have results."
  visibility: "internal"
```

**Customer note (near Threat Intel Feeds):**
```yaml
- id: sn-ti-data
  position: { x: -260, y: 110 }
  size: { width: 280, height: 110 }
  title: "Three data types, two write paths"
  content: "Structured: 8K IOC records as Iceberg table via catalog API. Semi-structured: 500 STIX 2.1 JSON bundles as S3 objects. Unstructured: 200 malware binary samples as S3 objects with metadata mirrored to queryable Iceberg table."
  color: "gray"
  visibility: "customer"
```

**FA internal note (near Threat Intel Feeds):**
```yaml
- id: sn-ti-fa
  position: { x: -260, y: 230 }
  size: { width: 280, height: 110 }
  title: "Key demo moment"
  content: "Open MinIO Console → navigate to threat-intel/feeds/stix/ and click a JSON file. Show it's a real STIX bundle. Then navigate to malware-vault/samples/ — show binary objects exist. Then run Query 8 in Metabase to show malware_metadata table. This IS the structured+unstructured unified story."
  visibility: "internal"
```

**Customer note (near Vulnerability Scanner):**
```yaml
- id: sn-vs-data
  position: { x: -260, y: 340 }
  size: { width: 280, height: 80 }
  title: "Vulnerability scan data"
  content: "15K scan findings as Iceberg table. CVE IDs, CVSS scores, remediation status, business unit, OS. Batch import — scans are periodic."
  color: "gray"
  visibility: "customer"
```

**FA internal note (near Vulnerability Scanner):**
```yaml
- id: sn-vs-fa
  position: { x: -260, y: 430 }
  size: { width: 280, height: 80 }
  title: "Query 6 setup"
  content: "80% of firewall src_ips match vuln scan host_ips — so the cross-join in Query 6 (exposed hosts) will return a meaningful prioritized remediation list. This is usually the 'wow' moment for CISOs."
  visibility: "internal"
```

### 2.2 AIStor Cluster Zone

**Customer note (above/on the AIStor cluster):**
```yaml
- id: sn-aistor-catalog
  position: { x: 80, y: -50 }
  size: { width: 320, height: 100 }
  title: "Built-in Iceberg V3 REST catalog"
  content: "No external metastore. No Polaris. No Hive. The catalog is embedded at /_iceberg on port 9000. Warehouse → Namespace → Table hierarchy. Structured Iceberg tables AND raw S3 objects coexist — same cluster, same encryption, same IAM."
  color: "teal"
  visibility: "customer"
```

**FA internal note (beside the AIStor cluster):**
```yaml
- id: sn-aistor-fa
  position: { x: 80, y: 60 }
  size: { width: 320, height: 120 }
  title: "Differentiator script"
  content: "Say: 'Every other Iceberg deployment requires a separate catalog service — Hive metastore, Nessie, Polaris. That's another component to deploy, secure, back up, and monitor. AIStor builds the catalog directly into the storage layer. One system. One security model.' Then open MinIO Console and show the tables AND the raw object buckets side by side."
  visibility: "internal"
```

**FA internal note (cost angle):**
```yaml
- id: sn-cost-fa
  position: { x: 410, y: -50 }
  size: { width: 250, height: 100 }
  title: "Cost comparison talking point"
  content: "Splunk: $150-200/GB ingested. At SOC scale (1TB/day), that's $55M-73M/year. MinIO AIStor + Trino + Metabase: storage cost only, no per-GB ingestion tax. Open source query + viz. Ask CPX what they're paying today."
  visibility: "internal"
```

### 2.3 Trino + Query Zone

**Customer note (near Trino):**
```yaml
- id: sn-trino-config
  position: { x: 420, y: 30 }
  size: { width: 250, height: 70 }
  title: "Standard SQL over Iceberg"
  content: "Trino connects to AIStor's Iceberg REST catalog. Any SQL query runs against all 4 tables. No proprietary query language — standard ANSI SQL."
  color: "blue"
  visibility: "customer"
```

**FA internal note (query walkthrough):**
```yaml
- id: sn-queries-fa
  position: { x: 420, y: 110 }
  size: { width: 280, height: 200 }
  title: "Query presentation order"
  content: "Open Metabase → CPX Demo Queries collection. Run in order:
Q1: Event count (confirms scale)
Q2: Show all tables (catalog works)
Q3: IOC correlation join (the wow query — pause here, explain)
Q4: Threat actor summary (who's attacking)
Q6: Exposed hosts (CISO moment — unpatched + suspicious)
Q8: Malware metadata (unstructured → queryable)
Q10: Run twice, 30s apart (streaming proof)
Skip Q5, Q7, Q9 if short on time."
  visibility: "internal"
```

### 2.4 Metabase Zone

**Customer note (near Metabase):**
```yaml
- id: sn-metabase-info
  position: { x: 420, y: 250 }
  size: { width: 250, height: 70 }
  title: "Auto-provisioned dashboards"
  content: "3 dashboards created automatically: SOC Overview, Threat Intelligence, Vulnerability Posture. Plus 10 pre-configured analyst queries."
  color: "purple"
  visibility: "customer"
```

**FA internal note (Metabase navigation):**
```yaml
- id: sn-metabase-fa
  position: { x: 420, y: 330 }
  size: { width: 280, height: 120 }
  title: "Dashboard flow"
  content: "Start with SOC Overview (big picture, time series). Move to Threat Intel (actor-specific). Then Vuln Posture (remediation angle). THEN switch to Demo Queries collection for the interactive portion.

If dashboards are slow to load, Metabase is still syncing schema. Wait 15s and refresh. Check Admin → Databases → sync status if stuck."
  visibility: "internal"
```

### 2.5 Sovereignty / Compliance Zone

**Customer note (bottom of canvas or near the platform zone):**
```yaml
- id: sn-sovereignty
  position: { x: 80, y: 360 }
  size: { width: 320, height: 80 }
  title: "Full data sovereignty"
  content: "Everything runs on-prem. No cloud dependency. UAE PDPL compliant. Data never leaves your infrastructure. Open standards — Iceberg + S3 API. Swap any component without vendor lock-in."
  color: "teal"
  visibility: "customer"
```

**FA internal note (compliance details):**
```yaml
- id: sn-compliance-fa
  position: { x: 80, y: 450 }
  size: { width: 320, height: 100 }
  title: "Compliance talking points"
  content: "UAE Federal Decree-Law No. 45/2021 (PDPL) — data must remain under UAE jurisdiction. CPX serves government + critical infrastructure — sovereignty is non-negotiable. Also mention: MinIO supports server-side encryption (SSE-S3, SSE-KMS), object locking (WORM), and granular IAM. If they ask about NESA compliance, AIStor's audit logging covers it."
  visibility: "internal"
```

### 2.6 Opening / Closing Reminders

**FA internal note (canvas corner — opening):**
```yaml
- id: sn-opening-fa
  position: { x: -400, y: -100 }
  size: { width: 300, height: 120 }
  title: "Opening (before deploy)"
  content: "Show canvas first — narrate the topology. 'Three source systems on the left — your firewalls, threat intel, vuln scanners. MinIO AIStor in the center — one system for tables AND objects. Trino for SQL. Metabase for dashboards. Everything on-prem, everything sovereign.' THEN click Deploy."
  visibility: "internal"
```

**FA internal note (canvas corner — closing):**
```yaml
- id: sn-closing-fa
  position: { x: -400, y: 350 }
  size: { width: 300, height: 120 }
  title: "Closing (after queries)"
  content: "Recap: 'One platform. Structured tables + raw objects. Standard SQL + auto-provisioned dashboards. Sovereign. On-prem. A fraction of Splunk's cost. And the same data can power ML anomaly detection and AI threat hunting tomorrow — no ETL, no copying. That's AIStor Tables.'

Then offer: 'Want to see the AI extension? We have notebooks ready.'"
  visibility: "internal"
```

### 2.7 Template Update

Add all notes above to `demo-templates/sovereign-cyber-data-lake.yaml` under the `sticky_notes` section. Total: ~16 notes (8 customer-facing, 8 FA internal).

### 2.8 Deliverables

1. Updated template YAML with all 16 sticky notes
2. Verified: customer notes render correctly at all zoom levels
3. Verified: FA notes appear/disappear with toggle
4. Verified: FA notes auto-hide on deploy
5. Verified: all note content is accurate and matches the demo flow

**STOP after Phase 2. Do not proceed without confirmation.**

**Architect review gate:**
- Note placement doesn't overlap with component nodes at default zoom
- Note content is accurate (data volumes, query numbers, column names match the scenario YAMLs)
- FA internal notes contain actionable guidance, not just descriptions
- Customer notes are concise and presentation-quality (no jargon, no internal references)

**Playwright MCP E2E tests:**

```
TEST 2.1: Template loads with mixed notes
  1. Load Sovereign Cyber Data Lake template
  2. Verify both customer and internal notes appear (toggle ON by default)
  3. Count visible notes: should be ~16
  4. Verify customer notes have standard styling
  5. Verify internal notes have amber border + "FA only" badge
  6. Screenshot: full canvas with all notes

TEST 2.2: Toggle hides internal notes only
  1. With template loaded, click FA notes toggle → OFF
  2. Verify ~8 internal notes disappear
  3. Verify ~8 customer notes remain visible
  4. Screenshot: canvas with only customer notes

TEST 2.3: Deploy auto-hides internal notes
  1. Toggle ON (all notes visible)
  2. Deploy the template
  3. Verify toggle auto-switches to OFF
  4. Verify internal notes hidden during running state
  5. Verify customer notes still visible
  6. Screenshot: deployed canvas (clean, customer-only)

TEST 2.4: Notes don't overlap components
  1. At default zoom, verify no note overlaps any component node
  2. Zoom out to 50% — verify notes are still readable
  3. Zoom in to 150% — verify no overflow
  4. Screenshot: multiple zoom levels
```

---

## Summary

This spec adds one UI feature (note visibility toggle) and 16 sticky notes for the CPX demo. The feature is small but high-leverage — it turns the canvas into a dual-purpose tool: a customer presentation surface AND an FA coaching sheet.

**Files changed:**
- Frontend: StickyNote type, sticky note renderer, properties panel, canvas toolbar
- Template: sovereign-cyber-data-lake.yaml (sticky_notes section)
- No backend changes (visibility is a frontend concern, persisted in demo state as a field on each note)

**Resource impact:** Zero. Notes are DOM elements with no deployment artifacts.
