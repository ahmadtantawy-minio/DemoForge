# DemoForge Backlog

> Archive of pre-2026-04-09 items: `plans/backlog-backup-2026-04-09.md`

---

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

## Ready (to implement)

### ~~Enhancement: Nginx fully component-driven config (phase 2)~~

**Goal:** Remove all edge-level nginx config (role, algorithm). Single mode property on the nginx component controls everything. Zero per-edge configuration required.

**Implementation:**
- `components/nginx/manifest.yaml`: replace `variant` section with a `config_schema` entry `mode` (select: `round-robin | least-conn | ip-hash | failover`, default `round-robin`). Remove `provides: [load-balance, failover]` — keep only `nginx-backend`.
- `components/nginx/templates/nginx.conf.j2`: branch on `node.config.mode` instead of `node.variant`. Determine primary/backup in failover mode by edge order in the edges list (first outbound `nginx-backend` edge = active, rest = backup). Algorithm for load-balance modes read from `node.config.mode` directly.
- `backend/app/engine/compose_generator.py`: update variant assignment for auto-generated LB nodes to use `config={"mode": "round-robin"}` instead of `variant="load-balancer"`. Auto-generated internal edges stay `load-balance` (template handles both).
- `frontend/src/components/canvas/edges/AnimatedDataEdge.tsx`: for `nginx-backend` edges, determine role from edge index among source node's outbound `nginx-backend` edges (index 0 = active in failover, all equal in load-balance). Remove `connectionConfig.role` lookup.
- `frontend/src/components/canvas/DiagramCanvas.tsx`: migration on load — if nginx node has `variant=failover-proxy`, set `config.mode=failover`; if `variant=load-balancer`, set `config.mode=round-robin`.
- `frontend/src/components/properties/PropertiesPanel.tsx`: nginx node shows mode dropdown (round-robin/least-conn/ip-hash/failover) in config section.
- Remove edge config panel for `nginx-backend` edges (no configurable fields remain).

**E2E tests (Playwright MCP):**
1. Navigate to `http://localhost:5173`, open a demo with an nginx node connected to 2 clusters
2. `browser_snapshot` — verify both `nginx-backend` edges show "Load Balance" label
3. Click nginx node → Properties Panel → change mode to "failover"
4. `browser_snapshot` — verify first edge shows "Active" (green), second shows "Standby" (dashed gray)
5. Change mode back to "least-conn" → `browser_snapshot` — verify both edges show "Load Balance" label, no active/standby distinction
6. Save diagram, reload page (`browser_navigate`) → `browser_snapshot` — verify mode persisted and edges still render correctly
7. Right-click nginx node — verify no "role" or "algorithm" config options appear on edges

---

### Enhancement: Container log viewer with per-component log shortcuts

**Goal:** One-click log access for any running container, with pre-defined per-component log tabs. Primary diagnostic tool for quorum failures, init errors, and runtime issues.

**Implementation:**

*Backend:*
- `backend/app/api/instances.py`: new endpoint `GET /api/demos/{demo_id}/instances/{node_id}/logs?tail=200&since=60s` — calls `docker logs --tail N --since T --timestamps {container_name}` via `asyncio.to_thread`, returns `{"lines": [...], "container": node_id, "truncated": bool}`.
- Second endpoint `POST /api/demos/{demo_id}/instances/{node_id}/exec-log` with body `{"command": "..."}` — runs arbitrary read-only command via `exec_in_container` and returns stdout. Used for component-specific log files (nginx access log, gen status, etc.).
- `backend/app/models/api_models.py`: add `LogResponse` model.

*Manifest schema:*
- Add optional `log_commands` list to component manifest schema. Each entry: `{name, command, description}`. Built-in defaults if absent: MinIO → `journalctl` or stdout; nginx → `/var/log/nginx/error.log`; file-generator → `/tmp/gen_status.json` + stdout.
- Add `log_commands` to manifests: `components/nginx/manifest.yaml`, `components/file-generator/manifest.yaml`, and any MinIO manifest.

*Frontend:*
- New `LogViewer` component (modal/drawer, similar to `MinioAdminPanel` pattern): shows tabbed log commands + raw docker logs tab. Auto-scroll to bottom. 3s polling when live mode on. Refresh button. Line count badge.
- Add "View Logs" to `ComponentNode` right-click context menu (only when `isRunning`).
- Add "View Logs" to `ClusterNode` right-click context menu → shows lb node logs by default, tab per pool node.
- Keyboard shortcut: `L` while a node is selected opens log viewer.

**E2E tests (Playwright MCP):**
1. Navigate to app with a running demo containing nginx and file-generator nodes
2. Right-click nginx node → `browser_snapshot` — verify "View Logs" option present in context menu
3. Click "View Logs" → `browser_wait_for` drawer to open → `browser_snapshot` — verify log panel visible with tabs ("Docker Logs", "Access Log", "Error Log")
4. `browser_snapshot` after 3s — verify log content is populated (not empty)
5. Click "Access Log" tab → `browser_snapshot` — verify tab switches and shows nginx access log output
6. Click Refresh button → verify timestamp updates
7. Right-click file-generator node → View Logs → `browser_snapshot` — verify "Generator Status" and "Generator Output" tabs present
8. Close log panel, press `L` key with node selected → `browser_snapshot` — verify panel reopens via keyboard shortcut
9. Verify "View Logs" is absent from context menu when demo is not running

---

### BUG: File-generator context menu too wide

**Root cause:** The context menu wrapper in the file-generator `ComponentNode` context menu (or the shared `ComponentContextMenu`) has no `max-w` constraint, inheriting full available width.

**Implementation:**
- Find the context menu div in `frontend/src/components/canvas/nodes/ComponentNode.tsx` (or its context menu sub-component). Add `min-w-[180px] max-w-[220px] w-max` to the outermost menu container. Verify other component context menus use the same class.

**E2E tests (Playwright MCP):**
1. Navigate to app with a file-generator node on the canvas
2. Right-click file-generator node → `browser_snapshot`
3. `browser_evaluate`: `document.querySelector('[data-context-menu]')?.getBoundingClientRect().width` — assert width ≤ 220
4. Right-click another component (e.g. nginx) → assert width is consistent (≤ 220)

---

### UX: Context menu not dismissed on canvas click

**Root cause:** The `DiagramCanvas` background `onClick` / `onPaneClick` handler does not clear the `contextMenu` state in `ComponentNode` or `ClusterNode` (each node manages its own context menu state locally, and there's no global context menu state to clear from outside the node).

**Implementation:**
- Add a global `contextMenuOpen` flag or `closeAllContextMenus` event to `diagramStore`. Alternatively, use a React context or a global `CustomEvent` (`canvas:close-menus`) dispatched on pane click.
- In `DiagramCanvas.tsx`, on `onPaneClick` prop of `<ReactFlow>`: dispatch `canvas:close-menus` custom event.
- In `ComponentNode` and `ClusterNode`: `useEffect` listens for `canvas:close-menus` event and calls `setContextMenu(null)`.
- Same for any other context menu holders (file-generator specific menu if separate).

**E2E tests (Playwright MCP):**
1. Navigate to app with at least one component on the canvas
2. Right-click a component node → `browser_snapshot` — verify context menu is visible
3. Click on empty canvas area → `browser_snapshot` — verify context menu is gone
4. Right-click a cluster node → context menu appears → click canvas → `browser_snapshot` — verify dismissed
5. Right-click canvas itself (canvas context menu) → click a node → verify canvas context menu dismissed

---

### BUG: Group node always renders above other nodes (wrong z-order)

**Root cause:** React Flow renders nodes in `nodes` array order — later entries render on top. Groups added after components end up at a higher index and render above them visually.

**Implementation:**
- In `diagramStore.ts`, `addNode` function: if the new node has `type === "group"`, prepend it to the `nodes` array (`[node, ...get().nodes]`) instead of appending. This ensures groups always render below all other nodes.
- In `setNodes`: apply a stable sort — groups first, then all other nodes — to preserve z-order across any state update that replaces the full nodes array (e.g. after load).
- In `DiagramCanvas.tsx`, when nodes are loaded from the backend: sort `allNodes` so groups come first before setting store state.

**E2E tests (Playwright MCP):**
1. Navigate to app with an existing component (e.g. nginx) on canvas
2. Drag a Group component from the palette onto the canvas, overlapping the nginx node
3. `browser_snapshot` — verify nginx node is visually on top of the group (group is behind)
4. Add another component (file-generator) on top of the group area
5. `browser_snapshot` — verify file-generator renders above the group, group stays behind both
6. Save and reload → `browser_snapshot` — verify z-order is preserved after page refresh
7. `browser_evaluate`: check that in the React Flow nodes array, all `type === "group"` nodes have lower indices than non-group nodes

---

### [x] Enhancement: Commission / Decommission Server Pool (runtime)

**Goal:** Allow users to commission new pools and decommission existing pools on a running cluster. Pool lifecycle status (commissioning / active / decommissioning / decommissioned) is reflected in the ClusterNode UI.

**Context:** MinIO supports pool decommissioning via `mc admin decommission start/status/cancel`. A pool being decommissioned continues serving reads while data is migrated to other pools. Commissioning is adding a new pool to an already-running cluster (expand capacity).

**Implementation:**

*Backend:*
- `backend/app/api/instances.py`: new endpoints:
  - `POST /api/demos/{demo_id}/clusters/{cluster_id}/pools/{pool_id}/decommission` — runs `mc admin decommission start <alias> <pool_args>`
  - `GET /api/demos/{demo_id}/clusters/{cluster_id}/pools/{pool_id}/decommission/status` — runs `mc admin decommission status <alias>`
  - `POST /api/demos/{demo_id}/clusters/{cluster_id}/pools/{pool_id}/decommission/cancel` — runs `mc admin decommission cancel <alias> <pool_args>`
- Pool status included in `cluster_health` response per pool: `commissioning | active | decommissioning | decommissioned`

*Frontend:*
- `ClusterNode`: pool label shows status badge (active / decommissioning / decommissioned)
- `ClusterContextMenu` (pool type, runtime): add "Decommission Pool" and "Cancel Decommission" options (visible only when running)
- `PropertiesPanel` or pool details panel: show decommission progress % if available
- `ClusterHeader` / pool summary: reflect pool count change after decommission completes

**E2E tests (Playwright MCP):**
1. Open a running demo with a multi-pool cluster
2. Right-click a pool → verify "Decommission Pool" appears only when running
3. Click "Decommission Pool" → `browser_snapshot` — verify status badge updates to "decommissioning"
4. Click "Cancel Decommission" → verify status resets to "active"
5. Non-running demo → right-click pool → verify "Decommission Pool" is absent

---

### Enhancement: Throughput tab in Designer control plane

**Goal:** Add a real-time throughput view to the Designer's control-plane tab bar. Shows PUT/GET rates per cluster as live gauges, as real-time as possible when the tab is active.

**Context:** Throughput data is already fetched by the Cockpit overlay from `mc admin prometheus metrics` (or equivalent). The new tab reuses the same data pipeline but displays it in a persistent in-canvas panel.

**Implementation:**

*Frontend:*
- Add a third tab "Throughput" to the control-plane panel (`frontend/src/components/control-plane/ControlPlane.tsx`) alongside the existing tabs
- `ThroughputTab` component: one gauge card per cluster showing:
  - PUT rate (ops/s and MB/s)
  - GET rate (ops/s and MB/s)
  - Current health badge (healthy / degraded / unreachable)
- Data source: `useDemoStore().clusterHealth` (already populated by polling when Cockpit is active). When Throughput tab is active, ensure polling is active even if Cockpit overlay is closed (add a `throughputTabActive` flag that keeps the health poller running).
- Gauges: simple arc or bar gauge — use existing Tailwind + inline SVG pattern (no new chart lib unless already bundled). Update at same cadence as `clusterHealth` polling (~5s).
- Empty state: "No clusters running" if no instances; "Start demo to see throughput" if not running.

**E2E tests (Playwright MCP):**
1. Open a running demo with at least one cluster
2. Navigate to Designer → `browser_snapshot` — verify "Throughput" tab visible in control plane
3. Click "Throughput" tab → `browser_snapshot` — verify gauge cards visible for each cluster
4. Verify PUT/GET rate labels are present (even if 0)
5. Wait 6s → `browser_snapshot` — verify timestamp/values have updated (polling active)
6. Close Cockpit overlay if open, ensure Throughput tab still shows live data

---

### BUG: Destroy does not remove Docker volumes (layout changes not picked up on redeploy)

**Root cause:** `stop_demo()` in `docker_manager.py` always calls `_compose_down` with `remove_volumes=False`. The Destroy endpoint calls `stop_demo()` without overriding this. After destroy, volumes persist — including `format.json` baked into MinIO volumes. If the user changed cluster topology (drives/nodes), the new containers fail to start because the old `format.json` records the wrong erasure set size.

**Status:** Fixed in code — `stop_demo(remove_volumes: bool = False)` now accepts a parameter; the destroy endpoint passes `remove_volumes=True`.

- `backend/app/engine/docker_manager.py`: `stop_demo` signature updated
- `backend/app/api/deploy.py`: destroy handler calls `stop_demo(demo_id, remove_volumes=True)`

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
