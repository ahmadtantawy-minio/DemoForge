# DemoForge Backlog

---

## Completed

- [x] shadcn/ui with zinc dark theme, all components migrated
- [x] Official SVG icons for MinIO, NGINX, Prometheus, Grafana
- [x] Easy edge removal (Backspace + hover X)
- [x] Docker lifecycle management — per-demo locks, timeouts, force-remove, non-blocking stop, background reconciliation
- [x] Deploy progress panel — 7 real-time steps via polling
- [x] UI/UX overhaul — demo manager modal, welcome screen, sidebar collapse, toasts, theme toggle, shadcn primitives
- [x] Terminal PTY support — interactive shell with echo via `script` wrapper
- [x] Web console proxy — X-Frame-Options stripped, base tag injection, WebSocket proxy
- [x] DemoForge branding — favicon, header logo (#C72C48)
- [x] License Sprint — global license injection, YAML store, settings API, deploy validation, MinIO AIStore component
- [x] URL-based routing — `/demo/{id}`, `/demo/{id}/instances`, refresh-safe
- [x] Diagram canvas follows light/dark theme

## Pre-Phase: Bug Fixes (~3-4 days)
> From phase3-and-beyond.md. Must fix before new features.

- [ ] BUG-1: NGINX template upstream direction inverted
- [ ] BUG-2: Init script results discarded, init_status hardcoded
- [ ] BUG-3: State recovery after backend restart — **Partially done** (recover_from_docker + sync_with_docker exist, verify completeness)
- [ ] BUG-4: Node ID counter resets on page reload
- [ ] BUG-5: Grafana secret keys mismatch environment keys
- [ ] BUG-6: Deploy endpoint exception logging — **Partially done** (progress panel catches errors, verify traceback logging)
- [ ] BUG-7: Cleanup on partial deploy failure — **Done** (rollback in docker_manager.py)
- [ ] BUG-8: Terminal panel tab duplication

## Phase A: Topology Foundation (1.5 weeks)
> Data models, connection system, edge properties — foundation for ALL future components

- [ ] **A1**: Add `display_name`, `labels`, `group_id` to DemoNode model + frontend types
- [ ] **A2**: Add `connection_config`, `auto_configure`, `label` to DemoEdge model + frontend types
- [ ] **A3**: Add DemoGroup model + `groups` field to DemoDefinition
- [ ] **A4**: Add `ConnectionConfigField` + `config_schema` to ConnectionProvides/Accepts
- [ ] **A5**: Update frontend TypeScript types to match all new fields
- [ ] **A6**: Update saveDiagram/fetchDemo to serialize/deserialize new fields (groups, display_name, connection_config)
- [ ] **A7**: Connection type picker dialog when creating edges (intersect provides/accepts)
- [ ] **A8**: Edge selection + edge properties panel with dynamic config forms

## Phase B: Node Grouping (1 week) — parallel with Phase C
> Visual clusters for multi-cluster topologies

- [ ] **B1**: GroupNode.tsx component (colored rectangle, label, description)
- [ ] **B2**: Load/save groups as React Flow parent nodes
- [ ] **B3**: Drag-to-create group from palette
- [ ] **B4**: Multi-select "Create Group" context menu action
- [ ] **B5**: Group resize handles and child node containment

## Phase C: Connection Configuration (1.5 weeks) — parallel with Phase B
> Declarative config schemas on manifests, dynamic forms

- [ ] **C1**: Add `config_schema` to MinIO manifests (replication, tiering, site-replication accepts)
- [ ] **C2**: Add `config_schema` to NGINX manifest (load-balance algorithm, backend_port)
- [ ] **C3**: Add tiering, site-replication, file-push connection types
- [ ] **C4**: Dynamic config form renderer (reads config_schema, renders shadcn form)
- [ ] **C5**: Edge config persistence through save pipeline
- [ ] **C6**: Pass connection_config into Jinja2 template context
- [ ] **C7**: Enhance nginx.conf.j2 to read algorithm/backend_port from edge config

## Phase D: Edge Automation Pipeline (2 weeks)
> Auto-generate init scripts from edge connections

- [ ] **D1**: `edge_automation.py` framework (registry, ordering, collective edge processing)
- [ ] **D2**: Load-balance automation (enhance nginx template from edge config)
- [ ] **D3**: Bucket replication automation (mc replicate commands)
- [ ] **D4**: Site replication automation (collective mc admin replicate add)
- [ ] **D5**: ILM tiering automation (mc admin tier + mc ilm rule)
- [ ] **D6**: Integrate `run_edge_init_scripts()` into deploy pipeline after node init
- [ ] **D7**: Generated config viewer (API + frontend modal showing nginx.conf, mc commands, etc.)

## Phase E: File Generator + Templates (1 week)
> Synthetic data generation for demos

- [ ] **E1**: File generator manifest + `generate.sh.j2` template (minio/mc image)
- [ ] **E2**: `file-push` connection type + config schema (size, count, format, rate, bucket)
- [ ] **E3**: `file-push` automation in edge_automation.py
- [ ] **E4**: File generator icon in ComponentIcon.tsx
- [ ] **E5**: Demo templates: multi-cluster, tiering, site-replication examples

## Remaining Backlog (lower priority)

- [ ] Verbose output panel (collapsed) in deploy/stop modals
- [ ] License info display per component (Apache 2.0, MIT, AGPL)
- [ ] DemoManager container/image tables sorting and filtering
- [ ] Keyboard shortcuts (Cmd+N, Cmd+D, Escape)
- [ ] Dynamic page title with active demo name
- [ ] Hide minimap when canvas empty
- [ ] TerminalPanel raw tabs → shadcn Tabs
- [ ] ComponentCard quick actions clickable
- [ ] Drag affordance (grip icon) on palette items
- [ ] Log filtering by level in Debug panel
- [ ] Debug error counter cap/reset
- [ ] Custom node names editable inline on canvas (double-click to edit)

## Consolidation Notes

| New Item | Replaces/Consolidates |
|----------|----------------------|
| A7 (connection picker) | Phase 3 item 3.11 + backlog "Edge connection type selector" |
| B1-B5 (grouping) | Phase 5 item 5.6 (annotated diagrams) — pulled forward |
| D3/D4 (replication) | Phase 4 item 4.2 (site replication) |
| E1-E4 (file generator) | Related to Phase 4 item 4.10 (traffic generator) — different scope, keep both |
| License Sprint | Phase 4 item 4.7 (AIStore) + backlog MinIO AIStore item — DONE |
