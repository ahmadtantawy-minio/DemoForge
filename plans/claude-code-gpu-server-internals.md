# Claude Code Instruction: GPU Server Internal Visualization & Edge Protocol Labels

This is a complementary instruction to `claude-code-stx-experience-enhancement.md` and `claude-code-inference-sim-ui-overhaul.md`. Apply after those are implemented.

Read before starting:
- `frontend/src/components/canvas/nodes/GroupNode.tsx` — group rendering
- `frontend/src/components/canvas/nodes/ComponentNode.tsx` — component rendering
- `frontend/src/components/canvas/DiagramCanvas.tsx` — node type registration
- `frontend/src/components/canvas/edges/AnimatedDataEdge.tsx` — edge rendering
- `frontend/src/types/index.ts` — type definitions
- `demo-templates/experience-stx-inference.yaml` — STX template

---

## Task 1: SchematicNode — visual-only canvas elements

### Problem

The GPU Server group needs to show internal structure (2 GPUs, each with G1/G2/G3 memory tiers) on the React Flow canvas. These aren't real Docker containers — they're architectural diagram elements that communicate what's inside the server without deploying anything.

### Solution: new `schematic` node type

A `SchematicNode` is a lightweight, non-deployable React Flow node. It renders as a compact labeled box on the canvas. It has no Docker container, no health status, no web UI, no terminal. It exists purely for visual communication.

File: `frontend/src/types/index.ts`

Add the data interface:

```typescript
export interface SchematicNodeData {
  label: string;              // Primary label, e.g. "GPU-A"
  sublabel?: string;          // Secondary text, e.g. "Rubin Ultra GPU"
  children?: SchematicChild[];  // Nested visual elements inside this schematic
  variant: "gpu" | "tier" | "generic";  // Controls visual style
  width?: number;
  height?: number;
}

export interface SchematicChild {
  id: string;
  label: string;              // e.g. "G1 — GPU HBM"
  detail?: string;            // e.g. "80 GB · nanosecond access"
  color: string;              // Tier color: "red" | "amber" | "blue" | "teal" | "gray"
}
```

File: `frontend/src/components/canvas/nodes/SchematicNode.tsx` (new file)

```tsx
import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import type { SchematicNodeData } from '../../../types';

const tierColors: Record<string, { bg: string; border: string; text: string }> = {
  red:   { bg: 'bg-red-500/10',   border: 'border-red-400/40',   text: 'text-red-300' },
  amber: { bg: 'bg-amber-500/10', border: 'border-amber-400/40', text: 'text-amber-300' },
  blue:  { bg: 'bg-blue-500/10',  border: 'border-blue-400/40',  text: 'text-blue-300' },
  teal:  { bg: 'bg-teal-500/10',  border: 'border-teal-400/40',  text: 'text-teal-300' },
  gray:  { bg: 'bg-zinc-500/10',  border: 'border-zinc-400/40',  text: 'text-zinc-400' },
};

function SchematicNode({ data }: NodeProps) {
  const d = data as SchematicNodeData;

  if (d.variant === 'gpu') {
    // GPU node: renders as a card with tier children stacked inside
    return (
      <div
        className="rounded-lg border border-dashed border-purple-400/30 bg-purple-500/5 p-3"
        style={{ width: d.width || 200, minHeight: d.height || 160 }}
      >
        {/* GPU header */}
        <div className="flex items-center gap-2 mb-3">
          <div className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
          <span className="text-xs font-semibold text-purple-200">{d.label}</span>
          {d.sublabel && (
            <span className="text-[10px] text-purple-400/60 ml-auto">{d.sublabel}</span>
          )}
        </div>

        {/* Tier rows stacked vertically */}
        <div className="space-y-1.5">
          {d.children?.map(child => {
            const colors = tierColors[child.color] || tierColors.gray;
            return (
              <div
                key={child.id}
                className={`rounded px-2 py-1.5 border ${colors.bg} ${colors.border}`}
              >
                <div className={`text-[11px] font-medium ${colors.text}`}>
                  {child.label}
                </div>
                {child.detail && (
                  <div className="text-[9px] text-zinc-500 mt-0.5">
                    {child.detail}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  // Generic schematic: simple labeled box
  return (
    <div
      className="rounded border border-dashed border-zinc-600 bg-zinc-800/30 px-3 py-2"
      style={{ width: d.width || 150 }}
    >
      <div className="text-xs font-medium text-zinc-300">{d.label}</div>
      {d.sublabel && (
        <div className="text-[10px] text-zinc-500 mt-0.5">{d.sublabel}</div>
      )}
    </div>
  );
}

export default memo(SchematicNode);
```

Register in DiagramCanvas.tsx:

```typescript
import SchematicNode from './nodes/SchematicNode';

const nodeTypes = {
  component: ComponentNode,
  cluster: ClusterNode,
  group: GroupNode,
  sticky: StickyNoteNode,
  annotation: AnnotationNode,
  schematic: SchematicNode,      // NEW
};
```

### Template YAML: schematic nodes

File: `backend/app/models/demo.py`

Add `DemoSchematicNode` model:

```python
class SchematicChild(BaseModel):
    id: str
    label: str
    detail: str = ""
    color: str = "gray"          # "red" | "amber" | "blue" | "teal" | "gray"

class DemoSchematicNode(BaseModel):
    id: str
    position: NodePosition
    label: str
    sublabel: str = ""
    variant: str = "generic"      # "gpu" | "tier" | "generic"
    children: list[SchematicChild] = []
    parent_group: str | None = None
    width: int | None = None
    height: int | None = None
```

Add to `DemoDefinition`:

```python
class DemoDefinition(BaseModel):
    # ... existing fields ...
    schematics: list[DemoSchematicNode] = []    # NEW: visual-only nodes
```

### Template loader: convert schematics to React Flow nodes

When loading a template, convert `schematics` entries into React Flow nodes of type `schematic`:

```python
for sch in demo.schematics:
    rf_node = {
        "id": sch.id,
        "type": "schematic",
        "position": {"x": sch.position.x, "y": sch.position.y},
        "data": {
            "label": sch.label,
            "sublabel": sch.sublabel,
            "variant": sch.variant,
            "children": [c.model_dump() for c in sch.children],
            "width": sch.width,
            "height": sch.height,
        },
        "draggable": demo.mode != "experience" or True,  # Always draggable (cosmetic)
        "selectable": False,        # Not selectable — no properties to show
        "deletable": False,         # Never deletable
        "connectable": False,       # No edges to/from schematics
    }
    if sch.parent_group:
        rf_node["parentId"] = sch.parent_group
        rf_node["extent"] = "parent"
```

**Schematic nodes are NOT included in compose generation.** The compose generator should skip any node with `type: "schematic"`. These are canvas-only elements.

---

## Task 2: GPU Server internal structure

### Updated STX Experience template

File: `demo-templates/experience-stx-inference.yaml`

Add two schematic nodes inside the GPU Server group, each representing a GPU with its internal memory tiers:

```yaml
schematics:
  # GPU-A with internal tiers
  - id: sch-gpu-a
    position: {x: 20, y: 50}        # Relative to gpu-server group
    parent_group: gpu-server
    label: "GPU-A"
    sublabel: "Rubin Ultra"
    variant: gpu
    width: 190
    height: 180
    children:
      - id: g1a
        label: "G1 — GPU HBM"
        detail: "80 GB · ~1 ns access"
        color: red
      - id: g2a
        label: "G2 — CPU DRAM"
        detail: "512 GB · ~100 ns access"
        color: amber
      - id: g3a
        label: "G3 — local NVMe"
        detail: "4 TB · ~100 μs access"
        color: blue

  # GPU-B with internal tiers
  - id: sch-gpu-b
    position: {x: 240, y: 50}       # Relative to gpu-server group, next to GPU-A
    parent_group: gpu-server
    label: "GPU-B"
    sublabel: "Rubin Ultra"
    variant: gpu
    width: 190
    height: 180
    children:
      - id: g1b
        label: "G1 — GPU HBM"
        detail: "80 GB · ~1 ns access"
        color: red
      - id: g2b
        label: "G2 — CPU DRAM"
        detail: "512 GB · ~100 ns access"
        color: amber
      - id: g3b
        label: "G3 — local NVMe"
        detail: "4 TB · ~100 μs access"
        color: blue
```

Update the GPU Server group dimensions to fit both schematic GPUs:

```yaml
groups:
  - id: gpu-server
    name: "GPU Server — Vera Rubin Compute Tray"
    position: {x: 250, y: 40}
    width: 480                       # Wider to fit 2 GPU schematics side by side
    height: 300
    style: "dashed"
    color: "purple"
```

The inference-sim node positions inside the group, below or overlapping the GPU schematics:

```yaml
nodes:
  - id: sim-1
    component: inference-sim
    variant: default
    position: {x: 140, y: 240}      # Below the GPU schematics, centered
    display_name: "Inference Simulator"
    parent_group: gpu-server
```

### Visual result on canvas

```
┌─── GPU Server — Vera Rubin Compute Tray ──────────────────────┐
│                                                                 │
│  ┌─ GPU-A ─────────────┐     ┌─ GPU-B ─────────────┐          │
│  │ Rubin Ultra         │     │ Rubin Ultra         │          │
│  │                     │     │                     │          │
│  │ ┌ G1 — GPU HBM ──┐ │     │ ┌ G1 — GPU HBM ──┐ │          │
│  │ │ 80 GB · ~1 ns   │ │     │ │ 80 GB · ~1 ns   │ │          │
│  │ └────────────────-┘ │     │ └─────────────────┘ │          │
│  │ ┌ G2 — CPU DRAM ─┐ │     │ ┌ G2 — CPU DRAM ─┐ │          │
│  │ │ 512 GB · ~100ns │ │     │ │ 512 GB · ~100ns │ │          │
│  │ └────────────────-┘ │     │ └─────────────────┘ │          │
│  │ ┌ G3 — local NVMe┐ │     │ ┌ G3 — local NVMe┐ │          │
│  │ │ 4 TB · ~100 μs  │ │     │ │ 4 TB · ~100 μs  │ │          │
│  │ └────────────────-┘ │     │ └─────────────────┘ │          │
│  └─────────────────────┘     └─────────────────────┘          │
│                                                                 │
│              ┌──────────────────────┐                          │
│              │  Inference Simulator │                          │
│              │  inference-sim       │                          │
│              └──────────────────────┘                          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
       │                               │
       │ NVMe-oF / RDMA               │ S3 over TCP
       │ ~500 μs                       │ ~5-50 ms
       ▼                               ▼
┌─ MinIO CMX (G3.5) ─┐        ┌─ MinIO Archive (G4) ─┐
│ 2 nodes · replicated│        │ 2 nodes · replicated │
└─────────────────────┘        └──────────────────────┘
```

---

## Task 3: Edge protocol and latency labels

### Problem

The current edges just show generic labels like "G3.5 context memory" and "G4 enterprise storage". They don't communicate the connectivity protocol or expected latency — which is critical to understanding why G3.5 is faster than G4.

### Solution: structured edge labels with protocol + latency

DemoForge edges already support labels. Extend the label format to include protocol and latency as structured metadata that renders below the main label.

File: `frontend/src/types/index.ts`

Add to the edge data interface (or create one if it doesn't exist):

```typescript
export interface DemoEdgeData {
  label?: string;
  protocol?: string;           // NEW: "NVMe-oF / RDMA", "S3 over TCP", etc.
  latency?: string;            // NEW: "~500 μs", "~5-50 ms", etc.
  bandwidth?: string;          // NEW: "800 Gb/s", "100 Gb/s", etc.
}
```

File: `backend/app/models/demo.py`

Add to `DemoEdge`:

```python
class DemoEdge(BaseModel):
    id: str
    source: str
    target: str
    connection_type: str = "s3"
    auto_configure: bool = True
    label: str = ""
    protocol: str = ""           # NEW
    latency: str = ""            # NEW
    bandwidth: str = ""          # NEW
    connection_config: dict = {}
```

### Edge rendering with protocol + latency

File: `frontend/src/components/canvas/edges/AnimatedDataEdge.tsx`

Update the edge label rendering to show protocol and latency below the main label:

```tsx
// Inside the edge label render (wherever the label text is positioned):
function EdgeLabel({ data }: { data: DemoEdgeData }) {
  if (!data.label && !data.protocol) return null;

  return (
    <div className="flex flex-col items-center pointer-events-none">
      {/* Main label */}
      {data.label && (
        <div className="text-[10px] font-medium text-foreground/70 bg-background/90 
                        px-1.5 py-0.5 rounded border border-border/50 whitespace-nowrap">
          {data.label}
        </div>
      )}
      {/* Protocol + latency sub-label */}
      {(data.protocol || data.latency) && (
        <div className="flex items-center gap-1.5 mt-0.5">
          {data.protocol && (
            <span className="text-[9px] font-mono text-teal-400/80 bg-teal-500/10 
                           px-1 py-0.5 rounded whitespace-nowrap">
              {data.protocol}
            </span>
          )}
          {data.latency && (
            <span className="text-[9px] text-amber-400/80 bg-amber-500/10 
                           px-1 py-0.5 rounded whitespace-nowrap">
              {data.latency}
            </span>
          )}
          {data.bandwidth && (
            <span className="text-[9px] text-blue-400/80 bg-blue-500/10 
                           px-1 py-0.5 rounded whitespace-nowrap">
              {data.bandwidth}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
```

The sub-labels render as small colored pills below the main label:
- **Protocol** in teal pill: `NVMe-oF / RDMA`
- **Latency** in amber pill: `~500 μs`
- **Bandwidth** in blue pill: `800 Gb/s`

### Edge label positioning

React Flow's `EdgeLabelRenderer` places labels at the midpoint of the edge path. The protocol/latency pills sit directly below the main label. For curved edges, the label follows the curve midpoint.

If the existing edge component uses `<EdgeLabelRenderer>`, add the protocol/latency inside it:

```tsx
<EdgeLabelRenderer>
  <div
    style={{
      position: 'absolute',
      transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
      pointerEvents: 'none',
    }}
  >
    <EdgeLabel data={data} />
  </div>
</EdgeLabelRenderer>
```

### Updated STX template edges

File: `demo-templates/experience-stx-inference.yaml`

Update edge definitions with protocol, latency, and bandwidth:

```yaml
edges:
  # Client → GPU Server (inference requests)
  - id: e-client-sim
    source: inference-client
    target: sim-1
    connection_type: inference-api
    auto_configure: true
    label: "Inference requests"
    protocol: "gRPC"
    latency: "~1 ms"
    bandwidth: "100 Gb/s"

  # GPU Server → MinIO G3.5 (KV cache context memory)
  - id: e-sim-g35
    source: sim-1
    target: minio-g35
    connection_type: s3
    auto_configure: true
    label: "G3.5 context memory"
    protocol: "NVMe-oF / RDMA"
    latency: "~200-500 μs"
    bandwidth: "800 Gb/s"
    connection_config:
      tier_role: "g35-cmx"

  # GPU Server → MinIO G4 (enterprise archive)
  - id: e-sim-g4
    source: sim-1
    target: minio-g4
    connection_type: s3
    auto_configure: true
    label: "G4 enterprise storage"
    protocol: "S3 over TCP"
    latency: "~5-50 ms"
    bandwidth: "100 Gb/s"
    connection_config:
      tier_role: "g4-archive"

  # GPU Server → Prometheus
  - id: e-sim-prom
    source: sim-1
    target: prometheus-1
    connection_type: metrics
    auto_configure: true
    label: "Sim metrics"
    protocol: "HTTP"

  # MinIO G3.5 → Prometheus
  - id: e-g35-prom
    source: minio-g35
    target: prometheus-1
    connection_type: metrics
    auto_configure: true
    label: "MinIO metrics"
    protocol: "HTTP"
```

### Why these specific protocols and latencies

| Edge | Protocol | Latency | Bandwidth | Rationale |
|------|----------|---------|-----------|-----------|
| Client → GPU | gRPC | ~1 ms | 100 Gb/s | Standard inference API protocol |
| GPU → G3.5 (CMX) | NVMe-oF / RDMA | ~200-500 μs | 800 Gb/s | BlueField-4 uses NVMe-over-Fabrics with RDMA. Spectrum-X provides 800Gb/s Ethernet. NVIDIA NIXL handles the transfer. This is the key differentiator — sub-millisecond access to shared storage. |
| GPU → G4 (Archive) | S3 over TCP | ~5-50 ms | 100 Gb/s | Standard S3 API over TCP/IP networking. No RDMA acceleration. This is the "traditional" storage path that CMX replaces. |
| Metrics | HTTP | — | — | Standard Prometheus scraping, not performance-critical |

The latency contrast between G3.5 (~500 μs) and G4 (~5-50 ms) is the visual punchline on the canvas. The audience sees the numbers before even opening the simulation.

---

## Task 4: Update annotation for internal tiers

Since the GPU internal tiers are now shown as schematic children inside the GPU-A and GPU-B nodes, the existing `ann-internal-tiers` annotation becomes redundant. Replace it with a more focused annotation about the connectivity:

```yaml
annotations:
  # Replace ann-internal-tiers with connectivity explanation
  - id: ann-connectivity
    position: {x: 150, y: 780}
    width: 350
    title: "Why G3.5 is faster than G4"
    body: "G3.5 uses **NVMe-oF over RDMA** via BlueField-4 and Spectrum-X Ethernet — **800 Gb/s** with sub-millisecond latency.\n\nG4 uses standard **S3 over TCP** — 10-100x slower. Without G3.5, every cross-GPU cache miss means a full recomputation."
    style: callout

  # Add annotation about GPU isolation
  - id: ann-gpu-isolation
    position: {x: 780, y: 50}
    width: 240
    title: "GPU memory is isolated"
    body: "Each GPU has its own G1/G2/G3 memory. GPU-B **cannot access** GPU-A's HBM directly.\n\nG3.5 (MinIO CMX) bridges this gap — shared, pod-level storage both GPUs can access."
    style: callout
```

---

## Task 5: Edge visual styling per protocol

### Different edge styles for different protocols

Make the edge line style visually encode the protocol type:

| Protocol | Edge style | Color |
|----------|-----------|-------|
| NVMe-oF / RDMA | Solid, thicker (2px) | Teal/green (`#1D9E75`) |
| S3 over TCP | Solid, normal (1.5px) | Default gray |
| gRPC | Dashed, normal | Blue |
| HTTP | Dotted, thin (1px) | Muted gray |

File: `frontend/src/components/canvas/edges/AnimatedDataEdge.tsx`

When rendering the edge path, check the protocol and adjust style:

```typescript
function getEdgeStyle(protocol?: string): React.CSSProperties {
  switch (protocol) {
    case 'NVMe-oF / RDMA':
      return { stroke: '#1D9E75', strokeWidth: 2.5, strokeDasharray: 'none' };
    case 'S3 over TCP':
      return { stroke: 'var(--edge-color, #888)', strokeWidth: 1.5, strokeDasharray: 'none' };
    case 'gRPC':
      return { stroke: '#378ADD', strokeWidth: 1.5, strokeDasharray: '6 3' };
    case 'HTTP':
      return { stroke: 'var(--edge-muted, #666)', strokeWidth: 1, strokeDasharray: '2 2' };
    default:
      return { strokeWidth: 1.5 };
  }
}
```

This makes the G3.5 edge visually stand out — thick, teal, solid — while the G4 edge is thinner and less prominent. The audience's eye is drawn to the fast path.

---

## Verification

### Unit tests

```python
def test_schematic_nodes_not_in_compose():
    """Schematic nodes should be excluded from compose generation."""
    # Load STX template
    # Generate compose
    # Verify no service named "sch-gpu-a" or "sch-gpu-b" exists in compose output
    template = load_template("experience-stx-inference")
    compose = generate_compose(template, "/tmp")
    with open(compose) as f:
        data = yaml.safe_load(f)
    assert "sch-gpu-a" not in data.get("services", {})
    assert "sch-gpu-b" not in data.get("services", {})

def test_schematic_nodes_have_children():
    """GPU schematic nodes should have 3 tier children each."""
    template = load_template("experience-stx-inference")
    gpu_a = next(s for s in template.schematics if s.id == "sch-gpu-a")
    assert len(gpu_a.children) == 3
    assert gpu_a.children[0].label == "G1 — GPU HBM"
    assert gpu_a.children[0].color == "red"

def test_schematic_nodes_have_parent_group():
    """GPU schematics should be inside the gpu-server group."""
    template = load_template("experience-stx-inference")
    for sch in template.schematics:
        assert sch.parent_group == "gpu-server"

def test_edge_protocol_fields():
    """Edges should have protocol and latency fields."""
    template = load_template("experience-stx-inference")
    g35_edge = next(e for e in template.edges if e.id == "e-sim-g35")
    assert g35_edge.protocol == "NVMe-oF / RDMA"
    assert g35_edge.latency == "~200-500 μs"
    assert g35_edge.bandwidth == "800 Gb/s"
    
    g4_edge = next(e for e in template.edges if e.id == "e-sim-g4")
    assert g4_edge.protocol == "S3 over TCP"
    assert g4_edge.latency == "~5-50 ms"

def test_template_has_5_component_nodes():
    """Template should have exactly 5 deployable component nodes."""
    template = load_template("experience-stx-inference")
    assert len(template.nodes) == 5  # client, sim, minio-g35, minio-g4, prometheus

def test_template_has_2_schematic_nodes():
    """Template should have 2 GPU schematic nodes."""
    template = load_template("experience-stx-inference")
    assert len(template.schematics) == 2
```

### Playwright E2E

```typescript
test.describe('GPU Server Internal Visualization', () => {
  test('shows two GPU schematics inside the server group', async ({ page }) => {
    await page.goto('/');
    // Load STX Experience

    // Both GPU schematics should be visible
    await expect(page.locator('[data-testid="rf-node-sch-gpu-a"]')).toBeVisible();
    await expect(page.locator('[data-testid="rf-node-sch-gpu-b"]')).toBeVisible();
    await expect(page.locator('text=GPU-A')).toBeVisible();
    await expect(page.locator('text=GPU-B')).toBeVisible();
  });

  test('each GPU shows G1/G2/G3 tier children', async ({ page }) => {
    await page.goto('/');
    // Load STX Experience

    // GPU-A should show all three tiers
    const gpuA = page.locator('[data-testid="rf-node-sch-gpu-a"]');
    await expect(gpuA.locator('text=G1 — GPU HBM')).toBeVisible();
    await expect(gpuA.locator('text=G2 — CPU DRAM')).toBeVisible();
    await expect(gpuA.locator('text=G3 — local NVMe')).toBeVisible();

    // GPU-B should show the same tiers
    const gpuB = page.locator('[data-testid="rf-node-sch-gpu-b"]');
    await expect(gpuB.locator('text=G1 — GPU HBM')).toBeVisible();
    await expect(gpuB.locator('text=G2 — CPU DRAM')).toBeVisible();
    await expect(gpuB.locator('text=G3 — local NVMe')).toBeVisible();
  });

  test('tier children show capacity and latency', async ({ page }) => {
    await page.goto('/');
    // Load STX Experience

    await expect(page.locator('text=80 GB')).toBeVisible();        // G1 capacity
    await expect(page.locator('text=512 GB')).toBeVisible();       // G2 capacity
    await expect(page.locator('text=4 TB')).toBeVisible();         // G3 capacity
    await expect(page.locator('text=~1 ns access')).toBeVisible(); // G1 latency
  });

  test('GPU schematics are inside the group boundary', async ({ page }) => {
    await page.goto('/');
    // Load STX Experience

    const group = page.locator('[data-testid="rf-node-gpu-server"]');
    const gpuA = page.locator('[data-testid="rf-node-sch-gpu-a"]');

    const groupBox = await group.boundingBox();
    const gpuABox = await gpuA.boundingBox();

    // GPU-A should be visually inside the group
    expect(gpuABox!.x).toBeGreaterThan(groupBox!.x);
    expect(gpuABox!.y).toBeGreaterThan(groupBox!.y);
    expect(gpuABox!.x + gpuABox!.width).toBeLessThan(groupBox!.x + groupBox!.width);
  });

  test('schematic nodes are not deployable', async ({ page }) => {
    await page.goto('/');
    // Load STX Experience, deploy

    await page.click('[data-testid="deploy-btn"]');
    // Wait for deployment
    await page.waitForTimeout(10000);

    // Should have 5 deployed containers, not 7
    // (inference-client, sim-1, minio-g35, minio-g4, prometheus — NOT sch-gpu-a, sch-gpu-b)
    const healthBadges = page.locator('[data-testid="health-badge"]');
    await expect(healthBadges).toHaveCount(5, { timeout: 120000 });
  });
});

test.describe('Edge Protocol Labels', () => {
  test('G3.5 edge shows RDMA protocol', async ({ page }) => {
    await page.goto('/');
    // Load STX Experience

    await expect(page.locator('text=NVMe-oF / RDMA')).toBeVisible();
  });

  test('G4 edge shows S3 over TCP', async ({ page }) => {
    await page.goto('/');
    // Load STX Experience

    await expect(page.locator('text=S3 over TCP')).toBeVisible();
  });

  test('edges show latency values', async ({ page }) => {
    await page.goto('/');
    // Load STX Experience

    await expect(page.locator('text=~200-500 μs')).toBeVisible();  // G3.5 latency
    await expect(page.locator('text=~5-50 ms')).toBeVisible();     // G4 latency
  });

  test('G3.5 edge is visually thicker than G4', async ({ page }) => {
    await page.goto('/');
    // Load STX Experience

    // The RDMA edge should have a thicker stroke
    const g35Edge = page.locator('[data-testid="edge-e-sim-g35"] path.react-flow__edge-path');
    const strokeWidth = await g35Edge.getAttribute('stroke-width');
    expect(parseFloat(strokeWidth || '1')).toBeGreaterThanOrEqual(2);
  });

  test('edge protocol pills have correct colors', async ({ page }) => {
    await page.goto('/');
    // Load STX Experience

    // RDMA pill should be teal-ish
    const rdmaPill = page.locator('text=NVMe-oF / RDMA').locator('..');
    await expect(rdmaPill).toHaveClass(/teal/);

    // Latency pill should be amber-ish
    const latencyPill = page.locator('text=~200-500 μs').locator('..');
    await expect(latencyPill).toHaveClass(/amber/);
  });
});
```

---

## What NOT to do

- Don't create Docker containers for the schematic GPU nodes — they are purely visual. The compose generator must skip them.
- Don't make schematic nodes selectable — clicking on them should not open the properties panel. They have no properties to edit.
- Don't draw React Flow edges between schematic nodes — G1/G2/G3 are internal to each GPU and don't need visible connections. The hierarchy is communicated by visual nesting.
- Don't use real NVIDIA product names beyond "Rubin Ultra" for the GPU sublabel — keep it generic enough to not require NVIDIA approval.
- Don't hardcode edge protocol/latency rendering for STX only — the edge label enhancement is generic and works for any template. Other templates can add protocol/latency labels too (e.g., "Kafka" protocol on streaming edges, "JDBC" on Trino→Metabase edges).
- Don't add protocol/latency to the metrics or Prometheus edges — only the data-path edges (G3.5 and G4) need this information. Keep metrics edges simple.
