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

- [ ] **Pipeline Orchestration**: Edge-driven step-by-step pipeline execution (NO Airflow)
  - Each edge = one pipeline step, activated via context menu
  - SE controls narrative: click each step, explain to audience
  - New connection types: `spark-submit`, `s3-queue`, `iceberg-catalog`, `sql-query`, `s3a`
  - Pre-built PySpark ETL job: read CSV → aggregate → write Parquet → register Iceberg
  - ClickHouse S3Queue: auto-ingest new objects from MinIO (CREATE TABLE with S3Queue engine)
  - Edge animation shows data flow during active pipeline steps

- [ ] **Data Generator Extensions**: Extend file-generator to push data to HDFS and Spark
  - Add `hdfs-push` connection type: generates files directly to HDFS via WebHDFS REST API
  - Add `spark-ingest` connection type: pushes data that triggers Spark processing pipeline
  - Context menu: "Generate to HDFS" / "Generate to Spark" options alongside existing MinIO push
  - Configurable: file format (CSV, JSON, Parquet), size, rate, target path

- [ ] **Demo Templates** — MinIO-centric pipeline scenarios for SEs:

  **Template 1: "MinIO as Data Lakehouse"** (primary demo)
  - Topology: File Gen → MinIO Cluster → Iceberg REST → Trino + Grafana
  - MinIO value: S3-compatible object storage AS the lakehouse — no HDFS needed
  - Steps: (1) generate data to MinIO, (2) Iceberg catalogs it as tables, (3) Trino queries via SQL
  - Shows: versioning, bucket policies, Iceberg table format on S3, SQL analytics
  - Cockpit: watch objects accumulate, query them live in Trino

  **Template 2: "MinIO Multi-Site Replication with Analytics"** (enterprise)
  - Topology: Site-A (MinIO+LB) ↔ Site-B (MinIO+LB) + ClickHouse on Site-B + Grafana
  - MinIO value: active-active replication, analytics on replicated data
  - Steps: (1) generate data on Site-A, (2) activate site-replication, (3) ClickHouse S3Queue on Site-B auto-ingests, (4) Grafana shows real-time dashboard
  - Shows: site-replication, data locality, real-time analytics on replicated data

  **Template 3: "MinIO ILM Tiering with Analytics"** (cost optimization)
  - Topology: Hot MinIO → ILM → Cold MinIO → Trino (query cold data) + ClickHouse (real-time on hot)
  - MinIO value: automatic data lifecycle, query both tiers transparently
  - Steps: (1) generate data to hot tier, (2) activate tiering, (3) data moves to cold after N days, (4) Trino queries across both tiers via Iceberg
  - Shows: ILM lifecycle, tiered storage, unified query layer

  **Template 4: "Hadoop to MinIO Migration"** (modernization)
  - Topology: HDFS → Spark (S3A) → MinIO → Iceberg → Trino (replacing Hive/Impala)
  - MinIO value: drop-in S3 replacement for HDFS, modern query engine
  - Steps: (1) data exists in HDFS, (2) Spark reads HDFS writes to MinIO via S3A, (3) Iceberg catalogs, (4) Trino replaces Hive/Impala
  - Shows: S3A compatibility, migration path, performance improvement

  **Template 5: "MinIO + Spark ETL Pipeline"** (data engineering)
  - Topology: File Gen → MinIO (raw) → Spark (transform) → MinIO (curated) → Trino
  - MinIO value: both raw and curated data on MinIO, Spark reads/writes via S3A
  - Steps: (1) ingest raw CSV/JSON, (2) Spark aggregates to Parquet, (3) query curated data
  - Shows: S3A connector, ETL on object storage, raw-to-curated pattern

  **Template 6: "MinIO Real-Time Ingest + Dashboard"** (IoT/streaming)
  - Topology: File Gen (burst) → MinIO → ClickHouse (S3Queue) → Grafana
  - MinIO value: S3 as event buffer, ClickHouse auto-ingests, zero Kafka needed
  - Steps: (1) burst-generate data, (2) ClickHouse S3Queue picks up objects automatically, (3) Grafana shows live metrics
  - Shows: S3Queue pattern, MinIO as streaming buffer, real-time dashboards

  **Template 7: "MinIO Cluster Resilience Demo"** (infrastructure)
  - Topology: MinIO Cluster (4-node EC) + LB + File Gen + Prometheus + Grafana
  - MinIO value: erasure coding, node failure tolerance, self-healing
  - Steps: (1) generate data, (2) stop 1-2 nodes, (3) show data still accessible, (4) restart nodes, (5) cluster self-heals
  - Shows: erasure coding, health monitoring, zero-downtime operations

  **Template 8: "MinIO Multi-Cloud Tiering"** (hybrid cloud)
  - Topology: MinIO Cluster → ILM → AWS S3 / Azure Blob / GCP (when Phase 7 ready)
  - MinIO value: single S3 API, transparent tiering to any cloud
  - Steps: (1) data on MinIO, (2) ILM moves cold data to cloud, (3) queries still work transparently
  - Shows: cloud-agnostic storage, cost optimization, hybrid architecture
  - Template 3: Full pipeline: Spark → MinIO (AIStore Tables) → Trino

## Future — MinIO MCP & AI Features (Phase 8)

- [ ] **MinIO MCP Server Sidecar**: Auto-deploy `quay.io/minio/aistor/mcp-server-aistor:latest` per cluster
  - StreamableHTTP mode on port 8090, 128MB RAM, 0.25 CPU
  - Exposes 25+ tools: list_buckets, create_bucket, get_object_metadata, admin_info, etc.
  - Toggle via `mcpEnabled` on cluster properties (default: on)
  - Backend proxy: POST /api/demos/{id}/mcp/{cluster}/tools/{tool_id}

- [ ] **MCP Tool Explorer Tab**: Add "MCP Tools" tab to MinIO Admin Panel
  - Tool list grouped by category (Read, Write, Admin)
  - Parameter forms auto-generated from tool schemas
  - Execute button with JSON result display
  - Quick-action presets (list buckets, storage usage, replication status)
  - Zero external dependencies — always works

- [ ] **MCP AI Chat Tab** (opt-in): Add "AI Chat" tab when API key configured
  - Settings page: Claude/OpenAI API key input
  - Backend routes chat → LLM API (with MCP tools as available tools) → executes tool calls → streams response
  - Chat shows expandable tool-call blocks (what tool ran, what it returned)
  - Demo: "Show me all buckets", "Create ml-training with versioning", "What's replication status?"

- [ ] **Delta Sharing Integration**: MinIO as governed data sharing platform
  - Research: how MinIO implements Delta Sharing protocol
  - Component or cluster toggle depending on implementation
  - Demo: share tables across clusters without copying data

- [ ] **AI/ML Pipeline Demo** (see Phase 9)

## Future — AI/ML Pipeline (Phase 9)

- [ ] **Ollama Container**: Local LLM serving (llama3.2:1b, phi3-mini)
  - Image: `ollama/ollama`, 2-4GB RAM with small model
  - Connection types: accepts model-store (MinIO), provides inference
  - Also generates embeddings (nomic-embed-text)

- [ ] **Vector Database**: Lightweight vector store for RAG
  - Qdrant (`qdrant/qdrant`, 100MB image, Rust-native) — recommended
  - Or ChromaDB (`chromadb/chroma`, Python-based, simple)
  - Connection: accepts embedding, backup to MinIO via s3

- [ ] **RAG Pipeline App**: Custom FastAPI container orchestrating the flow
  - Reads documents from MinIO → chunks → embeds via Ollama → stores in vector DB
  - Chat endpoint: embed query → search vectors → retrieve docs from MinIO → LLM generates answer
  - Web UI showing the full pipeline with step visualization

- [ ] **AI Demo Template: "MinIO as AI Data Store"**
  - Topology: File Gen → MinIO (documents) → RAG App → Ollama + Qdrant → Chat UI
  - MinIO value: training data store, document store, model registry, vector DB backup
  - Steps: (1) upload docs to MinIO, (2) RAG processes & embeds, (3) user asks questions, (4) answers cite MinIO-stored docs

## Future — Experience & Sharing (Phase 5)

- [ ] Demo Export/Import as archive
- [ ] Demo Snapshots (Checkpoint/Restore)
- [ ] Demo Template Library (5+ pre-built templates)
- [ ] Walkthrough Engine (guided demo steps)
- [ ] Settings/Preferences Page
- [ ] Offline Mode / Pre-Pull Images
