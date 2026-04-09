# DemoForge Backlog — Snapshot 2026-04-09

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
- [x] **FIX-1**: generate_compose deep-copies DemoDefinition (no in-place mutation)
- [x] **FIX-3**: Pause executes `mc replicate update --state disable` server-side
- [x] **FIX-4**: sync_with_docker wrapped in asyncio.to_thread (no event loop blocking)
- [x] **FIX-5**: Shell injection fixed with shlex.quote wrapping
- [x] **FIX-6**: Edge ID mapping via _original_edge_id (no more fuzzy matching)
- [x] **FIX-8**: NGINX S3 block includes proxy_http_version 1.1
- [x] **FIX-9**: mc admin tier add uses 'minio' type for MinIO-to-MinIO tiering
- [x] **FIX-10**: _demo_locks cleaned up on stop (no memory leak)
- [x] **FIX-11**: Erasure-coding minimum validation (node_count × drives ≥ 4)
- [x] **FIX-13**: Shared connectionMeta.ts (single source of truth for colors/labels)
- [x] **FIX-14**: ConnectionType includes cluster-replication/site-replication/tiering
- [x] **FIX-15**: Edge context menu labels dynamic per connection type
- [x] **FIX-16**: Password fields masked with show/hide eye toggle

## Remaining Fixes

### MEDIUM
- [x] **FIX-12**: Site-replication credential mismatch warning added
- [x] **FIX-17**: Init scripts parallelized per node via asyncio.gather
- [x] **FIX-18**: Shared docker_client in instances.py stop/start
- [ ] **FIX-2**: Verify `mc replicate add --remote-bucket URL` syntax works on AIStore image (validated on CE, needs AIStore test)
- [ ] **FIX-7**: Verify `--sync` and `--bandwidth` flags on AIStore mc (validated on CE)

### BUG FIXES
- [x] **BUG-NEW-1**: New cluster default is now 1 pool × 2 nodes × 4 NVMe drives × EC:2 (was 4 nodes × 4 SSD drives × EC:4)
- [x] **BUG-NEW-2**: Stop drive now uses `chmod 000 /dataN` instead of `mv` (mv was failing silently on Docker volume mount points, leaving drive accessible)
- [x] BUG-3: Edge configs recovered on backend restart
- [x] BUG-4: Node ID counter uses trailing-number regex across all ID types
- [x] BUG-9: Cockpit toggle moved to Zustand store for stable state
- [x] BUG-11: Cockpit shows bucket stats via mc ls --json + mc du --json through mc-shell
- [x] BUG-12: Site-replication pause now runs mc admin replicate remove
- [x] BUG-10: Cluster node shows "replicated" for < 4 drives, "erasure coded" otherwise
- [x] BUG-1: NGINX upstream direction — verified correct with embedded LB
- [x] BUG-5: Grafana secret keys — verified matching (GF_SECURITY_ADMIN_USER/PASSWORD)
- [x] BUG-8: Terminal tab duplication — already fixed with closedTabsRef

## Completed — Recent

- [x] **Network Overlay**: Live Docker IPs shown on all diagram nodes and cluster LBs
- [x] **Cockpit: Repositioned as right panel** — replaces PropertiesPanel when cockpit is ON
- [x] **Cockpit: Host Resource Utilization**: CPU%, memory shown at top of cockpit panel via Docker stats API (5s cache)
- [x] **Grafana MinIO Dashboard**: Official 37-panel dashboard (ID 13502) auto-provisioned
- [x] **Phase 6: Full Analytics Pipeline** — Trino, Iceberg REST, ClickHouse, Spark, HDFS components + 3 demo templates (tested e2e)
- [x] **Grafana Dashboards**: ClickHouse #869, Spark #7890, MinIO #13502 — auto-provisioned
- [x] **Custom Spark Image**: demoforge/spark-s3a with pre-baked hadoop-aws + aws-sdk JARs
- [x] **Demo Manager UI**: Separated My Demos / Templates tabs
- [x] **Phase 8: MinIO MCP Integration** — MCP sidecar per cluster, proxy API, Tool Explorer (26 tools), AI Chat (Ollama)
- [x] **MCP as cluster config** — toggle in Properties Panel, violet badge, context menu entries
- [x] **Operation Timeouts**: Per-operation timeouts — deploy (600s), stop (60s), destroy (120s), start (60s)
- [x] **Async Operation Queue**: All lifecycle endpoints return HTTP 202 + task_id; background task execution; task status polling
- [x] **File Generator Edge Animation**: Outgoing file-push edge animates while generation is running

## HIGH PRIORITY — Cockpit Rework

- [x] **Cockpit: Default tab = Cluster Health Summary** — "Health" tab (default) shows `mc admin info` data (mode, drives online/total, capacity, per-server drive status); current content moved to "Stats" tab
- [x] **Cockpit: Resizable panel** — already had left-edge resize handle (280–700px); fonts/elements scale via `transform: scale(width/380)` applied to a fixed-width inner container

## HIGH PRIORITY — Phase 6.5: Metabase BI Layer

### Sprint 1 — Metabase Core
- [ ] **Metabase Component Manifest**: `metabase/metabase:latest`, port 3000, H2 embedded DB
  - Category: analytics, accepts: `sql-query` (from Trino)
  - Health check: `/api/health`, secrets: admin email/password
  - Web UI: `dashboard` on port 3000
- [ ] **Metabase Init Script**: API-based auto-setup after health check
  - Complete first-run via `POST /api/setup` (admin user, skip wizard)
  - Add Trino database connection (derived from edge config)
  - Create 3-4 pre-seeded dashboard cards (orders/minute, revenue by region, KPIs)
- [ ] **Demo Template: "BI Dashboard - Lakehouse"**: 6 containers
  - File Gen → MinIO → Iceberg REST → Trino → Metabase + Prometheus
  - Reuses existing Iceberg REST + Trino components
  - Structured data generator pushes Parquet with orders schema

### Sprint 2 — AIStor Tables Path + Data Generator
- [ ] **Structured Data Generator Component**: Custom Python image (`demoforge/data-generator`)
  - Parquet profile: orders schema (order_id, customer_id, product_name, quantity, unit_price, order_date, region)
  - Partitioned by date: `raw-data/year=YYYY/month=MM/day=DD/`
  - Uses pyarrow + boto3, configurable batch size and interval
  - build_context pattern (like Spark custom image)
- [ ] **Trino AIStor Catalog Template**: `aistor-iceberg.properties.j2`
  - Points to MinIO's `/_iceberg` endpoint instead of Iceberg REST
  - SigV4 authentication
- [ ] **Demo Template: "BI Dashboard - AIStor Tables"**: 4 containers
  - Data Gen → MinIO AIStor (/_iceberg) → Trino → Metabase
  - License-gated via existing minio-aistore license_requirements
  - Lightest possible analytics demo

### Sprint 3 — Polish (optional)
- [ ] **Pre-seeded Metabase Dashboard**: Full 7-card dashboard via API
  - Orders per minute (line), Revenue by region (bar), Top products (horizontal bar)
  - Order volume trend (area), Total orders / Total revenue / Avg order value (KPIs)
- [ ] **Iceberg-native Data Generator Profile**: Write directly via pyiceberg to AIStor Tables
- [ ] **Metabase Auto-Refresh Demo**: 1-minute auto-refresh showing live data flow

## Medium Priority

- [ ] **S3 File Browser Enhancement**: Per-request node tracking, node distribution histogram
  - Shows "Served by: minio-2" banner via `X-Upstream-Server` header
  - Node distribution histogram for load-balance visualization

- [ ] **Data Generator Web Console**: Lightweight web UI for start/stop, live progress
  - REST API: POST /start, POST /stop, GET /status, GET /files

- [ ] **Configuration Panel Rework** — Educational code-editor-style configuration viewer
  - Show every mc command needed to build the setup from scratch
  - Syntax highlighting, inline comments, export as shell script

## Remaining Backlog (lower priority)

- [ ] **Bucket Policy UX Enhancement**: Bucket policy should be set per-bucket with a bucket picker
  - Move to MinIO Admin Panel → Buckets tab (already has per-bucket controls)
  - Add bucket selector dropdown before policy selection
  - Support bulk apply to all buckets
  - Show current policy status per bucket clearly
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

- [x] Bucket Policy Presets — API endpoint via mc-shell (public, download, upload, none)
- [ ] SSE Configuration (Server-Side Encryption with KES)
- [x] Versioning Configuration — API endpoint via mc-shell (enable/suspend)
- [x] IAM User/Policy Setup — API endpoint via mc-shell (add user, attach policy)
- [ ] KES Component for encryption key management

## Future — Cloud Provider Integration (Phase 7)

### Cloud Storage Components (ILM tiering destinations)
- [ ] **AWS S3 Component**: manifest, icon, connection type `s3-remote` (accepts tiering from MinIO)
- [ ] **Azure Blob Storage Component**: manifest, icon, connection type `azure-remote`
- [ ] **GCP Cloud Storage Component**: manifest, icon, connection type `gcs-remote`

### Credential Management
- [ ] **Credential Store**: secure credential profiles for cloud providers
- [ ] **Credential Picker**: when connecting MinIO → cloud component, select credential profile

### Cloud Data Browser
- [ ] **S3 Browser for Cloud**: lightweight web UI to browse remote S3/Azure/GCS buckets

## Completed — Template Manager (Phase 5)

- [x] **Template Gallery UI**: Card-based template browser with category filters

- [ ] **Template Detail View**: Expanded view when clicking a card
- [ ] **Template Persistence**: Survive Docker rebuilds
- [ ] **Template Metadata Schema**: YAML-based template definition
- [ ] **Seeded Templates** (ship with DemoForge)

## Completed — Analytics Ecosystem (Phase 6)

- [x] **HDFS Container**, **Apache Spark Container**, **Iceberg REST Catalog**, **Trino**, **ClickHouse**
- [x] **3 Analytics Templates**: Full Analytics Pipeline, Real-Time Analytics, Hadoop Migration
- [x] **Grafana Dashboards**: ClickHouse #869, Spark #7890, MinIO #13502

- [ ] **AIStore Tables**: MinIO's built-in Iceberg V3 table format (cluster config option)
- [ ] **Pipeline Orchestration**: Edge-driven step-by-step pipeline execution
- [ ] **Data Generator Extensions**: hdfs-push, spark-ingest connection types
- [ ] **Demo Templates 1–8**: Full SE narrative templates

## Completed — MinIO MCP & AI Features (Phase 8)

- [x] MinIO MCP Server Sidecar, Tool Explorer, AI Chat, AI Assistant Template

- [ ] **Delta Sharing Integration**: MinIO AIStor as governed data sharing platform
- [ ] **Delta Sharing Demo Template**

## Future — AI/ML Pipeline (Phase 9)

- [ ] **Ollama Container**, **Qdrant Vector Database**, **RAG Pipeline App**
- [ ] **New Connection Types for AI/ML** (6 types)
- [ ] **AI Demo Template: "MinIO as AI Data Store"**

## Backlog — Analytics & Data Pipeline

- [ ] Metabase dashboard timing on deploy
- [ ] AIStor warehouse auto-creation on deploy
- [ ] Metabase dashboard cards show 0 cards
- [ ] Edge labels for Iceberg mode
- [ ] Format selector locked in Iceberg mode
- [ ] Hive external table for JSON format
- [ ] Clickstream scenario
- [ ] Nginx LB SigV4 passthrough
- [ ] Setup Tables button for all catalogs
- [ ] Metabase data source auto-sync

## Future — Experience & Sharing (Phase 5)

- [ ] Demo Export/Import as archive
- [ ] Demo Snapshots (Checkpoint/Restore)
- [ ] Demo Template Library (5+ pre-built templates)
- [ ] Walkthrough Engine (guided demo steps)
- [ ] Settings/Preferences Page
- [ ] Offline Mode / Pre-Pull Images
