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

## Completed — Template Manager (Phase 5)

- [x] **Template Gallery UI**: Card-based template browser with category filters
  - Grid layout with category pills, tags, resource estimates
  - Loading skeletons, error states, keyboard navigation, ARIA labels
  - Detail dialog with editable descriptions and walkthrough steps
  - External dependency warnings (e.g. "Requires Docker 20+", "Needs 8GB+ RAM")
  - "Create Demo" button that instantiates the template

- [ ] **Template Detail View**: Expanded view when clicking a card
  - Full description of the demo scenario and its objective
  - MinIO value proposition highlighted (why MinIO matters in this pipeline)
  - Component list with icons, roles, and resource requirements
  - Connection/edge diagram showing data flow
  - Step-by-step walkthrough of what the SE will demonstrate
  - Prerequisites and setup notes
  - Editable — user can tweak the description text (persisted)

- [ ] **Template Persistence**: Survive Docker rebuilds
  - Templates stored in `demo-templates/` directory (volume-mounted, like `demos/`)
  - Each template is a YAML file with metadata + demo definition
  - User-edited descriptions saved back to the YAML
  - Seeded templates shipped with DemoForge, user can add custom ones
  - Backend: `GET /api/templates` lists all, `PATCH /api/templates/{id}` updates description

- [ ] **Template Metadata Schema**:
  ```yaml
  id: lakehouse-demo
  name: "MinIO as Data Lakehouse"
  category: analytics
  tags: [lakehouse, iceberg, trino, sql]
  description: "Full description..."
  objective: "Demonstrate MinIO as the foundation for an open data lakehouse"
  minio_value: "S3-compatible storage replaces HDFS as the lakehouse foundation"
  components:
    - {id: minio-cluster, label: "MinIO Cluster", role: "Lakehouse storage"}
    - {id: iceberg, label: "Iceberg REST", role: "Table catalog"}
    - {id: trino, label: "Trino", role: "SQL query engine"}
  estimated_resources: {memory: "4GB", cpu: 4, containers: 8}
  external_dependencies: []
  walkthrough:
    - step: "Deploy the demo"
      description: "Click Deploy to start all components"
    - step: "Generate sample data"
      description: "Right-click Data Generator → Start Generating"
  demo: { ... full DemoDefinition ... }
  ```

- [ ] **Seeded Templates** (ship with DemoForge):
  - Template 7 "Cluster Resilience" — works now (existing components)
  - Template 2 "Multi-Site Replication" — works now
  - Template 3 "ILM Tiering" — works now
  - Others seeded as analytics/AI components are built

## Completed — Analytics Ecosystem (Phase 6)

- [x] **HDFS Container**: apache/hadoop:3, pseudo-distributed mode, proper network binding
- [x] **Apache Spark Container**: demoforge/spark-s3a:3.5.0 with pre-baked S3A JARs
- [x] **Apache Iceberg REST Catalog**: tabulario/iceberg-rest, S3 + AWS credential auto-resolution
- [x] **Trino**: trinodb/trino with Iceberg catalog, S3 credentials, AWS env vars
- [x] **ClickHouse**: clickhouse-server with 1GB memory, port 9001 (avoid MinIO conflict)
- [x] **3 Analytics Templates**: Full Analytics Pipeline (9 containers), Real-Time Analytics, Hadoop Migration
- [x] **Grafana Dashboards**: Official ClickHouse #869, Spark #7890, MinIO #13502

- [ ] **AIStore Tables**: MinIO's built-in Iceberg V3 table format (cluster config option)
  - Requires AIStor Enterprise license + RELEASE.2026-02-02+
  - Endpoint: `/_iceberg`, SigV4 auth, `mc table` CLI commands
  - Planned for Phase 6.5 Sprint 2 (AIStor Tables demo path with Metabase)

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

## Completed — MinIO MCP & AI Features (Phase 8)

- [x] **MinIO MCP Server Sidecar**: Auto-deploys per cluster + standalone MinIO node
  - quay.io/minio/aistor/mcp-server-aistor:latest, StreamableHTTP on port 8090
  - 26 tools, configurable via `mcp_enabled` cluster property, violet MCP badge
- [x] **MCP Tool Explorer Tab**: Categorized tools, auto-generated parameter forms, quick actions
- [x] **MCP AI Chat Tab**: Ollama-powered (configurable endpoint), SSE streaming, multi-round tool calling
  - Settings API: GET/POST /api/settings/llm (endpoint, model, api_type)
  - Works with any OpenAI-compatible API (Ollama, vLLM, LiteLLM, OpenAI)
- [x] **MinIO AI Assistant Template**: Cluster + MCP sidecar + monitoring demo

- [ ] **Delta Sharing Integration**: MinIO AIStor as governed data sharing platform
  - AIStor embeds Delta Sharing protocol directly (no sidecar) — port 8080
  - Config: YAML file defining shares/schemas/tables with bearer token auth
  - Supports both Delta Lake AND Apache Iceberg tables
  - New connection type: `delta-sharing` (provides on AIStor, accepts on consumer)
  - Add `table-sharing` variant to `minio-aistore` manifest with config template
  - Custom `delta-sharing-client` component: Python FastAPI + `delta-sharing` pip package
    - Web UI: list shares, list tables, preview data (first N rows)
    - Pattern: same as s3-file-browser component
  - Demo: data in MinIO → shared via Delta Sharing → consumed by Python client
  - **AIStor Enterprise only** — not available in MinIO CE

- [ ] **Delta Sharing Demo Template: "MinIO Zero-Copy Data Sharing"**
  - Topology: File Gen → MinIO AIStor (table-sharing) → Delta Sharing Client + Grafana
  - MinIO value: first on-premises object store with native Delta Sharing
  - Steps: (1) generate data, (2) configure shares, (3) consumer reads without copying
  - Shows: zero-copy sharing, bearer token auth, cross-org data access

## Future — AI/ML Pipeline (Phase 9)

### Recommended Stack (fits 16GB laptop, ~3GB total for AI components)

- [ ] **Ollama Container**: Local LLM + embedding server
  - Image: `ollama/ollama:latest` (~1.2GB image, serves both inference + embeddings)
  - Models: `tinyllama` (637MB, 1.1B params) for chat, `all-minilm` (46MB) for embeddings
  - RAM: ~1.5GB with tinyllama loaded, CPU-only (Metal on Apple Silicon)
  - Ports: 11434 (REST API for /api/generate and /api/embeddings)
  - Connection types: provides inference, provides embedding, accepts model-store
  - Init script: `ollama pull tinyllama && ollama pull all-minilm`
  - Quick actions: "List models", "Pull TinyLlama", "Test generation", "Test embedding"

- [ ] **Qdrant Vector Database**: Lightweight vector store for RAG
  - Image: `qdrant/qdrant:latest` (100MB image, Rust-native, 256MB RAM)
  - Ports: 6333 (REST) + 6334 (gRPC), built-in web dashboard at /dashboard
  - Connection types: provides vector-search, accepts vector-backup (to MinIO S3)
  - Native S3 snapshot support — backs up to MinIO bucket
  - Why Qdrant: 3-5x lighter than Weaviate, no dependencies (unlike Milvus which needs etcd+MinIO)

- [ ] **RAG Pipeline App**: Custom DemoForge container (must build, ~500-800 lines Python)
  - Image: `demoforge/rag-pipeline:latest` (Python 3.11-slim + FastAPI + boto3 + httpx)
  - RAM: ~256MB, Port: 8501
  - Pipeline: reads docs from MinIO → chunks → embeds via Ollama → stores in Qdrant
  - Query: embed question → search Qdrant → retrieve original docs FROM MinIO → LLM answer
  - **Web UI with 3 panels**:
    - Left: pipeline visualizer (animated flow showing each stage lighting up)
    - Center: chat interface with expandable "Sources" showing MinIO object paths + similarity scores
    - Right: activity feed (live log of MinIO GETs/PUTs, Qdrant INSERTs/SEARCHes, Ollama calls)
  - Connection types: accepts document-ingest (MinIO), inference (Ollama), vector-search (Qdrant)
  - Every MinIO interaction explicitly surfaced for SE demo narrative

- [ ] **New Connection Types for AI/ML** (6 types):
  - `model-store` (MinIO → Ollama): model registry bucket, pink #ec4899
  - `document-ingest` (MinIO → RAG): document bucket for embedding, violet #8b5cf6
  - `embedding` (Ollama → RAG/Qdrant): embedding generation, teal #14b8a6
  - `vector-backup` (Qdrant → MinIO): snapshot persistence, amber #f59e0b
  - `inference` (Ollama → RAG): LLM generation, red #ef4444
  - `vector-search` (Qdrant → RAG): similarity search, cyan #06b6d4

- [ ] **AI Demo Template: "MinIO as AI Data Store"**
  - Topology: File Gen → MinIO (documents) → RAG App → Ollama + Qdrant → Chat UI
  - MinIO value: document store, model registry, vector DB backup — ALL on MinIO
  - Demo flow:
    1. "Data lives on MinIO" — show documents bucket, models bucket
    2. "Embed and index" — RAG reads from MinIO, chunks, embeds via Ollama, stores in Qdrant
    3. "Ask a question" — chat UI shows: query embedded → Qdrant searched → docs retrieved FROM MinIO → LLM answers
    4. "Backup vectors" — activate vector-backup edge, Qdrant snapshot appears in MinIO
    5. "Scale the data" — file-generator pushes 100 more docs, re-index, MinIO handles scale

- [ ] **Resource Budget** (16GB laptop):
  - MinIO single node: 256MB | Ollama (tinyllama): 1.5GB | Qdrant: 256MB | RAG app: 256MB
  - Total AI stack: ~2.3GB | With MinIO cluster (4-node): ~3.5GB | Leaves ~8GB for OS/Docker

## Future — Experience & Sharing (Phase 5)

- [ ] Demo Export/Import as archive
- [ ] Demo Snapshots (Checkpoint/Restore)
- [ ] Demo Template Library (5+ pre-built templates)
- [ ] Walkthrough Engine (guided demo steps)
- [ ] Settings/Preferences Page
- [ ] Offline Mode / Pre-Pull Images
