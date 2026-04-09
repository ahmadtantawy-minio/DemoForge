# DemoForge Refactor Source Extraction

Generated: 2026-04-09

---

## 1. Cluster Component & Node Types

### Node Type Registration

**`frontend/src/components/canvas/DiagramCanvas.tsx` (line 37)**

```typescript
const nodeTypes = {
  component: ComponentNode,
  group: GroupNode,
  sticky: StickyNoteNode,
  cluster: ClusterNode,
  annotation: AnnotationNode,
  schematic: SchematicNode,
};
```

React Flow node type `"cluster"` maps to `ClusterNode`. Used at line 819: `nodeTypes={nodeTypes}`.

---

### `frontend/src/components/canvas/nodes/ClusterNode.tsx`

```tsx
import { useState } from "react";
import { Copy } from "lucide-react";
import { createPortal } from "react-dom";
import { Handle, Position, type NodeProps, NodeResizer } from "@xyflow/react";
import { useDiagramStore } from "../../../stores/diagramStore";
import { useDemoStore } from "../../../stores/demoStore";
import { stopInstance, startInstance, resetCluster, stopDrive, startDrive } from "../../../api/client";
import { toast } from "../../../lib/toast";
import ComponentIcon from "../../shared/ComponentIcon";
import MinioAdminPanel from "../../minio/MinioAdminPanel";
import McpPanel from "../../minio/McpPanel";

interface ClusterNodeData {
  label: string;
  componentId: string;
  nodeCount: number;
  drivesPerNode: number;
  credentials: Record<string, string>;
  config: Record<string, string>;
  health?: string;
  mcpEnabled?: boolean;
  aistorTablesEnabled?: boolean;
  ecParity?: number;
  diskSizeTb?: number;
}

function erasureSetSize(totalDrives: number): number {
  for (let d = 16; d >= 2; d--) {
    if (totalDrives % d === 0) return d;
  }
  return totalDrives;
}

export default function ClusterNode({ id, data, selected }: NodeProps) {
  const nodeData = data as unknown as ClusterNodeData;
  const setSelectedNode = useDiagramStore((s) => s.setSelectedNode);
  const { instances, clusterHealth, activeDemoId, demos, setActiveView } = useDemoStore();
  const isRunning = demos.find((d) => d.id === activeDemoId)?.status === "running";
  const clusterStatus = isRunning ? (clusterHealth[id] ?? null) : null;
  const nodeCount = nodeData.nodeCount || 4;
  const drivesPerNode = nodeData.drivesPerNode || 1;
  const ecParity = nodeData.ecParity ?? 4;
  const diskSizeTb = nodeData.diskSizeTb ?? 8;
  const totalDrives = nodeCount * drivesPerNode;
  const setSize = erasureSetSize(totalDrives);
  const dataShards = Math.max(0, setSize - ecParity);
  const usableTb = totalDrives >= 4 && dataShards > 0
    ? Math.round(totalDrives * diskSizeTb * (dataShards / setSize))
    : null;
  const [contextNode, setContextNode] = useState<{ idx: number; x: number; y: number } | null>(null);
  const [driveSubmenu, setDriveSubmenu] = useState<number | null>(null);
  const [clusterMenu, setClusterMenu] = useState<{ x: number; y: number } | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [adminPanelOpen, setAdminPanelOpen] = useState(false);
  const [adminDefaultTab, setAdminDefaultTab] = useState<"overview" | "logs">("overview");
  const [mcpPanelOpen, setMcpPanelOpen] = useState(false);
  const [mcpDefaultTab, setMcpDefaultTab] = useState<"mcp-tools" | "ai-chat">("mcp-tools");
  const isAIStor = (nodeData.config?.MINIO_EDITION || "ce") === "aistor";
  const mcpEnabled = isAIStor && nodeData.mcpEnabled !== false;
  const aistorTablesEnabled = isAIStor && nodeData.aistorTablesEnabled === true;

  const clusterInstances = instances.filter((i) => i.node_id.startsWith(`${id}-node-`));
  const healthyCount = clusterInstances.filter((i) => i.health === "healthy").length;

  const _lbId = `${id}-lb`;
  const _lbInst = instances.find((i) => i.node_id === _lbId);
  const _apiBase = (import.meta as any).env?.VITE_API_URL || "http://localhost:9210";
  const consoleUrl = _lbInst?.health === "healthy" && activeDemoId
    ? `${_apiBase}/proxy/${activeDemoId}/${_lbId}/console/`
    : null;

  // ... (handlers: handleNodeRightClick, handleStopNode, handleStartNode,
  //      handleStopDrive, handleStartDrive, handleResetCluster)

  return (
    <>
      <NodeResizer isVisible={selected} minWidth={240} minHeight={160} />
      <div className="w-full h-full rounded-xl p-4 cursor-pointer border-2 border-primary/30 bg-primary/5"
        onClick={...} onContextMenu={...}>
        {/* Handles: data-in (left), data-in-top, cluster-out (top), cluster-in, cluster-out-bottom, data-out (right) */}
        {/* Header: icon + label + nodeCount x drivesPerNode + usable TB + health badges */}
        {/* LB row: NGINX badge + IP + MCP badge + Tables badge */}
        {/* Node grid: nodeCount tiles, each showing health, drive ratio, right-click */}
      </div>

      {/* Per-node context menu — portaled to body */}
      {/* Actions: Stop Node / Start Node / Drives submenu / Open Console / View in Instances / Reset Cluster / MinIO Admin */}

      {/* Cluster-level context menu — portaled to body */}
      {/* Actions (running): MinIO Console / MinIO Admin / MCP Tools / AI Chat / View in Instances / Reset Cluster */}
      {/* Actions (stopped): Delete Cluster */}

      <MinioAdminPanel open={adminPanelOpen} onOpenChange={setAdminPanelOpen}
        clusterId={id} clusterLabel={nodeData.label || "MinIO Cluster"}
        defaultTab={adminDefaultTab} consoleUrl={consoleUrl ?? undefined}
        nodes={clusterInstances.map((inst) => ({ id: inst.node_id, label: inst.node_id.replace(`${id}-`, "") }))}
      />
      {mcpPanelOpen && activeDemoId && (
        <McpPanel open={mcpPanelOpen} onOpenChange={setMcpPanelOpen}
          demoId={activeDemoId} clusterId={id}
          clusterLabel={nodeData.label || "MinIO Cluster"} defaultTab={mcpDefaultTab}
        />
      )}
    </>
  );
}
```

**Key observations:**
- `ClusterNodeData` is defined locally inside the file (duplicated — also in `types/index.ts`)
- Erasure set calculation (`erasureSetSize`) is duplicated here and in `PropertiesPanel.tsx` (as `computeErasureSetSize`)
- Context menus are inline/portaled — not using the shared `NodeContextMenu` component
- LB node lookup is done by convention: `${id}-lb` and `${id}-node-N`

---

## 2. Data Model / Types

### `frontend/src/types/index.ts` — Cluster-related types

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
  init_status: "pending" | "running" | "completed" | "failed";
  stopped_drives?: number[];
}

export interface ComponentNodeData {
  label: string;
  componentId: string;
  variant: string;
  config: Record<string, string>;
  health?: HealthStatus;
  networks?: string[];
  displayName?: string;
  labels?: Record<string, string>;
  groupId?: string | null;
}

// NOTE: This ClusterNodeData is missing ecParity, diskSizeTb, aistorTablesEnabled
// compared to the local interface in ClusterNode.tsx — DRIFT!
export interface ClusterNodeData {
  label: string;
  componentId: string;
  nodeCount: number;
  drivesPerNode: number;
  credentials: Record<string, string>;
  config: Record<string, string>;
  health?: HealthStatus;
  mcpEnabled?: boolean;
  // MISSING: ecParity, diskSizeTb, aistorTablesEnabled, ecParityUpgradePolicy
}

export interface DemoGroup {
  id: string;
  label: string;
  description?: string;
  color?: string;
  style?: string;
  position: { x: number; y: number };
  width?: number;
  height?: number;
  mode?: "visual" | "cluster";
  cluster_config?: Record<string, any>;
}
```

### `backend/app/models/demo.py` — Full source

```python
"""Pydantic models for demo definitions (saved/loaded as YAML)."""
from typing import Any
from pydantic import BaseModel

class NodePosition(BaseModel):
    x: float
    y: float

class NodeNetworkConfig(BaseModel):
    ip: str | None = None
    aliases: list[str] = []

class DemoNode(BaseModel):
    id: str                       # Unique within demo, e.g. "minio-1"
    component: str                # Component manifest ID, e.g. "minio"
    variant: str = "single"       # Which variant from the manifest
    position: NodePosition
    config: dict[str, str] = {}   # Override environment variables
    networks: dict[str, NodeNetworkConfig] = {}
    display_name: str = ""        # User-editable label
    labels: dict[str, str] = {}   # Key-value annotations
    group_id: str | None = None   # References a DemoGroup.id

class DemoEdge(BaseModel):
    id: str
    source: str                   # Node ID
    target: str                   # Node ID
    connection_type: str = "data" # Connection type (s3, jdbc, etc.)
    network: str = "default"      # Which network this edge traverses
    connection_config: dict[str, Any] = {}
    auto_configure: bool = True
    label: str = ""
    protocol: str = ""
    latency: str = ""
    bandwidth: str = ""
    source_handle: str | None = None
    target_handle: str | None = None

class DemoGroup(BaseModel):
    id: str
    label: str
    description: str = ""
    color: str = "#3b82f6"
    style: str = "solid"          # solid | dashed | dotted
    position: NodePosition
    width: float = 400
    height: float = 300
    mode: str = "visual"          # "visual" | "cluster"
    cluster_config: dict[str, Any] = {}  # e.g. {"drives_per_node": 1}

class DemoCluster(BaseModel):
    id: str
    component: str = "minio"          # "minio" (CE or AIStor edition via config)
    label: str = "MinIO Cluster"
    position: NodePosition
    node_count: int = 4               # Valid values: 4, 6, 8, 16
    drives_per_node: int = 1          # Valid values: 4, 6, 8, 12, 16
    credentials: dict[str, str] = {}  # root_user, root_password
    config: dict[str, str] = {}
    width: float = 280
    height: float = 200
    mcp_enabled: bool = True
    aistor_tables_enabled: bool = False
    ec_parity: int = 4
    ec_parity_upgrade_policy: str = "upgrade"  # "upgrade" or "ignore"
    disk_size_tb: int = 8              # Planning display only

class DemoStickyNote(BaseModel):
    id: str
    text: str = ""
    color: str = "#eab308"
    position: NodePosition
    width: float = 200
    height: float = 120

class SchematicChild(BaseModel):
    id: str
    label: str
    detail: str = ""
    color: str = "gray"

class DemoSchematicNode(BaseModel):
    id: str
    position: NodePosition
    label: str
    sublabel: str = ""
    variant: str = "generic"
    children: list[SchematicChild] = []
    parent_group: str | None = None
    width: int | None = None
    height: int | None = None

class DemoAnnotation(BaseModel):
    id: str
    position: NodePosition
    width: int = 300
    title: str = ""
    body: str = ""
    style: str = "info"
    step_number: int | None = None
    pointer_target: str | None = None
    collapsed: bool = False

class DemoNetwork(BaseModel):
    name: str
    subnet: str = "172.20.0.0/16"
    dns_suffix: str = "demo.local"
    driver: str = "bridge"

class DemoResourceSettings(BaseModel):
    default_memory: str = ""
    default_cpu: float = 0
    max_memory: str = ""
    max_cpu: float = 0
    total_memory: str = ""
    total_cpu: float = 0

class DemoDefinition(BaseModel):
    """Complete demo definition — serializable to/from YAML."""
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
    deploy_timeout_seconds: int | None = None
```

**Key observation:** `DemoCluster` has `ec_parity` (snake_case), but the React node data uses `ecParity` (camelCase). The serialization/deserialization between these formats happens in `frontend/src/api/client.ts` → `saveDiagram` which sends raw React Flow node data. The backend stores node data as-is in YAML.

---

## 3. Properties Panel — Cluster Section

### `frontend/src/components/properties/PropertiesPanel.tsx` (lines 850–1132)

This is the right panel that appears when a cluster node is selected.

**EC calculation helpers (defined at top of file):**
```typescript
function computeErasureSetSize(totalDrives: number): number {
  for (let d = 16; d >= 2; d--) {
    if (totalDrives % d === 0) return d;
  }
  return totalDrives;
}

function computeECOptions(setSize: number): { value: number; label: string }[] {
  const maxParity = Math.floor(setSize / 2);
  return Array.from({ length: maxParity - 1 }, (_, i) => {
    const p = i + 2;
    const data = setSize - p;
    return { value: p, label: `EC:${p} (${data} data + ${p} parity, tolerates ${p} drive failures)` };
  });
}
```

**Cluster properties panel (rendered when `selectedNode.type === "cluster"`):**

Fields rendered:
- **Label** — free text input → `updateCluster({ label })`
- **Edition** — select CE / AIStor → `updateCluster({ config: { MINIO_EDITION: v } })`; CE forces `mcpEnabled=false, aistorTablesEnabled=false`
- **Node Count** — select 2/4/6/8/16 → `updateCluster({ nodeCount })`, auto-adjusts drives and parity
- **Drives per Node** — select 1/2/4/6/8/12/16 → `updateCluster({ drivesPerNode })`, auto-adjusts parity
- **EC parity** — select from computed options → `updateCluster({ ecParity })`
- **Parity upgrade policy** — upgrade / ignore → `updateCluster({ ecParityUpgradePolicy })`
- **Disk size per node** — 1/2/4/8/16/32 TB (display only) → `updateCluster({ diskSizeTb })`
- **Root User** — `updateCluster({ credentials: { root_user } })`
- **Root Password** — `updateCluster({ credentials: { root_password } })`
- **Enable MCP AI Tools** — checkbox (AIStor only) → `updateCluster({ mcpEnabled })`
- **Enable AIStor Tables** — checkbox (AIStor only) → `updateCluster({ aistorTablesEnabled })` + auto-updates edges to Trino

**Capacity & resilience info card** (read-only display):
- Erasure sets, usable ratio, raw capacity, usable capacity, drive tolerance, read quorum, write quorum

**`updateCluster` mutates diagram store directly:**
```typescript
const updateCluster = (patch: Record<string, any>) => {
  setNodes(nodes.map((n) => n.id === selectedNodeId
    ? { ...n, data: { ...n.data, ...patch } }
    : n
  ));
};
```

**Important:** Changes are only saved to disk when `saveDiagram` is called (auto-save on deploy, or manual save).

---

## 4. Context Menus

### `frontend/src/components/canvas/nodes/NodeContextMenu.tsx`

Used for **regular ComponentNode** right-clicks (not cluster nodes). Props:

```typescript
interface Props {
  x: number;
  y: number;
  nodeId: string;
  componentId?: string;
  isCluster?: boolean;
  clusterLabel?: string;
  mcpEnabled?: boolean;
  instance: ContainerInstance | undefined;
  demoId: string;
  isRunning: boolean;
  nodeConfig?: Record<string, string>;
  onOpenTerminal: (nodeId: string) => void;
  onDeleteNode: (nodeId: string) => void;
  onOpenAdmin?: () => void;
  onOpenMcpTools?: () => void;
  onOpenAiChat?: () => void;
  onOpenSqlEditor?: () => void;
  onClose: () => void;
}
```

Dynamic menu items:
- Web UIs from `instance.web_uis`
- Terminal (if `instance.has_terminal`)
- Restart Container
- Start/Stop Generating (file-generator / data-generator only)
- MinIO Admin (if `isCluster && isRunning`)
- MCP Tools / AI Chat (if `mcpEnabled`)
- SQL Editor / Setup Tables (if componentId === "trino")
- Setup Dashboards (if componentId === "superset")
- Delete Component (if `!isRunning`)

**Cluster nodes do NOT use this component.** They have inline portaled context menus embedded directly in `ClusterNode.tsx` (two menus: per-node and cluster-level).

---

## 5. Docker Compose Generation

### `backend/app/engine/compose_generator.py` — Cluster expansion logic

**Function signature:**
```python
def generate_compose(
    demo: DemoDefinition,
    output_dir: str,
    components_dir: str = "./components"
) -> tuple[str, DemoDefinition]:
```

**DemoCluster expansion (lines 129–311):**

```python
for cluster in demo.clusters:
    drives = cluster.drives_per_node
    total_drives = cluster.node_count * drives
    # Auto-adjust to meet 4-drive EC minimum
    if total_drives < 4:
        drives = max(drives, 4 // cluster.node_count)

    alias_prefix = f"minio-{cluster.id.replace('-', '')}"
    # e.g. for id="minio-cluster-1" → alias_prefix="miniominocluster1"

    # Build expansion URL for single erasure-coded pool
    if drives > 1:
        expansion_url = f"http://{alias_prefix}{{1...{n}}}:9000/data{{1...{drives}}}"
    else:
        expansion_url = f"http://{alias_prefix}{{1...{n}}}:9000/data"

    # Inject synthetic DemoNode for each node (variant="cluster")
    for i, node_id in enumerate(generated_ids):
        synthetic_node = DemoNode(
            id=node_id,  # e.g. "minio-cluster-1-node-1"
            component=cluster.component,
            variant="cluster",
            config={
                "MINIO_ROOT_USER": cred_user,
                "MINIO_ROOT_PASSWORD": cred_pass,
                **cluster.config,
            },
        )
        synthetic_node.labels = {"_cluster_alias": f"{alias_prefix}{i + 1}"}

    # Inject NGINX LB node
    lb_node = DemoNode(id=f"{cluster.id}-lb", component="nginx", variant="load-balancer", ...)
    # Auto-generate load-balance edges from LB to each MinIO node

    # Register per-node commands
    server_cmd = ["server", expansion_url, "--console-address", ":9001"]
    for node_id in generated_ids:
        cluster_commands[node_id] = server_cmd
        cluster_credentials[node_id] = {
            "MINIO_ROOT_USER": cred_user,
            "MINIO_ROOT_PASSWORD": cred_pass,
            "MINIO_STORAGE_CLASS_STANDARD": f"EC:{cluster.ec_parity}",
            "MINIO_STORAGE_CLASS_RRS": "EC:1",
            "MINIO_STORAGE_CLASS_OPTIMIZE": cluster.ec_parity_upgrade_policy,
        }
```

**Group-based cluster expansion (legacy, lines 313–344):**
```python
for group in demo.groups:
    if group.mode != "cluster":
        continue
    # Uses peer_urls format instead of expansion notation
    peer_urls = [f"http://{project_name}-{n.id}:9000/data{{1...{drives}}}" for n in member_nodes]
    server_cmd = ["server"] + peer_urls + ["--console-address", ":9001"]
```

**Key difference:** `DemoCluster` uses MinIO's expansion notation `{1...N}` (single erasure pool). `DemoGroup(mode="cluster")` uses explicit peer URLs (less clean, legacy).

---

## 6. Template / Demo Persistence

### `frontend/src/stores/diagramStore.ts`

```typescript
interface DiagramState {
  nodes: Node[];
  edges: Edge[];
  selectedNodeId: string | null;
  selectedEdgeId: string | null;
  componentManifests: Record<string, ConnectionsDef>;
  pendingConnection: PendingConnection | null;
  isDirty: boolean;
  // ... methods
}
```

Key methods:
- `setNodes(nodes)` / `setEdges(edges)` — full replace
- `updateNodeHealth(nodeId, health)` — patches a single node's health in data
- `onConnect(connection)` — handles edge creation with connection type picker
- `setDirty(dirty)` — marks diagram as having unsaved changes
- `completePendingConnection(type, direction)` — finalizes edge type selection

**Cluster-specific logic in `onConnect`:**
```typescript
const isClusterToCluster = sourceNode.type === "cluster" && targetNode.type === "cluster";
if (isClusterToCluster) {
  // Only offers: cluster-replication, cluster-site-replication, cluster-tiering
}
// Cluster → Trino requires aistorTablesEnabled === true
if (sourceNode.type === "cluster" && targetComponentId === "trino") {
  if (!aistorEnabled) { toast.warning(...); return; }
  // Adds aistor-tables edge directly
}
```

### `frontend/src/stores/demoStore.ts`

```typescript
interface DemoState {
  demos: DemoSummary[];
  activeDemoId: string | null;
  instances: ContainerInstance[];
  clusterHealth: Record<string, string>;  // clusterId → "healthy"|"degraded"|"error"
  activeView: ViewType;
  currentPage: PageKey;
  cockpitEnabled: boolean;
  walkthroughOpen: boolean;
  resilienceProbes: ResilienceProbe[];
  faId: string;
  faIdentified: boolean;
  faMode: string;
  // ... setters
}
```

`clusterHealth` is populated from `fetchInstances` response (`cluster_health` field) and used by `ClusterNode` to show the quorum status badge.

### `frontend/src/api/client.ts` — Diagram save/load

```typescript
// Save: sends full node+edge array to backend
export const saveDiagram = (id: string, nodes: any[], edges: any[]) =>
  apiFetch<any>(`/api/demos/${id}/diagram`, {
    method: "PUT",
    body: JSON.stringify({ nodes, edges }),
  });

// Deploy: the deploy endpoint reads the saved diagram from disk
export const deployDemo = (id: string) =>
  apiFetch<...>(`/api/demos/${id}/deploy`, { method: "POST" });

// Instances polling: returns cluster_health alongside instances
export const fetchInstances = (demoId: string) =>
  apiFetch<{
    instances: ContainerInstance[];
    cluster_health?: Record<string, string>;
  }>(`/api/demos/${demoId}/instances`);
```

**Auto-save before deploy (in `Toolbar.tsx`):**
```typescript
const handleDeploy = async () => {
  const { nodes, edges } = useDiagramStore.getState();
  const groups = nodes.filter((n) => n.type === "group");
  const componentNodes = nodes.filter((n) => n.type !== "group");
  await saveDiagram(activeDemoId, [...componentNodes, ...groups], edges).catch(() => {});
  useDiagramStore.getState().setDirty(false);
  deployDemo(activeDemoId).catch(() => {});
};
```

### Template YAML format (DemoCluster example)

**`data/template-backups/site-replication-failover/v1.yaml`** (clusters section):

```yaml
clusters:
- id: minio-site-a
  component: minio
  label: MinIO Site A (Primary)
  position:
    x: 250
    y: 200
  node_count: 2
  drives_per_node: 1
  credentials:
    root_user: minioadmin
    root_password: minioadmin
  config: {}
  width: 280.0
  height: 200.0
  mcp_enabled: false
  # Note: ec_parity, ec_parity_upgrade_policy, disk_size_tb use DemoCluster defaults
- id: minio-site-b
  component: minio
  label: MinIO Site B (Backup)
  position:
    x: 700
    y: 200
  node_count: 2
  drives_per_node: 1
  credentials:
    root_user: minioadmin
    root_password: minioadmin
  config: {}
  width: 280.0
  height: 200.0
  mcp_enabled: false
edges:
- id: e-failover-site-a
  source: failover-gw
  target: minio-site-a
  connection_type: failover
  network: default
  auto_configure: true
  label: Primary
  connection_config:
    role: primary
```

**Full template with `clusters: []` (nodes-based)** — `demo-templates/bi-dashboard-lakehouse.yaml`:

```yaml
id: template-bi-dashboard-lakehouse
name: BI Dashboard — Lakehouse
nodes:
- id: minio-1
  component: minio
  position: { x: 100, y: 150 }
  display_name: MinIO
  config:
    MINIO_ROOT_USER: minioadmin
    MINIO_ROOT_PASSWORD: minioadmin
# ... other nodes
clusters: []
edges:
- id: e-datagen-minio
  source: data-gen
  target: minio-1
  connection_type: s3
  connection_config: { bucket: raw-data }
# ...
```

---

## 7. Erasure Set Calculation

Erasure set calculation is **duplicated** in two places:

### Frontend — `ClusterNode.tsx` (local)
```typescript
function erasureSetSize(totalDrives: number): number {
  for (let d = 16; d >= 2; d--) {
    if (totalDrives % d === 0) return d;
  }
  return totalDrives;
}
// Usage:
const setSize = erasureSetSize(totalDrives);
const dataShards = Math.max(0, setSize - ecParity);
const usableTb = totalDrives >= 4 && dataShards > 0
  ? Math.round(totalDrives * diskSizeTb * (dataShards / setSize))
  : null;
```

### Frontend — `PropertiesPanel.tsx` (local, differently named)
```typescript
function computeErasureSetSize(totalDrives: number): number {
  for (let d = 16; d >= 2; d--) {
    if (totalDrives % d === 0) return d;
  }
  return totalDrives;
}

function computeECOptions(setSize: number): { value: number; label: string }[] {
  const maxParity = Math.floor(setSize / 2);
  return Array.from({ length: maxParity - 1 }, (_, i) => {
    const p = i + 2;
    const data = setSize - p;
    return { value: p, label: `EC:${p} (${data} data + ${p} parity, tolerates ${p} drive failures)` };
  });
}

// Capacity display in info card:
const setSize = computeErasureSetSize(totalDrives);
const numSets = totalDrives / setSize;
const dataShards = setSize - parity;
const usableRatio = dataShards / setSize;
const rawTb = totalDrives * diskTb;
const usableTb = Math.round(rawTb * usableRatio);
const writeQuorum = dataShards === parity ? dataShards + 1 : dataShards;
```

**Both functions are identical in logic.** Should be extracted to a shared utility (e.g. `frontend/src/lib/erasure.ts`).

---

## 8. Container Lifecycle / Deploy

### `backend/app/api/deploy.py`

```python
@router.post("/api/demos/{demo_id}/deploy", response_model=DeployResponse)
async def deploy(demo_id: str):
    demo = _load_demo(demo_id)
    # Validation: license check, FA-mode readiness check
    # Drain guard: wait up to 30s for previous containers to be removed
    if not await wait_for_clean_state(demo_id, timeout=30):
        raise HTTPException(409, "Previous deploy still cleaning up — retry in a few seconds")
    # Kick off deploy_demo (docker_manager)
    running = await deploy_demo(demo, DATA_DIR, COMPONENTS_DIR, on_progress=on_progress)
```

### `backend/app/engine/docker_manager.py` — Deploy/Stop lifecycle

**Deploy flow (`deploy_demo`):**
1. Load previous cluster configs (`_load_cluster_configs`)
2. Detect changed clusters (`_detect_changed_clusters`)
3. For each changed cluster: `_remove_cluster_volumes(...)` — removes stale Docker volumes
4. `generate_compose(demo, output_dir)` — produces `docker-compose.yml`
5. `docker compose up -d` via subprocess
6. Save current cluster configs (`_save_cluster_configs`)

**Stop flow (`stop_demo` / `_cleanup_demo`):**
```python
async def _compose_down(compose_path, project_name, remove_volumes=True):
    cmd = ["docker", "compose", "-f", compose_path, "-p", project_name,
           "down", "--remove-orphans"]
    if remove_volumes:
        cmd.append("-v")
    # Runs with 180s timeout
```

**Stop = `docker compose down -v`** (removes volumes by default). This means redeploy with same config gets fresh volumes (correct behavior). Changed topology triggers explicit volume removal before compose up.

**Volume naming fix (key bug previously fixed):**
```python
async def _remove_cluster_volumes(project_name, cluster_id, old_node_count, old_drives, new_node_count, new_drives):
    for i in range(1, max_nodes + 1):
        node_id = f"{cluster_id}-node-{i}"
        vol_base = f"{project_name}-{node_id}-data"
        # Docker Compose prefixes named volumes with "{project_name}_"
        candidates.append(f"{project_name}_{vol_base}")   # real Docker name
        candidates.append(vol_base)                         # defensive fallback
        for d in range(1, max_drives + 1):
            candidates.append(f"{project_name}_{vol_base}{d}")
            candidates.append(f"{vol_base}{d}")
```

### `backend/app/api/instances.py` — Instance polling

```python
@router.get("/api/demos/{demo_id}/instances")
async def list_instances(demo_id: str):
    # 1. Check cluster health FIRST (authoritative override)
    cluster_health: dict[str, str] = {}
    cluster_node_health_override: dict[str, str] = {}
    if demo and demo.clusters:
        results = await asyncio.gather(*[_check_cluster_early(c.id) for c in demo.clusters])
        cluster_health = dict(results)
        for cluster in demo.clusters:
            if cluster_health.get(cluster.id) == "healthy":
                for i in range(1, cluster.node_count + 1):
                    cluster_node_health_override[f"{cluster.id}-node-{i}"] = "healthy"
    # 2. Per-container Docker health
    # 3. health = cluster_node_health_override.get(node_id, docker_health)
    # Returns: instances + cluster_health
```

---

## 9. File Tree Summary

```
frontend/src/
├── api/
│   └── client.ts               # All API calls: saveDiagram, deployDemo, fetchInstances, etc.
├── components/
│   ├── canvas/
│   │   ├── DiagramCanvas.tsx   # nodeTypes registration: {cluster: ClusterNode, ...}
│   │   ├── ConnectionTypePicker.tsx
│   │   └── nodes/
│   │       ├── ClusterNode.tsx        # Cluster visualization + inline context menus
│   │       ├── ComponentNode.tsx      # Single-container node
│   │       ├── GroupNode.tsx          # Visual group / legacy cluster group
│   │       ├── NodeContextMenu.tsx    # Context menu for ComponentNode
│   │       ├── StickyNoteNode.tsx
│   │       ├── AnnotationNode.tsx
│   │       └── SchematicNode.tsx
│   ├── properties/
│   │   └── PropertiesPanel.tsx  # Selected node properties (cluster section ~lines 850-1132)
│   ├── minio/
│   │   ├── MinioAdminPanel.tsx  # Admin modal (overview + logs tabs)
│   │   ├── McpPanel.tsx
│   │   └── McpChat.tsx
│   └── toolbar/
│       └── Toolbar.tsx          # Deploy button with auto-save + force sync
├── stores/
│   ├── diagramStore.ts          # React Flow nodes/edges state
│   ├── demoStore.ts             # Demo list, active demo, instances, clusterHealth
│   └── debugStore.ts            # Dev mode debug log entries
└── types/
    └── index.ts                 # Shared TS types (ClusterNodeData — has drift from ClusterNode.tsx)

backend/app/
├── api/
│   ├── deploy.py               # POST /api/demos/{id}/deploy
│   ├── instances.py            # GET /api/demos/{id}/instances (cluster health override)
│   ├── demos.py                # CRUD demos, diagram save/load
│   └── cluster_health.py       # Cluster health check endpoints
├── engine/
│   ├── compose_generator.py    # DemoCluster → docker-compose.yml expansion
│   ├── docker_manager.py       # deploy_demo, stop_demo, _remove_cluster_volumes
│   └── edge_automation.py      # Auto-configure init scripts from edges
└── models/
    └── demo.py                 # DemoDefinition, DemoCluster, DemoNode, DemoEdge, etc.

demo-templates/                 # Built-in YAML templates
data/
├── demoforge-{id}/             # Per-demo runtime data
│   ├── .cluster-configs.json   # Previous cluster topology (for volume cleanup detection)
│   └── {project_name}/         # Generated compose files, init scripts
└── template-backups/           # Snapshot of templates at deploy time
```

---

## 10. Existing Template with Cluster (DemoCluster format)

**`data/template-backups/site-replication-failover/v1.yaml`** — full clusters section:

```yaml
clusters:
- id: minio-site-a
  component: minio
  label: MinIO Site A (Primary)
  position:
    x: 250
    y: 200
  node_count: 2
  drives_per_node: 1
  credentials:
    root_user: minioadmin
    root_password: minioadmin
  config: {}
  width: 280.0
  height: 200.0
  mcp_enabled: false
  # Defaults from DemoCluster:
  # ec_parity: 4
  # ec_parity_upgrade_policy: "upgrade"
  # disk_size_tb: 8
  # aistor_tables_enabled: false

- id: minio-site-b
  component: minio
  label: MinIO Site B (Backup)
  position:
    x: 700
    y: 200
  node_count: 2
  drives_per_node: 1
  credentials:
    root_user: minioadmin
    root_password: minioadmin
  config: {}
  width: 280.0
  height: 200.0
  mcp_enabled: false
```

**React Flow node data for a cluster node** (as stored in `nodes[]` array in the diagram):

```json
{
  "id": "minio-cluster-1",
  "type": "cluster",
  "position": { "x": 250, "y": 200 },
  "width": 280,
  "height": 200,
  "data": {
    "label": "MinIO Cluster",
    "componentId": "minio",
    "nodeCount": 4,
    "drivesPerNode": 12,
    "ecParity": 4,
    "ecParityUpgradePolicy": "upgrade",
    "diskSizeTb": 8,
    "credentials": {
      "root_user": "minioadmin",
      "root_password": "minioadmin"
    },
    "config": {
      "MINIO_EDITION": "ce"
    },
    "mcpEnabled": false,
    "aistorTablesEnabled": false
  }
}
```

**Note on serialization:** The `demo.yaml` file stores clusters in `DemoCluster` format (snake_case). The React Flow canvas nodes array stores them as `type: "cluster"` nodes with camelCase data. The backend `demos.py` translates between these two representations on save (`PUT /api/demos/{id}/diagram`) and load (`GET /api/demos/{id}`).

---

## Key Issues / Drift to Fix in Refactor

| Issue | Location | Notes |
|-------|----------|-------|
| `ClusterNodeData` interface drift | `types/index.ts` vs `ClusterNode.tsx` | Missing `ecParity`, `diskSizeTb`, `aistorTablesEnabled`, `ecParityUpgradePolicy` |
| Erasure set calculation duplicated | `ClusterNode.tsx` (as `erasureSetSize`) and `PropertiesPanel.tsx` (as `computeErasureSetSize`) | Identical logic, different names |
| Context menus inline in ClusterNode | `ClusterNode.tsx` | ~300 lines of inline JSX; could be extracted to `ClusterContextMenu.tsx` |
| No `computeECOptions` in ClusterNode | `ClusterNode.tsx` | Only PropertiesPanel has the full EC options generator |
| `DemoGroup(mode="cluster")` is legacy | `compose_generator.py` lines 313–344 | Old pattern for group-based clusters, superseded by `DemoCluster` |
| `diskSizeTb` is frontend-only | `DemoCluster.disk_size_tb` | Backend model has the field but compose generation ignores it |
| LB node lookup by convention | `ClusterNode.tsx` | `${id}-lb` and `${id}-node-N` naming assumed everywhere |
