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
- [x] **Phase A: Topology Foundation** — display_name, labels, group_id, connection_config, auto_configure, connection types, type picker, edge properties panel with dynamic config forms
- [x] **Phase B: Node Grouping** — GroupNode, load/save groups, drag-to-create, multi-select, resize/containment
- [x] **Phase C: Connection Configuration** — config schemas on manifests, dynamic form renderer, edge config persistence, Jinja2 template enhancements
- [x] **Phase D: Edge Automation Pipeline** — edge_automation.py framework, load-balance, replication, site-replication, ILM tiering, pipeline integration, generated config viewer
- [x] **Phase E: File Generator + Templates** — file generator manifest, file-push connection, automation, demo templates
- [x] **Cluster Component** — DemoCluster with single-drop UX, erasure coding, edge fan-out, cluster resilience (stop/start individual nodes)
- [x] **Cluster-to-Cluster Replication** — bucket replication, site replication, ILM tiering between clusters via top/bottom handles
- [x] **Embedded NGINX LB** — auto-generated per cluster, console access, correct S3 proxy
- [x] **On-demand Edge Activation** — paused → activate → applied → pause lifecycle via edge context menu
- [x] **Edge Visual Indicators** — animated dot for active, pause icon, dashed line for pending, directional arrows, bidirectional support
- [x] **Handle Persistence** — sourceHandle/targetHandle saved and restored (top/bottom vs left/right)
- [x] **Demo Resource Settings** — per-container defaults, per-container caps, total demo budget with proportional scaling
- [x] **S3 File Browser Component** — custom FastAPI image, Dockerfile, manifest, auto-built via lifecycle script
- [x] **Lifecycle Script** — demoforge.sh auto-builds component images with build_context on start/build/nuke
- [x] **Cleanup on partial deploy failure** — rollback in docker_manager.py
- [x] **Component health on diagram** — pulsing yellow for starting, green/red dots, health updates during deploy

## Critical Fixes (from architect + MinIO expert review)

> These must be fixed before adding new features.

### CRITICAL
- [ ] **FIX-1**: `generate_compose` mutates `DemoDefinition` in-place → double-expansion on redeploy. Fix: work on `demo.model_copy(deep=True)`.
- [ ] **FIX-2**: `mc replicate add --remote-bucket URL` syntax is wrong — needs alias-based `--remote-bucket target/bucket`. Fix: two-step alias setup + alias-based remote.
- [ ] **FIX-3**: "Pause" is UI-only — doesn't stop MinIO replication. Fix: execute `mc replicate update --state disable` on pause, `--state enable` on re-activate.

### HIGH
- [ ] **FIX-4**: `sync_with_docker` blocks event loop. Fix: wrap in `asyncio.to_thread()` in main.py.
- [ ] **FIX-5**: Shell injection in edge activation `f"sh -c '{cmd}'"`. Fix: pass `["sh", "-c", cmd]` to exec_run.
- [ ] **FIX-6**: Edge ID mismatch — fragile fuzzy matching. Fix: store canonical edge ID map in `RunningDemo` during cluster expansion.
- [ ] **FIX-7**: `--sync` and `--bandwidth` flags removed from modern `mc replicate add`. Remove them.
- [ ] **FIX-8**: NGINX S3 block missing `proxy_http_version 1.1`. Fix: add to nginx.conf.j2 S3 location block.
- [ ] **FIX-9**: `mc admin tier add s3` should be `minio` for MinIO-to-MinIO tiering.
- [ ] **FIX-10**: `_demo_locks` dict grows unboundedly. Fix: cleanup on stop.

### MEDIUM
- [ ] **FIX-11**: No erasure-coding minimum validation (node_count × drives ≥ 4).
- [ ] **FIX-12**: Site-replication credential mismatch not validated.
- [ ] **FIX-13**: Duplicated `connectionColors`/`connectionLabels` across 3 files → extract to shared constant.
- [ ] **FIX-14**: `ConnectionType` TypeScript type missing cluster variants.
- [ ] **FIX-15**: Edge context menu hard-codes "Activate Replication" for all cluster edge types.
- [ ] **FIX-16**: Passwords shown in plaintext in PropertiesPanel cluster credentials.
- [ ] **FIX-17**: Init scripts run sequentially across all nodes → parallelize independent nodes.
- [ ] **FIX-18**: Duplicate `docker.from_env()` in instances.py stop/start → use shared client.

## Bug Fixes (from phase3-and-beyond.md)

- [ ] BUG-1: NGINX template upstream direction inverted
- [ ] BUG-3: State recovery after backend restart — edge configs lost on restart
- [ ] BUG-4: Node ID counter resets on page reload
- [ ] BUG-5: Grafana secret keys mismatch environment keys
- [ ] BUG-8: Terminal panel tab duplication

## High Priority — Next Up

- [ ] **Network Overlay**: After deploy, show container IPs on nodes + port/protocol on edges
  - Query Docker for container IP assignments
  - Show IPs as small badges on diagram nodes
  - Toggle-able overlay so it doesn't clutter design view

- [ ] **S3 File Browser Enhancement**: Per-request node tracking, node distribution histogram
  - Shows "Served by: minio-2" banner via `X-Upstream-Server` header
  - Node distribution histogram for load-balance visualization
  - Operations: list buckets, browse objects, upload, download, delete

- [ ] **Data Generator Web Console**: Lightweight web UI for start/stop, live progress
  - REST API: POST /start, POST /stop, GET /status, GET /files
  - Lower priority — terminal quick actions work for now

## Remaining Backlog (lower priority)

- [ ] Verbose output panel in deploy/stop modals
- [ ] License info display per component (Apache 2.0, MIT, AGPL)
- [ ] DemoManager sorting/filtering
- [ ] Keyboard shortcuts (Cmd+N, Cmd+D, Escape)
- [ ] Dynamic page title with active demo name
- [ ] Hide minimap when canvas empty
- [ ] TerminalPanel raw tabs → shadcn Tabs
- [ ] ComponentCard quick actions clickable
- [ ] Drag affordance on palette items
- [ ] Log filtering by level in Debug panel
- [ ] Custom node names editable inline on canvas

## Future — Advanced MinIO Features (Phase 4 remainder)

- [ ] Bucket Policy Presets (mc anonymous, mc policy)
- [ ] SSE Configuration (Server-Side Encryption with KES)
- [ ] Versioning Configuration UI
- [ ] IAM User/Policy Setup automation
- [ ] KES Component for encryption key management

## Future — Cloud Provider Integration

- [ ] AWS S3 component — manifest, icon, ILM tiering destination
- [ ] GCP Cloud Storage component — manifest, icon, ILM tiering destination
- [ ] Credential profiles for AWS/GCP
- [ ] ILM tiering automation for S3/GCS destinations

## Future — Experience & Sharing (Phase 5)

- [ ] Demo Export/Import as archive
- [ ] Demo Snapshots (Checkpoint/Restore)
- [ ] Demo Template Library (5+ pre-built templates)
- [ ] Walkthrough Engine (guided demo steps)
- [ ] Settings/Preferences Page
- [ ] Offline Mode / Pre-Pull Images
