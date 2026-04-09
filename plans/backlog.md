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

## Ready

- [x] **BUG: Stopped drives not reflected in health status** — stopping 2 drives on a cluster still shows "healthy" badge on the node and green status in Cockpit (32/32 online). The `clusterHealth` polling (`mc admin info`) should detect offline drives and flip status to "degraded"; the cluster node badge should reflect this. Need to verify: (1) `stopDrive` actually takes the drive offline from MinIO's perspective, (2) `mc admin info` backend parsing correctly counts `offlineDisks`, (3) the `clusterHealth` store value propagates to the node badge.

- [x] **BUG: Throughput not displayed in Cockpit Stats tab** — `rx_bytes_per_sec` / `tx_bytes_per_sec` show 0; Prometheus metrics endpoint may not be accessible from mc-shell, or the metric names have changed. Investigate `mc admin prometheus metrics` output and fix parsing or fallback.

- [x] **Enhancement: Multi-target file-generator** — file-generator should write to all connected clusters based on outbound edges; broken edges should visually reflect write failures (red/dashed). See plan: `.omc/plans/file-generator-multi-target.md`

- [x] **BUG: Component palette hidden when demo is stopped** — fixed by adding `not_deployed` to `isDemoEditable` in App.tsx.

- [x] **CHANGE: Pool index in container names for single-pool clusters** — fixed in `compose_generator.py`; all cluster container names now always include `pool{n}` segment.

- [x] **Enhancement: Copy/Paste components via context menu** — Copy added to component and cluster context menus; Paste added to canvas right-click; clipboard state in diagramStore.

- [x] **Enhancement: Cockpit resize from bottom-right corner** — currently the cockpit resizes from the left edge; should resize from the bottom-right corner handle instead for a more natural UX.

- [x] **BUG: Vertical scrolling disabled in Cockpit view** — the cockpit panel should allow vertical scrolling when content overflows.

---

## Ready

- [x] **UX: Site replication edge should show bidirectional arrows at design time** — at design time (demo not deployed), the "Site Replication" edge only shows one arrow (markerEnd at target). The markerStart arrow at the source end is hidden behind the source cluster node. Both directions should be clearly visible on the edge line itself, not just at the handle endpoints where they get clipped by the node rendering. Previous attempt used stationary polygon arrowheads via animateMotion at 25%/75% of path — user re-reported this is still not visible/working correctly.

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
