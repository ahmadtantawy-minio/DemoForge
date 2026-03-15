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
- [x] BUG-3: Edge configs recovered on backend restart
- [x] BUG-4: Node ID counter uses trailing-number regex across all ID types
- [x] BUG-9: Cockpit toggle moved to Zustand store for stable state
- [x] BUG-11: Cockpit shows bucket stats via mc ls --json + mc du --json through mc-shell
- [x] BUG-12: Site-replication pause now runs mc admin replicate remove
- [x] BUG-10: Cluster node shows "replicated" for < 4 drives, "erasure coded" otherwise
- [x] BUG-1: NGINX upstream direction — verified correct with embedded LB
- [x] BUG-5: Grafana secret keys — verified matching (GF_SECURITY_ADMIN_USER/PASSWORD)
- [x] BUG-8: Terminal tab duplication — already fixed with closedTabsRef

## High Priority — Next Up

- [x] **Network Overlay**: Live Docker IPs shown on all diagram nodes and cluster LBs

- [ ] **S3 File Browser Enhancement**: Per-request node tracking, node distribution histogram
  - Shows "Served by: minio-2" banner via `X-Upstream-Server` header
  - Node distribution histogram for load-balance visualization
  - Operations: list buckets, browse objects, upload, download, delete

- [ ] **Data Generator Web Console**: Lightweight web UI for start/stop, live progress
  - REST API: POST /start, POST /stop, GET /status, GET /files
  - Lower priority — terminal quick actions work for now

## High Priority — Next Up (continued)

- [x] **Cockpit: Repositioned as right panel** — replaces PropertiesPanel when cockpit is ON
- [x] **Cockpit: Host Resource Utilization**: CPU%, memory shown at top of cockpit panel via Docker stats API (5s cache)

- [x] **Grafana MinIO Dashboard**: Official 37-panel dashboard (ID 13502) auto-provisioned

## High Priority — Configuration & Educational Panel (Phase 3 rework)

- [ ] **Configuration Panel Rework** — Educational code-editor-style configuration viewer
  - Rework the generated config viewer to be a proper code editor with syntax highlighting
  - Show every mc command needed to build the setup from scratch (MinIO perspective)
  - Include inline comments explaining WHY each command is needed and WHAT it does
  - Layout: text editor panel with syntax coloring (shell commands, YAML, JSON)
  - Sections: cluster setup, bucket creation, versioning, replication config, IAM, tiering
  - Each section shows the actual mc commands with `# comments` explaining the purpose
  - Export button to copy all commands as a runnable shell script
  - Should serve as a learning tool for SEs to understand the MinIO configuration

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

- [x] Bucket Policy Presets — API endpoint via mc-shell (public, download, upload, none)
- [ ] SSE Configuration (Server-Side Encryption with KES)
- [x] Versioning Configuration — API endpoint via mc-shell (enable/suspend)
- [x] IAM User/Policy Setup — API endpoint via mc-shell (add user, attach policy)
- [ ] KES Component for encryption key management

## Future — Cloud Provider Integration (Phase 7)

### Cloud Storage Components (ILM tiering destinations)
- [ ] **AWS S3 Component**: manifest, icon, connection type `s3-remote` (accepts tiering from MinIO)
  - Config: access key, secret key, region, endpoint (for S3-compatible)
  - Edge automation: `mc admin tier add s3 ALIAS TIER-NAME --endpoint ... --access-key ... --secret-key ... --bucket ...`
- [ ] **Azure Blob Storage Component**: manifest, icon, connection type `azure-remote`
  - Config: account name, account key, container
  - Edge automation: `mc admin tier add azure ALIAS TIER-NAME --account-name ... --account-key ... --bucket ...`
- [ ] **GCP Cloud Storage Component**: manifest, icon, connection type `gcs-remote`
  - Config: service account JSON, project ID, bucket
  - Edge automation: `mc admin tier add gcs ALIAS TIER-NAME --credentials-file ... --bucket ...`

### Credential Management
- [ ] **Credential Store**: secure credential profiles for cloud providers
  - Backend: `backend/app/api/credentials.py` — CRUD API for credential profiles
  - Storage: encrypted YAML in `data/credentials.yaml` (like licenses)
  - Model: `{id, provider, label, config: {access_key, secret_key, region, ...}}`
  - UI: Settings dialog tab for managing cloud credentials
- [ ] **Credential Picker**: when connecting MinIO → cloud component, select credential profile
  - Edge config_schema includes `credential_profile_id` field
  - Edge automation resolves credentials from profile before running mc commands

### Cloud Data Browser
- [ ] **S3 Browser for Cloud**: lightweight web UI to browse remote S3/Azure/GCS buckets
  - Reuse S3 File Browser component with configurable endpoint
  - Shows objects in the tiered storage destination
  - Useful for verifying ILM tiering moved objects correctly

## Future — Analytics Ecosystem (Phase 6)

- [ ] **HDFS Container**: Hadoop HDFS for data migration demos (HDFS → MinIO)
  - Image: `apache/hadoop:3` or `bde2020/hadoop-namenode`
  - Connection types: hdfs-source (provides), data-migration (accepts from MinIO)
  - Demo: generate data to HDFS, migrate to MinIO via `mc mirror`

- [ ] **Apache Spark Container**: Spark with S3A connector pushing data to MinIO
  - Image: `bitnami/spark:latest` or `apache/spark:3.5`
  - Connection types: s3a-client (accepts s3), spark-submit, accepts hdfs
  - Demo: Spark job reads/writes parquet to MinIO buckets
  - Built-in jobs: aggregation pipeline that runs every X minutes, transforms and pushes to MinIO
  - Init script: pre-submit a sample PySpark job that reads raw data → aggregates → writes parquet

- [ ] **AIStore Tables**: MinIO's built-in table format (cluster config option)
  - Implementation: cluster property toggle, not a separate component
  - Enables table-format storage within existing MinIO clusters
  - Config: `MINIO_TABLES_ENABLED=on` environment variable

- [ ] **Apache Iceberg REST Catalog**: Standalone Iceberg catalog on MinIO storage
  - Image: `tabulario/iceberg-rest:latest`
  - Connection types: accepts s3 (MinIO), provides iceberg-catalog
  - Demo: create Iceberg tables stored on MinIO, query via Trino

- [ ] **Trino** (Priority 1 query engine): SQL query engine for lakehouse analytics
  - Image: `trinodb/trino:latest` (~2.5GB, JVM, 1GB RAM)
  - Connection types: accepts iceberg-catalog, accepts s3, provides sql-query
  - Template mounts: minio.properties.j2, iceberg.properties.j2 for catalog config
  - Demo: SQL queries over Parquet/Iceberg on MinIO, CREATE TABLE AS SELECT
  - **NOT Starburst** — license key required, no demo value over open-source Trino at small scale

- [ ] **ClickHouse** (Priority 2 query engine): Real-time analytics on MinIO data
  - Image: `clickhouse/clickhouse-server:latest` (~1GB, C++ native, 512MB RAM)
  - Connection types: accepts s3 (via s3() table function), provides sql-query
  - No catalog needed — direct S3 reads, S3Queue for continuous ingestion
  - Demo: real-time dashboards, log analytics, hot-cold architecture with MinIO
  - Reads Iceberg tables created by Trino (IcebergS3 engine, read-only)
  - Note: native port 9000 conflicts with MinIO — use HTTP port 8123 only

- [ ] **Cloudera: NOT RECOMMENDED** — infeasible in Docker (64GB+ RAM minimum, commercial license)
  - For "Hadoop migration" narrative, use standalone HDFS + Spark + Trino instead
  - This tells a better story: "Replace entire Hadoop stack with MinIO + Trino"

- [ ] **Data Generator Extensions**: Extend file-generator to push data to HDFS and Spark
  - Add `hdfs-push` connection type: generates files directly to HDFS via WebHDFS REST API
  - Add `spark-ingest` connection type: pushes data that triggers Spark processing pipeline
  - Context menu: "Generate to HDFS" / "Generate to Spark" options alongside existing MinIO push
  - Configurable: file format (CSV, JSON, Parquet), size, rate, target path

- [ ] **Analytics Demo Templates**:
  - Template 1: "Open Lakehouse" — File Gen → MinIO → Iceberg → Trino → SQL queries
  - Template 2: "Real-Time Analytics" — File Gen → MinIO → ClickHouse → Grafana dashboards
  - Template 3: "Unified Analytics" — MinIO → Iceberg → Trino (batch) + ClickHouse (real-time)
  - Template 4: "Hadoop Migration" — HDFS → Spark → MinIO + Trino replacing Hive/Impala
  - Template 3: Full pipeline: Spark → MinIO (AIStore Tables) → Trino

## Future — Experience & Sharing (Phase 5)

- [ ] Demo Export/Import as archive
- [ ] Demo Snapshots (Checkpoint/Restore)
- [ ] Demo Template Library (5+ pre-built templates)
- [ ] Walkthrough Engine (guided demo steps)
- [ ] Settings/Preferences Page
- [ ] Offline Mode / Pre-Pull Images
