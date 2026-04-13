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

- [ ] **Enhancement: Archive templates in dev mode** — Dev mode only. Archived templates are hidden from the main gallery view unless the user explicitly navigates to an "Archived" section/tab. Archived templates remain on disk but are excluded from the default list. Useful for keeping the gallery clean without deleting templates. Archived state stored as a flag in the template YAML (e.g. `_template.archived: true`). FA mode never sees archived templates (they are effectively invisible outside dev mode).



- [x] **Enhancement: Push to Hub button always visible in dev mode** — Button added to the source/sync status banner, always visible in dev mode regardless of sync configuration. Calls existing POST /api/templates/push-all-builtin.

- [x] **Enhancement: Sync from Hub button in FA mode** — "Sync from Hub" button added to the source/sync status banner, always visible in FA/standard mode regardless of sync configuration. Calls existing POST /api/templates/sync.

---

## Demo Management UX

- [x] **Enhancement: Last updated timestamp on demos** — Wherever demos are listed or examined (demo manager, canvas header, any demo list view), show the last modified date/time in local timezone. Needs a `updated_at` field persisted on the demo state whenever the user makes a change (topology edits, config changes, saves). Display format: relative ("2 hours ago") with full timestamp on hover (e.g. "Apr 13, 2026, 14:32"). Scope: demo list/manager view, canvas title bar or header area, demo detail panel if any.
