# DemoForge Backlog

> Archive of pre-2026-04-09 items: `plans/backlog-backup-2026-04-09.md`

---

## Backlog

- [x] **Enhancement: Smart connection type picker when linking External System / Data Generator → MinIO Node or Cluster**
  - When the user draws an edge from an External System or Data Generator component to a MinIO Node or MinIO Cluster, the connection type picker should offer two options: **S3** (standard) and **AIStor Tables (SigV4 Iceberg)**.
  - The AIStor Tables option should only appear when the target Node or Cluster has AIStor Tables enabled in its config.
  - If only one type is valid (e.g. AIStor Tables not enabled), skip the picker and default to S3.

- [x] **Enhancement: MinIO Node — AIStor Tables & MCP Server feature toggles**
  - The MinIO Node (single-node component) currently has no AIStor Tables or MCP Server config options, unlike the MinIO Cluster which exposes these in its properties panel.
  - Add feature toggle fields to the Node component manifest and its PropertiesPanel section: `aistor_tables_enabled` (bool, default false) and `mcp_enabled` (bool, default false), mirroring what the Cluster config already supports.
  - These toggles should drive container env vars and init scripts the same way cluster-level toggles do.

- [x] **Change: Sovereign Cyber Data Lake template — replace MinIO Node with a 4×4 MinIO Cluster**
  - Update `demo-templates/sovereign-cyber-data-lake.yaml` to use a MinIO Cluster node (4 nodes × 4 drives, 1 TB per disk) instead of the current MinIO Node.
  - AIStor Tables enabled; MCP Server disabled.
  - Adjust edges, layout positions, and any init scripts that reference the old node ID.

- [x] **Change: Cyber Lake template — Metabase dashboard provisioning as startup procedure, not an edge**
  - The current template has a `dashboard-provision` edge from External System → Metabase. This is architecturally wrong: dashboard provisioning is a one-time init action, not a runtime data connection.
  - Remove the `dashboard-provision` edge from the template. Move provisioning into the External System container's startup/init script (already done at runtime via `metabase_client.py`) and remove the `dashboard-provision` connection type from the External System manifest's `provides` list if it is only used for this template.
  - The Metabase node should remain in the template but connected only via a standard service/web-ui relationship, not a data edge.

- [x] **Enhancement: Edge label on External System → MinIO link shows scenario data type and format**
  - When an External System node is connected to a MinIO Node or Cluster and a scenario is selected (e.g. "SOC Firewall Events"), the edge between them should display a short label indicating both what is being generated and its format (e.g. "Iceberg · Parquet · firewall-events").
  - Source of truth: the scenario YAML — combine `output.format` (e.g. Parquet, JSON) and `output.table` or `description` into the label.
  - The label should update reactively when the scenario changes in PropertiesPanel.
  - Keep the label concise (≤ 40 chars); use the existing AnimatedDataEdge label slot.

- [x] **Enhancement: External System — update icon and palette category**
  - The External System component currently uses a cloud icon and is grouped with infrastructure components. It should use an icon that represents a generic external system / enterprise application (e.g. a building/server/globe icon), and its palette category should be aligned with Data Generators so they appear together in the designer sidebar.

- [x] **Investigation + Fix: Throughput tab in Cockpit shows no metrics**
  - Root cause: `mc admin bandwidth --json` is a continuous monitoring tool — a single-shot call returns 0 or hangs, blocking every cockpit request. Removed it entirely.
  - Fix: Prometheus counter-diff (`_get_throughput_from_prometheus`) is now the unconditional primary source. Added 8-sample rolling window (`_rolling_throughput`) that averages non-zero samples, smoothing out the initial zero from the first poll.
  - Best practice used: rolling average over last 8 samples (non-zero only) rather than instantaneous rate.

- [x] **BUG: FA mode designer shows all components in palette — should only show FA-ready/validated ones**
  - Fixed: `backend/app/api/registry.py` already filters to `fa_ready` components when `DEMOFORGE_MODE` is `fa` or `dev` (lines 14-19). The `/api/registry/components` endpoint applies the filter; `ComponentPalette` in the frontend fetches from this endpoint and renders only what the backend returns. No frontend change required.

- [x] **Enhancement: External System component — scenario picker + auto-connect (like data-generator)**
  - Full scenario engine implemented: Python container (`components/external-system/`), 3 SOC scenario YAMLs (soc-firewall-events, soc-threat-intel, soc-vuln-scan), Metabase dashboard + saved_queries provisioning
  - Scenario picker: `GET /api/registry/components/external-system/scenarios` endpoint; `ScenarioPicker.tsx` dropdown in PropertiesPanel for external-system nodes; selecting a scenario sets `ES_SCENARIO` config
  - Template: `demo-templates/sovereign-cyber-data-lake.yaml` — 6 nodes, 6 edges, AIStor Tables logo backdrop, FA Guide + SE guide
  - Demo script: `demo-templates/guides/cpx-demo-script.md` — 25-minute script, 13 scenes

- [x] **BUG: FA mode shows all templates including non-FA ones in tier tabs and My Templates**
  - Fixed in `TemplateGallery.tsx`: tier tab filter and count now apply `faMode !== "fa" || t.validated` so only fa_ready templates appear in Essentials/Advanced/Experiences when in FA mode
  - Fixed My Templates filter and count: in FA mode with faId set, restricts to `saved_by === faId` (only this FA's own published templates)

---

- [x] **BUG: Destroying a demo does not stop the running containers**
  - Fixed: `_cleanup_demo` now always calls `_force_remove_containers` as a final pass after compose down (not just on failure). Added `os.path.exists(compose_path)` guard — if the compose file is missing, skips directly to force-remove. Belt-and-suspenders: even if compose down succeeds, the Docker API force-remove pass catches any stragglers.

- [x] **BUG: Cockpit Health tab shows stale/old date for cluster last-seen timestamp**
  - Fixed: The displayed value was `servers[0].version` (MinIO binary release date like `RELEASE.2026-03-20T23:11:32Z`) which never changes. Replaced with formatted `servers[0].uptime` (seconds → "3d 4h online") which reflects actual server runtime. Added `formatUptime()` helper in CockpitOverlay.tsx.

- [x] **Enhancement: Cockpit Stats tab — replace UP/DOWN object counters with per-cluster storage utilisation**
  - Fixed: Removed `↑ txRate` and `↓ rxRate` byte-rate indicators from the Stats tab footer (these belong in Throughput tab). Replaced with object count + storage utilisation bar (used/total bytes + % bar) sourced from `healthData?.clusters` capacity data already in scope.

- [x] **BUG: Cockpit Throughput tab always shows 0 ops/s and 0 req/s**
  - Fixed: `_get_minio_cluster_metrics` now tries both `pool1-node-1` (multi-pool) and `node-1` (single-pool) naming — single-pool clusters were failing silently because the hardcoded `pool1-node-1` suffix didn't match their actual container names. Also widened Prometheus metric name matching in `_get_throughput_from_prometheus` to handle `minio_` prefix and `method` label variants.

- [x] **BUG: Sovereign Cyber Data Lake — data volume not growing (JSON files not being written)**
  - Fixed: `compose_generator.py` was injecting `ICEBERG_CATALOG_URI` for external-system containers but not `ICEBERG_WAREHOUSE`. The container defaulted to `"warehouse"` while AIStor clusters use `"analytics"` — causing all Iceberg writes to silently fail. Now injects `ICEBERG_WAREHOUSE` from cluster/node config alongside `ICEBERG_CATALOG_URI` in all AIStor branches.

- [x] **Enhancement: External System properties panel — show data push frequency per dataset**
  - Fixed: Added `stream_rate?: string` and `seed_rows?: number` to `ScenarioDataset` type. Registry endpoint now reads `generation.stream_rate` and `generation.seed_rows` from scenario YAML. ScenarioPicker dataset cards show formatted rate (e.g. "500k seed rows, then 25/s") in blue text.

- [x] **Enhancement: SQL Editor — scenario-driven tabs and richer pre-built queries**
  - Fixed: `scenario-queries/all` endpoint now scans both `data-generator/datasets/` AND `external-system/scenarios/` directories. When a demo is running, filters to only scenarios present in deployed nodes (`ES_SCENARIO` / `DG_SCENARIO` config). External-system queries use `catalog=iceberg` and namespace from the scenario YAML. Graceful fallback: shows all scenarios when demo is not running.

## In Progress

- [x] **Proper Health Reporting in Cockpit**: When a cluster is not deployed or unreachable, the Health tab shows "0/0 online" and "0 B / 0 B" instead of a meaningful state.
  - When demo is `not_deployed` or `stopped`: show "Not deployed" / "Stopped" placeholder
  - When `mc admin info` fetch fails or times out: show "Unreachable" with error reason
  - Backend `cluster_health` endpoint returns structured `{status, drives_online, drives_total, capacity_used, capacity_total, error}`
  - Frontend renders state-appropriate UI: `healthy | degraded | unreachable | stopped | not_deployed`

---

## Ready (completed)

- [x] **BUG: Stopped drives not reflected in health status**
- [x] **BUG: Throughput not displayed in Cockpit Stats tab**
- [x] **Enhancement: Multi-target file-generator**
- [x] **BUG: Component palette hidden when demo is stopped**
- [x] **CHANGE: Pool index in container names for single-pool clusters**
- [x] **Enhancement: Copy/Paste components via context menu**
- [x] **Enhancement: Cockpit resize from bottom-right corner**
- [x] **BUG: Vertical scrolling disabled in Cockpit view**
- [x] **UX: Site replication edge bidirectional arrows at design time**
- [x] **Enhancement: Nginx connector unification (phase 1)** — Unified to single `nginx-backend` edge type; dynamic label/style derives from nginx `variant`. Backward-compatible migration.
- [x] **BUG: First cluster disappears from Cockpit after a while** — Fixed: all aliases now always appear in cockpit/health responses even on fetch failure.
- [x] **BUG: Cluster node connector handles reset to default size on page refresh** — Fixed: clusters loaded with both top-level `width`/`height` and `style`.
- [x] **Enhancement: Cluster-level throughput stats (PUT/GET rates)** — Fixed: `mc admin prometheus metrics` fallback added; PUT/GET ops/s displayed in Stats tab.
- [x] **Enhancement: Throughput tab in Designer control plane** — "Throughput" tab in Instances view polls `/cockpit` at 5s, shows PUT/GET ops/s + bandwidth per cluster with health badge.
- [x] **Enhancement: Commission / Decommission Server Pool (runtime)** — 3 backend endpoints; runtime pool context menu with Decommission/Cancel; PoolContainer status badge; decommission status polled on startup.
- [x] **BUG: File-generator context menu too wide** — `min-w-[180px] max-w-[220px]` constraint added to NodeContextMenu.
- [x] **UX: Context menu not dismissed on canvas click** — `canvas:close-menus` CustomEvent dispatched on pane click; ClusterNode and DiagramCanvas listen and close.
- [x] **BUG: Group node always renders above other nodes** — Groups prepended in `addNode`; stable sort in `setNodes`; sort on diagram load.
- [x] **Enhancement: Container log viewer with per-component log shortcuts** — LogViewer drawer with Docker Logs + manifest log_commands tabs; 3s polling; L key shortcut; View Logs in ComponentNode + ClusterNode menus.
- [x] **BUG: Destroy does not remove Docker volumes** — `stop_demo(remove_volumes=True)` called by destroy endpoint.
- [x] **Enhancement: Nginx fully component-driven config (phase 2)** — `load-balance`/`failover` provides removed from manifest; `variants` section removed; mode select drives everything via `node.config.mode`; auto-generated LB node uses `config={mode: round-robin}`; AnimatedDataEdge, DiagramCanvas migration, and PropertiesPanel mode dropdown all in place.

---

## Parked (future phases)

- **Phase 6.5 — Metabase BI Layer**: Metabase component, init script, BI templates (see backup)
- **Phase 7 — Cloud Provider Integration**: AWS S3 / Azure Blob / GCS as ILM tier destinations, credential store (see backup)
- **Phase 8 — Delta Sharing**: AIStor Delta Sharing integration + demo template (see backup)
- **Phase 9 — AI/ML Pipeline**: Ollama, Qdrant, RAG app, connection types, AI demo template (see backup)
- **Template System**: Template Detail View, persistence, seeded templates, metadata schema (see backup)
- **Analytics pipeline bugs**: Metabase timing, AIStor warehouse, SigV4 passthrough, etc. (see backup)
- **Phase 5 — Experience & Sharing**: Export/import, snapshots, walkthrough engine (see backup)
- **Remaining Fixes**: FIX-2 (mc replicate add AIStore syntax), FIX-7 (--sync/--bandwidth AIStore mc) (see backup)
- **Medium Priority**: S3 File Browser Enhancement, Data Generator Web Console, Configuration Panel Rework (see backup)
- **UX / Polish**: Bucket Policy UX, verbose deploy output, DemoManager sorting, keyboard shortcuts, dynamic page title, inline node naming, hide minimap, log filtering (see backup)

---

## Template Gallery UX

- [x] **BUG: FA mode shows all templates instead of only FA-Ready ones** — Root cause: `fa-setup.sh` and `fa-update.sh` were not writing `DEMOFORGE_MODE=fa` to `.env.local`. Fixed in both scripts. Also added auto-detection in `demoforge.sh` `load_env()`: if `DEMOFORGE_FA_ID` is set and mode is `standard`, automatically promotes to `fa` and persists to `.env.local`.

- [x] **BUG: Sync returns 401 Unauthorized from hub-connector** — `template_sync.py` sends `X-Api-Key: {DEMOFORGE_API_KEY}` (the FA key) to `http://host.docker.internal:8080/api/hub/templates/`. The hub-connector at :8080 was started with a separate `CONNECTOR_KEY` (from bootstrap) and rejects the FA key with 401. Root cause: the connector key and FA key are different credentials, but the backend only knows the FA key. Fix options: (a) write `DEMOFORGE_HUB_URL` (the direct gateway URL) to `.env.local` during `fa-setup` and update `template_sync.py` to hit the gateway directly with the FA key, or (b) update the hub-connector to accept the FA key for proxied template requests. The duplicate sync button was also fixed (both were calling the same broken endpoint — now only one button in FA mode).

- [x] **BUG: Template last-updated date not visible / not tracked** — Baked `updated_at` into all 28 builtin template YAMLs from CHANGELOG. Backend `_template_summary()` now reads `meta.get("updated_at")` first (works on FA machines), then falls back to CHANGELOG. `save_as_template()` and `update_template()` both write `updated_at`. Frontend gate updated to show date for user templates too (was `source !== "user"`).

- [x] **Enhancement: Archive templates in dev mode** — Backend: `_template_summary()` returns `archived` field; `list_templates()` excludes archived by default with `include_archived` query param; `POST /api/templates/{id}/archive` endpoint (dev mode only, handles both archive/unarchive via body). Frontend: "Archived" tab (dev mode only); archive/unarchive in 3-dot dropdown; `fetchTemplates` passes `include_archived=true` when Archived tab active.



- [x] **Enhancement: Push to Hub button always visible in dev mode** — Button added to the source/sync status banner, always visible in dev mode regardless of sync configuration. Calls existing POST /api/templates/push-all-builtin.

- [x] **Enhancement: Sync from Hub button in FA mode** — "Sync from Hub" button added to the source/sync status banner, always visible in FA/standard mode regardless of sync configuration. Calls existing POST /api/templates/sync.

---

## Deploy & Health Reliability

- [x] **BUG: Cluster node connector handles wrong position on load (right + bottom handles)** — On initial canvas load, the right and bottom connector handles on MinIO cluster nodes render at incorrect positions (stuck at y≈200px). They self-correct the moment any UI change triggers a re-render. Root cause: `DiagramCanvas.tsx:502` creates new cluster nodes with `style: { width: 380, height: 200 }` — the hardcoded `height: 200` constrains ReactFlow's initial handle layout. The `ResizeObserver` in `ClusterNode.tsx:75` correctly calls `updateNodeInternals()` after the DOM grows beyond 200px (which happens on re-render), but the initial load never triggers this. A previous fix (removed `height` from database-loaded clusters) fixed the load path but missed the new-cluster creation path at line 502. Fix: remove `height: 200` from `style` at `DiagramCanvas.tsx:502` so new clusters are treated identically to loaded clusters. Must verify that pool-add, field-edit, and resize interactions still correctly update handle positions via the existing ResizeObserver.

- [x] **Enhancement: Throughput — nginx (edge) + MinIO (per-cluster) metrics in cockpit** — Current throughput collection (`cockpit.py`) uses `mc admin bandwidth` per cluster alias, falling back to `mc admin prometheus metrics`. Both return 0 during writes in practice because: (a) `mc admin bandwidth` only captures live inter-node replication traffic, not inbound client writes; (b) the Prometheus fallback measures ops/s but not byte rates; (c) the nginx LB layer — which is the actual entry point for all client writes — is completely uninstrumented. The result is 0 RX/0 TX shown in the Throughput tab even when objects are actively being written.
  - **Layer 1 — nginx throughput**: Each cluster has an auto-generated nginx LB node. Enable `stub_status` on the nginx container (or parse `$bytes_sent`/`$request_length` from access logs via a short tail). Poll `http://{project_name}-{cluster_id}-lb:80/nginx_status` from the mc-shell or backend; compute req/s and bytes/s from the `Active connections` + `requests` counters with delta-over-time. This gives external-facing throughput: what clients actually pushed/pulled.
  - **Layer 2 — per-cluster MinIO throughput**: Replace `mc admin bandwidth` (unreliable for inbound) with a direct Prometheus scrape of `minio_s3_traffic_received_bytes_total` and `minio_s3_traffic_sent_bytes_total` from the LB (`http://{lb}:9000/minio/v2/metrics/cluster`). Compute per-second delta between cockpit polls (already cached in `_PROM_SNAPSHOT_CACHE`). This gives what MinIO actually ingested/served.
  - **Cockpit response shape**: extend `throughput` per cluster to `{nginx_rx, nginx_tx, minio_rx, minio_tx, nginx_req_per_sec}` so the frontend can show both layers side by side.
  - **Frontend**: Throughput tab renders two rows per cluster — "Nginx (edge)" and "MinIO (cluster)" — with separate sparklines or badges so the user can immediately spot mismatches (e.g. nginx sees traffic but MinIO shows 0 → stuck at LB).

- [x] **Enhancement: Show `updated_at` on template cards + backfill for user templates** — Currently `updated_at` is only rendered in the detail/sidebar panel after clicking a card, not visible in the grid view. Also, user templates created before the last-updated fix have no `updated_at` in their YAML `_template` block (the CHANGELOG fallback only applies to builtin/synced sources, `templates.py:231`). Fix requires: (a) add a last-updated line to the template card in grid view (relative format "X days ago", full date on hover); (b) backfill `updated_at` on load for user templates that are missing it (use file `mtime` as fallback); (c) format the detail panel date as relative + absolute, not a raw string.

- [x] **Enhancement: Bubble up all errors from "Promote to Source" steps** — The promote endpoint (`templates.py:719`) silently swallows step failures: if stripping metadata, writing to `demo-templates/`, removing the user-templates shadow, or removing the stale synced copy fails partway through, the response either raises a 500 or returns partial success with only `push_warning` surfaced. The frontend (`TemplateGallery.tsx:313-323`) only checks `push_warning` and `pushed` — it doesn't handle partial failures (e.g. file written but shadow not removed). Fix: return a structured result with per-step status (`stripped`, `written`, `shadow_removed`, `synced_removed`, `pushed`); frontend shows a detailed error toast for any failed step rather than a generic success toast.

- [x] **Enhancement: Publish user templates to hub for team-wide FA access** — "My Template" + "FA Ready" templates are only visible in dev mode; FA agents cannot sync them because the publish pathway is a stub. Full implementation requires:
  1. **Backend** (`template_sync.py:126-128`): implement `publish_template(template_id)` — upload the user template YAML to hub-api (or GCS bucket) so FA agents can pick it up on next sync. Currently returns hard-coded `"not yet implemented"` error.
  2. **Backend** (`templates.py:829-853`): the `POST /api/templates/{id}/publish` endpoint exists and is wired to the UI but delegates to the stub above — needs to call the real publish flow and return structured status.
  3. **Hub-side**: expose an endpoint (or GCS write path) that accepts a validated template YAML upload from a dev/publisher and makes it available in the synced-templates bucket. Needs auth (dev/FA key).
  4. **Sync pull** (`sync_templates()`): already pulls from hub — no changes needed once the template is published to the remote bucket.
  5. **Frontend** (`TemplateGallery.tsx:268-275`): `handlePublish()` and `publishTemplate()` client call already exist — add success/failure toast and a "Published" badge state after successful upload. Currently the button fires but the user sees no feedback because the backend silently fails.
  - User templates are stored in `./user-templates/`; synced templates land in `./synced-templates/`. The missing piece is the upload bridge between the two across machines.

- [x] **Enhancement: Pre-select source template when saving as template** — When a demo was originally created from a template (i.e. has a `source_template_id` or equivalent), opening the "Save as Template" dialog should pre-select that template in the "override existing" dropdown so the user doesn't have to find and re-select it manually. If no source template is tracked, fall back to the current blank-selection behaviour.

- [x] **Enhancement: Per-container health check isolation during deploy** — Currently, a single container whose init_script hangs (e.g. `exec_in_container` timeout) blocks all subsequent init_scripts in the deploy pipeline. Each container's health check / init_script should run with an independent timeout and not prevent other containers from completing their startup. Deploy should proceed in parallel where possible; a single failing or slow container should mark that node as `error` without stalling the entire demo from reaching `running`. Also consider a per-node `init_status` that surfaces in the Instances panel so the user can see which specific node is stuck. Root cause seen with `inference-sim` init_script using `wget` (not available in Python container), which caused the deploy task to hang indefinitely.

---

## Images & Registry

- [x] **BUG: Template tab counts inconsistent when Archived tab selected** — `fetchTemplates({ includeArchived: true })` inflates the `templates` array, causing tier/My Templates/FA Ready counts to include archived items. Fixed by adding `!t.archived` guard on all non-Archived tab count computations in `TemplateGallery.tsx`.

- [x] **BUG: Private Registry shown as "unreachable" when no registry is configured** — `registry-health` endpoint always returns `not_configured` (private registry was removed with hub-connector). Frontend maps `not_configured` → `"unreachable"` state showing yellow warning banner. Fix: (a) backend should check `DEMOFORGE_REGISTRY_PUSH_HOST` env var and ping it if set, otherwise return `not_configured`; (b) frontend should treat `not_configured` as neutral "Not configured" rather than yellow "unreachable" warning. Also, "Push Images to Hub" button is disabled when registry `!== "connected"` — this should be gated on `DEMOFORGE_REGISTRY_PUSH_HOST` being set, not on registry reachability.

- [x] **BUG: FA Management unavailable in dev-gcp mode** — FA Management requires a local hub-api (admin key is local-hub-only; GCP gateway rejects it). In `faMode="dev"` + `hubLocal=false` (dev-gcp), the page shows an informational 503. This is architecturally correct — the admin key is only valid against a local hub-api. Consider whether FA Management should be hidden entirely in dev-gcp mode (no local hub running) or if a read-only gateway mode is feasible.

---

## Demo Management UX

- [x] **Enhancement: Last updated timestamp on demos** — Wherever demos are listed or examined (demo manager, canvas header, any demo list view), show the last modified date/time in local timezone. Needs a `updated_at` field persisted on the demo state whenever the user makes a change (topology edits, config changes, saves). Display format: relative ("2 hours ago") with full timestamp on hover (e.g. "Apr 13, 2026, 14:32"). Scope: demo list/manager view, canvas title bar or header area, demo detail panel if any.
