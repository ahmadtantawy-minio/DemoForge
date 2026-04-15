# Investigation: External System Component Prerequisites
*Generated: 2026-04-14*

---

## Section 1: Component Manifest Structure

### Location
Component manifests live at:
```
components/{component-id}/manifest.yaml
```

### Complete Manifest: NGINX (infrastructure, single container)
**File:** `components/nginx/manifest.yaml`

```yaml
id: nginx
name: NGINX
category: infrastructure
icon: nginx
version: "latest"
image: nginx:latest
image_size_mb: 25
description: "High-performance load balancer and reverse proxy"

resources:
  memory: "128m"
  cpu: 0.25

ports:
  - name: http
    container: 80
    protocol: tcp
  - name: console
    container: 9001
    protocol: tcp
  - name: status
    container: 8080
    protocol: tcp

environment:
  NGINX_ENTRYPOINT_QUIET_LOGS: "1"

volumes: []

health_check:
  endpoint: /nginx_status
  port: 80
  interval: 10s
  timeout: 5s

secrets: []

web_ui:
  - name: console
    port: 9001
    path: "/"
    description: "MinIO Console (load-balanced across cluster nodes)"
  - name: status
    port: 80
    path: "/"
    description: "NGINX status page"

terminal:
  shell: /bin/sh
  welcome_message: "NGINX load balancer container."
  quick_actions:
    - label: "Test config"
      command: "nginx -t"
    - label: "Reload"
      command: "nginx -s reload"
    - label: "Active connections"
      command: "curl -s http://localhost/nginx_status"
    - label: "Tail access log"
      command: "tail -f /var/log/nginx/access.log"
    - label: "Tail error log"
      command: "tail -f /var/log/nginx/error.log"

connections:
  provides:
    - type: nginx-backend
      port: 80
      description: "Nginx backend connection (load-balance or failover, controlled by node mode)"
      config_schema: []
    - type: http
      port: 80
      description: "HTTP endpoint"
  accepts:
    - type: s3
      config_schema: []
    - type: http
      config_schema: []
    - type: file-push
      config_schema: []

log_commands:
  - name: "Access Log"
    command: "tail -100 /var/log/nginx/access.log 2>/dev/null || echo 'No access log'"
    description: "Last 100 lines of nginx access log"
  - name: "Error Log"
    command: "tail -100 /var/log/nginx/error.log 2>/dev/null || echo 'No error log'"
    description: "Last 100 lines of nginx error log"
  - name: "Config Test"
    command: "nginx -t 2>&1"
    description: "Validate nginx configuration"
  - name: "Active Connections"
    command: "curl -s http://localhost/nginx_status 2>/dev/null || echo 'Status endpoint unavailable'"
    description: "Current nginx connection stats"

template_mounts:
  - template: "nginx.conf.j2"
    mount_path: "/etc/nginx/conf.d/default.conf"

static_mounts: []

init_scripts:
  - command: "nginx -s reload"
    wait_for_healthy: true
    timeout: 30
    order: 10
    description: "Reload nginx with generated config"
```

### Complete Manifest: Prometheus (observability, single container)
**File:** `components/prometheus/manifest.yaml`

```yaml
id: prometheus
name: Prometheus
category: observability
icon: prometheus
version: "latest"
image: prom/prometheus:latest
image_size_mb: 90
description: "Metrics collection and alerting system"

resources:
  memory: "256m"
  cpu: 0.5

ports:
  - name: http
    container: 9090
    protocol: tcp

environment: {}

volumes:
  - name: data
    path: /prometheus
    size: 1g

command:
  - "--config.file=/etc/prometheus/prometheus.yml"
  - "--storage.tsdb.path=/prometheus"
  - "--storage.tsdb.retention.time=1h"
  - "--web.enable-lifecycle"

health_check:
  endpoint: /-/healthy
  port: 9090
  interval: 10s
  timeout: 5s

secrets: []

web_ui:
  - name: prometheus
    port: 9090
    path: "/"
    description: "Prometheus query UI and target status"

terminal:
  shell: /bin/sh
  welcome_message: "Prometheus container."
  quick_actions:
    - label: "Check targets"
      command: "wget -qO- http://localhost:9090/api/v1/targets 2>/dev/null | head -100"
    - label: "Reload config"
      command: "wget -qO- --post-data='' http://localhost:9090/-/reload"
    - label: "Tail logs"
      command: "tail -f /proc/1/fd/1 /proc/1/fd/2"

connections:
  provides:
    - type: metrics-query
      port: 9090
      description: "PromQL query endpoint"
  accepts:
    - type: metrics
      config_schema:
        - key: scrape_interval
          label: "Scrape Interval"
          type: string
          default: "15s"

variants:
  default:
    description: "Single Prometheus instance"

template_mounts:
  - template: "prometheus.yml.j2"
    mount_path: "/etc/prometheus/prometheus.yml"

static_mounts: []
init_scripts: []
```

### Complete Manifest: Data Generator (tooling, single container, complex connections)
**File:** `components/data-generator/manifest.yaml` (key sections)

```yaml
id: data-generator
name: Data Generator
category: tooling
icon: data-generator
version: '1.0'
image: demoforge/data-generator:latest
build_context: .
description: Generates structured data (orders schema) in Parquet, JSON, or CSV format and pushes to MinIO.

resources:
  memory: 256m
  cpu: 0.25

ports: []

environment:
  S3_ENDPOINT: localhost:9000
  S3_ACCESS_KEY: minioadmin
  S3_SECRET_KEY: minioadmin
  S3_BUCKET: raw-data
  DG_WRITE_MODE: iceberg
  DG_FORMAT: parquet
  DG_FILE_SIZE_ROWS: '1000'
  DG_RATE: '1'
  DG_BATCH_SIZE: '10'
  DG_SCENARIO: ecommerce-orders
  DG_RATE_PROFILE: medium
  PARTITION_BY_DATE: 'true'
  KAFKA_BOOTSTRAP_SERVERS: ''
  KAFKA_TOPIC: ''

secrets:
- key: S3_ACCESS_KEY
  label: S3 Access Key
  default: minioadmin
- key: S3_SECRET_KEY
  label: S3 Secret Key
  default: minioadmin

web_ui: []

connections:
  provides:
  - type: structured-data
    port: 0
    description: Pushes structured data (Parquet/JSON/CSV) to an S3 target
    config_schema:
    - key: format
      label: File Format
      type: select
      options:
      - parquet
      - json
      - csv
      default: parquet
    - key: rows_per_file
      label: Rows per File
      type: number
      default: '1000'
    - key: rate
      label: Files per Minute
      type: number
      default: '1'
    - key: target_bucket
      label: Target Bucket
      type: string
      default: data-lake
  - type: kafka
    port: 0
  - type: file-push
    port: 0
  accepts:
  - type: s3
    config_schema:
    - key: bucket
      label: Target Bucket
      type: string
      default: raw-data
    - key: format
      label: File Format
      type: select
      options: [parquet, json, csv]
      default: parquet
    - key: rows_per_file
      label: Rows per File
      type: number
      default: '1000'
    - key: rate
      label: Files per Minute
      type: number
      default: '1'
  - type: kafka
    config_schema:
    - key: topic
      label: Kafka Topic
      type: string
      default: data-generator
```

### Manifest Python Schema
**File:** `backend/app/models/component.py`

```python
class ComponentManifest(BaseModel):
    """Full component manifest parsed from YAML."""
    id: str
    name: str
    category: str
    icon: str = ""
    version: str = ""
    image: str
    build_context: str = ""       # If set, path relative to component dir for docker build
    description: str = ""
    resources: ResourceDef = ResourceDef()
    ports: list[PortDef] = []
    environment: dict[str, str] = {}
    volumes: list[VolumeDef] = []
    command: list[str] = []
    entrypoint: list[str] = []
    health_check: HealthCheckDef | None = None
    secrets: list[SecretDef] = []
    web_ui: list[WebUIDef] = []
    terminal: TerminalDef = TerminalDef()
    connections: ConnectionsDef = ConnectionsDef()
    variants: dict[str, VariantDef] = {}
    template_mounts: list[TemplateMountDef] = []
    static_mounts: list[StaticMountDef] = []
    init_scripts: list[InitScriptDef] = []
    license_requirements: list[LicenseRequirement] = []
    image_size_mb: float | None = None
    shm_size: str | None = None
    resource_weight: str = "medium"      # "light" | "medium" | "heavy"
    depends_on_components: list[str] = []
    log_commands: list[LogCommandDef] = []
```

### Component Categories
- `storage` — Object storage, lake storage
- `analytics` — Query engines, data processing
- `streaming` — Message brokers, event systems
- `ai` — LLM inference, embeddings
- `database` — Relational and NoSQL databases
- `cloud` — Cloud platform services
- `infrastructure` (or `infra`) — Load balancers, proxies
- `tooling` — Utilities, generators, monitoring
- `observability` — Metrics, dashboards

### Properties Panel Fields
Defined via `connections.accepts[*].config_schema` and `connections.provides[*].config_schema`.

Each field:
```python
class ConnectionConfigField:
    key: str            # Identifier / env var name
    label: str          # Human-readable label
    type: str           # "string" | "number" | "boolean" | "select"
    default: str        # Default value
    required: bool      # Whether required
    options: list[str]  # For select type
    description: str    # Optional help text
```

---

## Section 2: Docker Compose Generation

### Location
**File:** `backend/app/engine/compose_generator.py` (~1435 lines)

### Core Generation Flow

1. **Cluster Expansion** — DemoCluster objects expand into synthetic DemoNode entries; NGINX LB auto-injected
2. **Network Setup** — networks from `demo.networks` mapped to Docker compose networks; default subnet `172.20.0.0/16`
3. **Service Generation** — per-node service definitions including image, env, resources, health checks, volumes
4. **Auto-Configuration** — edge-driven environment variable injection

### Manifest → Docker Compose Field Mapping

| Manifest Field | Docker Compose Field | Notes |
|---|---|---|
| `image` | `services[name].image` | Edition-aware for MinIO |
| `ports[*].container` | `services[name].expose` | Exposed to other containers |
| `environment` | `services[name].environment` | Merged with node config |
| `resources.memory` | `services[name].mem_limit` | Per-demo limits applied |
| `resources.cpu` | `services[name].cpus` | Per-demo limits applied |
| `volumes` | `services[name].volumes` | Named volumes created |
| `command` | `services[name].command` | Or variant.command if set |
| `health_check` | `services[name].healthcheck` | curl-based HTTP check |
| `template_mounts` | `services[name].volumes` | Rendered Jinja2 → bind mount |
| `static_mounts` | `services[name].volumes` | Bind mount from component dir |

### Edge → Environment Variable Mapping (`_edge_env_map`)

```python
_edge_env_map = {
    "target_bucket": "S3_BUCKET",
    "bucket": "S3_BUCKET",
    "format": "DG_FORMAT",
    "rows_per_file": "DG_FILE_SIZE_ROWS",
    "rate": "DG_RATE",
    "scenario": "DG_SCENARIO",
    "rate_profile": "DG_RATE_PROFILE",
    "documents_bucket": "DOCUMENTS_BUCKET",
    "audit_bucket": "AUDIT_BUCKET",
    "snapshot_bucket": "QDRANT_SNAPSHOT_BUCKET",
    "embedding_model": "EMBEDDING_MODEL",
    "chat_model": "CHAT_MODEL",
    "artifact_bucket": "MLFLOW_ARTIFACTS_BUCKET",
    "training_bucket": "TRAINING_BUCKET",
    "source_bucket": "LABELING_SOURCE_BUCKET",
    "output_bucket": "LABELING_OUTPUT_BUCKET",
    "milvus_bucket": "MINIO_BUCKET_NAME",
    "dag_bucket": "AIRFLOW_DAG_BUCKET",
    "log_bucket": "AIRFLOW_LOG_BUCKET",
    "sink_bucket": "S3_BUCKET",
    "sink_format": "S3_SINK_FORMAT",
    "flush_size": "S3_FLUSH_SIZE",
    "source_name": "DREMIO_SOURCE_NAME",
    "topic": "KAFKA_TOPIC",
}
```

### S3 Endpoint Resolution

When component A has an `s3`/`structured-data`/`file-push`/`aistor-tables` edge to component B:
- If B is MinIO node: `S3_ENDPOINT = http://{project_name}-{peer_id}:{port}`
- If B is cluster LB: `S3_ENDPOINT = http://{project_name}-{cluster_id}-lb:80`
- Credentials (`MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD`) copied from peer node config

### Example Generated Docker Compose (from template)

```yaml
services:
  demoforge-data-gen:
    image: demoforge/data-generator:latest
    environment:
      S3_ENDPOINT: "http://demoforge-minio-1:9000"
      S3_BUCKET: "raw-data"
      ICEBERG_CATALOG_URI: "http://demoforge-iceberg-rest:8181"
      ICEBERG_WAREHOUSE: "analytics"
    networks:
      demoforge-default:
        aliases: []
    depends_on:
      demoforge-minio-1:
        condition: service_healthy

  demoforge-trino:
    image: trinodb/trino:latest
    environment:
      AWS_ACCESS_KEY_ID: "minioadmin"
      AWS_SECRET_ACCESS_KEY: "minioadmin"
    volumes:
      - "/path/to/data/demoforge-trino/iceberg.properties:/etc/trino/catalog/iceberg.properties:ro"
    networks:
      demoforge-default:
        aliases: []
```

---

## Section 3: Connection System (Edges)

### All Connection Types
**File:** `frontend/src/types/index.ts`

```typescript
export type ConnectionType =
  | "s3" | "http" | "metrics" | "replication" | "site-replication"
  | "load-balance" | "data" | "metrics-query" | "tiering" | "file-push"
  | "cluster-replication" | "cluster-site-replication" | "cluster-tiering"
  | "iceberg-catalog" | "sql-query" | "s3-queue" | "spark-submit" | "hdfs"
  | "failover" | "llm-api" | "vector-db" | "mlflow-tracking" | "labeling-api"
  | "vector-db-milvus" | "etcd" | "workflow-api" | "llm-gateway"
  | "structured-data" | "kafka" | "kafka-connect" | "dremio-sql"
  | "dremio-flight" | "schema-registry" | "aistor-tables"
  | "inference-api" | "nginx-backend";
```

### Connection TypeScript Interfaces

```typescript
export interface ComponentEdgeData {
  connectionType: ConnectionType;
  network: string;
  label: string;
  status?: "active" | "idle" | "error";
  connectionConfig?: Record<string, any>;
  autoConfigure?: boolean;
}

export interface ConnectionProvides {
  type: string;
  port: number;
  description: string;
  path: string;
  config_schema: ConnectionConfigField[];
}

export interface ConnectionAccepts {
  type: string;
  config_schema: ConnectionConfigField[];
}

export interface ConnectionsDef {
  provides: ConnectionProvides[];
  accepts: ConnectionAccepts[];
}
```

### Connection Validation Logic
**File:** `frontend/src/stores/diagramStore.ts` (lines 67-201)

1. Extract `provides` types from source component
2. Extract `accepts` types from target component
3. Find intersection (forward direction)
4. Also check reverse: target provides → source accepts
5. If multiple valid types: show picker with direction labels
6. Special cases:
   - Cluster-to-cluster: always use cluster-level types
   - NGINX: always use `nginx-backend`
   - Cluster→Trino: requires `aistorTablesEnabled` flag

### Color Metadata
**File:** `frontend/src/lib/connectionMeta.ts`

```typescript
export const connectionColors: Record<string, string> = {
  s3: "#3b82f6",
  http: "#6b7280",
  metrics: "#22c55e",
  replication: "#a855f7",
  "site-replication": "#d946ef",
  "load-balance": "#f97316",
  "tiering": "#eab308",
  "file-push": "#06b6d4",
  "structured-data": "#059669",
  "llm-api": "#a855f7",
  "vector-db": "#06b6d4",
  "kafka": "#e11d48",
  "inference-api": "#76b900",
  // ... all 36 types
};
```

### How Components Receive Peer Connection Details

DNS: service names are `{project_name}-{node_id}` (Docker Compose service names)

Flow:
1. Edge `data-gen → minio-1` with type `s3`
2. Compose generator detects the s3 edge
3. Resolves `http://demoforge-minio-1:9000` as endpoint
4. Injects `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY` into `data-gen` environment

### Connection Constraints
- Manifest level: component declares `provides` and `accepts` — only compatible types can connect
- DiagramStore: validates intersection of types at draw time
- Special validations: cluster→Trino requires aistorTablesEnabled flag

---

## Section 4: Component Properties Panel

### Supported Field Types
**File:** `frontend/src/components/properties/ConfigSchemaForm.tsx`

| Type | UI Control | Notes |
|---|---|---|
| `string` | Text input | Plain text |
| `number` | Numeric input | |
| `boolean` | Checkbox | |
| `select` | Dropdown | Requires `options: string[]` |

### Property Flow Into Compose

**Path 1: Component-level config**
```
manifest.environment (defaults)
  ↓ merged with
demo.nodes[i].config (UI overrides)
  ↓
compose_generator → environment dict
  ↓
docker-compose.yml services[name].environment
```

**Path 2: Edge connection config**
```
manifest.connections.accepts[j].config_schema (field definitions)
  ↓ populated by user in edge UI
edge.connection_config (values)
  ↓ mapped through
_edge_env_map (key → env var name)
  ↓
docker-compose.yml services[name].environment
```

### Dynamic Field Visibility
**Not currently implemented.** All fields always shown. To add in future: `visible_if` field on `ConnectionConfigField` + condition logic in `ConfigSchemaForm`.

---

## Section 5: Component Lifecycle & State

### Demo-Level States
**File:** `frontend/src/types/index.ts`

```typescript
status: "not_deployed" | "stopped" | "deploying" | "running" | "stopping" | "error"
```

State machine:
```
not_deployed → deploy() → deploying → running
running → stop() → stopping → stopped
stopped → start() → deploying → running
stopped → destroy() → not_deployed
```

### Container-Level Health States

```typescript
export type HealthStatus = "healthy" | "starting" | "degraded" | "error" | "stopped";

export interface ContainerInstance {
  node_id: string;
  component_id: string;
  container_name: string;
  health: HealthStatus;
  web_uis: WebUILink[];
  has_terminal: boolean;
  quick_actions: QuickAction[];
  resource_usage?: Record<string, number>;
  networks: NetworkMembership[];
  credentials: CredentialInfo[];
  init_status: "pending" | "running" | "completed" | "failed" | "timeout";
  stopped_drives?: number[];
}
```

### Health Check in Manifest → Docker Compose

Manifest:
```yaml
health_check:
  endpoint: /minio/health/live
  port: 9000
  interval: 10s
  timeout: 5s
  start_period: 15s    # Optional; default 15s regular, 90s cluster
```

Generated Docker Compose:
```yaml
healthcheck:
  test: ["CMD-SHELL", "curl -sf http://localhost:9000/minio/health/live || wget -qO- http://localhost:9000/minio/health/live || bash -c 'echo > /dev/tcp/localhost/9000'"]
  interval: 10s
  timeout: 5s
  retries: 5
  start_period: 15s
```

### Web UI Declaration

Manifest:
```yaml
web_ui:
  - name: console
    port: 9001
    path: /
    description: MinIO Console — bucket management, monitoring, and admin
```

Runtime type:
```typescript
export interface WebUILink {
  name: string;
  proxy_url: string;    # "/api/proxy/{demoId}/{nodeId}/{port}{path}"
  description: string;
}
```

### Available Actions Per State

**running:** restart container, stop/start instance, open Web UI, open terminal, view logs, execute command, stop/start individual drives (MinIO only)  
**not_deployed:** deploy  
**stopped:** start, destroy

---

## Section 6: File/Volume Mounting

### Volume Types in Manifest

```python
class VolumeDef(BaseModel):
    name: str
    path: str       # Mount path inside container
    size: str = "1g"
```

Named volumes become: `{project_name}-{node_id}-{vol.name}:{vol.path}`

### Template Mounts (Jinja2)

**Manifest declaration:**
```yaml
template_mounts:
  - template: "nginx.conf.j2"
    mount_path: "/etc/nginx/conf.d/default.conf"
```

**Rendering in compose_generator.py:**
```python
def _render_templates(template_dir, node, demo, output_dir, project_name, manifest):
    env = Environment(loader=FileSystemLoader(template_dir))
    results = []
    for tm in manifest.template_mounts:
        template = env.get_template(tm.template)
        rendered = template.render(
            node=node, demo=demo, nodes=demo.nodes,
            edges=demo.edges, project_name=project_name,
        )
        host_path = os.path.join(output_dir, project_name, node.id, tm.template.removesuffix(".j2"))
        os.makedirs(os.path.dirname(host_path), exist_ok=True)
        with open(host_path, "w") as f:
            f.write(rendered)
        results.append((os.path.abspath(host_path), tm.mount_path))
    return results
```

Templates have access to: `node`, `demo`, `nodes` (all), `edges` (all), `project_name`

### Static Mounts

```yaml
static_mounts:
  - host_path: "provisioning/dashboards/dashboards.yml"
    mount_path: "/etc/grafana/provisioning/dashboards/dashboards.yml"
```

Bind-mounted read-only from `components/{id}/{host_path}` into the container.

### Template Files Found in Codebase

- `components/nginx/templates/nginx.conf.j2`
- `components/prometheus/templates/prometheus.yml.j2`
- `components/grafana/templates/datasources.yml.j2`
- `components/trino/templates/iceberg.properties.j2`
- `components/trino/templates/aistor-iceberg.properties.j2`
- `components/trino/templates/hive.properties.j2`
- `components/kong-gateway/templates/kong.yml.j2`
- `components/resilience-tester/templates/test.sh.j2`
- `components/litellm/templates/`
- `components/spark/templates/`
- `components/s3-file-browser/templates/`
- `components/file-generator/templates/`

### Where Rendered Files Live on Disk

Rendered at: `{output_dir}/{project_name}/{node_id}/{template_name_without_j2}`  
Mounted as bind volume (read-only) into container.

---

## Section 7: Current Component List

37 component manifests total at `components/{id}/manifest.yaml`:

| Component ID | Name | Category | Containers | Has Web UI |
|---|---|---|---|---|
| airflow | Apache Airflow | tooling | 1 | Yes (webserver) |
| clickhouse | ClickHouse | database | 1 | Yes |
| data-generator | Data Generator | tooling | 1 | No |
| dremio | Dremio | analytics | 1 | Yes |
| etcd | etcd | database | 1 | No |
| event-bridge | Event Bridge | streaming | 1 | No |
| event-producer | Event Producer | streaming | 1 | No |
| file-generator | File Generator | tooling | 1 | No |
| grafana | Grafana | observability | 1 | Yes |
| hdfs | HDFS | storage | 1 | Yes |
| iceberg-rest | Iceberg REST Catalog | storage | 1 | Yes |
| inference-client | Inference Client | ai | 1 | No |
| inference-sim | Inference Simulator | ai | 1 | No |
| jupyterlab | JupyterLab | tooling | 1 | Yes |
| kafka-connect-s3 | Kafka Connect S3 | streaming | 1 | Yes |
| kong-gateway | Kong Gateway | infrastructure | 1 | Yes |
| label-studio | Label Studio | tooling | 1 | Yes |
| litellm | LiteLLM | ai | 1 | Yes |
| metabase | Metabase | analytics | 1 | Yes |
| milvus | Milvus | database | 1 | Yes |
| minio | MinIO | storage | 1 (or N for cluster) | Yes (console) |
| mlflow | MLflow | tooling | 1 | Yes |
| ml-trainer | ML Trainer | ai | 1 | No |
| nessie | Nessie | storage | 1 | Yes |
| nginx | NGINX | infrastructure | 1 | Yes (status page) |
| ollama | Ollama | ai | 1 | No |
| prometheus | Prometheus | observability | 1 | Yes |
| qdrant | Qdrant | database | 1 | Yes |
| rag-app | RAG Application | ai | 1 | Yes |
| redpanda | Redpanda | streaming | 1 | No |
| redpanda-console | Redpanda Console | streaming | 1 | Yes |
| resilience-tester | Resilience Tester | tooling | 1 | No |
| s3-file-browser | S3 File Browser | tooling | 1 | Yes |
| solace-pubsub | Solace PubSub+ | streaming | 1 | Yes |
| spark | Apache Spark | analytics | 1 | Yes (UI) |
| superset | Apache Superset | analytics | 1 | Yes |
| trino | Trino | analytics | 1 | Yes |

---

## Section 8: Template System

### Template YAML Format
**File:** `demo-templates/bi-dashboard-lakehouse.yaml` (representative example)

```yaml
_template:
  name: Lakehouse quickstart
  tier: essentials                          # "essentials" | "advanced" | "experience"
  category: lakehouse
  tags: [metabase, bi, dashboard, iceberg, trino, lakehouse, visualization]
  description: 'Full BI stack: ...'
  objective: Demonstrate MinIO as the foundation...
  minio_value: MinIO is the single storage layer...
  estimated_resources:
    memory: 5GB
    cpu: 5
    containers: 7
  external_dependencies: []
  walkthrough:
  - step: Deploy the demo
    description: Click Deploy to start all components...
  se_guide:
    pitch: Show how MinIO + Iceberg + Trino creates...
    audience: Data engineers, analytics leads
    talking_points: [...]
    demo_flow:
    - step: 1
      action: Click Deploy and wait...
      say: This spins up the complete lakehouse stack...
    common_questions:
    - q: How does this compare to Snowflake?
      a: Same queryable lakehouse architecture...
  fa_ready: true
  updated_at: "2026-03-31"

id: template-bi-dashboard-lakehouse
name: BI Dashboard — Lakehouse
description: 'Full BI stack: MinIO → Iceberg → Trino → Metabase dashboards'

networks:
- name: default
  subnet: 172.20.0.0/16
  driver: bridge

nodes:
- id: data-gen
  component: data-generator
  variant: default
  position:
    x: -200
    y: 150
  display_name: Data Generator
  config: {}
- id: minio-1
  component: minio
  position:
    x: 100
    y: 150
  display_name: MinIO
  config:
    MINIO_ROOT_USER: minioadmin
    MINIO_ROOT_PASSWORD: minioadmin

clusters: []

edges:
- id: e-datagen-minio
  source: data-gen
  target: minio-1
  connection_type: s3
  network: default
  auto_configure: true
  label: Parquet data
  connection_config:
    bucket: raw-data

groups: []
sticky_notes: []

resources:
  default_memory: 512m
  default_cpu: 0.5
  max_memory: 2g
  max_cpu: 2.0
  total_memory: 8g
  total_cpu: 8.0
```

### Template TypeScript Interface

```typescript
export interface DemoTemplate {
  id: string;
  name: string;
  description: string;
  tier: "essentials" | "advanced" | "experience";
  category: string;
  tags: string[];
  objective: string;
  minio_value: string;
  mode?: "standard" | "experience";
  component_count: number;
  container_count: number;
  estimated_resources: { memory?: string; cpu?: number; containers?: number; };
  walkthrough: { step: string; description: string }[];
  external_dependencies: string[];
  has_se_guide: boolean;
  source: "builtin" | "synced" | "user";
  editable: boolean;
  customized?: boolean;
  origin?: string;
  saved_by?: string;
  validated?: boolean;
  archived?: boolean;
  updated_at?: string;
  changelog?: Array<{ date: string; summary: string; changed_by?: string }>;
}
```

### Template Directory Structure
- `demo-templates/` — 32+ built-in templates
- `demo-templates/synced-templates/` — Admin-synced templates
- `demo-templates/user-templates/` — User-created templates

### How Templates Create Demos

```typescript
// frontend/src/api/client.ts
export const createFromTemplate = (templateId: string) =>
  apiFetch<DemoSummary>(`/api/demos/from-template/${templateId}`, { method: "POST" });
```

Backend:
1. Load template YAML
2. Parse nodes, edges, clusters
3. Create new DemoDefinition
4. Save to demo database
5. Return DemoSummary

---

## Key Design Insights for "External System" Component

1. **No-container components are not currently modeled.** Every component has an `image` field. An "External System" component would either need a real sidecar/proxy container, or the schema would need extending to mark a component as `virtual: true` with no generated Docker service.

2. **Connection resolution is hardcoded per edge type in `compose_generator.py`.** Adding a new connection type (e.g., `external-api`) requires explicit handling in the auto-resolution section of the generator — it's not pluggable.

3. **Properties panel fields come from `connection_config` schemas only** — there is no separate "node properties" schema independent of connections. Node-level config keys that map to env vars are set directly in `demo.nodes[i].config` from the frontend, but the UI form for these is driven by the `secrets` list and some component-specific hardcoded panels.

4. **`image` is required in the Pydantic model with no default** — a virtual/reference component would need schema change or a sentinel image value.

5. **Jinja2 templates for config generation are powerful** — an External System component could use a template to generate a config file (e.g., `/etc/app/external.json`) that other components mount, but currently the template context is per-node, not cross-node.

6. **Connection colors and labels in `connectionMeta.ts` must be manually extended** for any new connection type to render correctly in the UI.
