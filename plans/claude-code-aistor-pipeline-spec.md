# DemoForge: AIStor Tables Pipeline, Metabase Provisioning & Canvas Branding

## Overview

This is the companion spec to `claude-code-external-system-spec.md`. While that spec covers the External System component and Scenario YAML engine, this spec covers the remaining pieces needed for a complete demo pipeline:

1. **MinIO AIStor Tables integration** — Ensuring the MinIO component supports the built-in Iceberg REST Catalog, and that the Trino connector is correctly configured to query it
2. **Metabase auto-provisioning** — Enhancements to the Metabase component so it auto-configures its Trino data source when connected via edge
3. **Canvas Image component** — A visual-only canvas element for logos, branding, and contextual backdrops (with MinIO AIStor and AIStor Tables logo presets)

**Dependency:** This spec assumes the External System spec is being implemented in parallel or has already been completed. The AIStor Tables and Metabase work can proceed independently, but the Canvas Image component has no dependencies.

---

## Agent Review, Validation & Testing Requirements

The same review and testing standards from the External System spec apply here:

- **Architect/senior agent review** at every phase stop gate — fit review, non-breakage review, code quality review
- **Playwright MCP E2E tests** for all phases producing deployable artifacts
- **Regression testing** — existing templates and components must continue to work unchanged
- **Screenshots** captured at every assertion point as evidence
- **No proceeding on failure** — fix, re-run all tests, then proceed

Refer to the External System spec for the full protocol. This spec defines its own test scenarios below.

---

## Phase 0 — Read-Only Investigation

**DO NOT write any code in this phase. Only read and report.**

### 0.1 MinIO Component — AIStor Tables State

Read the MinIO component thoroughly:
- `components/minio/manifest.yaml` — full contents
- All files under `components/minio/` — templates, static mounts, Dockerfile if any
- How does the MinIO image get selected? Is there a mechanism to switch between `minio/minio` (community) and the AIStor image?
- Is there already an `aistorTablesEnabled` flag or similar? (The External System investigation found a reference to this in the Trino→MinIO connection validation)
- What environment variables or command flags does the MinIO container use?
- How does the MinIO cluster component differ from a single-node MinIO?

### 0.2 Trino Component — Iceberg Connector Templates

Read the Trino component thoroughly:
- `components/trino/manifest.yaml` — full contents
- `components/trino/templates/iceberg.properties.j2` — full contents with line numbers
- `components/trino/templates/aistor-iceberg.properties.j2` — full contents with line numbers
- `components/trino/templates/hive.properties.j2` — full contents
- Any other files under `components/trino/`
- How does Trino currently detect whether it's connected to a MinIO with AIStor Tables vs a regular MinIO + separate Iceberg REST catalog?
- How are catalog properties files mounted into the Trino container?

### 0.3 Metabase Component — Current State

Read the Metabase component thoroughly:
- `components/metabase/manifest.yaml` — full contents
- All files under `components/metabase/` — templates, static mounts, init scripts
- What Metabase version/image is used?
- Does Metabase currently auto-configure any data sources, or is it a blank slate on first deploy?
- What connection types does it accept/provide?
- How does Metabase connect to Trino? (JDBC? What driver?)
- Is there any existing init script or provisioning logic?

### 0.4 Connection Type: aistor-tables — Compose Generation

Deep dive into how `aistor-tables` is handled in `compose_generator.py`:
- What environment variables are injected when an `aistor-tables` edge exists?
- Is `ICEBERG_CATALOG_URI` already set? What's its format?
- Does the compose generator construct the `/_iceberg` path, or does the consuming component do it?
- How does Trino's Iceberg connector template (`aistor-iceberg.properties.j2`) use these variables?
- Show the complete auto-configuration code path for an `aistor-tables` edge between Trino and MinIO

### 0.5 Connection Type: sql-query — Compose Generation

How does `sql-query` work between Metabase and Trino:
- What environment variables are injected?
- Does Metabase receive Trino's hostname and port automatically?
- Is there any JDBC URL construction logic?

### 0.6 Canvas Node Visuals

- How are node icons rendered? SVG? Image file? CSS class?
- Where is the icon mapping defined (component ID → icon asset)?
- What icon formats are supported?
- Is there a mechanism for a component to render as a purely visual element (no ports, no connections)?
- Can a node have custom dimensions (wider/taller than default)?
- Can a node render an image (PNG/SVG) instead of the standard component box?

### 0.7 Frontend Component Palette

- How are components organized in the palette/sidebar?
- How are component categories ordered?
- Is there a filtering or search mechanism?
- Can a component be flagged as "visual only" or "non-deployable"?

### 0.8 Report Format

Produce a single report with:
1. Complete MinIO manifest and all template/config files
2. Complete Trino manifest and ALL template files (iceberg, aistor-iceberg, hive)
3. Complete Metabase manifest and all supporting files
4. Complete auto-configuration code for `aistor-tables` edges in compose_generator.py
5. Complete auto-configuration code for `sql-query` edges
6. Icon rendering system: file paths, formats, how they're loaded
7. Whether node custom sizing/image rendering exists
8. Component palette organization code

**STOP after producing this report. Do not proceed to Phase 1 without explicit confirmation.**

**Architect review gate:** The architect reviews the report for completeness and identifies any assumptions in this spec that need amendment. Key questions: Does the `aistor-iceberg.properties.j2` template already produce a working Trino↔AIStor REST catalog config? If so, what (if anything) needs changing? Does Metabase already have Trino connectivity logic?

---

## Phase 1 — AIStor Tables: MinIO + Trino Integration Validation

This phase ensures the MinIO AIStor → Trino → Iceberg query path works correctly. Based on Phase 0 findings, this may require changes or may just need validation that the existing implementation is correct.

### 1.1 MinIO AIStor Image Configuration

The MinIO component must support selecting the AIStor image. Based on the research, AIStor Tables is available starting from `RELEASE.2026-02-02T23-40-11Z`. The key technical facts:

- **Iceberg REST Catalog endpoint:** `http://{minio_host}:9000/_iceberg` (same port as S3 API)
- **Authentication:** AWS SigV4 with service name `s3tables`
- **Hierarchy:** Warehouse → Namespace → Table
- **No additional ports needed** — the `/_iceberg` path is served on the standard S3 API port (9000)
- **No additional configuration flags needed** — Tables support is built into AIStor builds

**What to verify/implement:**
1. The MinIO component's `aistorTablesEnabled` flag (if it exists) correctly switches to the AIStor image
2. If the flag doesn't exist, add it as a node-level config option (boolean toggle in properties panel)
3. When AIStor Tables is enabled, the compose generator should set `ICEBERG_CATALOG_URI` on any connected component that accepts `aistor-tables` connections

### 1.2 Trino Iceberg Connector for AIStor

The Trino catalog properties file for AIStor Tables should produce:

```properties
connector.name=iceberg
iceberg.catalog.type=rest
iceberg.rest-catalog.uri=http://{minio_service_name}:9000/_iceberg
iceberg.rest-catalog.warehouse={warehouse_name}
iceberg.rest-catalog.vended-credentials-enabled=true

# S3 filesystem configuration (Trino reads data files directly from MinIO)
fs.native-s3.enabled=true
s3.endpoint=http://{minio_service_name}:9000
s3.region=us-east-1
s3.path-style-access=true
s3.aws-access-key={access_key}
s3.aws-secret-key={secret_key}

# REST catalog SigV4 auth
iceberg.rest-catalog.security=OAUTH2
```

**Note:** The exact properties depend on the Trino version. The investigation in Phase 0 will reveal what the existing `aistor-iceberg.properties.j2` template already contains. The goal is to ensure it produces a working config — not to rewrite it unnecessarily.

**What to verify/implement:**
1. The `aistor-iceberg.properties.j2` template renders correct properties when a Trino→MinIO `aistor-tables` edge exists
2. The template has access to the MinIO node's hostname, port, and credentials via Jinja2 context
3. The `warehouse` name is configurable (default: `analytics`)
4. Test: deploy MinIO (AIStor) + Trino, create an Iceberg table via PyIceberg, query it via Trino — must work

### 1.3 Warehouse Configuration

The AIStor Tables hierarchy is Warehouse → Namespace → Table. The warehouse must be created before tables can be written.

**Options:**
- **Option A:** The External System container creates the warehouse as part of its init sequence (preferred — keeps it in the scenario engine)
- **Option B:** The MinIO component has an init script that creates a default warehouse
- **Option C:** The warehouse is created on-demand by the first write operation

Recommend **Option A** — the External System container creates the warehouse as its first action after connecting to AIStor. The warehouse name comes from the scenario YAML (default: `analytics`). This keeps the MinIO component clean and stateless.

### 1.4 Deliverables

1. Validated or updated `aistor-iceberg.properties.j2` template
2. Validated or updated MinIO manifest (AIStor toggle)
3. Validated compose generator auto-configuration for `aistor-tables` edges
4. Documentation of the working config (for future reference)

**STOP after Phase 1 deliverables. Do not proceed to Phase 2 without explicit confirmation.**

**Architect review gate:** The architect verifies:
- The Trino↔AIStor connection actually works (not just theoretically correct config)
- The SigV4 authentication is handled correctly
- The template renders correctly for both single-node MinIO and MinIO cluster topologies
- Existing Trino connections to non-AIStor MinIO (via separate Iceberg REST catalog) still work — no regression

**Playwright MCP E2E tests:**

```
TEST 1.1: AIStor Tables toggle exists
  1. Open DemoForge canvas
  2. Place a MinIO node
  3. Open properties panel
  4. Verify AIStor Tables toggle/option exists
  5. Enable it
  6. Screenshot: properties panel with toggle

TEST 1.2: Trino connects to AIStor via aistor-tables edge
  1. Place MinIO (AIStor enabled) and Trino on canvas
  2. Connect Trino → MinIO with aistor-tables connection type
  3. Deploy
  4. Wait for both containers to be healthy
  5. Open Trino UI
  6. Run: SHOW CATALOGS — verify the AIStor catalog appears
  7. Screenshot: Trino catalog list

TEST 1.3: Existing Iceberg REST catalog still works (REGRESSION)
  1. Load any existing template that uses Trino + separate iceberg-rest catalog
  2. Deploy
  3. Verify Trino can query Iceberg tables
  4. Destroy
  5. Screenshot: working query
```

---

## Phase 2 — Metabase Auto-Provisioning

Enhance the Metabase component so it auto-configures its Trino data source when connected via an edge, eliminating manual setup during demos.

### 2.1 Current State Assessment

Based on Phase 0 findings, determine whether Metabase currently:
- Starts as a blank instance (most likely)
- Has any init script or first-boot logic
- Has Trino JDBC driver bundled or needs it added

### 2.2 Metabase Trino Auto-Configuration

When a `sql-query` edge connects Metabase to Trino, the compose generator should inject:
- `TRINO_HOST` — Trino container hostname
- `TRINO_PORT` — Trino HTTP port (typically 8080)
- `TRINO_USER` — Trino user (default: `trino` or `demoforge`)
- `TRINO_CATALOG` — The catalog name to query (default: `aistor` for AIStor Tables, `iceberg` otherwise)

### 2.3 Metabase Init Script

Create an init script (or enhance if one exists) that runs after Metabase is healthy:

```
1. Wait for Metabase to be ready (GET /api/health returns ok)
2. Check if first-time setup is needed (GET /api/session/properties)
3. If first-time: run setup via POST /api/setup
   - Admin email: admin@demoforge.local
   - Admin password: DemoForge2026!
   - Skip optional steps
4. Authenticate: POST /api/session → get session token
5. Check if Trino database already exists: GET /api/database
6. If not: create Trino database via POST /api/database
   - Engine: "starburst" (Trino-compatible)
   - Host: ${TRINO_HOST}
   - Port: ${TRINO_PORT}
   - User: ${TRINO_USER}
   - Database (catalog): ${TRINO_CATALOG}
7. Trigger schema sync: POST /api/database/{id}/sync_schema
8. Log success: "Metabase configured with Trino data source"
```

**Implementation options:**
- **Option A:** A Jinja2-templated shell script mounted into the Metabase container, run via `init_scripts` in the manifest (preferred if the existing init_scripts mechanism supports post-healthy execution)
- **Option B:** A sidecar container that runs once and exits (adds complexity)
- **Option C:** Bake the logic into the External System container's provisioner (already planned in the External System spec — but this makes Metabase dependent on having an External System connected)

Recommend **Option A** for basic Trino setup, with the External System's provisioner handling dashboard creation on top. This separation means Metabase works correctly even without an External System connected — an FA can manually create queries and dashboards.

### 2.4 Metabase Driver for Trino

Metabase needs a Trino-compatible JDBC driver. Check Phase 0 findings for:
- Does the current Metabase image include the Starburst driver?
- If not, does it need to be added to `/plugins`?
- Is there a Metabase version that bundles it natively?

If the driver needs to be added, create a custom Dockerfile that extends the Metabase image and copies the driver JAR into `/plugins/`.

### 2.5 Metabase Admin Credentials

Default credentials for the auto-setup:
- **Email:** `admin@demoforge.local`
- **Password:** `DemoForge2026!`

These should be configurable via environment variables:
- `MB_ADMIN_EMAIL` (default: `admin@demoforge.local`)
- `MB_ADMIN_PASSWORD` (default: `DemoForge2026!`)

The FA never needs to know these — they open Metabase from the canvas "Open UI" button, and the init script has already configured everything.

### 2.6 Deliverables

1. Updated `components/metabase/manifest.yaml` (new env vars, init script reference)
2. Metabase init script (shell or Python)
3. Updated Dockerfile (if driver addition needed)
4. Updated compose generator handling for `sql-query` edge → Metabase
5. Verified: Deploy MinIO + Trino + Metabase, confirm Metabase auto-configures Trino data source

**STOP after Phase 2 deliverables. Do not proceed to Phase 3 without explicit confirmation.**

**Architect review gate:** The architect verifies:
- Init script handles all error cases (Metabase slow to start, Trino not ready yet, network timeout)
- Init script is idempotent (running twice doesn't create duplicate data sources)
- Credentials are not hardcoded in source — they flow from env vars
- Metabase image with driver still builds and starts correctly
- Existing Metabase behavior is unchanged when no Trino edge exists

**Playwright MCP E2E tests:**

```
TEST 2.1: Metabase starts and completes setup
  1. Deploy MinIO + Trino + Metabase (connected)
  2. Wait for all containers healthy
  3. Open Metabase UI
  4. Verify login page appears (NOT setup wizard — init script should have completed setup)
  5. Screenshot: Metabase login page

TEST 2.2: Trino data source auto-configured
  1. Log into Metabase (admin@demoforge.local / DemoForge2026!)
  2. Navigate to Admin → Databases
  3. Verify Trino database appears
  4. Verify connection status is "synced" or "syncing"
  5. Screenshot: database admin page

TEST 2.3: Can query Trino from Metabase
  1. Navigate to New → SQL Query
  2. Select Trino database
  3. Run: SELECT 1 AS test
  4. Verify result returns
  5. Screenshot: query result

TEST 2.4: Metabase without Trino edge still works (REGRESSION)
  1. Deploy Metabase standalone (no Trino edge)
  2. Wait for healthy
  3. Open Metabase UI
  4. Verify it starts normally (setup wizard appears since no auto-config)
  5. Destroy
  6. Screenshot: standalone Metabase
```

---

## Phase 3 — Canvas Image Component

A visual-only canvas element that renders an image (logo, diagram, or badge) on the canvas. Not a deployable container — purely for presentation and context during demos.

### 3.1 Design Concept

The Canvas Image component serves several purposes:
- **Branding:** Place MinIO AIStor or AIStor Tables logos on the canvas to make the demo look professional
- **Context:** Add customer logos, architecture labels, or visual separators
- **Storytelling:** Mark areas of the canvas ("On-Prem Zone," "Cloud Zone," "Customer Environment")

On the canvas, it renders as an image with optional label, no ports, no connections, no container. Think of it as a "sticker" on the canvas.

### 3.2 Architecture Decision: NOT a Component

Based on the Phase 0 investigation of the External System spec, we know that `ComponentManifest` requires an `image` field (Docker image), and every component generates a Docker Compose service. A canvas image/logo element should NOT be a component — it produces no container.

Instead, implement it as a **new canvas element type** alongside existing nodes, groups, and sticky notes. The demo template YAML already has `sticky_notes: []` — this is the same pattern.

```typescript
// New type in the frontend
export interface CanvasImage {
  id: string;
  position: { x: number; y: number };
  size: { width: number; height: number };
  image_id: string;        // References a preset or custom image
  label?: string;          // Optional text label below image
  opacity: number;         // 0.0-1.0 (default: 0.8 for backdrop feel)
  locked: boolean;         // Prevent accidental dragging (default: false)
  layer: "background" | "foreground";  // Render behind or in front of nodes
}
```

### 3.3 Preset Image Library

Ship with a built-in set of preset images. These are SVG files stored in the frontend assets:

```
frontend/src/assets/canvas-images/
├── minio-aistor-logo.svg
├── minio-aistor-tables-logo.svg
├── minio-logo.svg
├── minio-logo-white.svg
├── apache-iceberg-logo.svg
├── trino-logo.svg
├── zone-on-prem.svg          # "On-Premises" badge/banner
├── zone-cloud.svg            # "Cloud" badge/banner
├── zone-customer.svg         # "Customer Environment" badge/banner
├── arrow-right-large.svg     # Visual flow arrow
├── arrow-down-large.svg      # Visual flow arrow
├── divider-horizontal.svg    # Visual separator
├── divider-vertical.svg      # Visual separator
```

For the MinIO logos, source from official MinIO brand assets. If unavailable at build time, use placeholder SVGs that will be replaced.

### 3.4 Image Picker UI

When the FA clicks "Add Image" from the canvas toolbar (or right-click context menu):
1. A modal/popover shows the preset image library as a grid of thumbnails
2. FA clicks a preset to add it to the canvas at the center of the current viewport
3. Once placed, the FA can:
   - Drag to reposition
   - Resize via corner handles
   - Adjust opacity via a slider in the properties panel
   - Set to background/foreground layer
   - Add a text label
   - Lock position
   - Delete

### 3.5 Template YAML Representation

Add `canvas_images` to the demo template schema:

```yaml
# In demo template YAML
canvas_images:
  - id: aistor-logo
    image_id: minio-aistor-tables-logo
    position: { x: 50, y: 80 }
    size: { width: 200, height: 60 }
    opacity: 0.15
    layer: background
    locked: true

  - id: customer-zone-label
    image_id: zone-customer
    position: { x: -350, y: -50 }
    size: { width: 180, height: 40 }
    opacity: 0.7
    layer: foreground
    label: "CPX SOC Systems"
    locked: false
```

### 3.6 Rendering

- **Background layer:** Rendered behind all React Flow nodes, edges, and groups. Uses React Flow's custom background or a layer with lower z-index.
- **Foreground layer:** Rendered on top of edges but behind node selections/menus. Uses a React Flow custom node type with `zIndex` control.
- **Opacity:** Applied via CSS `opacity` on the image element.
- **Non-interactive in deployed state:** When a demo is deployed (running), canvas images are visible but not selectable/draggable to prevent accidental repositioning during a live demo.

### 3.7 Backend Changes

Minimal backend changes needed:
- Add `canvas_images` field to the `DemoDefinition` model (list of `CanvasImage`, default `[]`)
- Ensure `canvas_images` is persisted when saving demos and templates
- Ensure `canvas_images` is included when loading demos and templates
- **No compose generator changes** — canvas images produce no Docker services
- **No API changes** — canvas images are part of the demo state, saved with the existing demo save endpoint

### 3.8 Compose Generator: Ignore Canvas Images

The compose generator must skip `canvas_images` entirely. Add a comment in the generator making this explicit: canvas images are visual-only elements with no deployment artifacts.

### 3.9 Deliverables

1. `CanvasImage` TypeScript type definition
2. `canvas_images` field added to `DemoDefinition` backend model
3. Frontend rendering for canvas images (background and foreground layers)
4. Image picker UI (modal with preset grid)
5. Properties panel for canvas images (opacity, layer, label, lock, size, delete)
6. Preset SVG files in `frontend/src/assets/canvas-images/`
7. Template YAML save/load support for `canvas_images`
8. At least one preset image renders correctly on canvas

**STOP after Phase 3 deliverables. Do not proceed to Phase 4 without explicit confirmation.**

**Architect review gate:** The architect verifies:
- Canvas images do NOT affect compose generation (zero Docker artifacts)
- Canvas images persist correctly across save/load/template operations
- Existing demos without `canvas_images` still load correctly (backward compatibility)
- The React Flow performance is not degraded by image rendering (especially with large/many images)
- SVG assets are properly sized and optimized (no 5MB PNGs)
- The image picker UI follows the existing DemoForge design language (shadcn/ui zinc dark theme)

**Playwright MCP E2E tests:**

```
TEST 3.1: Add canvas image from toolbar
  1. Open DemoForge canvas
  2. Find and click "Add Image" button in toolbar (or right-click → Add Image)
  3. Verify image picker modal appears
  4. Verify preset thumbnails are visible (MinIO AIStor, AIStor Tables, etc.)
  5. Click "MinIO AIStor Tables" preset
  6. Verify image appears on canvas
  7. Screenshot: image on canvas

TEST 3.2: Canvas image properties
  1. Select the placed canvas image
  2. Verify properties panel shows opacity slider, layer toggle, label input, lock toggle
  3. Change opacity to 0.3
  4. Verify image opacity updates visually
  5. Set layer to "background"
  6. Verify image renders behind nodes
  7. Add label "MinIO AIStor Tables"
  8. Verify label appears below image
  9. Screenshot: image with properties

TEST 3.3: Canvas image persists in save
  1. Place a canvas image
  2. Save demo as template
  3. Create new demo from that template
  4. Verify canvas image appears in the new demo at the correct position
  5. Screenshot: loaded template with image

TEST 3.4: Canvas image resize and drag
  1. Place a canvas image
  2. Drag it to a new position
  3. Resize via corner handles
  4. Verify position and size update
  5. Lock the image
  6. Attempt to drag — verify it doesn't move
  7. Screenshot: resized and locked image

TEST 3.5: Deploy still works with canvas images (REGRESSION)
  1. Place canvas images AND deployable components on canvas
  2. Deploy
  3. Verify containers start correctly
  4. Verify canvas images are still visible but non-interactive
  5. Destroy
  6. Verify canvas images are still present
  7. Screenshot: deployed canvas with images

TEST 3.6: Old demos without canvas_images still load (REGRESSION)
  1. Load an existing demo/template that predates canvas_images
  2. Verify it loads without errors
  3. Verify canvas is empty of images (no crash from missing field)
  4. Screenshot: old template loaded cleanly
```

---

## Phase 4 — Unified Template & Full Pipeline Validation

Bring everything together: External System + AIStor Tables + Trino + Metabase + Canvas Images.

### 4.1 Enhanced Sovereign Cyber Data Lake Template

Update the `sovereign-cyber-data-lake` template (from the External System spec) to include canvas images:

```yaml
# Add to the template YAML
canvas_images:
  - id: aistor-tables-backdrop
    image_id: minio-aistor-tables-logo
    position: { x: 100, y: 250 }
    size: { width: 280, height: 80 }
    opacity: 0.08
    layer: background
    locked: true

  - id: customer-zone
    image_id: zone-customer
    position: { x: -350, y: -30 }
    size: { width: 160, height: 36 }
    opacity: 0.6
    layer: foreground
    label: "Customer SOC Systems"
    locked: true

  - id: data-platform-label
    image_id: zone-on-prem
    position: { x: 100, y: -30 }
    size: { width: 160, height: 36 }
    opacity: 0.6
    layer: foreground
    label: "Sovereign Data Platform"
    locked: true
```

### 4.2 Full Pipeline Validation

This is the acceptance test for the entire data analytics demo pipeline:

```
FULL PIPELINE TEST: Sovereign Cyber Data Lake End-to-End

  Setup:
    - Start DemoForge (make dev)
    - Load "Sovereign Cyber Data Lake" template

  Step 1: Canvas Verification
    1. Verify canvas shows correct topology:
       - External System ("Perimeter Firewall") → MinIO AIStor → Trino → Metabase
       - External System → Metabase (dashboard-provision edge)
    2. Verify canvas images render:
       - AIStor Tables logo as subtle background
       - "Customer SOC Systems" label near External System
       - "Sovereign Data Platform" label near MinIO/Trino/Metabase
    3. Screenshot: complete canvas before deployment

  Step 2: Deployment
    4. Click Deploy
    5. Wait for all containers to go green (healthy)
    6. Verify MinIO AIStor is running with Tables enabled
    7. Verify Trino is running with AIStor Iceberg catalog
    8. Verify Metabase is running with Trino data source auto-configured
    9. Verify External System container starts data generation
    10. Screenshot: all containers healthy

  Step 3: Data Verification
    11. Open MinIO Console
    12. Verify Iceberg table data exists in warehouse bucket
    13. Screenshot: MinIO Console showing data
    14. Open Trino UI
    15. Run: SHOW SCHEMAS FROM aistor → verify "soc" schema exists
    16. Run: SHOW TABLES FROM aistor.soc → verify firewall_events, threat_iocs, vulnerability_scan
    17. Run: SELECT count(*) FROM aistor.soc.firewall_events → verify ~500K rows
    18. Run cross-table join:
        SELECT f.dst_ip, t.threat_actor, t.confidence, count(*) as hits
        FROM aistor.soc.firewall_events f
        JOIN aistor.soc.threat_iocs t ON f.dst_ip = t.indicator
        WHERE t.ioc_type = 'ipv4'
        GROUP BY 1, 2, 3
        ORDER BY hits DESC LIMIT 10
    19. Verify non-empty results (correlation engine worked)
    20. Screenshot: Trino query results

  Step 4: Dashboard Verification
    21. Open Metabase
    22. Verify auto-login works (or login with admin creds)
    23. Navigate to "SOC Overview" dashboard
    24. Verify all charts render with data:
        - Events (24h) number card
        - Critical/High Alerts number card
        - Event Volume time series
        - Severity Distribution donut
        - Top Blocked Destinations bar chart
        - MITRE ATT&CK coverage
        - Geographic distribution
    25. Screenshot: SOC Overview dashboard
    26. Navigate to "Threat Intelligence" dashboard
    27. Verify IOC-firewall join table shows correlated hits
    28. Screenshot: Threat Intelligence dashboard
    29. Navigate to "Vulnerability Posture" dashboard
    30. Verify vulnerability charts render
    31. Screenshot: Vulnerability Posture dashboard

  Step 5: Live Demo Simulation
    32. Wait 60 seconds
    33. Refresh SOC Overview dashboard
    34. Verify numbers have increased (streaming is working)
    35. Screenshot: updated numbers

  Step 6: Cleanup
    36. Stop the demo
    37. Verify all containers stop
    38. Verify canvas images are still visible
    39. Destroy the demo
    40. Verify clean state
    41. Screenshot: clean canvas with images preserved
```

### 4.3 Second Scenario Test

Create a minimal test with a different scenario to validate the pluggable nature:

```
SCENARIO SWAP TEST:

  1. Create new demo on empty canvas
  2. Drag External System → rename to "Order Processing System"
  3. Set scenario to "ecommerce-orders"
  4. Connect to MinIO (AIStor) → Trino → Metabase
  5. Deploy
  6. Verify e-commerce data seeds correctly
  7. Verify e-commerce dashboards appear in Metabase
  8. Destroy
  9. Screenshot: e-commerce demo working
```

### 4.4 Deliverables

1. Updated `sovereign-cyber-data-lake` template with canvas images
2. Full pipeline test results (all 41 steps above) with screenshots
3. Scenario swap test results with screenshots
4. Any bug fixes discovered during integration testing

**STOP after Phase 4. Review with Ahmad before any further work.**

**Architect review gate — FINAL:** Comprehensive review:
- Full codebase diff across all phases of BOTH specs (External System + this spec)
- Verify no unintended side effects on any existing component or template
- Performance check: does the full deployment start within a reasonable time (< 3 minutes)?
- Verify all canvas images render correctly at different zoom levels
- Verify the demo is presentable to a customer (no debug output, no broken UI, no missing data)

**Playwright MCP E2E tests — FULL SUITE:** Run ALL tests from both specs:
- External System spec: TEST 2.1–2.6, 3.1–3.6, 4.1–4.4
- This spec: TEST 1.1–1.3, 2.1–2.4, 3.1–3.6, FULL PIPELINE TEST, SCENARIO SWAP TEST

**All tests must pass in a single clean run.** Produce a final combined test report covering both specs.

**Final summary document** listing:
1. All files created across both specs (with paths)
2. All files modified across both specs (with paths and change summary)
3. All new dependencies introduced
4. Known limitations or future work
5. Complete Playwright test report with screenshots
6. Deployment resource requirements (memory, CPU, disk)
