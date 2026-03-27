# Claude Code Instruction: STX Experience Enhancement + Experience Mode Layout Fix

Read these files before starting:
- `frontend/src/components/canvas/nodes/AnnotationNode.tsx` — annotation rendering
- `frontend/src/components/canvas/nodes/ComponentNode.tsx` — component node rendering
- `frontend/src/components/canvas/DiagramCanvas.tsx` — node types, edge types, event handlers
- `frontend/src/stores/diagramStore.ts` — node change handlers, experience mode check
- `frontend/src/types/index.ts` — all type definitions
- `demo-templates/experience-stx-inference.yaml` — current STX template
- `backend/app/models/demo.py` — DemoDefinition, DemoAnnotation, group model

---

## Task 1: Experience Mode — Allow Layout Repositioning

### Problem

Experience mode currently blocks ALL node changes including drag. The user can't reposition nodes to clean up the layout. The template author's initial positions might not be ideal, and different screen sizes render differently.

### Solution

Change Experience mode to block **structural** changes but allow **cosmetic** changes:

**ALLOWED in Experience mode:**
- Drag/reposition nodes (including annotations)
- Pan and zoom the canvas
- Select nodes (to view read-only properties)
- Save repositioned layout

**BLOCKED in Experience mode:**
- Add new nodes (palette hidden)
- Delete nodes or edges
- Add or remove edges (no connecting)
- Change node properties (variant, config, environment vars)
- Change edge labels or connection types

### Implementation

File: `frontend/src/stores/diagramStore.ts`

Find the `onNodesChange` handler. Currently it likely does something like:

```typescript
onNodesChange: (changes) => {
  const isExperience = /* check */;
  if (isExperience) return; // ← THIS IS THE PROBLEM: blocks everything
  set({ nodes: applyNodeChanges(changes, get().nodes) });
},
```

Change to:

```typescript
onNodesChange: (changes) => {
  const isExperience = get().isExperience();
  if (isExperience) {
    // In Experience mode, only allow position changes (drag) and selection
    const allowedChanges = changes.filter(change => 
      change.type === 'position' || change.type === 'select' || change.type === 'dimensions'
    );
    if (allowedChanges.length > 0) {
      set({ nodes: applyNodeChanges(allowedChanges, get().nodes) });
    }
    return;
  }
  set({ nodes: applyNodeChanges(changes, get().nodes) });
},
```

Similarly for `onEdgesChange`:

```typescript
onEdgesChange: (changes) => {
  const isExperience = get().isExperience();
  if (isExperience) {
    // In Experience mode, only allow selection changes on edges
    const allowedChanges = changes.filter(change => change.type === 'select');
    if (allowedChanges.length > 0) {
      set({ edges: applyEdgeChanges(allowedChanges, get().edges) });
    }
    return;
  }
  set({ edges: applyEdgeChanges(changes, get().edges) });
},
```

For `onConnect` — keep it blocked:

```typescript
onConnect: (connection) => {
  if (get().isExperience()) return; // No new edges
  set({ edges: addEdge(connection, get().edges) });
},
```

File: `frontend/src/components/canvas/DiagramCanvas.tsx`

On the `<ReactFlow>` component, set these props conditionally:

```typescript
const isExperience = useDiagramStore(s => s.isExperience());

<ReactFlow
  nodes={nodes}
  edges={edges}
  onNodesChange={onNodesChange}
  onEdgesChange={onEdgesChange}
  onConnect={onConnect}
  nodesDraggable={true}              // ← Always true, even in Experience
  nodesConnectable={!isExperience}   // ← Block new connections in Experience
  elementsSelectable={true}          // ← Always true
  deleteKeyCode={isExperience ? null : 'Backspace'}  // ← Block delete key in Experience
  // ...
>
```

### Layout auto-save for Experience mode

When the user repositions nodes in an Experience, save the new positions so they persist on reload.

File: `frontend/src/stores/diagramStore.ts`

Add a debounced save function that fires after drag ends in Experience mode:

```typescript
// After onNodesChange processes a position change in Experience mode:
if (isExperience && allowedChanges.some(c => c.type === 'position' && !c.dragging)) {
  // Position change finished (drag ended) — save layout
  debouncedSaveExperienceLayout(get().nodes);
}
```

The save function:

```typescript
const debouncedSaveExperienceLayout = debounce((nodes: Node[]) => {
  const demoId = useDemoStore.getState().activeDemoId;
  if (!demoId) return;
  
  // Save only positions, not structural changes
  const positions = nodes.map(n => ({ id: n.id, x: n.position.x, y: n.position.y }));
  
  fetch(`${API_BASE}/api/demos/${demoId}/layout`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ positions }),
  });
}, 1000);
```

File: `backend/app/api/demos.py`

Add a layout-only save endpoint:

```python
@router.put("/api/demos/{demo_id}/layout")
async def save_layout(demo_id: str, req: dict):
    """Save node positions without changing structure. Used by Experience mode."""
    demo = _load_demo(demo_id)
    if not demo:
        raise HTTPException(404, "Demo not found")
    
    positions = {p["id"]: (p["x"], p["y"]) for p in req.get("positions", [])}
    
    for node in demo.nodes:
        if node.id in positions:
            node.position.x, node.position.y = positions[node.id]
    
    for ann in demo.annotations:
        if ann.id in positions:
            ann.position.x, ann.position.y = positions[ann.id]
    
    _save_demo(demo)
    return {"status": "saved", "positions_updated": len(positions)}
```

### Experience mode banner update

Update the banner text from "this simulation cannot be modified" to something more accurate:

```
"Experience mode — rearrange the layout freely, but components and connections are fixed"
```

### PropertiesPanel in Experience mode

When a node is selected in Experience mode, the properties panel should show:
- Component name and description (read-only)
- Health status (if deployed)
- Web UI links (clickable)
- Terminal button (functional)
- All config fields shown as read-only text (no edit controls)
- No "Delete node" button
- No variant dropdown

File: `frontend/src/components/properties/PropertiesPanel.tsx`

Find where edit controls render and wrap them:

```typescript
const isExperience = useDiagramStore(s => s.isExperience());

// For variant selector:
{isExperience ? (
  <div className="text-sm text-muted-foreground">{selectedNode.data.variant}</div>
) : (
  <Select value={variant} onValueChange={setVariant}>
    {/* variant options */}
  </Select>
)}

// For environment variables:
{isExperience ? (
  <div className="text-xs font-mono text-muted-foreground">
    {Object.entries(config).map(([k, v]) => (
      <div key={k}>{k}: {v}</div>
    ))}
  </div>
) : (
  /* editable key-value form */
)}

// Hide delete button entirely:
{!isExperience && (
  <Button variant="destructive" onClick={deleteNode}>Delete node</Button>
)}
```

---

## Task 2: STX Experience — Enhanced Architecture

### New topology

The current template has 4 nodes: inference-sim, minio-g35, minio-g4, prometheus.

The new topology adds:
1. **"GPU Server" GroupNode** — visual container wrapping the inference-sim, representing a Vera Rubin compute tray
2. **"Inference Client" node** — sends requests into the GPU server, represents the workload
3. **Internal tier annotations** — inside the GPU Server group, labels showing G1/G2/G3
4. **Updated edges** — client → sim, sim → MinIO G3.5, sim → MinIO G4
5. **Better annotation placement** with the new layout

### Add inference-client component

Create a minimal component manifest for the inference client — it's just a traffic generator focused on inference requests.

File: `components/inference-client/manifest.yaml`

```yaml
id: inference-client
name: Inference Client
category: simulation
icon: inference-client
version: "1.0"
image: curlimages/curl:latest
description: "Simulates inference API requests to the GPU server"

resources:
  memory: "64m"
  cpu: 0.1

ports: []

environment:
  INFERENCE_ENDPOINT: ""
  REQUEST_RATE: "10"
  CONTEXT_LENGTH: "32768"

volumes: []
command: ["sh", "-c", "while true; do sleep 3600; done"]

health_check:
  endpoint: ""
  port: 0

secrets: []
web_ui: []

terminal:
  shell: /bin/sh
  welcome_message: "Inference client — generates simulated LLM requests."
  quick_actions:
    - label: "Send test request"
      command: "wget -qO- http://$INFERENCE_ENDPOINT/sim/start --post-data='' 2>/dev/null || echo 'Simulator not ready'"

connections:
  provides: []
  accepts:
    - type: inference-api
      config_schema: []
```

Add edge resolution for the new connection type:

File: `backend/app/engine/compose_generator.py`

```python
# Inference API connection
if edge.connection_type == "inference-api":
    peer_manifest = get_component(peer_component)
    if peer_manifest:
        api_port = next((p.container for p in peer_manifest.ports if p.name == "web"), 8095)
        env["INFERENCE_ENDPOINT"] = f"{project_name}-{peer_id}:{api_port}"
```

File: `frontend/src/types/index.ts` — add to `ConnectionType`:

```typescript
| "inference-api"
```

### Updated template

File: `demo-templates/experience-stx-inference.yaml`

Replace the entire template with this expanded version:

```yaml
_template:
  name: "NVIDIA STX: inside inference memory"
  tier: experience
  mode: experience
  category: simulation
  tags: ["nvidia", "stx", "cmx", "inference", "kv-cache", "memory-hierarchy", "bluefield-4"]
  description: "Interactive simulation of the NVIDIA STX/CMX inference memory architecture. Visualizes how KV cache blocks flow through 5 memory tiers during LLM inference."
  objective: "Explain the NVIDIA STX architecture and demonstrate MinIO AIStor's role as the G3.5 context memory tier"
  minio_value: "MinIO AIStor operates as the G3.5 context memory storage tier in the NVIDIA STX architecture, providing petabyte-scale, high-bandwidth KV cache storage between local NVMe and enterprise storage."
  estimated_resources:
    memory: "2GB"
    cpu: 2
    containers: 5
  walkthrough:
    - step: "Deploy the simulation"
      description: "Click Deploy. The GPU server, two MinIO tiers, and monitoring start up."
    - step: "Open the simulation"
      description: "Click 'Simulation' on the Inference Simulator node inside the GPU Server group."
    - step: "Run with CMX enabled"
      description: "Click 'Multi-turn chat burst'. Watch blocks flow through all 5 tiers. GPU utilization stays high."
    - step: "Toggle CMX off"
      description: "Flip the G3.5 CMX toggle. Blocks skip MinIO and dump to G4. Recomputations spike."
    - step: "Check MinIO Console"
      description: "Open MinIO Console for the G3.5 instance. See real KV cache objects appearing."
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
  # Inference client — outside the GPU server
  - id: inference-client
    component: inference-client
    variant: default
    position: {x: 50, y: 180}
    display_name: "Inference Client"

  # Inference simulator — inside the GPU Server group
  - id: sim-1
    component: inference-sim
    variant: default
    position: {x: 420, y: 160}
    display_name: "Inference Simulator"
    parent_group: gpu-server

  # MinIO G3.5 — outside the GPU server, to the left-bottom
  - id: minio-g35
    component: minio
    variant: single
    position: {x: 200, y: 500}
    display_name: "MinIO AIStor (G3.5 CMX)"

  # MinIO G4 — outside the GPU server, to the right-bottom
  - id: minio-g4
    component: minio
    variant: single
    position: {x: 700, y: 500}
    display_name: "MinIO AIStor (G4 Archive)"

  # Prometheus
  - id: prometheus-1
    component: prometheus
    variant: default
    position: {x: 450, y: 700}
    display_name: "Prometheus"

clusters: []

groups:
  - id: gpu-server
    name: "GPU Server — Vera Rubin Compute Tray"
    position: {x: 280, y: 60}
    width: 450
    height: 320
    style: "dashed"
    color: "purple"

edges:
  # Client → Simulator (inference requests)
  - id: e-client-sim
    source: inference-client
    target: sim-1
    connection_type: inference-api
    auto_configure: true
    label: "Inference requests"

  # Simulator → MinIO G3.5 (KV cache context memory)
  - id: e-sim-g35
    source: sim-1
    target: minio-g35
    connection_type: s3
    auto_configure: true
    label: "G3.5 context memory"
    connection_config:
      tier_role: "g35-cmx"

  # Simulator → MinIO G4 (enterprise archive)
  - id: e-sim-g4
    source: sim-1
    target: minio-g4
    connection_type: s3
    auto_configure: true
    label: "G4 enterprise storage"
    connection_config:
      tier_role: "g4-archive"

  # Simulator → Prometheus (metrics)
  - id: e-sim-prom
    source: sim-1
    target: prometheus-1
    connection_type: metrics
    auto_configure: true
    label: "Sim metrics"

  # MinIO G3.5 → Prometheus (storage metrics)
  - id: e-g35-prom
    source: minio-g35
    target: prometheus-1
    connection_type: metrics
    auto_configure: true
    label: "MinIO metrics"

annotations:
  # Architecture overview — top left
  - id: ann-arch
    position: {x: -300, y: 30}
    width: 260
    title: "NVIDIA STX architecture"
    body: "STX is a modular reference architecture for AI storage, built on **BlueField-4** processors.\n\nIt introduces a **G3.5 context memory tier** between local NVMe and enterprise storage, designed for KV cache in LLM inference."
    style: info

  # GPU Server internal tiers — inside the group box
  - id: ann-internal-tiers
    position: {x: 290, y: 290}
    width: 420
    title: "Internal tiers (inside the GPU server)"
    body: "**G1** — GPU HBM: 80GB, nanosecond access. Active KV cache lives here.\n**G2** — CPU DRAM: 512GB, microsecond access. Overflow from G1.\n**G3** — Local NVMe: 4TB, ~100μs access. Node-local flash."
    style: callout

  # Step 1 — start here
  - id: ann-step1
    position: {x: 50, y: 20}
    width: 200
    title: "Start here"
    body: "Deploy, then click **Simulation** on the inference node."
    style: step
    step_number: 1
    pointer_target: sim-1

  # Step 2 — the key toggle
  - id: ann-step2
    position: {x: 780, y: 100}
    width: 220
    title: "The key toggle"
    body: "In the simulation UI, toggle **G3.5 CMX** on and off to see the dramatic difference."
    style: step
    step_number: 2

  # G3.5 explanation — near the CMX MinIO
  - id: ann-g35
    position: {x: -100, y: 500}
    width: 260
    title: "The G3.5 tier — MinIO AIStor"
    body: "Runs on BlueField-4 with **800Gb/s** connectivity. Provides petabyte-scale KV cache with **sub-millisecond** access via RDMA.\n\nThe simulation writes **real S3 objects** to this instance."
    style: callout
    pointer_target: minio-g35

  # G4 explanation — near the archive MinIO
  - id: ann-g4
    position: {x: 950, y: 450}
    width: 240
    title: "G4 — enterprise storage"
    body: "Long-term archival tier for cold KV cache. Higher latency than G3.5.\n\nWithout CMX, blocks evict directly here, causing **recomputation stalls**."
    style: info
    pointer_target: minio-g4

  # Step 3 — see real ops
  - id: ann-step3
    position: {x: -100, y: 680}
    width: 240
    title: "See real S3 ops"
    body: "Open **MinIO Console** for the G3.5 instance. Watch KV cache objects appear and disappear as the simulation runs."
    style: step
    step_number: 3
    pointer_target: minio-g35

  # Inference client explanation
  - id: ann-client
    position: {x: -200, y: 160}
    width: 220
    title: "Inference workload"
    body: "Simulates multi-turn chat sessions, agentic reasoning, and code generation requests hitting the GPU server."
    style: info
    pointer_target: inference-client

  # Performance claim — bottom center
  - id: ann-claim
    position: {x: 300, y: 830}
    width: 350
    title: "Performance claim"
    body: "NVIDIA reports **up to 5x tokens/sec** and **5x power efficiency** with CMX vs traditional storage.\n\nThis simulation models the architectural reason: eliminating KV cache recomputation by keeping context in a fast, accessible tier."
    style: warning

resources:
  default_memory: "256m"
  default_cpu: 0.25
  total_memory: "3g"
  total_cpu: 3.0
```

### GroupNode rendering for Experience

The GroupNode should render with:
- A **dashed border** (matching the screenshot style)
- The group name as a **header label** at the top
- A subtle background tint (purple for GPU server)
- Child nodes positioned **relative to the group** (React Flow `parentId` mechanism)

File: `frontend/src/components/canvas/nodes/GroupNode.tsx`

Check how GroupNode currently renders. Ensure it supports:

```typescript
interface GroupNodeData {
  name: string;
  style?: "solid" | "dashed";
  color?: string;   // "purple" | "teal" | "gray" — maps to a subtle bg tint
  width: number;
  height: number;
}
```

The group should render as:

```tsx
<div
  className={cn(
    "rounded-xl border-2 px-4 pt-2 pb-4",
    data.style === "dashed" ? "border-dashed" : "border-solid",
    colorClasses[data.color || "gray"],
  )}
  style={{ width: data.width, height: data.height }}
>
  <div className="text-xs font-semibold text-muted-foreground mb-1">
    {data.name}
  </div>
  {/* Child nodes are positioned inside by React Flow's parent mechanism */}
</div>
```

Color classes:
```typescript
const colorClasses: Record<string, string> = {
  purple: "border-purple-400/50 bg-purple-500/5 dark:border-purple-400/30 dark:bg-purple-500/10",
  teal:   "border-teal-400/50 bg-teal-500/5 dark:border-teal-400/30 dark:bg-teal-500/10",
  gray:   "border-border bg-muted/30",
};
```

### Making the inference-sim a child of the GPU Server group

In the template YAML, the `sim-1` node has `parent_group: gpu-server`. When loading the template, the backend (or frontend template loader) should set the React Flow `parentId` property:

```typescript
// When converting template nodes to React Flow nodes:
if (templateNode.parent_group) {
  rfNode.parentId = templateNode.parent_group;
  rfNode.extent = 'parent';  // Constrain drag within parent
}
```

The group node itself gets:

```typescript
{
  id: "gpu-server",
  type: "group",
  position: { x: 280, y: 60 },
  data: {
    name: "GPU Server — Vera Rubin Compute Tray",
    style: "dashed",
    color: "purple",
    width: 450,
    height: 320,
  },
  style: { width: 450, height: 320 },
}
```

And the child node's position is **relative to the group's top-left corner**:

```typescript
{
  id: "sim-1",
  type: "component",
  position: { x: 140, y: 100 },  // Relative to gpu-server group
  parentId: "gpu-server",
  extent: "parent",
  data: { /* ... */ },
}
```

### Backend model change for parent_group

File: `backend/app/models/demo.py`

Add to `DemoNode`:

```python
class DemoNode(BaseModel):
    id: str
    component: str
    variant: str = "single"
    position: NodePosition
    display_name: str = ""
    config: dict[str, str] = {}
    parent_group: str | None = None  # NEW: group ID this node belongs to
```

Add to `DemoGroup`:

```python
class DemoGroup(BaseModel):
    id: str
    name: str
    position: NodePosition
    width: int = 400
    height: int = 300
    style: str = "dashed"    # "solid" | "dashed"
    color: str = "gray"      # "purple" | "teal" | "gray"
```

---

## Task 3: Verification

### Unit tests

```python
def test_experience_mode_layout_save():
    """PUT /api/demos/{id}/layout should update positions only."""
    # Create experience demo
    # Save initial positions
    # Call layout endpoint with new positions
    # Reload demo and verify positions changed
    # Verify node components and edges unchanged

def test_experience_template_has_group():
    """STX Experience template should have a gpu-server group."""
    template = load_template("experience-stx-inference")
    groups = [g for g in template.groups if g.id == "gpu-server"]
    assert len(groups) == 1
    assert groups[0].name == "GPU Server — Vera Rubin Compute Tray"

def test_sim_node_has_parent_group():
    """sim-1 node should have parent_group set to gpu-server."""
    template = load_template("experience-stx-inference")
    sim_node = next(n for n in template.nodes if n.id == "sim-1")
    assert sim_node.parent_group == "gpu-server"

def test_experience_has_inference_client():
    """STX Experience should have an inference-client node."""
    template = load_template("experience-stx-inference")
    client_node = next((n for n in template.nodes if n.component == "inference-client"), None)
    assert client_node is not None

def test_experience_has_9_annotations():
    """STX Experience should have 9 annotations."""
    template = load_template("experience-stx-inference")
    assert len(template.annotations) == 9

def test_inference_api_edge_resolution():
    """inference-api edge should set INFERENCE_ENDPOINT env var."""
    # Mock compose generation with inference-client → inference-sim edge
    # Verify INFERENCE_ENDPOINT is set on the client container
```

### Playwright E2E

```typescript
test.describe('Experience Mode Layout', () => {
  test('can drag nodes in experience mode', async ({ page }) => {
    await page.goto('/');
    // Load STX Experience template
    // Verify experience banner is visible
    
    // Get initial position of a node
    const node = page.locator('[data-testid="rf-node-minio-g35"]');
    const initialBox = await node.boundingBox();
    
    // Drag the node
    await node.dragTo(page.locator('.react-flow__pane'), {
      targetPosition: { x: initialBox!.x + 100, y: initialBox!.y + 50 }
    });
    
    // Verify node moved
    const newBox = await node.boundingBox();
    expect(newBox!.x).not.toBe(initialBox!.x);
  });

  test('cannot delete nodes in experience mode', async ({ page }) => {
    await page.goto('/');
    // Load STX Experience
    
    // Select a node
    await page.click('[data-testid="rf-node-minio-g35"]');
    
    // Press delete key
    await page.keyboard.press('Backspace');
    
    // Node should still exist
    await expect(page.locator('[data-testid="rf-node-minio-g35"]')).toBeVisible();
  });

  test('cannot add nodes in experience mode', async ({ page }) => {
    await page.goto('/');
    // Load STX Experience
    
    // Component palette should be hidden
    await expect(page.locator('[data-testid="component-palette"]')).not.toBeVisible();
  });

  test('properties panel is read-only in experience mode', async ({ page }) => {
    await page.goto('/');
    // Load STX Experience
    
    // Select a node
    await page.click('[data-testid="rf-node-minio-g35"]');
    
    // Should NOT have editable inputs
    await expect(page.locator('[data-testid="variant-select"]')).not.toBeVisible();
    await expect(page.locator('[data-testid="delete-node-btn"]')).not.toBeVisible();
    
    // Should have read-only info
    await expect(page.locator('text=MinIO AIStor (G3.5 CMX)')).toBeVisible();
  });

  test('layout persists after repositioning', async ({ page }) => {
    await page.goto('/');
    // Load STX Experience
    
    // Drag a node to a new position
    const node = page.locator('[data-testid="rf-node-minio-g35"]');
    await node.dragTo(page.locator('.react-flow__pane'), {
      targetPosition: { x: 400, y: 600 }
    });
    
    // Wait for debounced save
    await page.waitForTimeout(1500);
    
    // Reload the page
    await page.reload();
    
    // Node should be at the new position (not the original template position)
    const box = await node.boundingBox();
    // Position should be closer to where we dragged than the original
  });
});

test.describe('STX Experience Architecture', () => {
  test('GPU Server group is visible', async ({ page }) => {
    await page.goto('/');
    // Load STX Experience
    
    await expect(page.locator('[data-testid="rf-node-gpu-server"]')).toBeVisible();
    await expect(page.locator('text=GPU Server')).toBeVisible();
  });

  test('inference simulator is inside GPU Server group', async ({ page }) => {
    await page.goto('/');
    // Load STX Experience
    
    // The sim-1 node should be visually inside the gpu-server group
    const group = page.locator('[data-testid="rf-node-gpu-server"]');
    const sim = page.locator('[data-testid="rf-node-sim-1"]');
    
    const groupBox = await group.boundingBox();
    const simBox = await sim.boundingBox();
    
    // sim should be inside group bounds
    expect(simBox!.x).toBeGreaterThan(groupBox!.x);
    expect(simBox!.y).toBeGreaterThan(groupBox!.y);
    expect(simBox!.x + simBox!.width).toBeLessThan(groupBox!.x + groupBox!.width);
    expect(simBox!.y + simBox!.height).toBeLessThan(groupBox!.y + groupBox!.height);
  });

  test('inference client is outside GPU Server group', async ({ page }) => {
    await page.goto('/');
    // Load STX Experience
    
    const group = page.locator('[data-testid="rf-node-gpu-server"]');
    const client = page.locator('[data-testid="rf-node-inference-client"]');
    
    const groupBox = await group.boundingBox();
    const clientBox = await client.boundingBox();
    
    // Client should be outside (to the left of) the group
    expect(clientBox!.x + clientBox!.width).toBeLessThan(groupBox!.x);
  });

  test('internal tiers annotation is inside group', async ({ page }) => {
    await page.goto('/');
    // Load STX Experience
    
    // Should see the internal tiers annotation with G1, G2, G3 labels
    await expect(page.locator('text=Internal tiers')).toBeVisible();
    await expect(page.locator('text=GPU HBM')).toBeVisible();
    await expect(page.locator('text=CPU DRAM')).toBeVisible();
    await expect(page.locator('text=Local NVMe')).toBeVisible();
  });

  test('all 9 annotations render', async ({ page }) => {
    await page.goto('/');
    // Load STX Experience
    
    const annotations = page.locator('[data-testid^="rf-node-ann-"]');
    await expect(annotations).toHaveCount(9);
  });

  test('has 5 component nodes', async ({ page }) => {
    await page.goto('/');
    // Load STX Experience
    
    // 5 component nodes: inference-client, sim-1, minio-g35, minio-g4, prometheus-1
    // Plus 1 group node: gpu-server
    // Plus 9 annotation nodes
    // Total react-flow nodes: 15
    const componentNodes = page.locator('.react-flow__node[data-testid^="rf-node-"]:not([data-testid^="rf-node-ann-"]):not([data-testid="rf-node-gpu-server"])');
    await expect(componentNodes).toHaveCount(5);
  });

  test('deploy creates all containers', async ({ page }) => {
    await page.goto('/');
    // Load STX Experience
    // Click Deploy
    await page.click('[data-testid="deploy-btn"]');
    
    // Wait for all nodes healthy (timeout 120s for image pulls)
    await expect(page.locator('[data-testid="health-badge-healthy"]')).toHaveCount(5, { timeout: 120000 });
  });
});
```

---

## What NOT to do

- Don't make the inference-client a heavyweight container — it's just a placeholder that sends curl requests. The real simulation logic lives in inference-sim.
- Don't put the annotations inside the group's React Flow children — annotations are independent nodes with `pointer_target` leader lines. They float outside the group visually even if they describe things inside it.
- Don't allow edge modification in Experience mode — even though we now allow node dragging, edges must remain fixed.
- Don't auto-layout Experience templates on load — the template author's positions are the starting point. The user can adjust from there.
- Don't remove the `isExperience` check from `addNode` — we still block adding new nodes.
