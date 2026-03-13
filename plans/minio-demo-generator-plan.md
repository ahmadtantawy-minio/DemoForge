# MinIO Demo Environment Generator — Technical Plan

## 1. Executive Summary

**Project Name:** MinIO DemoForge  
**Purpose:** A visual, diagram-driven tool that generates containerized demo environments showcasing MinIO's capabilities across its full ecosystem — from multi-site replication and lakehouse architectures to AI/ML pipelines and hybrid cloud scenarios.

The tool allows a solutions engineer to visually compose a demo topology (MinIO clusters, analytics engines, databases, AI tools, cloud targets), hit "deploy," and have a fully functional, networked environment running on a laptop within minutes — complete with live traffic, monitoring, and interactive consoles.

---

## 2. MinIO Ecosystem Assessment

### 2.1 Core MinIO Capabilities to Demo

Based on research into MinIO's current product positioning (AIStor, formerly MinIO Enterprise Object Store), the following capabilities need to be demonstrable:

**Storage Fundamentals**
- Single-node and distributed (multi-node, multi-drive) deployments
- Erasure coding configuration
- Object versioning and locking
- Lifecycle management (ILM) and tiering
- S3 API compatibility (GET/PUT, multipart, presigned URLs)

**Replication**
- Bucket replication: active-passive (one-way)
- Bucket replication: active-active (two-way)
- Multi-site active-active replication (3+ sites, mesh topology)
- Site replication (full IAM, bucket, and object sync)
- Batch replication for granular object selection
- Replication to/from AWS S3 using `mc mirror` (client-side)
- Replication to/from GCP Cloud Storage using `mc mirror`

**Security and Identity**
- IAM users, groups, policies (PBAC)
- SSE-S3 and SSE-KMS encryption
- External IDP integration (LDAP/OpenID Connect)
- Bucket notifications and audit logging
- Object locking for compliance (WORM)

**Observability**
- Prometheus metrics endpoint
- Grafana dashboards
- Bucket and cluster health APIs
- Replication status tracking (X-Amz-Replication-Status)

### 2.2 Surrounding Tech Stack (Validated Integrations)

**Analytics / Lakehouse**
| Component | Role | Docker Image (Lightweight) |
|-----------|------|---------------------------|
| Apache Spark | ETL, batch processing, Iceberg writes | `bitnami/spark` (slim) |
| Trino (Starburst open-source) | Distributed SQL query engine | `trinodb/trino` |
| Apache Hive Metastore | Metadata catalog for Iceberg/Hive tables | `apache/hive` |
| Apache Iceberg | Open table format for lakehouse | (runs within Spark/Trino) |
| Dremio | Data lakehouse platform | `dremio/dremio-oss` |
| DuckDB | In-process analytical DB | (CLI or embedded) |
| Apache Superset | BI dashboards and visualization | `apache/superset` |

**Streaming / Messaging**
| Component | Role | Docker Image |
|-----------|------|-------------|
| Apache Kafka (KRaft mode) | Event streaming, CDC | `bitnami/kafka` (no ZK needed) |
| Apache Flink | Stream processing | `flink` |
| Apache NiFi | Data ingestion and routing | `apache/nifi` |

**AI / ML / Inference**
| Component | Role | Docker Image |
|-----------|------|-------------|
| Ollama | Local LLM inference | `ollama/ollama` |
| vLLM | High-performance LLM serving | `vllm/vllm-openai` |
| MLflow | ML experiment tracking | `ghcr.io/mlflow/mlflow` |
| LangChain (app) | RAG pipeline orchestration | Custom Python container |
| JupyterLab | Interactive notebooks | `jupyter/minimal-notebook` |

**Vector / KV Databases**
| Component | Role | Docker Image |
|-----------|------|-------------|
| Weaviate | Vector DB for semantic search | `semitechnologies/weaviate` |
| Milvus | Vector DB (MinIO as storage backend) | `milvusdb/milvus` |
| Qdrant | Lightweight vector DB | `qdrant/qdrant` |
| Redis | Caching, session store, table schemas | `redis:alpine` |
| PostgreSQL | Metadata store (Hive, MLflow) | `postgres:alpine` |
| ClickHouse | Real-time OLAP | `clickhouse/clickhouse-server` |

**Cloud Targets (Simulated)**
| Component | Role | Docker Image |
|-----------|------|-------------|
| LocalStack | AWS S3/SQS/Lambda simulation | `localstack/localstack` |
| Fake GCS Server | GCP Cloud Storage simulation | `fsouza/fake-gcs-server` |
| Azurite | Azure Blob Storage simulation | `mcr.microsoft.com/azure-storage/azurite` |

**Infrastructure / Networking**
| Component | Role | Docker Image |
|-----------|------|-------------|
| NGINX | Load balancer / reverse proxy | `nginx:alpine` |
| Prometheus | Metrics collection | `prom/prometheus` |
| Grafana | Metrics visualization | `grafana/grafana` |
| MinIO Console | Built-in web UI | (included in `minio/minio`) |

**Legacy / Migration**
| Component | Role | Docker Image |
|-----------|------|-------------|
| HDFS (Hadoop) | Legacy storage for migration demos | `apache/hadoop` (minimal) |

---

## 3. Architecture Design

### 3.1 System Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     DemoForge UI (React)                     │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────┐ │
│  │  Diagram      │  │  Demo        │  │  Control Plane     │ │
│  │  Editor       │  │  Manager     │  │  (Web UIs +        │ │
│  │  (React Flow) │  │  (CRUD)      │  │   Terminals)       │ │
│  └──────┬───────┘  └──────┬───────┘  └────────┬───────────┘ │
│         │                  │                    │             │
│         └──────────┬───────┴────────────────────┘             │
│                    │  REST / WebSocket                        │
├────────────────────┼─────────────────────────────────────────┤
│                    ▼                                          │
│           DemoForge Engine (Python / FastAPI)                 │
│  ┌──────────────┐ ┌───────────────┐ ┌────────────────────┐  │
│  │ Component     │ │ Compose       │ │ Secret / License   │  │
│  │ Registry      │ │ Generator     │ │ Manager (Vault)    │  │
│  └──────────────┘ └───────────────┘ └────────────────────┘  │
│  ┌──────────────┐ ┌───────────────┐ ┌────────────────────┐  │
│  │ Network       │ │ Health        │ │ Traffic            │  │
│  │ Manager       │ │ Monitor       │ │ Generator Ctrl     │  │
│  └──────────────┘ └───────────────┘ └────────────────────┘  │
│  ┌──────────────────────────────────────────────────────┐    │
│  │ Reverse Proxy Gateway                                 │    │
│  │ Routes /proxy/{demo}/{node}/{ui} → container:port     │    │
│  │ Also joins every demo network for direct access       │    │
│  └──────────────────────────────────────────────────────┘    │
│                    │                                          │
│                    ▼  Docker Socket + Network Membership      │
├──────────────────────────────────────────────────────────────┤
│                Docker Engine (Host)                           │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │ Demo-A       │  │ Demo-B       │  │ Demo-C              │  │
│  │ Network      │  │ Network      │  │ Network             │  │
│  │ (sandboxed)  │  │ (sandboxed)  │  │ (sandboxed)         │  │
│  │  minio-1     │  │  minio-1     │  │  minio-1  minio-2   │  │
│  │  spark       │  │  trino       │  │  kafka    spark      │  │
│  │  jupyter     │  │  superset    │  │  weaviate  grafana   │  │
│  │              │  │              │  │                       │  │
│  │ NO host port │  │ NO host port │  │ NO host port         │  │
│  │ exposure     │  │ exposure     │  │ exposure             │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
│                                                               │
│  Only DemoForge exposes ports: 3000 (UI) + 8000 (API)        │
└──────────────────────────────────────────────────────────────┘
```

### 3.2 Key Design Principles

1. **Diagram-first**: The source of truth is the visual diagram. Everything is generated from it.
2. **Component-as-plugin**: Each technology is a self-contained module with a manifest (YAML), Dockerfile/image ref, config templates, and health check definition.
3. **Sandboxed by demo**: Each demo gets its own Docker network(s) and volume namespace. No container ports are exposed to the host — components live in their own world and are accessed exclusively through DemoForge's reverse proxy and terminal bridge. This eliminates port conflicts entirely and means you can run unlimited concurrent demos (within resource limits).
4. **Single entry point**: The only ports exposed on the host are DemoForge itself (3000 for UI, 8000 for API). Every component dashboard, API, and terminal is accessed through these two ports via proxy routing.
5. **Lightweight by default**: Alpine-based images, single-node deployments, memory limits on every container.
6. **Offline-capable**: All images can be pre-pulled; no runtime internet dependency.

---

## 4. Recommended Tech Stack

### 4.1 Frontend

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Framework | **React 18 + TypeScript** | Industry standard, massive ecosystem |
| Diagram editor | **React Flow (@xyflow/react v12)** | MIT licensed, purpose-built for node-based editors, drag-and-drop, custom nodes/edges, minimap, controls |
| State management | **Zustand** | Tiny (1KB), no boilerplate, works perfectly with React Flow |
| Terminal | **xterm.js** | Full terminal emulator in browser, used by VS Code |
| Styling | **Tailwind CSS** | Utility-first, fast prototyping, small bundle |
| Charts/metrics | **Recharts** | React-native charting, lightweight |
| HTTP/WebSocket | **Native fetch + native WebSocket** | Zero dependencies |

### 4.2 Backend

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Framework | **Python 3.12 + FastAPI** | Async, fast, auto-docs, Docker SDK is Python-native |
| Docker control | **docker-py (docker SDK)** | Direct Docker engine control; can build compose files AND manage containers programmatically |
| Compose generation | **PyYAML + Jinja2** | Template-driven docker-compose.yml generation from diagram state |
| Reverse proxy | **httpx (async) inside FastAPI** | Proxies web UI requests to containers over internal Docker networks; handles HTTP, WebSocket, and SSE forwarding. No external proxy needed — FastAPI IS the gateway |
| WebSocket | **FastAPI WebSocket** | Built-in, streams container logs, health status, and terminal sessions to UI |
| Secret management | **SQLite + Fernet encryption** | Zero infrastructure; encrypted at rest; sufficient for demo keys |
| Task queue | **asyncio tasks** | No need for Celery/Redis; FastAPI's background tasks suffice |
| Container runtime | **Docker Compose v2** | `docker compose` (plugin) — lighter than Kubernetes, native on every laptop |

### 4.3 Why NOT Kubernetes (K3s, Kind, etc.)

For a laptop demo tool, Docker Compose wins over Kubernetes because:
- **Memory**: K3s needs ~512MB overhead; Compose needs ~0MB overhead
- **Startup**: Compose containers start in seconds; K3s pods need scheduler + kubelet cycles
- **Simplicity**: No RBAC, no CRDs, no service mesh complexity
- **Networking**: Docker networks are simpler to reason about for demos
- **Portability**: Docker Desktop on Mac/Win/Linux; K3s has platform-specific issues

If Kubernetes demos are needed later, we can add a K3d component that runs *inside* a Docker container.

### 4.4 Resource Budget (Laptop Target: 16GB RAM, 8 cores)

| Component | Memory | CPU |
|-----------|--------|-----|
| DemoForge UI + Backend | 200MB | 0.5 |
| MinIO (per instance) | 256MB | 0.5 |
| Trino | 1GB | 1.0 |
| Spark (single-node) | 1GB | 1.0 |
| Kafka (KRaft) | 512MB | 0.5 |
| PostgreSQL | 128MB | 0.25 |
| Redis | 64MB | 0.1 |
| Prometheus + Grafana | 256MB | 0.25 |
| Vector DB (Qdrant/Weaviate) | 512MB | 0.5 |
| LocalStack (AWS sim) | 512MB | 0.5 |
| **Typical demo (8 components)** | **~4-6GB** | **~4 cores** |

This leaves room for 2 concurrent demos on a 16GB machine.

---

## 5. Component Registry Design

Every component in the ecosystem is defined by a YAML manifest. This is the core extensibility mechanism.

```yaml
# components/minio/manifest.yaml
id: minio
name: MinIO Object Store
category: storage          # storage | analytics | streaming | ai | database | cloud | infra
icon: minio.svg
version: "RELEASE.2025-02-28"
image: minio/minio:latest
description: "S3-compatible high-performance object storage"

resources:
  memory: 256m
  cpu: 0.5

ports:                     # Internal container ports (never exposed to host)
  - name: api
    container: 9000
    protocol: tcp
  - name: console
    container: 9001
    protocol: tcp

environment:
  MINIO_ROOT_USER: "${MINIO_ROOT_USER:-minioadmin}"
  MINIO_ROOT_PASSWORD: "${MINIO_ROOT_PASSWORD:-minioadmin}"
  MINIO_PROMETHEUS_AUTH_TYPE: "public"

volumes:
  - name: data
    path: /data
    size: 1g

command: ["server", "/data", "--console-address", ":9001"]

health_check:
  endpoint: /minio/health/live
  port: 9000
  interval: 10s
  timeout: 5s

secrets:
  - key: MINIO_ROOT_USER
    label: "Root User"
    default: "minioadmin"
  - key: MINIO_ROOT_PASSWORD
    label: "Root Password"
    default: "minioadmin"
  - key: MINIO_LICENSE_KEY
    label: "Enterprise License Key"
    required: false

web_ui:
  - name: "MinIO Console"
    port: 9001
    path: "/"
    icon: "minio-console.svg"
    description: "Built-in web UI for bucket management, monitoring, and admin"
  - name: "Metrics API"
    port: 9000
    path: "/minio/v2/metrics/cluster"
    icon: "metrics.svg"
    description: "Prometheus-compatible metrics endpoint"

connections:
  provides:
    - type: s3
      port: 9000
      description: "S3-compatible API endpoint"
    - type: metrics
      port: 9000
      path: /minio/v2/metrics
  accepts:
    - type: s3            # for replication targets
    - type: ldap           # for external IDP
    - type: kms            # for encryption

variants:
  single:
    description: "Single node, single drive"
    command: ["server", "/data", "--console-address", ":9001"]
  distributed:
    description: "4-node distributed (simulated with 4 drives)"
    command: ["server", "/data{1...4}", "--console-address", ":9001"]
  cluster:
    description: "Multi-node cluster (requires multiple instances)"
    replicas: 4

config_templates:
  replication:
    file: templates/replication.sh.j2
    description: "Setup bucket or site replication between MinIO instances"
  buckets:
    file: templates/create-buckets.sh.j2
    description: "Create initial buckets and policies"
```

### Component Categories and Initial Catalog

**Phase 1 (MVP):**
- `minio` — with single, distributed, cluster variants
- `minio-client` — mc CLI sidecar for setup scripts
- `nginx` — load balancer for multi-node
- `prometheus` + `grafana` — monitoring
- `traffic-generator` — custom S3 workload generator
- `localstack` — AWS S3 simulation target
- `postgresql` — metadata store
- `redis` — caching layer

**Phase 2 (Analytics):**
- `trino` — distributed SQL
- `spark` — ETL and batch
- `hive-metastore` — table catalog
- `iceberg` — (table format, configures within Spark/Trino)
- `superset` — BI dashboards
- `duckdb` — embedded analytics

**Phase 3 (AI/ML):**
- `ollama` — local LLM inference
- `weaviate` / `qdrant` / `milvus` — vector databases
- `jupyter` — notebooks
- `mlflow` — experiment tracking

**Phase 4 (Advanced):**
- `kafka` — event streaming (KRaft mode)
- `flink` — stream processing
- `hdfs` — legacy migration source
- `fake-gcs-server` — GCP simulation
- `azurite` — Azure simulation
- `clickhouse` — real-time OLAP
- `dremio` — lakehouse platform

---

## 6. Traffic Generator Design

A custom, lightweight container that generates realistic S3 workloads against MinIO.

```yaml
# components/traffic-generator/manifest.yaml
id: traffic-generator
name: S3 Traffic Generator
category: tooling
image: demoforge/traffic-gen:latest  # custom build
description: "Generates configurable S3 workloads"

connections:
  accepts:
    - type: s3   # must be connected to a MinIO instance

settings:
  - key: workload_profile
    type: enum
    options: [mixed, write-heavy, read-heavy, small-files, large-files, ai-training]
    default: mixed
  - key: concurrency
    type: int
    range: [1, 100]
    default: 10
  - key: object_size
    type: enum
    options: [1KB, 64KB, 1MB, 10MB, 100MB, 1GB]
    default: 1MB
  - key: rate_limit
    type: string
    default: "100/s"
  - key: bucket_name
    type: string
    default: "demo-data"
  - key: duration
    type: string
    default: "continuous"
```

The traffic generator itself is a Python container using `boto3` with configurable workload profiles:

- **mixed**: 70% PUT, 20% GET, 5% LIST, 5% DELETE
- **write-heavy**: 95% PUT, 5% LIST (data ingestion scenario)
- **read-heavy**: 10% PUT, 80% GET, 10% LIST (serving scenario)
- **small-files**: objects 1KB–64KB (IoT / log ingestion)
- **large-files**: objects 100MB–1GB (media / ML training data)
- **ai-training**: writes Parquet, CSV, and image files to structured bucket paths

The generator exposes a `/metrics` endpoint for Prometheus and a `/status` API for the UI to show live throughput, object count, and error rates.

---

## 7. Demo Definition Schema

A demo is the complete serialized state of a diagram. It maps directly to deployment artifacts.

```yaml
# demos/lakehouse-demo.yaml
id: lakehouse-demo
name: "Data Lakehouse with Iceberg"
description: "MinIO + Spark + Trino + Iceberg lakehouse architecture"
created: 2025-03-13T00:00:00Z
author: "SE Team"

network:
  name: lakehouse-net
  subnet: 172.20.0.0/16
  dns_suffix: lakehouse.demo

nodes:
  - id: minio-1
    component: minio
    variant: distributed
    position: { x: 400, y: 200 }
    config:
      MINIO_ROOT_USER: "admin"
      MINIO_ROOT_PASSWORD: "supersecret"
    network:
      ip: 172.20.1.10
      aliases: ["s3.lakehouse.demo"]

  - id: hive-meta
    component: hive-metastore
    position: { x: 400, y: 400 }
    config:
      DATABASE_TYPE: postgresql
    network:
      ip: 172.20.2.10

  - id: trino-1
    component: trino
    position: { x: 200, y: 400 }
    config:
      CATALOGS: "iceberg,hive"
    network:
      ip: 172.20.3.10

  - id: spark-1
    component: spark
    position: { x: 600, y: 400 }
    config:
      SPARK_MODE: master
    network:
      ip: 172.20.4.10

  - id: traffic
    component: traffic-generator
    position: { x: 100, y: 200 }
    config:
      workload_profile: "ai-training"
      concurrency: 20

edges:
  - source: traffic
    target: minio-1
    type: s3
    label: "Write workload"
  - source: trino-1
    target: minio-1
    type: s3
    label: "Query data"
  - source: trino-1
    target: hive-meta
    type: jdbc
    label: "Metadata"
  - source: spark-1
    target: minio-1
    type: s3
    label: "ETL read/write"
  - source: spark-1
    target: hive-meta
    type: thrift
    label: "Table catalog"

init_scripts:
  - name: "Create Iceberg tables"
    target: spark-1
    script: scripts/create-iceberg-tables.sh
  - name: "Create buckets"
    target: minio-1
    script: scripts/create-buckets.sh
```

---

## 8. Networking Strategy

Each demo gets isolated Docker networks with configurable subnets to simulate geographic separation.

```
Demo: "Multi-Site Replication"
├── network: site-a (172.30.0.0/24)  — "US East"
│   ├── minio-a1 (172.30.0.10)
│   ├── minio-a2 (172.30.0.11)
│   └── nginx-a  (172.30.0.2)
├── network: site-b (172.31.0.0/24)  — "US West"
│   ├── minio-b1 (172.31.0.10)
│   └── nginx-b  (172.31.0.2)
├── network: site-c (172.32.0.0/24)  — "EU"
│   ├── minio-c1 (172.32.0.10)
│   └── nginx-c  (172.32.0.2)
└── network: backbone (172.29.0.0/24) — inter-site link
    ├── nginx-a, nginx-b, nginx-c (dual-homed)
    └── tc (traffic control) container for latency simulation
```

**Latency Simulation:** A small `tc` (traffic control) sidecar container using `iproute2` can inject configurable latency between networks to simulate WAN links (e.g., 50ms US-East to US-West, 120ms US to EU).

**Sandboxed Networking — No Host Port Exposure:**

Unlike traditional Docker Compose setups that map container ports to host ports, DemoForge keeps all component ports internal to their Docker network. No `ports:` declarations appear in the generated compose files — only `expose:` for inter-container communication.

The DemoForge backend container dynamically joins each demo's Docker network(s) at deploy time. This gives it direct access to every container by hostname and internal port. The proxy gateway then routes requests from the browser through to the right container:

```
Browser request:
  GET /proxy/lakehouse-demo/minio-1/console/

FastAPI proxy gateway:
  1. Look up demo "lakehouse-demo" → network "lakehouse-net"
  2. Look up node "minio-1" → container hostname "demoforge-lakehouse-minio-1"
  3. Look up UI "console" → manifest says port 9001, path "/"
  4. Forward request to http://demoforge-lakehouse-minio-1:9001/
  5. Rewrite response URLs so relative links continue to work through the proxy
  6. Stream response back to browser
```

**Why this is better than port exposure:**
- **Zero port conflicts**: Two demos can both have a MinIO on port 9001 internally — they're on separate networks
- **No port math**: No base offsets, no remembering which port is which
- **Cleaner security**: Host firewall sees only ports 3000 and 8000
- **Unlimited concurrent demos**: Network isolation is free; port space is finite
- **Simpler compose generation**: No host port allocation logic needed
- **Portable URLs**: Proxy paths like `/proxy/lakehouse/minio-1/console/` are self-documenting and shareable

**DemoForge network membership:**

When a demo is deployed, the backend does:
```python
# Join the demo's network so we can reach its containers
network = docker_client.networks.get("demoforge-lakehouse-net")
network.connect(demoforge_backend_container)
```

When a demo is torn down, the backend disconnects from that network. The backend can be connected to multiple demo networks simultaneously — Docker supports unlimited network memberships per container.

**Special case — multi-network demos:**

For demos with multiple networks (e.g., multi-site replication with site-a, site-b, site-c, backbone), the backend joins ALL of the demo's networks. This means it can reach every container in every "site" directly, even though the sites are isolated from each other (which is the point of the demo).

---

## 9. Secret & License Management

```
┌──────────────────────────────────┐
│  Secret Store (SQLite + Fernet)  │
├──────────────────────────────────┤
│  minio.license_key    = ****     │
│  minio.root_password  = ****     │
│  starburst.license    = ****     │
│  aws.access_key       = ****     │
│  aws.secret_key       = ****     │
│  grafana.admin_pass   = ****     │
└──────────────────────────────────┘
```

- Each component manifest declares its required and optional secrets
- The UI provides a "Secrets Vault" panel where you enter keys once
- Secrets are injected into containers via Docker environment variables (not mounted files, for simplicity)
- A `.env.encrypted` file can be committed to version control safely
- On first run, the tool prompts for any missing required secrets
- Default/demo values are provided for everything except actual license keys

---

## 10. UI Design

### 10.1 Main Layout

```
┌──────────────────────────────────────────────────────────────────────┐
│  DemoForge      [Demo: Lakehouse ▼]  [▶ Deploy] [⏹ Stop]           │
│                                      [Diagram | Control Plane]       │
├────────────┬─────────────────────────────┬───────────────────────────┤
│            │                             │                           │
│  Component │     Diagram Canvas          │   Properties              │
│  Palette   │     (React Flow)            │   Panel                   │
│            │                             │                           │
│  ┌──────┐  │   ┌─────┐    ┌─────┐       │   Component: minio-1      │
│  │MinIO │  │   │ M-1 │───▶│Trino│       │   Status: ● HEALTHY       │
│  ├──────┤  │   └──┬──┘    └─────┘       │   Via: /proxy/lakehouse/minio-1   │
│  │Spark │  │      │                      │   Memory: 245/256 MB      │
│  ├──────┤  │   ┌──▼──┐    ┌──────┐      │                           │
│  │Trino │  │   │Spark│───▶│Grafana│     │   [🔗 Open Console]       │
│  ├──────┤  │   └─────┘    └──────┘      │   [>_ Terminal]           │
│  │Kafka │  │                             │   [⚙ Settings]           │
│  ├──────┤  │  Double-click a node to     │   [📋 Logs]              │
│  │ ...  │  │  open its web UI directly   │                           │
│            │                             │                           │
├────────────┴─────────────────────────────┴───────────────────────────┤
│  Terminal Tabs: [minio-1] [trino-1] [+ new]          [Logs | Shell] │
│  ┌──────────────────────────────────────────────────────────────────┐│
│  │ [lakehouse:minio-1] # mc admin info local                       ││
│  │ ● Uptime: 2h 15m  ● Objects: 12,453  ● Size: 4.2 GB            ││
│  │ [mc ls] [mc admin replicate status] [mc admin info]   ← chips   ││
│  └──────────────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────────┘
```

### 10.2 Diagram Node Types (Custom React Flow Nodes)

Each node type renders differently based on component category:

- **Storage nodes** (MinIO): Show bucket count, replication status, throughput gauge
- **Analytics nodes** (Trino/Spark): Show query count, active workers
- **Database nodes**: Show connection count, table count
- **Cloud target nodes** (AWS/GCP): Show sync status, object count delta
- **Traffic generator**: Show live ops/sec, bandwidth, error rate

### 10.3 Edge Decorators

Edges (connections) display:
- Connection type icon (S3, JDBC, Thrift, HTTP)
- Live traffic indicator (animated dots flowing along the edge)
- Bandwidth label when traffic is active
- Status color (green=healthy, yellow=degraded, red=error)

---

## 11. Demo Control Plane — Per-Instance Management Interface

Once a demo is deployed, each running instance needs a unified control surface. The Demo Control Plane is a dedicated panel that gives the operator immediate access to every component's web UI, admin panels, and shell — without hunting for port numbers or remembering URLs.

### 11.1 Concept

Every running demo gets its own **Control Plane view** — a runtime dashboard that sits alongside the diagram. While the diagram shows the *topology* (what's connected to what), the Control Plane shows the *operational surface* (how to interact with each running component). Think of it as the "cockpit" for a deployed demo.

```
┌──────────────────────────────────────────────────────────────────────┐
│  DemoForge  ▸ Lakehouse Demo (running)    [Diagram] [Control Plane] │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌─ minio-1 ──────────────────────────────────────── ● HEALTHY ──┐  │
│  │                                                                │  │
│  │  [🔗 MinIO Console]  [🔗 Metrics API]  [>_ Terminal]          │  │
│  │                                                                │  │
│  │  Internal: minio-1:9001            Objects: 12,453             │  │
│  │  Buckets: 4     Replication: active   Uptime: 2h 15m          │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌─ trino-1 ─────────────────────────────────────── ● HEALTHY ───┐  │
│  │                                                                │  │
│  │  [🔗 Trino Web UI]  [>_ Terminal]  [>_ Trino CLI]             │  │
│  │                                                                │  │
│  │  Internal: trino-1:8080            Active queries: 2           │  │
│  │  Workers: 1     Catalogs: iceberg, hive                        │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌─ spark-1 ─────────────────────────────────────── ● HEALTHY ───┐  │
│  │                                                                │  │
│  │  [🔗 Spark Master UI]  [🔗 Spark History]  [>_ Terminal]      │  │
│  │                                                                │  │
│  │  Internal: spark-1:8080            Jobs: 3 completed           │  │
│  │  Workers: 1     Mode: standalone                               │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌─ grafana ─────────────────────────────────────── ● HEALTHY ───┐  │
│  │                                                                │  │
│  │  [🔗 Grafana Dashboard]  [>_ Terminal]                         │  │
│  │                                                                │  │
│  │  Internal: grafana:3000            Dashboards: 3 loaded        │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌─ traffic-gen ─────────────────────────────────── ● RUNNING ───┐  │
│  │                                                                │  │
│  │  [🔗 Status API]  [>_ Terminal]  [⏸ Pause] [⚙ Settings]      │  │
│  │                                                                │  │
│  │  Profile: ai-training   Ops/sec: 245   Bandwidth: 48 MB/s     │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  All web UIs are accessed via /proxy/{demo}/{node}/{ui} — no        │
│  ports are exposed to the host. DemoForge is the single gateway.    │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

### 11.2 Component Web UI Registry

Each component manifest declares its web UIs under a `web_ui` key. The Control Plane reads these declarations and auto-generates clickable links that route through the DemoForge reverse proxy — no host port exposure needed. Clicking "MinIO Console" on node `minio-1` in demo `lakehouse` opens `/proxy/lakehouse/minio-1/console/` in a new tab (or embedded iframe), which the backend forwards to `minio-1:9001` over the internal Docker network.

Known web UIs across the component catalog:

| Component | Web UI | Container Port | Description |
|-----------|--------|---------------|-------------|
| MinIO | MinIO Console | 9001 | Bucket management, user/policy admin, replication status, metrics |
| MinIO | S3 Browser (optional) | 9000 | Direct S3 API endpoint for tools like CyberDuck |
| Grafana | Grafana Dashboard | 3000 | Pre-loaded dashboards for MinIO, Kafka, Spark metrics |
| Prometheus | Prometheus UI | 9090 | Query browser, target health, alerts |
| Trino | Trino Web UI | 8080 | Query monitor, worker status, cluster overview |
| Spark | Spark Master UI | 8080 | Job status, executors, DAG visualization |
| Spark | Spark History Server | 18080 | Completed job history and stage details |
| Superset | Superset Dashboard | 8088 | BI dashboards, SQL Lab, chart builder |
| JupyterLab | Jupyter UI | 8888 | Notebook interface with pre-loaded MinIO examples |
| MLflow | MLflow Tracking UI | 5000 | Experiment tracking, model registry, artifact browser |
| Kafka (KRaft) | — | — | No built-in UI (use Kafka UI sidecar below) |
| Kafka UI | Kafka UI | 8080 | Topic browser, consumer groups, message viewer |
| Apache NiFi | NiFi Canvas | 8443 | Visual data flow editor |
| Weaviate | — | — | REST API only (terminal access for queries) |
| Qdrant | Qdrant Dashboard | 6333 | Collection browser, point visualization |
| Milvus | Attu UI | 3000 | Collection manager, vector visualization |
| ClickHouse | Play UI | 8123 | Built-in SQL playground |
| LocalStack | LocalStack Dashboard | 4566 | Resource browser for simulated AWS services |
| Dremio | Dremio UI | 9047 | Data catalog, SQL editor, acceleration |
| HDFS | NameNode UI | 9870 | HDFS file browser, datanode health |
| Ollama | — | — | REST API only (terminal for model pulls and chat) |

Components without a web UI (Weaviate, Ollama, Redis, PostgreSQL) get a prominent terminal button instead, with pre-loaded helpful commands shown as quick-action chips.

### 11.3 Terminal Access (Container Shell)

Every running component gets a **terminal button** that opens an xterm.js session attached to that container via `docker exec`. The backend handles this through a WebSocket bridge:

```
Browser (xterm.js) ↔ WebSocket ↔ FastAPI ↔ docker exec -it <container> /bin/sh
```

**Terminal features:**

- **Per-container shell**: Each terminal session is isolated to its container. The prompt shows the container name and demo context (e.g., `[lakehouse:minio-1] #`).
- **Multiple concurrent terminals**: Open shells into different containers side-by-side. Tabbed interface in the bottom panel.
- **Pre-loaded CLI tools**: Each component image includes its own CLI. MinIO containers include `mc` pre-configured with the local alias. Trino containers include the Trino CLI. Spark containers include `spark-sql` and `spark-submit`.
- **Quick-action chips**: Contextual command suggestions above the terminal based on component type:

| Component | Quick-action chips |
|-----------|-------------------|
| MinIO | `mc admin info` · `mc ls` · `mc admin replicate status` · `mc admin prometheus metrics` |
| Trino | `trino --catalog iceberg` · `SHOW SCHEMAS` · `SHOW TABLES` |
| Spark | `spark-sql` · `spark-submit --help` · `pyspark` |
| Kafka | `kafka-topics.sh --list` · `kafka-console-consumer.sh` |
| PostgreSQL | `psql -U postgres` · `\dt` · `\l` |
| Redis | `redis-cli` · `INFO` · `KEYS *` |
| Weaviate | `curl localhost:8080/v1/schema` · `curl localhost:8080/v1/objects` |
| Ollama | `ollama list` · `ollama run llama3` |

- **Command history persistence**: Terminal history is saved per-container across panel open/close (stored in browser memory for the session).
- **Copy/paste support**: Standard clipboard integration via xterm.js.

### 11.4 Contextual Dashboards per Component

Since all web UIs are accessed through the DemoForge proxy, embedding them as **iframe previews** directly in the Control Plane is straightforward — the iframe `src` is just a proxy path on the same origin, so there are no CORS or mixed-content issues. Each component card can show a live thumbnail of its dashboard that expands to full screen on click.

**Embedded preview priority** (only for components where the UI is self-contained and useful at a glance):
1. **MinIO Console** — bucket list, replication status bars, throughput gauges
2. **Grafana** — pre-loaded MinIO dashboard with live metrics
3. **Superset** — any dashboard charts created during the demo

For any component, clicking the web UI button opens the proxied dashboard in a **full-width panel** within DemoForge (not an external browser tab). This keeps the user inside the tool during demos. A "pop out" button is available for anyone who wants a separate browser tab.

**Proxy path pattern:**
```
/proxy/{demo_id}/{node_id}/{ui_name}/   → component web UI
/proxy/{demo_id}/{node_id}/{ui_name}/*  → all sub-paths forwarded
```

Example URLs (all on localhost:3000, the DemoForge UI origin):
- MinIO Console: `/proxy/lakehouse/minio-1/console/`
- Grafana: `/proxy/lakehouse/grafana/dashboard/d/minio-overview`
- Trino Web UI: `/proxy/lakehouse/trino-1/webui/ui/`
- Spark Master: `/proxy/replication-demo/spark-1/master/`

### 11.5 Health and Status Indicators

Each component card in the Control Plane shows a real-time health badge:

| Badge | Meaning | Source |
|-------|---------|--------|
| ● HEALTHY | Container running, health check passing | Docker health check + component-specific endpoint |
| ● STARTING | Container running, health check not yet passing | Docker state = running, health = starting |
| ● DEGRADED | Container running, but health check intermittent | Health check flapping (pass/fail within 30s window) |
| ● ERROR | Container running, health check failing | Health endpoint returning non-200 or timeout |
| ● STOPPED | Container exited or not started | Docker state = exited/created |

Health data flows via the same WebSocket that powers log streaming — the backend polls container health every 5 seconds and pushes state changes to the UI.

### 11.6 Cross-Navigation: Diagram ↔ Control Plane

The diagram view and the Control Plane are tightly linked:

- **Click a node in the diagram** → the Control Plane scrolls to and highlights that component's card, with its web UI links and terminal ready.
- **Click a component card in the Control Plane** → the diagram pans and zooms to center that node, highlighting its connections.
- **Double-click a node in the diagram** → directly opens that component's primary web UI in a full-width proxied panel within DemoForge. This is the fastest path to "show me the dashboard" — one double-click from diagram to live MinIO Console.
- **Right-click a node** → context menu with: Open Web UI, Open Terminal, View Logs, Restart Container, View Config.
- **Keyboard shortcut** (Tab) → toggles between Diagram and Control Plane views.

### 11.7 Backend API for the Control Plane

```
GET  /api/demos/{demo_id}/instances
     → Returns all running containers with status, web_ui proxy paths, health

GET  /api/demos/{demo_id}/instances/{node_id}
     → Single container detail: health, resource usage, available UIs and terminals

ANY  /proxy/{demo_id}/{node_id}/{ui_name}/{path:path}
     → Reverse proxy gateway: forwards HTTP/WebSocket requests to
       the container's internal port over the Docker network.
       Handles URL rewriting, cookie path adjustment, and WebSocket upgrade.

WS   /api/demos/{demo_id}/instances/{node_id}/terminal
     → WebSocket for interactive shell (xterm.js ↔ docker exec)

WS   /api/demos/{demo_id}/instances/{node_id}/logs
     → WebSocket streaming container stdout/stderr

GET  /api/demos/{demo_id}/instances/{node_id}/health
     → Current health status + last check timestamp

POST /api/demos/{demo_id}/instances/{node_id}/restart
     → Restart a single container without tearing down the demo

POST /api/demos/{demo_id}/instances/{node_id}/exec
     → Execute a one-shot command (for quick-action chips)
```

**Proxy implementation notes:**

The reverse proxy is built into FastAPI using `httpx.AsyncClient` for HTTP forwarding and native WebSocket relay for WebSocket connections. Key behaviors:

- **URL rewriting**: Response bodies containing absolute URLs (like `href="/static/..."` in Grafana or MinIO Console) are rewritten to include the proxy prefix (`/proxy/lakehouse/grafana/dashboard/static/...`). This uses a streaming response transformer, not full buffering.
- **WebSocket passthrough**: For UIs that use WebSocket (Grafana live, Jupyter kernels, NiFi), the proxy upgrades the connection and relays frames bidirectionally.
- **Session/cookie scoping**: Cookies set by proxied UIs are scoped to their proxy path (`Path=/proxy/lakehouse/grafana/`) so different demos and components don't collide.
- **No authentication passthrough**: DemoForge auto-injects credentials for component UIs where possible (e.g., Grafana admin login) to reduce friction during demos. The manifest `credentials` field controls this.

### 11.8 Component Manifest — web_ui Declaration

The `web_ui` key in each component manifest drives everything. Here's a richer example showing different components:

```yaml
# components/trino/manifest.yaml (excerpt)
web_ui:
  - name: "Trino Web UI"
    port: 8080
    path: "/ui/"
    icon: "trino.svg"
    description: "Query monitor, worker status, cluster overview"
    credentials:
      username: "admin"
      password: null   # no password by default

terminal:
  shell: /bin/bash
  welcome_message: "Trino container — use 'trino' CLI to connect"
  quick_actions:
    - label: "Trino CLI (Iceberg)"
      command: "trino --catalog iceberg --schema default"
    - label: "Show tables"
      command: "trino --execute 'SHOW SCHEMAS FROM iceberg'"
    - label: "Cluster info"
      command: "trino --execute 'SELECT * FROM system.runtime.nodes'"
```

```yaml
# components/grafana/manifest.yaml (excerpt)
web_ui:
  - name: "Grafana Dashboard"
    port: 3000
    path: "/d/minio-overview"
    icon: "grafana.svg"
    description: "Pre-loaded MinIO monitoring dashboards"
    credentials:
      username: "admin"
      password: "${GRAFANA_ADMIN_PASSWORD:-admin}"
    embed_preview: true   # show iframe thumbnail in Control Plane

terminal:
  shell: /bin/sh
  quick_actions:
    - label: "List dashboards"
      command: "curl -s localhost:3000/api/search | python3 -m json.tool"
```

```yaml
# components/redis/manifest.yaml (excerpt)
web_ui: []  # no web UI

terminal:
  shell: /bin/sh
  welcome_message: "Redis container — use 'redis-cli' to connect"
  quick_actions:
    - label: "Redis CLI"
      command: "redis-cli"
    - label: "Server info"
      command: "redis-cli INFO server"
    - label: "Key count"
      command: "redis-cli DBSIZE"
```

---

## 12. Pre-Built Demo Templates

The tool ships with these ready-to-deploy scenarios:

| # | Template Name | Components | Showcases |
|---|--------------|------------|-----------|
| 1 | **Single MinIO** | MinIO, mc, traffic-gen | Basic S3 operations, console tour |
| 2 | **Active-Active Replication** | 2× MinIO, NGINX, traffic-gen, Prometheus, Grafana | Bucket replication, failover |
| 3 | **Multi-Site Mesh** | 3× MinIO + NGINX, backbone network | Site replication across "regions" |
| 4 | **Data Lakehouse** | MinIO, Spark, Trino, Hive Metastore, Iceberg, Superset | Analytics on object storage |
| 5 | **AI/ML Pipeline** | MinIO, JupyterLab, MLflow, Weaviate, Ollama | RAG pipeline, model storage |
| 6 | **Hybrid Cloud** | MinIO, LocalStack (AWS), Fake-GCS, traffic-gen | Cloud repatriation, multi-cloud |
| 7 | **HDFS Migration** | MinIO, HDFS, Spark, traffic-gen | Legacy migration to object storage |
| 8 | **Streaming Lakehouse** | MinIO, Kafka, Spark Streaming, Trino, Iceberg | Real-time data ingestion |
| 9 | **Secure Compliance** | MinIO (WORM), PostgreSQL (audit), Prometheus | Object lock, encryption, audit |
| 10 | **Edge to Core** | 2× MinIO (edge/core), NGINX, traffic-gen | Edge data collection + replication |

---

## 13. Project Structure

```
demoforge/
├── frontend/                       # React app
│   ├── src/
│   │   ├── components/
│   │   │   ├── canvas/             # React Flow diagram
│   │   │   │   ├── DiagramCanvas.tsx
│   │   │   │   ├── nodes/          # Custom node components
│   │   │   │   │   ├── MinIONode.tsx
│   │   │   │   │   ├── AnalyticsNode.tsx
│   │   │   │   │   ├── DatabaseNode.tsx
│   │   │   │   │   ├── CloudNode.tsx
│   │   │   │   │   └── TrafficGenNode.tsx
│   │   │   │   └── edges/
│   │   │   │       └── AnimatedDataEdge.tsx
│   │   │   ├── palette/            # Drag-and-drop component palette
│   │   │   ├── properties/         # Right-side config panel
│   │   │   ├── console/            # xterm.js terminal
│   │   │   ├── control-plane/      # Per-demo instance management
│   │   │   │   ├── ControlPlane.tsx       # Main control plane view
│   │   │   │   ├── ComponentCard.tsx      # Per-component card with status
│   │   │   │   ├── WebUIButton.tsx        # Clickable link to component dashboard
│   │   │   │   ├── TerminalTab.tsx        # xterm.js shell per container
│   │   │   │   ├── QuickActionChips.tsx   # Pre-loaded command suggestions
│   │   │   │   ├── HealthBadge.tsx        # Real-time health indicator
│   │   │   │   └── EmbedPreview.tsx       # Optional iframe dashboard preview
│   │   │   ├── metrics/            # Live metrics dashboard
│   │   │   └── vault/              # Secret management UI
│   │   ├── stores/                 # Zustand state
│   │   │   ├── diagramStore.ts
│   │   │   ├── demoStore.ts
│   │   │   └── metricsStore.ts
│   │   └── api/                    # Backend API client
│   ├── package.json
│   └── vite.config.ts              # Vite for fast dev builds
│
├── backend/                        # FastAPI server
│   ├── app/
│   │   ├── main.py                 # FastAPI app
│   │   ├── api/
│   │   │   ├── demos.py            # Demo CRUD
│   │   │   ├── deploy.py           # Deploy/destroy
│   │   │   ├── instances.py        # Control plane: per-container status, proxy paths, health
│   │   │   ├── proxy.py            # Reverse proxy: /proxy/{demo}/{node}/{ui}/* → container:port
│   │   │   ├── terminal.py         # WebSocket shell bridge (xterm.js ↔ docker exec)
│   │   │   ├── health.py           # Component health
│   │   │   ├── secrets.py          # Vault API
│   │   │   └── ws.py               # WebSocket (logs, metrics)
│   │   ├── engine/
│   │   │   ├── compose_generator.py  # YAML generation (no host port mappings)
│   │   │   ├── docker_manager.py     # Docker SDK operations
│   │   │   ├── network_manager.py    # Network creation/teardown + backend network joining
│   │   │   ├── proxy_gateway.py      # Reverse proxy: routes /proxy/{demo}/{node}/{ui}/* to containers
│   │   │   ├── terminal_bridge.py    # WebSocket ↔ docker exec shell multiplexer
│   │   │   ├── health_monitor.py     # Periodic health checks (via internal network, not host ports)
│   │   │   └── init_runner.py        # Post-deploy init scripts
│   │   ├── registry/
│   │   │   └── loader.py           # Load component manifests
│   │   ├── secrets/
│   │   │   └── vault.py            # SQLite + Fernet
│   │   └── models/
│   │       ├── demo.py             # Demo schema
│   │       ├── component.py        # Component schema
│   │       └── diagram.py          # Diagram state schema
│   ├── requirements.txt
│   └── Dockerfile
│
├── components/                     # Component registry
│   ├── minio/
│   │   ├── manifest.yaml
│   │   ├── templates/
│   │   │   ├── replication.sh.j2
│   │   │   └── create-buckets.sh.j2
│   │   └── grafana-dashboard.json
│   ├── trino/
│   │   ├── manifest.yaml
│   │   └── templates/
│   │       └── catalog-iceberg.properties.j2
│   ├── spark/
│   ├── kafka/
│   ├── traffic-generator/
│   │   ├── manifest.yaml
│   │   ├── Dockerfile
│   │   └── src/
│   │       ├── generator.py
│   │       └── profiles/
│   └── ... (one dir per component)
│
├── demos/                          # Pre-built demo templates
│   ├── single-minio.yaml
│   ├── active-active-replication.yaml
│   ├── lakehouse.yaml
│   └── ...
│
├── docker-compose.yaml             # DemoForge itself
├── Makefile                        # Dev commands
└── README.md
```

---

## 14. Implementation Roadmap

### Phase 1 — Foundation (Weeks 1–3)

**Goal:** Diagram editor + single MinIO deployment from diagram + Control Plane access

- Set up React + Vite + React Flow frontend scaffold
- Build FastAPI backend with Docker SDK integration
- Create component registry loader (YAML manifest parsing, including `web_ui` and `terminal` declarations)
- Build `minio` component manifest (single + distributed variants)
- Implement compose generator: diagram state → docker-compose.yml
- Implement deploy/destroy lifecycle via Docker SDK
- Basic health monitoring (container status polling)
- WebSocket log streaming from containers to UI
- Basic properties panel (view/edit node config)
- **Control Plane v1**: component cards with health badge, web UI link buttons (routed through reverse proxy), and single-container terminal via xterm.js ↔ WebSocket ↔ `docker exec`
- **Reverse proxy gateway**: backend joins demo Docker networks and forwards `/proxy/{demo}/{node}/{ui}/*` to the container's internal port — zero host port exposure
- **Diagram ↔ Control Plane navigation**: click a node to jump to its control card; double-click to open primary web UI in proxied panel

**Deliverable:** Draw a MinIO node, hit deploy, get a running MinIO — then click through to the MinIO Console (proxied through DemoForge, no exposed ports), open a terminal into the container, and run `mc` commands, all from within DemoForge.

### Phase 2 — Connections & Replication (Weeks 4–5)

**Goal:** Multi-instance demos with replication + multi-container Control Plane

- Edge (connection) system in React Flow with typed connections
- Build NGINX load balancer component
- Implement Prometheus + Grafana monitoring stack (with pre-loaded MinIO dashboards)
- Build multi-network support (Docker network per "site")
- Implement site replication setup scripts (mc admin replicate)
- Implement bucket replication setup scripts
- Animated edge data flow indicators
- Multi-network proxy support (backend joins all of a demo's networks for multi-site demos)
- **Control Plane v2**: tabbed multi-terminal (open shells to multiple containers simultaneously), quick-action chips per component type, right-click context menu on diagram nodes, container restart without full teardown

**Deliverable:** Deploy a 3-site replication demo with monitoring, and manage all instances from the Control Plane — open MinIO Consoles for each site, Grafana dashboards, and terminals side by side.

### Phase 3 — Traffic & Secrets (Weeks 6–7)

**Goal:** Live traffic generation, secret management, and embedded dashboard previews

- Build traffic generator container (Python + boto3)
- Traffic generator settings UI (profile, concurrency, object size)
- Live metrics overlay on diagram nodes (ops/sec, bandwidth)
- Secret vault backend (SQLite + Fernet)
- Secret vault UI
- Component secret injection during deployment
- Demo save/load (YAML serialization of diagram state)
- **Control Plane v3**: embedded iframe previews for Grafana and MinIO Console (optional toggle), credential display with copy-to-clipboard for components requiring login, traffic generator pause/resume/settings controls directly in control card

**Deliverable:** Generate traffic, see live metrics on diagram, manage keys, and monitor everything from embedded dashboard thumbnails in the Control Plane.

### Phase 4 — Analytics Stack (Weeks 8–10)

**Goal:** Lakehouse demo capability

- Trino component (with Iceberg connector config)
- Spark component (master + worker)
- Hive Metastore component
- PostgreSQL component (for HMS backing store)
- Init script runner (post-deploy setup, table creation)
- Superset component for dashboards
- Pre-built "Lakehouse" demo template

**Deliverable:** One-click deploy of a full lakehouse with querying.

### Phase 5 — AI/ML & Cloud (Weeks 11–13)

**Goal:** AI pipeline demos and cloud simulation

- Ollama, Weaviate/Qdrant, JupyterLab, MLflow components
- LocalStack, Fake-GCS, Azurite cloud simulation components
- `mc mirror` script templates for cross-cloud replication
- HDFS component for migration demos
- RAG pipeline demo template
- Hybrid cloud demo template

**Deliverable:** Full AI and multi-cloud demo capability.

### Phase 6 — Polish & Actions (Weeks 14–16)

**Goal:** Production-quality UX, action system

- Demo template gallery with previews
- Action system: pluggable operations (migration job, benchmark, failover test)
- Network latency simulation (tc-based)
- Export demo as standalone docker-compose for customer handoff
- Documentation and onboarding flow
- Performance optimization (lazy component loading, image caching)

**Deliverable:** Polished tool ready for daily SE use.

---

## 15. Quick Start (Day One)

```bash
# Clone and start DemoForge
git clone https://github.com/org/demoforge.git
cd demoforge

# Pre-pull common images (one-time, ~5GB)
make pull-images

# Start DemoForge
docker compose up -d

# Open browser
open http://localhost:3000
```

The tool itself runs as two containers (frontend + backend) plus a volume for the SQLite vault and demo definitions. Everything else is dynamically created.

---

## 16. Key Technical Decisions Summary

| Decision | Choice | Alternatives Considered |
|----------|--------|------------------------|
| Container orchestration | Docker Compose v2 | K3s, Kind, Podman — too heavy for laptop |
| Diagram library | React Flow | JointJS (paid), GoJS (paid), D3 (too low-level) |
| Backend language | Python/FastAPI | Go (faster but worse Docker SDK), Node (weaker Docker tooling) |
| State management | Zustand | Redux (too heavy), Jotai (similar but less popular) |
| Secret storage | SQLite + Fernet | HashiCorp Vault (overkill), env files (no encryption) |
| Compose generation | Jinja2 templates | Pulumi/CDK (over-engineered), raw Python dicts (unmaintainable) |
| Terminal emulation | xterm.js | No real alternative for browser terminals |
| Container shell bridge | FastAPI WebSocket ↔ docker exec | SSH (needs sshd in every container), ttyd (extra process per container) |
| Component UI access | Reverse proxy (httpx in FastAPI) | Host port exposure (port conflicts, messy), Traefik (extra infra), Nginx sidecar (over-engineered) |
| Cloud simulation | LocalStack + Fake-GCS + Azurite | Real cloud accounts (needs internet, costs money) |
| Metrics | Prometheus + Grafana | Datadog (requires account), custom (reinventing wheel) |
| Build tool | Vite | Webpack (slower), Turbopack (less mature) |

---

## 17. Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Laptop resource exhaustion | Demos crash or become unresponsive | Memory limits on every container; UI shows total resource usage; warn before deploy if insufficient |
| Docker image pull times | Slow first run | Pre-pull script; offline image bundle option; show progress in UI |
| Component version drift | Configs break with new releases | Pin all image versions in manifests; test matrix in CI |
| Complex init scripts fail silently | Demo appears up but isn't functional | Health checks validate actual readiness, not just container status; init script output in console |
| Proxy URL rewriting breaks component UIs | Some web UIs use absolute paths or hardcoded origins that break under a proxy prefix | Per-component proxy rewrite rules in manifest; test each component's UI through proxy during development; fallback "pop out to direct access" option that temporarily exposes the port |
| WebSocket shell sessions leak | Terminal tabs left open consume docker exec processes | Auto-timeout idle sessions after 10 min; backend tracks and cleans up orphaned exec instances on demo teardown |
| MinIO license needed for enterprise features | Can't demo site replication without license | Clearly mark which features need a license key; graceful degradation for community edition |

---

## 18. Next Steps

1. **Validate this plan** — review with stakeholders, adjust scope
2. **Set up the monorepo** — React + FastAPI + component registry structure
3. **Build the MinIO component manifest** — the first and most important component
4. **Prototype the diagram → compose pipeline** — the core technical risk
5. **Build a walking skeleton** — drag MinIO onto canvas, deploy, see it running, click through to its Console from the Control Plane, open a terminal and run `mc ls`

The fastest path to value is Phase 1: a working diagram editor that can deploy a single MinIO instance with full Control Plane access — web UI links, terminal, and health status. From there, every subsequent phase adds components and connections incrementally.
