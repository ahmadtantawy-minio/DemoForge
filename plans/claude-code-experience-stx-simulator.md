# Claude Code Instruction: STX/CMX Inference Memory Simulator ("Experience" Template)

Work in a git worktree:

```
git worktree add ../demoforge-experience feature/experience-templates
cd ../demoforge-experience
```

## What this is

A new category of DemoForge template called an **Experience** — a fixed, read-only, simulation-driven demo that can't be modified by the user. Unlike regular templates where users drag components, edit properties, and build custom topologies, an Experience is a curated, narrated walkthrough with annotations on the canvas and a dedicated simulation UI.

The first Experience is the **"NVIDIA STX: Inside Inference Memory"** simulator, which visualizes how KV cache blocks flow through the 5-tier memory hierarchy (GPU HBM → CPU DRAM → local NVMe → MinIO CMX → enterprise storage) during LLM inference, and demonstrates why the G3.5 context memory tier (MinIO AIStor on BlueField-4) dramatically improves throughput.

Before making changes, read:
- `components/minio/manifest.yaml` — manifest schema
- `frontend/src/components/canvas/nodes/ComponentNode.tsx` — node rendering
- `frontend/src/components/canvas/nodes/StickyNoteNode.tsx` — existing annotation pattern
- `frontend/src/stores/diagramStore.ts` — node/edge state management
- `frontend/src/stores/demoStore.ts` — demo state, active view
- `frontend/src/types/index.ts` — all type definitions
- `demo-templates/bi-dashboard-lakehouse.yaml` — template structure reference
- `backend/app/models/demo.py` — DemoDefinition, DemoNode, DemoStickyNote models

---

## Part 1: The "Experience" template type

### 1.1 Backend: new template mode

File: `backend/app/models/demo.py`

Add a `mode` field to the template metadata and demo definition:

```python
class DemoDefinition(BaseModel):
    id: str
    name: str
    description: str = ""
    mode: str = "standard"          # NEW: "standard" | "experience"
    networks: list[DemoNetwork] = [DemoNetwork(name="default")]
    nodes: list[DemoNode] = []
    edges: list[DemoEdge] = []
    groups: list[DemoGroup] = []
    sticky_notes: list[DemoStickyNote] = []
    annotations: list[DemoAnnotation] = []   # NEW: rich text annotations
    clusters: list[DemoCluster] = []
    resources: DemoResourceSettings = DemoResourceSettings()
```

Add the `DemoAnnotation` model:

```python
class DemoAnnotation(BaseModel):
    id: str
    position: NodePosition                   # x, y on canvas
    width: int = 300                         # Width in pixels
    title: str = ""                          # Bold heading
    body: str = ""                           # Markdown-like body text (support **bold**, line breaks)
    style: str = "info"                      # "info" | "callout" | "warning" | "step"
    step_number: int | None = None           # For "step" style — shows a numbered circle
    pointer_target: str | None = None        # Node ID to draw a leader line to (optional)
    collapsed: bool = False                  # Can be collapsed to just the title
```

### 1.2 Backend: experience template metadata

In the `_template` block, add:

```yaml
_template:
  mode: "experience"                # NEW — marks this as read-only
  # ... rest of template metadata
```

The template loader should read this and set `mode: "experience"` on the loaded demo definition.

### 1.3 Frontend: experience mode enforcement

File: `frontend/src/stores/diagramStore.ts`

When the loaded demo has `mode === "experience"`:

- `onNodesChange`: block all changes except viewport pan/zoom. No drag, no delete, no add.
- `onEdgesChange`: block all changes.
- `onConnect`: no-op.
- `addNode`: no-op.
- Node selection still works (for viewing properties), but the properties panel shows read-only info.

Add a computed flag:

```typescript
isExperience: () => {
  const demo = useDemoStore.getState().demos.find(d => d.id === useDemoStore.getState().activeDemoId);
  return demo?.mode === "experience";
},
```

File: `frontend/src/components/properties/PropertiesPanel.tsx`

When `isExperience`:
- Hide all edit controls (dropdowns, text inputs, config forms)
- Show component info as read-only text
- Show a prominent "Open Simulation" button for the inference-sim node
- Hide "Delete node", "Change variant", and any modification controls

File: `frontend/src/components/canvas/DiagramCanvas.tsx` (or wherever the toolbar lives)

When `isExperience`:
- Hide the component palette / sidebar (can't add new components)
- Hide the "Add node" button
- Show a banner: "Experience mode — this simulation cannot be modified"
- Keep Deploy/Stop buttons functional
- Keep the view toggle (diagram / control plane) functional

### 1.4 Frontend: AnnotationNode — new React Flow node type

File: `frontend/src/components/canvas/nodes/AnnotationNode.tsx`

A new node type for rich text annotations on the canvas. These are not editable in Experience mode — they're part of the curated narrative.

```tsx
export default function AnnotationNode({ id, data }: NodeProps) {
  const annotationData = data as AnnotationNodeData;
  const isExperience = useDiagramStore(s => s.isExperience());

  return (
    <div
      className={`
        rounded-lg border-0 px-4 py-3 max-w-[${annotationData.width || 300}px]
        ${styleClasses[annotationData.style]}
        ${isExperience ? 'pointer-events-none select-text' : ''}
      `}
      style={{ width: annotationData.width || 300 }}
    >
      {/* Step number badge */}
      {annotationData.style === "step" && annotationData.stepNumber && (
        <div className="w-6 h-6 rounded-full bg-primary text-primary-foreground
          flex items-center justify-center text-xs font-semibold mb-2">
          {annotationData.stepNumber}
        </div>
      )}

      {/* Title */}
      {annotationData.title && (
        <div className="text-sm font-semibold mb-1">{annotationData.title}</div>
      )}

      {/* Body — render with basic formatting */}
      {annotationData.body && (
        <div className="text-xs text-muted-foreground leading-relaxed whitespace-pre-line">
          {renderAnnotationBody(annotationData.body)}
        </div>
      )}

      {/* No handles — annotations don't connect */}
    </div>
  );
}

// Style variants
const styleClasses = {
  info: "bg-blue-50/80 dark:bg-blue-950/30 border-l-2 border-l-blue-400",
  callout: "bg-amber-50/80 dark:bg-amber-950/30 border-l-2 border-l-amber-400",
  warning: "bg-red-50/80 dark:bg-red-950/30 border-l-2 border-l-red-400",
  step: "bg-background/90 border border-border shadow-sm",
};

// Basic text formatting: **bold** and line breaks
function renderAnnotationBody(text: string) {
  return text.split('\n').map((line, i) => (
    <span key={i}>
      {line.split(/(\*\*.*?\*\*)/).map((part, j) =>
        part.startsWith('**') && part.endsWith('**')
          ? <strong key={j} className="font-medium text-foreground">{part.slice(2, -2)}</strong>
          : part
      )}
      {i < text.split('\n').length - 1 && <br />}
    </span>
  ));
}
```

Data shape — add to `frontend/src/types/index.ts`:

```typescript
export interface AnnotationNodeData {
  title: string;
  body: string;
  style: "info" | "callout" | "warning" | "step";
  stepNumber?: number;
  width?: number;
  pointerTarget?: string;    // Node ID to draw a dashed leader line to
}
```

Register the new node type in the React Flow `nodeTypes` map (wherever `ComponentNode`, `ClusterNode`, `GroupNode`, `StickyNoteNode` are registered):

```typescript
const nodeTypes = {
  component: ComponentNode,
  cluster: ClusterNode,
  group: GroupNode,
  sticky: StickyNoteNode,
  annotation: AnnotationNode,    // NEW
};
```

### 1.5 Frontend: leader lines from annotations to nodes

When an annotation has `pointerTarget` set, draw a dashed leader line from the annotation to the target node. This is a custom edge rendered in the React Flow edges layer.

Add a new edge type `annotation-pointer`:

```typescript
// In the edge types map
const edgeTypes = {
  animated: AnimatedDataEdge,
  "annotation-pointer": AnnotationPointerEdge,   // NEW
};
```

The `AnnotationPointerEdge` is a simple dashed line with no arrowhead and no label — just a visual connection from the annotation to the thing it's describing. Use `stroke-dasharray: "4 3"`, `stroke-width: 0.5`, `color: var(--color-text-tertiary)`, `opacity: 0.5`.

### 1.6 Backend: template loader for annotations

File: `backend/app/api/templates.py` (or wherever templates are loaded)

When loading a template, convert `annotations` entries into React Flow nodes of type `annotation`:

```python
for ann in demo.annotations:
    node = {
        "id": ann.id,
        "type": "annotation",
        "position": {"x": ann.position.x, "y": ann.position.y},
        "data": {
            "title": ann.title,
            "body": ann.body,
            "style": ann.style,
            "stepNumber": ann.step_number,
            "width": ann.width,
            "pointerTarget": ann.pointer_target,
        },
        "draggable": demo.mode != "experience",
        "selectable": True,
        "deletable": demo.mode != "experience",
    }
```

And create annotation-pointer edges:

```python
for ann in demo.annotations:
    if ann.pointer_target:
        edges.append({
            "id": f"ann-{ann.id}-ptr",
            "source": ann.id,
            "target": ann.pointer_target,
            "type": "annotation-pointer",
        })
```

---

## Part 2: The inference-sim container

### 2.1 Component manifest — `components/inference-sim/manifest.yaml`

```yaml
id: inference-sim
name: Inference Memory Simulator
category: simulation
icon: inference-sim
version: "1.0"
image: demoforge/inference-sim:latest
build_context: "."
description: "Simulates LLM inference KV cache lifecycle across the NVIDIA STX 5-tier memory hierarchy"

resources:
  memory: "512m"
  cpu: 0.5

ports:
  - name: web
    container: 8095
    protocol: tcp

environment:
  MINIO_ENDPOINT_G35: ""
  MINIO_ENDPOINT_G4: ""
  MINIO_ACCESS_KEY: "minioadmin"
  MINIO_SECRET_KEY: "minioadmin"
  KV_BUCKET_HOT: "kv-cache-hot"
  KV_BUCKET_WARM: "kv-cache-warm"
  KV_BUCKET_COLD: "kv-cache-cold"
  G1_CAPACITY_GB: "80"
  G2_CAPACITY_GB: "512"
  G3_CAPACITY_GB: "4000"
  G35_CAPACITY_GB: "50000"
  SIM_DEFAULT_USERS: "50"
  SIM_DEFAULT_CONTEXT: "32768"

volumes: []

command: []

health_check:
  endpoint: /health
  port: 8095
  interval: 10s
  timeout: 5s
  start_period: "10s"

secrets:
  - key: MINIO_ACCESS_KEY
    label: "MinIO Access Key"
    default: "minioadmin"
  - key: MINIO_SECRET_KEY
    label: "MinIO Secret Key"
    default: "minioadmin"

web_ui:
  - name: simulation
    port: 8095
    path: /
    description: "STX/CMX inference memory simulator — interactive visualization"

terminal:
  shell: /bin/sh
  welcome_message: "Inference Memory Simulator."
  quick_actions:
    - label: "Status"
      command: "wget -qO- http://localhost:8095/status 2>/dev/null || echo 'Not ready'"
    - label: "Start simulation"
      command: "wget -qO- --post-data='' http://localhost:8095/sim/start 2>/dev/null || echo 'Failed'"
    - label: "Stop simulation"
      command: "wget -qO- --post-data='' http://localhost:8095/sim/stop 2>/dev/null || echo 'Failed'"

connections:
  provides: []
  accepts:
    - type: s3
      config_schema:
        - key: tier_role
          label: "Storage Tier Role"
          type: select
          options: ["g35-cmx", "g4-archive"]
          default: "g35-cmx"
          description: "Which tier this MinIO instance represents"

variants:
  default:
    description: "Full simulation with visualization UI"

template_mounts: []
static_mounts: []

init_scripts:
  - command: "sh -c 'until wget -qO- http://localhost:8095/health 2>/dev/null | grep -q ok; do sleep 2; done; echo Simulator ready'"
    wait_for_healthy: true
    timeout: 30
    order: 1
    description: "Wait for simulator to initialize"
```

### 2.2 Build the inference-sim container

Create `components/inference-sim/`:

```
components/inference-sim/
  manifest.yaml
  Dockerfile
  requirements.txt
  app/
    main.py                   # FastAPI app
    config.py                 # Settings from env vars
    simulation/
      engine.py               # Core simulation loop
      kv_block_manager.py     # Tier management, eviction, promotion policies
      session_manager.py      # User session lifecycle
      request_generator.py    # Simulated inference requests
      minio_backend.py        # Real S3 operations for G3.5/G4 tiers
      metrics.py              # Prometheus-compatible metrics
    models.py                 # Pydantic models for API
    static/
      index.html              # Full simulation visualization UI
```

#### `Dockerfile`

```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends wget && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8095"]
```

#### `requirements.txt`

```
fastapi==0.115.12
uvicorn[standard]==0.34.0
boto3==1.35.0
pydantic==2.11.1
prometheus-client==0.21.0
websockets==13.1
```

#### API endpoints

```
GET  /health
  → {"status": "ok", "minio_g35_connected": bool, "minio_g4_connected": bool}

GET  /status
  → Full simulation state: tiers (used/capacity), sessions, metrics, config

POST /sim/start
  Body: {users: 50, context_tokens: 32768, speed: 5, cmx_enabled: true}
  → Starts the simulation loop

POST /sim/stop
  → Stops the simulation loop

POST /sim/config
  Body: {users?, context_tokens?, speed?, cmx_enabled?}
  → Updates config while running (hot-reconfigure)

WS   /sim/stream
  → WebSocket that pushes state updates at 5Hz for the visualization UI
  → Each message: {tiers: {...}, sessions: [...], metrics: {...}, tick: N}

GET  /metrics
  → Prometheus format: inference_sim_gpu_utilization, inference_sim_ttft_ms,
     inference_sim_cache_hit_rate, inference_sim_recomputations_total,
     inference_sim_s3_operations_total, inference_sim_kv_blocks_active
```

#### Simulation engine logic

**`simulation/engine.py`** — main simulation loop running in an asyncio task:

Each tick (200ms real-time, multiplied by speed factor):

1. **Generate new sessions** — with configurable arrival rate. Each session gets a unique ID, a KV cache block sized proportionally to context length (`context_tokens / 1024 * 2.5 MB`).

2. **Session lifecycle** — each session cycles through: active (generating tokens, KV cache in G1) → idle (user paused, start eviction timer) → returning (user comes back, need to prestage KV cache) → terminated (session ends, KV cache can be freed).

3. **Eviction cascade** — when a tier exceeds capacity, the block manager evicts the coldest idle session's blocks to the next tier down. Policy: LRU within each tier. The cascade: G1 → G2 → G3 → G3.5 → G4. If CMX is disabled, G3.5 is skipped entirely.

4. **Promotion (prestaging)** — when a session becomes active again, its KV blocks are promoted back to G1. The latency of this promotion depends on which tier the blocks are in:
   - G2 → G1: ~100us (simulated as instant)
   - G3 → G1: ~500us (simulated as 1 tick)
   - G3.5 → G1: ~2ms (simulated as 2 ticks) — this is the CMX path
   - G4 → G1: ~50ms (simulated as 10 ticks) — slow, noticeable stall
   - Recomputation (no cache): ~500ms (simulated as 50 ticks) — very slow

5. **Real MinIO operations** — when blocks evict to G3.5 or G4, the simulator writes actual S3 objects to the configured MinIO instance. When blocks promote back from G3.5/G4, it reads them. Object key pattern: `sessions/{session_id}/block-{seq}.kv`. Object size: the simulated KV block size (scaled down — e.g., 100KB per block instead of 50MB, to be laptop-friendly). The S3 operations are real — the audience can see them in MinIO Console.

6. **Metrics** — computed per tick and exposed via the `/metrics` endpoint and WebSocket stream:
   - GPU utilization: `G1_used / G1_capacity * 100`
   - TTFT (time to first token): simulated based on where the returning session's KV blocks are
   - Cache hit rate: `promotions_from_cache / (promotions_from_cache + recomputations)`
   - S3 operations per second: actual PUT/GET count
   - Recomputation count: sessions that had to recompute because their KV cache was lost

**`simulation/kv_block_manager.py`** — the tier state machine:

```python
class Tier:
    name: str              # "G1", "G2", "G3", "G3.5", "G4"
    capacity_gb: float     # Configurable
    used_gb: float = 0
    blocks: dict[str, KVBlock] = {}   # session_id → block
    latency_ms: float      # Simulated access latency

class KVBlock:
    session_id: str
    size_gb: float
    tier: str
    last_access: float     # Timestamp
    idle_ticks: int = 0

class KVBlockManager:
    tiers: dict[str, Tier]
    cmx_enabled: bool

    def evict(self, from_tier: str) -> str | None:
        """Evict coldest block from tier, return session_id or None."""
        # Find coldest idle block
        # Move to next tier (skip G3.5 if CMX disabled)
        # If moving to G3.5 or G4, trigger real S3 PUT
        # Return session_id of evicted block

    def promote(self, session_id: str, to_tier: str = "G1") -> int:
        """Promote session's blocks back to G1. Return simulated latency in ticks."""
        # Find which tier holds this session's blocks
        # If G3.5 or G4, trigger real S3 GET
        # Move blocks to G1
        # Return latency based on source tier

    def enforce_capacity(self):
        """Cascade evictions through all tiers to stay within capacity."""
```

**`simulation/minio_backend.py`** — real S3 operations:

```python
class MinIOBackend:
    def __init__(self, endpoint, access_key, secret_key, bucket):
        self.s3 = boto3.client('s3', endpoint_url=endpoint, ...)

    def put_kv_block(self, session_id: str, block_seq: int, data: bytes, metadata: dict):
        """Write a KV cache block to MinIO. Returns latency in ms."""
        key = f"sessions/{session_id}/block-{block_seq}.kv"
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=data,
            Metadata={
                "tier": metadata.get("tier", "g35"),
                "session": session_id,
                "tokens": str(metadata.get("tokens", 0)),
                "created": datetime.utcnow().isoformat(),
            })

    def get_kv_block(self, session_id: str, block_seq: int) -> bytes:
        """Read a KV cache block from MinIO."""
        key = f"sessions/{session_id}/block-{block_seq}.kv"
        return self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def delete_session(self, session_id: str):
        """Delete all blocks for a terminated session."""
        # List and delete all objects under sessions/{session_id}/

    def get_stats(self) -> dict:
        """Return bucket stats: object count, total size."""
```

Generate synthetic KV block data: random bytes of the configured block size (default 100KB — small enough to be laptop-friendly, large enough to be visible in MinIO Console).

### 2.3 Visualization UI — `app/static/index.html`

A single HTML file with embedded CSS and JS. This is the heart of the Experience — what the audience actually sees.

**Structure (top to bottom):**

**Header bar:**
- Title: "NVIDIA STX: Inside inference memory"
- Status badge: running/stopped
- Subtitle: "Simulating KV cache lifecycle across the 5-tier memory hierarchy"

**Tier legend** — horizontal row of colored dots with labels: G1 GPU HBM, G2 CPU DRAM, G3 local NVMe, G3.5 MinIO CMX, G4 enterprise

**Main layout — two columns:**

**Left column (60% width): tier visualization**
- Five horizontal tier bars stacked vertically, tallest (G1) at top
- Each bar shows: tier label on left, fill level as colored bar, percentage on right, capacity on far right
- The G3.5 bar is visually highlighted (thicker border, slightly larger) when CMX is enabled, and faded/grayed when disabled
- **Animated blocks**: small colored rectangles (6x28px) positioned inside each tier bar, representing individual KV cache blocks. When a block evicts, it animates (CSS transition) from its position in the source tier to a position in the target tier. Use `position: absolute` within each tier bar and animate `top` and `left` with `transition: all 0.4s ease-in-out`.
- Below the tiers: **session swimlane** — last 15 active sessions shown as horizontal rows. Each row is a bar colored by which tier holds that session's KV cache. Active sessions pulse slightly. Idle sessions fade.

**Right column (40% width): metrics + controls**

Metrics section (6 cards):
- GPU utilization (percentage, colored green >80%, amber 50-80%, red <50%)
- Avg TTFT (milliseconds, colored green <100ms, amber 100-300ms, red >300ms)
- Cache hit rate (percentage, green)
- Active KV blocks (count)
- Recomputations (count, red — this is the "bad" metric)
- S3 ops/sec (count, green — shows MinIO is working)

Controls section:
- G3.5 CMX toggle (prominent — this is the demo's key toggle)
- Users slider (10 — 500)
- Context length dropdown (4K, 16K, 32K, 64K, 128K)
- Simulation speed (1x, 5x, 20x)
- Start/Stop button
- Reset button (clears all state, deletes MinIO objects)

**Bottom section: scenario buttons**

Pre-built scenario buttons that configure the simulation for specific demo stories:

- **"Multi-turn chat burst"** — 200 users, 32K context, many idle/return cycles. Shows CMX absorbing the bursty pattern.
- **"Agentic deep reasoning"** — 20 users, 128K context, long-lived sessions. Shows massive KV cache that doesn't fit in G1/G2 without CMX.
- **"Scale-out stress test"** — 500 users, 16K context, high churn. Shows CMX preventing recomputation at scale.

Each button sets the controls and starts the simulation in one click.

**WebSocket connection:**

The UI connects to `ws://{host}/sim/stream` and receives state updates at 5Hz. Each message contains the full simulation state: tier fill levels, per-session tier assignments, metrics. The UI renders smoothly by interpolating between updates.

**CSS animation for block movement:**

When a block changes tier, the UI creates a temporary "flying block" element that animates from the source tier position to the destination tier position using CSS `transition`. After the transition completes, the flying block is removed and the block appears in its new tier. This creates the visual effect of blocks physically flowing between tiers.

```javascript
function animateBlockMove(blockId, fromTier, toTier) {
  const fromBar = document.getElementById(`tier-${fromTier}`);
  const toBar = document.getElementById(`tier-${toTier}`);
  const fromRect = fromBar.getBoundingClientRect();
  const toRect = toBar.getBoundingClientRect();

  const flyer = document.createElement('div');
  flyer.className = 'block-flyer';
  flyer.style.cssText = `
    position: fixed; width: 6px; height: 28px; border-radius: 2px;
    background: ${tierColors[fromTier]};
    left: ${fromRect.right - 10}px; top: ${fromRect.top + 4}px;
    transition: all 0.4s ease-in-out; z-index: 100;
  `;
  document.body.appendChild(flyer);

  requestAnimationFrame(() => {
    flyer.style.left = `${toRect.left + 10}px`;
    flyer.style.top = `${toRect.top + 4}px`;
    flyer.style.background = tierColors[toTier];
  });

  setTimeout(() => flyer.remove(), 450);
}
```

---

## Part 3: Edge resolution for tier_role

File: `backend/app/engine/compose_generator.py`

When an `s3` edge from `inference-sim` to a MinIO node has `tier_role` in its config:

```python
if node_component == "inference-sim" and peer_component in ("minio", "minio-aistore"):
    edge_cfg = edge.connection_config or {}
    tier_role = edge_cfg.get("tier_role", "g35-cmx")
    peer_endpoint = f"http://{project_name}-{peer_id}:9000"

    if tier_role == "g35-cmx":
        env["MINIO_ENDPOINT_G35"] = peer_endpoint
    elif tier_role == "g4-archive":
        env["MINIO_ENDPOINT_G4"] = peer_endpoint

    env["MINIO_ACCESS_KEY"] = peer_env.get("MINIO_ROOT_USER", "minioadmin")
    env["MINIO_SECRET_KEY"] = peer_env.get("MINIO_ROOT_PASSWORD", "minioadmin")
```

---

## Part 4: The Experience template

### `demo-templates/experience-stx-inference.yaml`

```yaml
_template:
  name: "NVIDIA STX: Inside Inference Memory"
  mode: "experience"
  category: "simulation"
  tags: ["nvidia", "stx", "cmx", "inference", "kv-cache", "memory-hierarchy", "bluefield-4"]
  description: "Interactive simulation of the NVIDIA STX/CMX inference memory architecture. Visualizes how KV cache blocks flow through 5 memory tiers during LLM inference, and demonstrates why the G3.5 context memory tier (MinIO AIStor) dramatically improves throughput."
  objective: "Explain the NVIDIA STX architecture and demonstrate MinIO AIStor's role as the G3.5 context memory tier for agentic AI inference"
  minio_value: "MinIO AIStor operates as the G3.5 context memory storage tier in the NVIDIA STX architecture, providing petabyte-scale, high-bandwidth KV cache storage that sits between local NVMe and enterprise storage. It enables up to 5x token throughput by eliminating costly KV cache recomputation."
  estimated_resources:
    memory: "2GB"
    cpu: 2
    containers: 4
  walkthrough:
    - step: "Deploy the simulation"
      description: "Click Deploy. The simulator, two MinIO instances (G3.5 and G4), and Prometheus start."
    - step: "Open the simulation"
      description: "Click 'Simulation' on the inference-sim node. The interactive visualization opens."
    - step: "Start with CMX enabled"
      description: "Click 'Multi-turn chat burst'. Watch blocks flow through all 5 tiers. GPU utilization stays high. TTFT stays low."
    - step: "Toggle CMX off"
      description: "Flip the G3.5 CMX toggle. Blocks skip MinIO and dump to G4. Recomputations spike. GPU utilization drops."
    - step: "Toggle CMX back on"
      description: "Turn CMX on again. MinIO absorbs the overflow. Metrics recover. The difference is immediate."
    - step: "Check MinIO Console"
      description: "Open MinIO Console for the G3.5 instance. See real KV cache objects in the kv-cache-hot bucket, appearing and disappearing as the simulation runs."
    - step: "Try agentic workload"
      description: "Click 'Agentic deep reasoning'. 128K context windows with long-lived sessions. Without CMX, the system can't cope. With CMX, MinIO handles it."
  external_dependencies: []

id: experience-stx-inference
name: "NVIDIA STX: Inside Inference Memory"
description: "Simulate KV cache flow through the 5-tier memory hierarchy. Toggle MinIO CMX to see the throughput difference."
mode: experience

networks:
  - name: default
    subnet: 172.20.0.0/16
    driver: bridge

nodes:
  - id: sim-1
    component: inference-sim
    variant: default
    position: {x: 400, y: 50}
    display_name: "Inference Simulator"

  - id: minio-g35
    component: minio
    variant: single
    position: {x: 100, y: 250}
    display_name: "MinIO AIStor (G3.5 CMX)"

  - id: minio-g4
    component: minio
    variant: single
    position: {x: 700, y: 250}
    display_name: "MinIO AIStor (G4 Archive)"

  - id: prometheus-1
    component: prometheus
    variant: default
    position: {x: 400, y: 420}
    display_name: "Prometheus"

clusters: []

edges:
  - id: e-sim-g35
    source: sim-1
    target: minio-g35
    connection_type: s3
    auto_configure: true
    label: "G3.5 context memory"
    connection_config:
      tier_role: "g35-cmx"

  - id: e-sim-g4
    source: sim-1
    target: minio-g4
    connection_type: s3
    auto_configure: true
    label: "G4 enterprise storage"
    connection_config:
      tier_role: "g4-archive"

  - id: e-sim-prom
    source: sim-1
    target: prometheus-1
    connection_type: metrics
    auto_configure: true
    label: "Sim metrics"

  - id: e-g35-prom
    source: minio-g35
    target: prometheus-1
    connection_type: metrics
    auto_configure: true
    label: "MinIO metrics"

groups: []
sticky_notes: []

annotations:
  - id: ann-arch
    position: {x: -250, y: 30}
    width: 280
    title: "NVIDIA STX architecture"
    body: "STX is a modular reference architecture for AI storage, built on **BlueField-4** processors.\n\nIt introduces a new **G3.5 context memory tier** between local NVMe and enterprise storage, specifically designed for KV cache in LLM inference."
    style: info

  - id: ann-g35
    position: {x: -250, y: 250}
    width: 280
    title: "The G3.5 tier — MinIO AIStor"
    body: "MinIO AIStor runs on BlueField-4, delivering **800Gb/s connectivity** and petabyte-scale KV cache storage.\n\nUnlike traditional storage, CMX provides **sub-millisecond** access to inference context via RDMA, keeping GPU utilization high."
    style: callout
    pointer_target: minio-g35

  - id: ann-g4
    position: {x: 900, y: 200}
    width: 250
    title: "G4 — enterprise storage"
    body: "Long-term archival tier for cold KV cache. Higher latency than G3.5.\n\nWithout CMX, blocks evict directly here, causing **recomputation stalls**."
    style: info
    pointer_target: minio-g4

  - id: ann-step1
    position: {x: 350, y: -80}
    width: 260
    title: "Start here"
    body: "Deploy, then click **Simulation** on the inference node to open the interactive visualization."
    style: step
    step_number: 1
    pointer_target: sim-1

  - id: ann-step2
    position: {x: 660, y: 50}
    width: 240
    title: "The key toggle"
    body: "In the simulation UI, toggle **G3.5 CMX** on and off to see the dramatic difference in GPU utilization and latency."
    style: step
    step_number: 2

  - id: ann-step3
    position: {x: -30, y: 400}
    width: 240
    title: "See real S3 ops"
    body: "Open **MinIO Console** for the G3.5 instance. Watch KV cache objects appear and disappear as the simulation runs."
    style: step
    step_number: 3
    pointer_target: minio-g35

  - id: ann-claim
    position: {x: 300, y: 520}
    width: 320
    title: "Performance claim"
    body: "NVIDIA reports **up to 5x tokens/sec** and **5x power efficiency** with CMX vs traditional storage.\n\nThis simulation models the architectural reason: eliminating KV cache recomputation by keeping context in a fast, accessible tier."
    style: warning

resources:
  default_memory: "512m"
  default_cpu: 0.5
  total_memory: "3g"
  total_cpu: 3.0
```

---

## Part 5: Template gallery UI update

The template gallery should visually distinguish Experiences from regular templates.

In the template list/grid, Experience templates get:
- A distinct badge: "Experience" in a purple pill (vs no badge for standard templates)
- A different card style: maybe a subtle border accent or icon indicating it's a curated, non-editable experience
- Sort order: Experiences appear in their own section at the top, separate from editable templates
- Description text that says "Interactive simulation — read-only" below the title

When loading an Experience from the gallery, show a brief modal or banner:

> "This is a curated Experience. The topology and components are fixed — deploy and interact with the simulation."

---

## Part 6: Build order

1. **DemoAnnotation model + AnnotationNode** — add the data model, create the React Flow node type, test with a simple annotation on any existing template
2. **Experience mode enforcement** — add `mode` field, disable editing when `mode === "experience"`, hide modification controls
3. **Leader lines** — annotation-pointer edge type, renders dashed lines from annotations to target nodes
4. **inference-sim container** — build the simulation engine: session manager, KV block manager, tier policies, MinIO S3 backend
5. **Visualization UI** — the single HTML file with tier bars, animated blocks, session swimlanes, metrics, controls, scenario buttons
6. **WebSocket streaming** — connect the simulation engine to the UI via WebSocket at 5Hz
7. **Template** — create the Experience template with all annotations
8. **Template gallery update** — visual distinction for Experiences

---

## Part 7: Verification

### Test 1: Annotation rendering
1. Load the Experience template
2. Verify all 7 annotations appear on the canvas at their specified positions
3. Verify leader lines from annotations to their target nodes
4. Verify annotation styles: blue for info, amber for callout, red for warning, neutral with number for step

### Test 2: Experience mode lockdown
1. Load the Experience template
2. Try to drag a node — should be blocked
3. Try to delete a node — should be blocked
4. Try to add a component from the palette — palette should be hidden
5. Properties panel shows read-only info
6. Deploy and Stop buttons still work

### Test 3: Simulation basics
1. Deploy the Experience
2. Open the simulation UI (via "Simulation" link on inference-sim node)
3. Click Start with default settings (50 users, 32K context, CMX on)
4. Verify: tier bars fill up, sessions appear in swimlane, metrics update
5. Verify: G3.5 bar shows activity (blocks evicting to MinIO)

### Test 4: CMX toggle
1. With simulation running, toggle CMX off
2. Verify: G3.5 bar empties/grays out, blocks skip to G4
3. Verify: recomputations increase, GPU utilization drops, TTFT increases
4. Toggle CMX back on
5. Verify: metrics recover within 10-15 seconds

### Test 5: Real MinIO operations
1. With simulation running (CMX on), open MinIO Console for the G3.5 instance
2. Navigate to `kv-cache-hot` bucket
3. Verify: objects appearing under `sessions/` prefix
4. Verify: objects have metadata (tier, session, tokens, created)
5. Stop simulation
6. Click Reset in the simulation UI
7. Verify: objects are cleaned up from MinIO

### Test 6: Scenario buttons
1. Click "Multi-turn chat burst" — verify settings change, simulation starts, bursty pattern visible
2. Stop, click "Agentic deep reasoning" — verify 128K context, fewer but larger KV blocks
3. Stop, click "Scale-out stress test" — verify 500 users, rapid churn

### Test 7: Block animation
1. Start simulation at 1x speed
2. Watch for eviction events — blocks should visually animate from one tier bar to another
3. Watch for promotion events — blocks moving back up when sessions return
4. The animation should be smooth (CSS transition), not jumpy

---

## What NOT to do

- Don't claim this is real performance data — it's a simulation of the architecture
- Don't try to make the block animation photorealistic — small colored rectangles sliding between bars is sufficient and readable
- Don't use Canvas2D or WebGL for the visualization — HTML/CSS/SVG with transitions is enough and simpler to maintain
- Don't allow editing in Experience mode — the whole point is it's curated
- Don't create real KV cache-sized objects (50MB+) in MinIO — use 100KB blocks, enough to be visible without filling the laptop's disk
- Don't add GPU-related dependencies — this is pure CPU simulation
- Don't modify existing node types — AnnotationNode is a new type alongside the existing ones
- Don't make Experiences editable "with a toggle" — they're fundamentally different from standard templates
