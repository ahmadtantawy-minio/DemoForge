# DemoForge Template Management — Technical Investigation

Produced: 2026-03-30. Covers the 10 investigation areas requested in `claude-code-prompt-template-investigation.md`.

---

## 1. Template Files on Disk

Templates live in `demo-templates/` at the project root. There are **26 template YAML files** totaling ~4,809 lines. No other template directories exist — `backend/app/demo_templates/` and `templates/` do not exist.

```
demo-templates/
├── active-active-replication.yaml       (8,170 bytes)
├── automated-ml-pipeline.yaml           (2,989 bytes)
├── bi-dashboard-aistor-tables.yaml      (7,457 bytes)
├── bi-dashboard-lakehouse.yaml          (9,008 bytes)
├── complete-analytics.yaml              (7,154 bytes)
├── data-labeling-pipeline.yaml          (2,857 bytes)
├── dremio-lakehouse.yaml                (4,617 bytes)
├── enterprise-vector-search.yaml        (3,022 bytes)
├── experience-medallion.yaml            (5,328 bytes)
├── experience-stx-inference.yaml        (9,182 bytes)
├── full-analytics-pipeline.yaml         (5,680 bytes)
├── hadoop-migration.yaml                (3,290 bytes)
├── minio-ai-platform.yaml              (4,601 bytes)
├── ml-experiment-lab.yaml               (8,524 bytes)
├── multi-cluster-replication.yaml       (4,133 bytes)
├── multi-site-replication-3way.yaml     (6,164 bytes)
├── multi-site-replication.yaml          (6,891 bytes)
├── rag-pipeline.yaml                    (8,302 bytes)
├── realtime-analytics.yaml              (7,686 bytes)
├── site-replication-failover.yaml       (10,363 bytes)
├── site-replication.yaml                (4,328 bytes)
├── streaming-lakehouse.yaml             (4,531 bytes)
├── template-customer-360.yaml           (9,042 bytes)
├── template-smart-tiering.yaml          (10,064 bytes)
├── template-time-travel.yaml            (4,679 bytes)
└── versioned-data-lake.yaml             (3,869 bytes)
```

**Gotcha:** Template IDs are derived from the filename (strip `.yaml`), NOT from the `id` field inside the YAML. The `id` field inside the YAML is the *demo* ID that gets overwritten with a UUID when creating from the template.

---

## 2. How Templates Are Loaded

Templates are **read from disk on every request** — there is no registry, cache, or in-memory dict. The backend reads the `demo-templates/` directory each time `GET /api/templates` is called.

```python
# backend/app/api/templates.py

TEMPLATES_DIR = os.environ.get("DEMOFORGE_TEMPLATES_DIR", "./demo-templates")

def _safe_path(template_id: str) -> str | None:
    """Resolve template path and validate it stays within TEMPLATES_DIR."""
    path = os.path.join(TEMPLATES_DIR, f"{template_id}.yaml")
    real = os.path.realpath(path)
    if not real.startswith(os.path.realpath(TEMPLATES_DIR)):
        return None
    return path

def _load_template_raw(template_id: str) -> dict | None:
    path = _safe_path(template_id)
    if not path or not os.path.exists(path):
        return None
    with open(path) as f:
        return yaml.safe_load(f)

@router.get("/api/templates")
async def list_templates():
    templates = []
    if os.path.isdir(TEMPLATES_DIR):
        for fname in sorted(os.listdir(TEMPLATES_DIR)):
            if fname.endswith(".yaml"):
                try:
                    with open(os.path.join(TEMPLATES_DIR, fname)) as f:
                        raw = yaml.safe_load(f)
                    templates.append(_template_summary(fname, raw))
                except Exception:
                    pass
    return {"templates": templates}
```

The `list_templates` endpoint reads every YAML file in the directory, parses it, and builds a summary. Individual templates are loaded by `_load_template_raw(template_id)` which opens `{TEMPLATES_DIR}/{template_id}.yaml`.

**Gotcha:** Exceptions during parsing are silently swallowed (`except Exception: pass`), so a malformed template YAML will be silently excluded from the list.

---

## 3. Template Data Model

### Backend (Python)

There is **no dedicated Pydantic model for templates**. Templates reuse the `DemoDefinition` model with an extra `_template` metadata key in the raw YAML dict. The summary is built dynamically by the `_template_summary()` function:

```python
# backend/app/api/templates.py

def _template_summary(fname: str, raw: dict) -> dict:
    """Build a template summary from raw YAML data."""
    meta = raw.get("_template", {})
    template_id = fname.replace(".yaml", "")

    node_count = len(raw.get("nodes", []))
    container_count = node_count
    for cluster in raw.get("clusters", []):
        container_count += cluster.get("node_count", 0)

    resources = meta.get("estimated_resources", {})
    mode = meta.get("mode", raw.get("mode", "standard"))
    tier = meta.get("tier", "experience" if mode == "experience" else "essentials")

    return {
        "id": template_id,
        "name": meta.get("name", raw.get("name", "")),
        "description": meta.get("description", raw.get("description", "")),
        "tier": tier,
        "category": meta.get("category", "general"),
        "tags": meta.get("tags", []),
        "objective": meta.get("objective", ""),
        "minio_value": meta.get("minio_value", ""),
        "mode": mode,
        "component_count": node_count + len(raw.get("clusters", [])),
        "container_count": container_count,
        "estimated_resources": resources,
        "walkthrough": meta.get("walkthrough", []),
        "external_dependencies": meta.get("external_dependencies", []),
        "has_se_guide": bool(meta.get("se_guide")),
    }
```

The underlying demo definition model used when creating a demo from a template:

```python
# backend/app/models/demo.py

class DemoDefinition(BaseModel):
    id: str
    name: str
    description: str = ""
    mode: str = "standard"          # "standard" | "experience"
    networks: list[DemoNetwork] = [DemoNetwork(name="default")]
    nodes: list[DemoNode] = []
    edges: list[DemoEdge] = []
    groups: list[DemoGroup] = []
    sticky_notes: list[DemoStickyNote] = []
    annotations: list[DemoAnnotation] = []
    schematics: list[DemoSchematicNode] = []
    clusters: list[DemoCluster] = []
    resources: DemoResourceSettings = DemoResourceSettings()
```

### Frontend (TypeScript)

```typescript
// frontend/src/types/index.ts

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
  estimated_resources: {
    memory?: string;
    cpu?: number;
    containers?: number;
  };
  walkthrough: { step: string; description: string }[];
  external_dependencies: string[];
  has_se_guide: boolean;
}

export interface DemoTemplateDetail extends DemoTemplate {
  nodes: any[];
  edges: any[];
  clusters: any[];
  networks: any[];
  groups: any[];
}
```

**Gotcha:** The `DemoTemplateDetail` type uses `any[]` for nodes/edges/clusters/networks/groups — there's no typed frontend model for these nested structures within the template detail response.

---

## 4. Complete Template YAML Examples

### Smallest template — `data-labeling-pipeline.yaml` (2,857 bytes, 4 nodes, 3 edges)

```yaml
_template:
  name: AI data labeling pipeline
  tier: advanced
  category: ai
  tags:
  - label-studio
  - labeling
  - annotation
  - training-data
  description: Generate data into MinIO, label it in Label Studio, export annotations back to MinIO, train on labeled data.
  objective: Demonstrate MinIO as the data backbone for AI data preparation
  minio_value: Raw data, labeled annotations, and trained models all live in MinIO. Label Studio reads directly from and writes to MinIO buckets. No data ever leaves your infrastructure.
  estimated_resources:
    memory: 3GB
    cpu: 2
    containers: 4
  external_dependencies: []
  walkthrough:
  - step: Deploy and generate data
    description: Deploy the demo. Start data generator with 'Text classification' scenario.
  - step: Open Label Studio
    description: Open Label Studio UI. Create a project for text classification.
  - step: Connect MinIO as source
    description: Add S3 storage source pointing to the support-tickets bucket in MinIO.
  - step: Label some tickets
    description: Annotate 10-20 support tickets with categories. Label Studio reads from MinIO.
  - step: Export annotations
    description: Export labeled data back to the output bucket in MinIO.
  - step: Verify in MinIO
    description: Open MinIO Console — see raw data in source bucket, annotations in output bucket.
id: template-data-labeling-pipeline
name: AI Data Labeling Pipeline
description: Generate → Label in Label Studio → Export to MinIO → all data stays on your infrastructure
networks:
- name: default
  subnet: 172.20.0.0/16
  driver: bridge
nodes:
- id: minio-1
  component: minio
  variant: single
  position:
    x: 250
    y: 250
  display_name: MinIO
- id: data-gen
  component: data-generator
  variant: default
  position:
    x: -100
    y: 250
  display_name: Data Generator
  config:
    DG_SCENARIO: text-classification
    DG_FORMAT: json
- id: label-studio-1
  component: label-studio
  variant: default
  position:
    x: 600
    y: 100
  display_name: Label Studio
- id: jupyter-1
  component: jupyterlab
  variant: default
  position:
    x: 600
    y: 400
  display_name: JupyterLab
clusters: []
edges:
- id: e-datagen-minio
  source: data-gen
  target: minio-1
  connection_type: s3
  auto_configure: true
  label: Support tickets
  connection_config:
    bucket: labeling-data
    format: json
- id: e-label-minio
  source: label-studio-1
  target: minio-1
  connection_type: s3
  auto_configure: true
  label: Read data + write labels
  connection_config:
    source_bucket: labeling-data
    output_bucket: labeled-output
- id: e-jupyter-minio
  source: jupyter-1
  target: minio-1
  connection_type: s3
  auto_configure: true
  label: Train on labeled data
groups: []
sticky_notes: []
resources:
  default_memory: 512m
  default_cpu: 0.5
  total_memory: 4g
  total_cpu: 3.0
```

### Medium-complexity template — `site-replication.yaml` (4,328 bytes, 8 nodes, 10 edges)

```yaml
_template:
  name: Site replication (bidirectional)
  tier: advanced
  category: infrastructure
  tags:
  - site-replication
  - bidirectional
  - active-active
  - multi-site
  - high-availability
  - load-balancer
  - monitoring
  description: Two MinIO sites with full bidirectional site replication, each fronted by an NGINX load balancer. Any change on either site — buckets, objects, IAM policies — replicates automatically to
    the other.
  objective: Demonstrate MinIO's site replication feature where two fully independent MinIO deployments stay in complete sync, including metadata and IAM
  minio_value: MinIO site replication goes beyond bucket replication — it synchronizes the entire namespace including IAM users, policies, and bucket configurations, enabling true active-active multi-site
    deployments
  estimated_resources:
    memory: 5GB
    cpu: 5
    containers: 8
  external_dependencies: []
  walkthrough:
  - step: Deploy the demo
    description: Click Deploy to start both sites, each with two MinIO nodes behind NGINX, plus Prometheus and Grafana
  - step: Write to Site 1
    description: Connect to the Site 1 NGINX endpoint and create a bucket and upload objects
  - step: Verify on Site 2
    description: Open the Site 2 MinIO console and confirm the same bucket and objects appear automatically
  - step: Write to Site 2
    description: Upload different objects directly to Site 2 and verify they replicate back to Site 1
  - step: Test IAM sync
    description: Create a new IAM user or policy on Site 1 and confirm it appears on Site 2 — site replication syncs identity too
  - step: Simulate site failure
    description: Stop all Site 1 nodes and verify Site 2 serves all data independently with no data loss
  - step: Monitor replication health
    description: Review Grafana dashboards for replication throughput and lag between both sites
id: template-site-replication-bidirectional
name: Site replication (bidirectional)
description: Two MinIO sites with full bidirectional site replication. Each site has its own NGINX load balancer. Changes on either site replicate to the other.
networks:
- name: default
nodes:
- id: nginx-site1
  component: nginx
  variant: single
  position: {x: 100, y: 150}
  display_name: Site 1 LB
- id: minio-site1-a
  component: minio
  variant: single
  position: {x: 400, y: 50}
  display_name: Site 1 - Node A
- id: minio-site1-b
  component: minio
  variant: single
  position: {x: 400, y: 250}
  display_name: Site 1 - Node B
- id: nginx-site2
  component: nginx
  variant: single
  position: {x: 100, y: 550}
  display_name: Site 2 LB
- id: minio-site2-a
  component: minio
  variant: single
  position: {x: 400, y: 450}
  display_name: Site 2 - Node A
- id: minio-site2-b
  component: minio
  variant: single
  position: {x: 400, y: 650}
  display_name: Site 2 - Node B
- id: prometheus
  component: prometheus
  variant: single
  position: {x: 700, y: 350}
- id: grafana
  component: grafana
  variant: single
  position: {x: 900, y: 350}
edges:
- id: e-lb-s1a
  source: nginx-site1
  target: minio-site1-a
  connection_type: load-balance
  connection_config: {algorithm: round-robin, backend_port: '9000'}
- id: e-lb-s1b
  source: nginx-site1
  target: minio-site1-b
  connection_type: load-balance
  connection_config: {algorithm: round-robin, backend_port: '9000'}
- id: e-lb-s2a
  source: nginx-site2
  target: minio-site2-a
  connection_type: load-balance
  connection_config: {algorithm: round-robin, backend_port: '9000'}
- id: e-lb-s2b
  source: nginx-site2
  target: minio-site2-b
  connection_type: load-balance
  connection_config: {algorithm: round-robin, backend_port: '9000'}
- id: e-site-repl
  source: minio-site1-a
  target: minio-site2-a
  connection_type: site-replication
  connection_config: {replication_mode: two-way}
- id: e-m-s1a
  source: minio-site1-a
  target: prometheus
  connection_type: metrics
- id: e-m-s1b
  source: minio-site1-b
  target: prometheus
  connection_type: metrics
- id: e-m-s2a
  source: minio-site2-a
  target: prometheus
  connection_type: metrics
- id: e-m-s2b
  source: minio-site2-b
  target: prometheus
  connection_type: metrics
- id: e-grafana
  source: prometheus
  target: grafana
  connection_type: metrics-query
```

**Gotcha:** Templates have a dual structure — the `_template` key holds metadata (name, tier, category, tags, walkthrough, SE guide, etc.) while the rest of the YAML is a standard `DemoDefinition`. When creating a demo from a template, the `_template` key is stripped and the `id` is replaced with a UUID.

---

## 5. Runtime State — What Happens After a User Modifies the Diagram?

### Zustand Stores

**diagramStore** — holds React Flow nodes and edges in memory:

```typescript
// frontend/src/stores/diagramStore.ts

interface DiagramState {
  nodes: Node[];
  edges: Edge[];
  selectedNodeId: string | null;
  selectedEdgeId: string | null;
  componentManifests: Record<string, ConnectionsDef>;
  pendingConnection: PendingConnection | null;
  onNodesChange: OnNodesChange;
  onEdgesChange: OnEdgesChange;
  onConnect: (connection: Connection) => void;
  addNode: (node: Node) => void;
  setSelectedNode: (id: string | null) => void;
  setSelectedEdge: (id: string | null) => void;
  setNodes: (nodes: Node[]) => void;
  setEdges: (edges: Edge[]) => void;
  updateNodeHealth: (nodeId: string, health: string) => void;
  setComponentManifests: (manifests: Record<string, ConnectionsDef>) => void;
  setPendingConnection: (pending: PendingConnection | null) => void;
  completePendingConnection: (connectionType: string) => void;
}
```

**demoStore** — holds the list of demos, active demo ID, instances, and UI state:

```typescript
// frontend/src/stores/demoStore.ts

interface DemoState {
  demos: DemoSummary[];
  activeDemoId: string | null;
  instances: ContainerInstance[];
  activeView: ViewType;              // "diagram" | "control-plane"
  currentPage: PageKey;              // "home" | "designer" | "templates" | "images" | "settings"
  cockpitEnabled: boolean;
  walkthroughOpen: boolean;
  resilienceProbes: ResilienceProbe[];
  // ... setters
}
```

### Auto-Save Mechanism

Diagram state is **auto-saved to the backend via debounced PUT** whenever nodes or edges change. There is **no localStorage** involved.

```typescript
// frontend/src/components/canvas/DiagramCanvas.tsx (lines 258-265)

const debouncedSave = useRef(
  debounce((demoId: string, ns: Node[], es: Edge[]) => {
    const groups = ns.filter((n) => n.type === "group");
    const componentNodes = ns.filter((n) => n.type !== "group");
    saveDiagram(demoId, [...componentNodes, ...groups], es).catch(() => {});
  }, 500)
).current;
```

This calls `PUT /api/demos/{demo_id}/diagram` with the full nodes and edges arrays:

```typescript
// frontend/src/api/client.ts (lines 79-83)

export const saveDiagram = (id: string, nodes: any[], edges: any[]) =>
  apiFetch<any>(`/api/demos/${id}/diagram`, {
    method: "PUT",
    body: JSON.stringify({ nodes, edges }),
  });
```

The backend handler (`save_diagram` in `backend/app/api/demos.py:84-203`) converts React Flow nodes/edges back into `DemoNode`/`DemoEdge`/`DemoCluster`/`DemoGroup`/`DemoStickyNote` models and writes the full YAML file:

```python
# backend/app/api/demos.py

@router.put("/api/demos/{demo_id}/diagram")
async def save_diagram(demo_id: str, req: SaveDiagramRequest):
    demo = _load_demo(demo_id)
    if not demo:
        raise HTTPException(404, "Demo not found")
    # Experience mode demos are read-only — skip saving
    if demo.mode == "experience":
        return {"status": "saved"}
    # Convert React Flow nodes → DemoNodes (skip group/sticky/annotation-type nodes)
    demo.nodes = []
    demo.groups = []
    demo.sticky_notes = []
    demo.clusters = []
    # ... [converts each node type, builds edges] ...
    _save_demo(demo)
    return {"status": "saved"}
```

For Experience mode, there is a separate `PUT /api/demos/{demo_id}/layout` endpoint that only saves positions (not structure).

### What survives what:

- **Browser refresh**: Diagram reloads from backend YAML (last auto-saved state). Unsaved changes within the 500ms debounce window are lost.
- **Demo stop**: No effect on diagram state — the YAML file persists.
- **DemoForge restart**: Demo YAML files persist in `demos/` dir (volume-mounted). Running container state is recovered from Docker labels on startup. Diagram state is fully preserved.

**Gotcha:** Experience-mode demos skip the save endpoint entirely — the diagram is read-only from the template. Only layout positions (node x/y) can be saved.

---

## 6. Demo Lifecycle — Deploy Flow

### Full trace: User clicks Deploy → containers start

**1. Frontend — user clicks Deploy button**
```typescript
// frontend/src/components/toolbar/Toolbar.tsx
// Calls deployDemo(activeDemoId) which hits:
export const deployDemo = (id: string) =>
  apiFetch<{ demo_id: string; status: string }>(`/api/demos/${id}/deploy`, { method: "POST" });
```

**2. Backend — deploy endpoint**
```python
# backend/app/api/deploy.py

@router.post("/api/demos/{demo_id}/deploy", response_model=DeployResponse)
async def deploy(demo_id: str):
    demo = _load_demo(demo_id)              # Read YAML from disk
    # Guards: demo exists, has nodes, not already running, previous containers cleaned up
    # Validate required licenses
    progress = DeployProgress()              # Create progress tracker
    state.deploy_progress[demo_id] = progress
    running = await deploy_demo(demo, DATA_DIR, COMPONENTS_DIR, on_progress=on_progress)
    return DeployResponse(demo_id=demo_id, status=running.status)
```

**3. Engine — deploy_demo**
```python
# backend/app/engine/docker_manager.py

async def deploy_demo(demo: DemoDefinition, data_dir: str, components_dir: str, on_progress=None):
    async with _get_lock(demo.id):
        # Step 1: Generate docker-compose.yaml from DemoDefinition
        # Step 2: Create Docker network
        # Step 3: docker compose up -d
        # Step 4: Join backend to demo network (for proxy access)
        # Step 5: Wait for health checks
        # Step 6: Run init scripts (mc commands, etc.)
        # Step 7: Run edge automation (replication, tiering, etc.)
        # Register in state store, start health monitor
        return running_demo
```

**4. Frontend — polls progress**
```typescript
// Frontend polls GET /api/demos/{demo_id}/deploy/progress every ~1s
// Shows 7 real-time steps in the DeployProgress panel
```

**5. Frontend — polls instances after deploy**
```typescript
// App.tsx polls GET /api/demos/{demo_id}/instances every 5s
// Updates node health on diagram, edge config status, failover status
```

---

## 7. Template Creation/Update

### What exists today:

**Updating template metadata — YES, exists:**

```python
# backend/app/api/templates.py

@router.patch("/api/templates/{template_id}")
async def update_template(template_id: str, req: dict):
    raw = _load_template_raw(template_id)
    if not raw:
        raise HTTPException(404, "Template not found")
    meta = raw.get("_template", {})
    # Update allowed metadata fields ONLY
    if "name" in req: meta["name"] = req["name"]; raw["name"] = req["name"]
    if "description" in req: meta["description"] = req["description"]; raw["description"] = req["description"]
    if "objective" in req: meta["objective"] = req["objective"]
    if "minio_value" in req: meta["minio_value"] = req["minio_value"]
    raw["_template"] = meta
    _save_template_raw(template_id, raw)
    return _template_summary(f"{template_id}.yaml", raw)
```

This is exposed in the frontend TemplateGallery detail dialog with editable fields for description, objective, and MinIO value proposition.

**Creating a demo FROM a template — YES, exists:**

```python
# backend/app/api/templates.py

@router.post("/api/demos/from-template/{template_id}")
async def create_from_template(template_id: str):
    raw = _load_template_raw(template_id)
    demo_raw = {k: v for k, v in raw.items() if k != "_template"}  # Strip metadata
    demo_id = str(uuid.uuid4())[:8]
    demo_raw["id"] = demo_id
    demo = DemoDefinition(**demo_raw)
    # Save to demos directory
    path = os.path.join(DEMOS_DIR, f"{demo.id}.yaml")
    with open(path, "w") as f:
        yaml.dump(demo.model_dump(), f, default_flow_style=False, sort_keys=False)
    return DemoSummary(...)
```

**Saving a modified demo BACK as a new template — NO, does not exist.** There is no "Save as Template" or "Publish Template" feature. Users cannot create new templates from the UI. Templates are authored manually as YAML files in the `demo-templates/` directory.

**Demo export/import exists but is separate from templates:**

```python
# backend/app/api/demos.py

@router.get("/api/demos/{demo_id}/export")       # Downloads demo as YAML
@router.post("/api/demos/import")                 # Uploads YAML, creates demo
```

These export/import raw `DemoDefinition` YAML without the `_template` metadata block.

**Gotcha:** There is a `scripts/fix_template_connections.py` one-off migration script that bulk-updates template YAML files, but it's not part of the runtime system.

---

## 8. Docker Packaging

Templates are **volume-mounted, not baked into the Docker image**.

```dockerfile
# backend/Dockerfile — NO COPY for templates
FROM python:3.12-slim
# ... docker CLI install ...
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9210"]
```

```yaml
# docker-compose.yml — templates mounted read-only
services:
  backend:
    volumes:
      - ./components:/app/components:ro
      - ./demos:/app/demos
      - ./data:/app/data
      - ./demo-templates:/app/demo-templates:ro    # <-- HERE
    environment:
      - DEMOFORGE_TEMPLATES_DIR=/app/demo-templates
```

**Key facts:**
- Templates are mounted `:ro` (read-only) into the backend container
- Demos are mounted `:rw` (read-write)
- Components are mounted `:ro`
- Data directory is `:rw`
- Templates survive Docker rebuilds because they live on the host filesystem

**Gotcha:** The `PATCH /api/templates/{template_id}` endpoint writes to the template file, but the volume is mounted `:ro`. This means metadata updates will **fail silently or error** when running inside Docker. It only works in dev mode (`./demoforge.sh dev:be`) where the backend runs directly on the host. This is a bug — either the mount should be `:rw` or the PATCH endpoint should be disabled in Docker mode.

---

## 9. Any Existing Sync/Remote Logic

**No remote template sync exists.** There is no code for:
- Fetching templates from S3, GCS, or any remote URL
- Template hub or centralized template repository
- `TEMPLATE_SOURCE` or `TEMPLATE_URL` environment variables
- Any sync mechanism between DemoForge instances

The grep results for `sync|remote.*template|s3.*template|gcs|hub.*url|TEMPLATE_SOURCE|TEMPLATE_URL` returned zero relevant matches — all hits were for Docker state sync (`sync_with_docker`), Grafana dashboard sync, and MinIO replication sync (none related to template management).

---

## 10. Frontend Template Gallery

The template gallery is implemented in `frontend/src/components/templates/TemplateGallery.tsx` (614 lines). It is used in three places:

1. **TemplatesPage** (`frontend/src/pages/TemplatesPage.tsx`) — standalone page at `/templates`
2. **DemoSelectorModal** (`frontend/src/components/shared/DemoSelectorModal.tsx`) — "Templates" tab in the demo picker modal
3. **WelcomeScreen** (`frontend/src/components/shared/WelcomeScreen.tsx`) — template quick-create dropdown

### How the frontend fetches templates:

```typescript
// frontend/src/api/client.ts

export const fetchTemplates = () =>
  apiFetch<{ templates: DemoTemplate[] }>("/api/templates");

export const fetchTemplate = (templateId: string) =>
  apiFetch<DemoTemplateDetail>(`/api/templates/${templateId}`);

export const updateTemplate = (templateId: string, patch: {...}) =>
  apiFetch<DemoTemplate>(`/api/templates/${templateId}`, { method: "PATCH", body: JSON.stringify(patch) });

export const createFromTemplate = (templateId: string) =>
  apiFetch<DemoSummary>(`/api/demos/from-template/${templateId}`, { method: "POST" });
```

### Gallery features:

- **Tier tabs**: Essentials / Advanced / Experiences — filters templates by `tier` field
- **Category filter pills**: infrastructure, replication, analytics, lakehouse, ai, simulation, general
- **Template cards**: show name, description, category pill, tags, container count, memory/CPU estimates, "Create Demo" button
- **Detail dialog**: opens on card click, shows editable description/objective/minio_value, component list, walkthrough steps, "Create Demo" button
- **Loading skeletons**, **error state** with retry, **empty state**
- **SE Guide badge**: shown when `has_se_guide` is true (separate `GET /api/templates/{id}/guide` endpoint)

### What UI exists for creating/editing templates:

- **Editing metadata**: YES — description, objective, and minio_value are editable in the detail dialog with a "Save Changes" button (calls `PATCH /api/templates/{id}`)
- **Creating new templates**: NO — there is no UI for saving a demo as a template
- **Editing template topology**: NO — the template's nodes/edges/clusters are display-only in the detail dialog

### Template Gallery component signature and key state:

```typescript
// frontend/src/components/templates/TemplateGallery.tsx

interface TemplateGalleryProps {
  onCreateDemo: (demoId: string) => void;   // Callback when demo is created from template
}

export default function TemplateGallery({ onCreateDemo }: TemplateGalleryProps) {
  const [templates, setTemplates] = useState<DemoTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [selectedTemplate, setSelectedTemplate] = useState<DemoTemplateDetail | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [creating, setCreating] = useState<string | null>(null);
  const [loadingDetail, setLoadingDetail] = useState<string | null>(null);
  const [activeCategory, setActiveCategory] = useState<string | null>(null);
  const [activeTier, setActiveTier] = useState<string>("essentials");

  // Editable fields in the detail dialog
  const [editDescription, setEditDescription] = useState("");
  const [editObjective, setEditObjective] = useState("");
  const [editMinioValue, setEditMinioValue] = useState("");
  const [dirty, setDirty] = useState(false);
  // ...
}
```

Templates are fetched once on mount via `useEffect` → `fetchTemplates()`. No periodic refresh.

---

## Summary of Key Gotchas

1. **Template IDs are filenames**, not the `id` field in the YAML. The YAML `id` field is the demo seed ID that gets replaced with a UUID on create.
2. **No caching** — every `GET /api/templates` reads all 26 YAML files from disk.
3. **`:ro` mount vs PATCH endpoint conflict** — the `PATCH /api/templates/{id}` endpoint writes to disk, but templates are mounted read-only in Docker.
4. **No "Save as Template"** — users cannot create templates from modified demos. Templates are hand-authored YAML.
5. **No remote sync** — templates are purely local files. No hub, no S3, no remote fetch.
6. **Experience mode is read-only** — `save_diagram` is a no-op for experience-mode demos (only position changes via `save_layout` are persisted).
7. **Silent parse failures** — malformed template YAML files are silently excluded from the list.
8. **Walkthrough lookup by name** — `GET /api/demos/{id}/walkthrough` finds the matching template by comparing `demo.name == template.name`, which breaks if the user renames the demo.
