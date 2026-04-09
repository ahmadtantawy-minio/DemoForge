# MinIO Cluster Multi-Pool & Lifecycle Refactor

## Overview

Refactor the MinIO cluster component from a flat cluster-level configuration to a **pool-driven architecture** where each server pool independently owns its erasure topology (node count, drives per node, disk size, disk type, EC parity, volume path). The cluster level retains only shared concerns: identity, credentials, load balancer, and feature flags.

This refactor also introduces:
- Visual drive grids on each node tile (4-column wrapped layout, individually right-clickable)
- Per-layer context menus with clean config-time vs runtime separation
- Backward-compatible migration for existing templates/demos (flat → pool-wrapped)
- Stop/start lifecycle (preserves state) vs destroy & redeploy (clean slate)
- Disk type indicator per pool (NVMe/SSD vs HDD) — display only, for demo storytelling

---

## Code Structure & Modularization Guidelines

**These rules apply to ALL phases. Every new file and every refactored file must follow them.**

### File Organization

The current `ClusterNode.tsx` is a ~350-line monolith containing rendering, context menus, state management, erasure calculation, and portal logic. This refactor MUST decompose it into focused modules.

**New directory structure:**

```
frontend/src/
├── components/
│   ├── canvas/
│   │   └── nodes/
│   │       ├── ClusterNode.tsx          ← SLIM orchestrator (~80-100 lines max)
│   │       └── cluster/                 ← NEW directory for cluster subcomponents
│   │           ├── ClusterHeader.tsx     ← Icon + title + summary + health badge
│   │           ├── FeatureBadges.tsx     ← LB, MCP, AIStor, EC badges row
│   │           ├── PoolContainer.tsx     ← Dashed pool wrapper + pool header + node row
│   │           ├── NodeTile.tsx          ← Node head + drive grid + label
│   │           ├── DriveCell.tsx         ← Single drive: 8×6px, hover, right-click
│   │           ├── CapacityBar.tsx       ← Aggregate capacity bar + text
│   │           ├── AddPoolButton.tsx     ← "+ Add server pool" button
│   │           └── ClusterContextMenu.tsx ← All 4 context menu variants
│   ├── properties/
│   │   ├── PropertiesPanel.tsx          ← Orchestrator (delegates to sub-panels)
│   │   └── cluster/                     ← NEW directory for cluster property sub-panels
│   │       ├── ClusterPropertiesPanel.tsx  ← Cluster-level: label, edition, creds, features
│   │       ├── PoolPropertiesPanel.tsx     ← Pool-level: topology, EC, capacity stats
│   │       ├── NodePropertiesPanel.tsx     ← Node-level: container info, drive grid
│   │       └── DrivePropertiesPanel.tsx    ← Drive-level: path, status, healing
│   └── minio/
│       ├── MinioAdminPanel.tsx           ← Unchanged
│       └── McpPanel.tsx                  ← Unchanged
├── lib/
│   ├── erasure.ts                       ← NEW: shared erasure set calculation
│   ├── clusterMigration.ts              ← NEW: flat → pool migration
│   └── clusterUtils.ts                  ← NEW: helper functions (instance filtering, naming, aggregates)
└── types/
    └── index.ts                         ← Updated: MinioServerPool, fix ClusterNodeData drift
```

### Modularization Rules

1. **Single Responsibility**: Each file does ONE thing. `NodeTile.tsx` renders a node tile. It does not compute erasure sets, filter instances, or manage context menu state.

2. **No Duplicated Logic**: The erasure calculator exists ONLY in `lib/erasure.ts`. Delete ALL copies from `ClusterNode.tsx` and `PropertiesPanel.tsx`. Import from the shared module.

3. **Component Size Limit**: No single component file exceeds ~150 lines of JSX. If it does, extract a subcomponent. The current 350-line `ClusterNode.tsx` must become an ~80-100 line orchestrator that composes subcomponents.

4. **Types Live in `types/`**: Delete the local `ClusterNodeData` interface from `ClusterNode.tsx`. The canonical type lives in `types/index.ts`. One source of truth.

5. **Context Menus are a Single Component**: `ClusterContextMenu.tsx` receives selection context (what was clicked) and demo state (running/stopped) and renders the appropriate menu variant. It does NOT live inline in `ClusterNode.tsx`.

6. **Props Down, Events Up**: Subcomponents receive data via props and communicate user actions via callback props (`onContextMenu`, `onClick`, `onPoolSelect`). No subcomponent reaches into Zustand stores directly — only the top-level `ClusterNode.tsx` orchestrator connects to stores.

7. **Utility Functions in `lib/`**: Instance filtering, container naming logic, pool aggregation, and migration all go in `lib/` — not scattered across components.

8. **Backend Follows Same Pattern**: The compose generator's cluster expansion logic should be in a dedicated function (e.g. `_expand_cluster_pools`) rather than inline in the main loop. Pool iteration is its own function.

### Import Conventions

```typescript
// Types — from types/
import type { MinioServerPool, ClusterNodeData, ContainerInstance } from "../../../types";

// Utilities — from lib/
import { computePoolErasureStats, computeECOptions } from "../../../lib/erasure";
import { migrateClusterData } from "../../../lib/clusterMigration";
import { getClusterInstances, getPoolInstances, computeClusterAggregates } from "../../../lib/clusterUtils";

// Subcomponents — from ./cluster/
import ClusterHeader from "./cluster/ClusterHeader";
import PoolContainer from "./cluster/PoolContainer";
import NodeTile from "./cluster/NodeTile";
```

---

## Current State Summary (from codebase investigation)

- **Frontend cluster type**: `ClusterNode.tsx` registers as React Flow node type `"cluster"` in `DiagramCanvas.tsx`
- **Node tiles are internal renders** (NOT React Flow child nodes) — simpler refactor path
- **Data model**: `ClusterNodeData` (frontend, camelCase) ↔ `DemoCluster` (backend Pydantic, snake_case)
- **Interface drift**: `types/index.ts` is missing `ecParity`, `diskSizeTb`, `aistorTablesEnabled`, `ecParityUpgradePolicy` that exist in `ClusterNode.tsx` local interface
- **Erasure calc duplicated**: identical logic in `ClusterNode.tsx` (`erasureSetSize`) and `PropertiesPanel.tsx` (`computeErasureSetSize`)
- **Context menus are inline portaled JSX** in `ClusterNode.tsx` (~300 lines), NOT using shared `NodeContextMenu`
- **Compose generation**: `compose_generator.py` uses MinIO expansion notation `http://alias{1...N}:9000/data{1...M}` — single pool
- **Stop = destroy**: `docker compose down -v` (removes volumes). No stop-and-preserve exists today
- **Container naming**: `{cluster_id}-node-{N}` for nodes, `{cluster_id}-lb` for LB
- **No schema versioning** on templates. `DemoCluster` Pydantic model uses defaults for missing fields
- **Volume cleanup**: `.cluster-configs.json` stores previous topology; `_remove_cluster_volumes` compares old vs new on deploy

---

## Phase 0 — Architecture Review (MANDATORY BEFORE CODE)

### 0.1 Files to Read

| # | File | What to Understand |
|---|------|-------------------|
| 1 | `frontend/src/components/canvas/nodes/ClusterNode.tsx` | Full component: rendering, context menus, state, handlers |
| 2 | `frontend/src/components/properties/PropertiesPanel.tsx` (lines 850–1132) | Cluster properties panel: all fields, updateCluster pattern, EC calc |
| 3 | `frontend/src/types/index.ts` | `ClusterNodeData` interface (has drift from ClusterNode.tsx local interface) |
| 4 | `frontend/src/stores/diagramStore.ts` | `setNodes`, `onConnect` (cluster-to-cluster edge logic), `isDirty` |
| 5 | `frontend/src/stores/demoStore.ts` | `clusterHealth`, `instances`, `activeDemoId` |
| 6 | `frontend/src/api/client.ts` | `saveDiagram`, `deployDemo`, `fetchInstances`, `stopInstance`, `startInstance`, `resetCluster`, `stopDrive`, `startDrive` |
| 7 | `backend/app/models/demo.py` | `DemoCluster` model (full Pydantic definition — this is the persistence model) |
| 8 | `backend/app/engine/compose_generator.py` (lines 129–311) | DemoCluster expansion: expansion_url, synthetic nodes, LB, server_cmd |
| 9 | `backend/app/engine/docker_manager.py` | `deploy_demo`, `_cleanup_demo`, `_compose_down`, `_remove_cluster_volumes` |
| 10 | `backend/app/api/deploy.py` | Deploy endpoint, drain guard |
| 11 | `backend/app/api/instances.py` | Instance polling, `cluster_health`, `cluster_node_health_override` |
| 12 | `frontend/src/components/minio/MinioAdminPanel.tsx` | Admin modal — uses `clusterId`, `nodes` array |
| 13 | `frontend/src/components/canvas/nodes/NodeContextMenu.tsx` | Shared context menu (reference for pattern) |
| 14 | One template YAML from `demo-templates/` that has clusters |

### 0.2 Risk Assessment — Answer Before Proceeding

**Data model risks:**

| # | Question | Expected | Risk if Different |
|---|----------|----------|-------------------|
| 1 | Does anything outside `ClusterNode.tsx` and `PropertiesPanel.tsx` directly read `data.nodeCount` or `data.drivesPerNode`? | Check `diagramStore.ts` `onConnect`, edge automation | Those references need updating too |
| 2 | Does `compose_generator.py` read `DemoCluster.ec_parity` directly? | Direct field access | Must switch to `get_pools()` accessor |
| 3 | Does `instances.py` use `cluster.node_count` for health override keys? | Yes — `for i in range(1, cluster.node_count + 1)` | Must iterate pools |
| 4 | Does `_remove_cluster_volumes` use `.cluster-configs.json` format? | Yes | Must update to pool-aware format |

**Compose generation risks:**

| # | Risk | Details |
|---|------|---------|
| 5 | Multi-pool server command | Must concatenate: `server http://pool1{1...N}/data{1...M} http://pool2{1...N}/data{1...M}`. ALL nodes get same command. |
| 6 | Container naming | Single pool keeps `{cluster_id}-node-{N}`. Multi-pool: `{cluster_id}-pool{P}-node-{N}`. Affects everywhere. |
| 7 | Instance filtering | `instances.filter(i => i.node_id.startsWith(\`${id}-node-\`))` BREAKS for multi-pool. |

**Lifecycle risks:**

| # | Risk | Details |
|---|------|---------|
| 8 | Stop = destroy today | Only `docker compose down -v`. New stop-preserve = new endpoint. |
| 9 | Dirty state | No mechanism. Topology change while stopped needs enforcement. |

**STOP. Share risk assessment. Do not proceed to Phase 1 until reviewed.**

---

## Phase 1 — Data Model & Migration

### 1.1 Extract Shared Erasure Calculator

**Create `frontend/src/lib/erasure.ts`:**

```typescript
export function computeErasureSetSize(totalDrives: number): number {
  for (let d = 16; d >= 2; d--) {
    if (totalDrives % d === 0) return d;
  }
  return totalDrives;
}

export function computeECOptions(setSize: number): { value: number; label: string }[] {
  const maxParity = Math.floor(setSize / 2);
  return Array.from({ length: maxParity - 1 }, (_, i) => {
    const p = i + 2;
    const data = setSize - p;
    return { value: p, label: `EC:${p} (${data} data + ${p} parity, tolerates ${p} failures)` };
  });
}

export interface ErasureStats {
  setSize: number; numSets: number; dataShards: number; parityShards: number;
  usableRatio: number; rawTb: number; usableTb: number;
  driveTolerance: number; readQuorum: number; writeQuorum: number;
}

export function computePoolErasureStats(
  nodeCount: number, drivesPerNode: number, ecParity: number, diskSizeTb: number
): ErasureStats {
  const totalDrives = nodeCount * drivesPerNode;
  const setSize = computeErasureSetSize(totalDrives);
  const numSets = totalDrives / setSize;
  const dataShards = Math.max(0, setSize - ecParity);
  const usableRatio = dataShards / setSize;
  const rawTb = totalDrives * diskSizeTb;
  const usableTb = totalDrives >= 4 && dataShards > 0 ? Math.round(rawTb * usableRatio) : 0;
  const writeQuorum = dataShards === ecParity ? dataShards + 1 : dataShards;
  return { setSize, numSets, dataShards, parityShards: ecParity, usableRatio, rawTb, usableTb, driveTolerance: ecParity, readQuorum: dataShards, writeQuorum };
}
```

Delete `erasureSetSize` from `ClusterNode.tsx`. Delete `computeErasureSetSize` and `computeECOptions` from `PropertiesPanel.tsx`. Both import from `lib/erasure.ts`.

### 1.2 Shared Utilities

**Create `frontend/src/lib/clusterUtils.ts`:**

```typescript
import type { MinioServerPool, ContainerInstance } from "../types";
import { computePoolErasureStats } from "./erasure";

/** Filter instances belonging to a cluster (handles both naming patterns). */
export function getClusterInstances(instances: ContainerInstance[], clusterId: string): ContainerInstance[] {
  return instances.filter(i =>
    (i.node_id.startsWith(`${clusterId}-node-`) || i.node_id.startsWith(`${clusterId}-pool`))
    && i.node_id !== `${clusterId}-lb`
  );
}

/** Filter instances belonging to a specific pool. */
export function getPoolInstances(instances: ContainerInstance[], clusterId: string, poolIndex: number, totalPools: number): ContainerInstance[] {
  if (totalPools === 1) {
    return instances.filter(i => i.node_id.startsWith(`${clusterId}-node-`));
  }
  return instances.filter(i => i.node_id.startsWith(`${clusterId}-pool${poolIndex}-node-`));
}

/** Compute aggregate stats across all pools. */
export function computeClusterAggregates(pools: MinioServerPool[]) {
  const stats = pools.map(p => computePoolErasureStats(p.nodeCount, p.drivesPerNode, p.ecParity, p.diskSizeTb));
  const ecValues = new Set(pools.map(p => p.ecParity));
  return {
    totalNodes: pools.reduce((s, p) => s + p.nodeCount, 0),
    totalDrives: pools.reduce((s, p) => s + p.nodeCount * p.drivesPerNode, 0),
    totalRawTb: stats.reduce((s, ps) => s + ps.rawTb, 0),
    totalUsableTb: stats.reduce((s, ps) => s + ps.usableTb, 0),
    usableRatio: stats.length > 0 ? stats.reduce((s, ps) => s + ps.usableRatio, 0) / stats.length : 0,
    ecSummary: ecValues.size === 1 ? `EC:${pools[0].ecParity}` : "mixed EC",
    maxDriveTolerance: Math.min(...stats.map(ps => ps.driveTolerance)),
  };
}

/** Generate container name for a node given pool context. */
export function nodeContainerName(clusterId: string, poolIndex: number, nodeIndex: number, totalPools: number): string {
  if (totalPools === 1) return `${clusterId}-node-${nodeIndex}`;
  return `${clusterId}-pool${poolIndex}-node-${nodeIndex}`;
}
```

### 1.3 New Frontend Types

**Update `frontend/src/types/index.ts`:**

```typescript
export type DiskType = "nvme" | "ssd" | "hdd";

export interface MinioServerPool {
  id: string;                        // "pool-1", "pool-2"
  nodeCount: number;                 // 2, 4, 6, 8, 16
  drivesPerNode: number;             // 1, 2, 4, 6, 8, 12, 16
  diskSizeTb: number;                // 1, 2, 4, 8, 16, 32
  diskType: DiskType;                // "nvme" | "ssd" | "hdd" — display only
  ecParity: number;                  // 2..setSize/2
  ecParityUpgradePolicy: string;     // "upgrade" | "ignore"
  volumePath: string;                // "/data"
}

// UPDATED: fixes drift, adds pool support
export interface ClusterNodeData {
  label: string;
  componentId: string;
  credentials: Record<string, string>;
  config: Record<string, string>;
  health?: HealthStatus;
  loadBalancer?: boolean;
  mcpEnabled?: boolean;
  aistorTablesEnabled?: boolean;
  serverPools?: MinioServerPool[];
  // DEPRECATED flat fields — detected on load, migrated, never written
  nodeCount?: number;
  drivesPerNode?: number;
  ecParity?: number;
  ecParityUpgradePolicy?: string;
  diskSizeTb?: number;
}
```

Delete the local `ClusterNodeData` interface from `ClusterNode.tsx`.

### 1.4 Frontend Migration

**Create `frontend/src/lib/clusterMigration.ts`:**

```typescript
import type { MinioServerPool, ClusterNodeData } from "../types";

export function migrateClusterData(data: any): ClusterNodeData {
  if (Array.isArray(data.serverPools) && data.serverPools.length > 0) return data;
  const pool: MinioServerPool = {
    id: "pool-1",
    nodeCount: data.nodeCount ?? 4,
    drivesPerNode: data.drivesPerNode ?? 4,
    diskSizeTb: data.diskSizeTb ?? 8,
    diskType: "ssd",  // default for migrated pools
    ecParity: data.ecParity ?? 4,
    ecParityUpgradePolicy: data.ecParityUpgradePolicy ?? "upgrade",
    volumePath: "/data",
  };
  const { nodeCount, drivesPerNode, diskSizeTb, ecParity, ecParityUpgradePolicy, ...rest } = data;
  return { ...rest, serverPools: [pool] };
}
```

Call in `diagramStore.ts` on node load for every `type === "cluster"` node.

### 1.5 Backend Migration

**Update `backend/app/models/demo.py`:**

```python
class DemoServerPool(BaseModel):
    id: str = "pool-1"
    node_count: int = 4
    drives_per_node: int = 4
    disk_size_tb: int = 8
    disk_type: str = "ssd"              # "nvme" | "ssd" | "hdd" — display only
    ec_parity: int = 4
    ec_parity_upgrade_policy: str = "upgrade"
    volume_path: str = "/data"

class DemoCluster(BaseModel):
    # ... existing fields kept for backward compat loading ...
    server_pools: list[DemoServerPool] = []

    def get_pools(self) -> list[DemoServerPool]:
        if self.server_pools:
            return self.server_pools
        return [DemoServerPool(
            node_count=self.node_count, drives_per_node=self.drives_per_node,
            disk_size_tb=self.disk_size_tb, ec_parity=self.ec_parity,
            ec_parity_upgrade_policy=self.ec_parity_upgrade_policy,
        )]
```

### 1.6 Validation

- [ ] Load existing flat demo → renders same as before (1 pool, hidden border)
- [ ] Load template YAML → migration wraps into pool with `diskType: "ssd"` default
- [ ] Save → YAML has `server_pools` with `disk_type` field
- [ ] Reload → no re-migration
- [ ] Compose generator: identical single-pool output
- [ ] Instance health override: works
- [ ] Volume cleanup: works
- [ ] No duplicated erasure code anywhere

---

## Phase 2 — Cluster Component Visual Refactor

### 2.1 Layout Specification (Pixel-Precise)

This section describes EXACTLY what the cluster component looks like on the React Flow canvas. Follow these dimensions precisely.

#### Overall Cluster Container

```
┌─────────────────────────────────────────────────────────┐  ← 1.5px solid border
│  padding: 14px                                           │     border-color: zinc-400/30
│                                                          │     border-radius: 14px
│  ┌─ HEADER ──────────────────────────────────────────┐  │     bg: zinc-50/5 (subtle tint)
│  │ [M] MinIO Cluster                                  │  │
│  │     2 pools · 8 nodes · 96 drives · 336 TB usable │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  [Load balancer] [MCP server] [AIStor tables] [EC:2]    │  ← badge row, gap: 4px
│                                                          │
│  ┌─ POOL 1 ──────────────────────────── 168 TB ──────┐  │  ← 1px dashed border (hidden if 1 pool)
│  │ ● Pool 1 — 4 × 12 NVMe drives                     │  │     border-radius: 10px
│  │                                                     │  │     padding: 10px
│  │  [NODE] [NODE] [NODE] [NODE]                       │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                          │
│  ┌─ POOL 2 ──────────────────────────── 168 TB ──────┐  │
│  │ ● Pool 2 — 4 × 12 HDD drives                      │  │
│  │                                                     │  │
│  │  [NODE] [NODE] [NODE] [NODE]                       │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                          │
│  [        + Add server pool        ]                     │  ← dashed border button
│                                                          │
│  ████████████████████████░░░░  ← capacity bar (3px h)   │
│  336 TB / 384 TB raw          88% usable                │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

#### Header Component (`ClusterHeader.tsx`)

```
┌──────────────────────────────────────────────┐
│ [34×34 dark icon]  MinIO Cluster             │  ← title: 14px, font-weight 500
│   with M letter     2 pools · 8 nodes ·...   │  ← subtitle: 11px, zinc-400
│   border-radius 7px                          │     white-space: nowrap (NO wrapping)
│   bg: #1d1d1d                                │
│   color: #C72C48                             │  Health badge (if running):
│                                    [●healthy]│  ← right-aligned, green dot + text
└──────────────────────────────────────────────┘
```

Subtitle format:
- 1 pool: `4 nodes × 12 drives · EC:2 · 168 TB usable`
- 2+ pools: `2 pools · 8 nodes · 96 drives · 336 TB usable`

#### Feature Badges Row (`FeatureBadges.tsx`)

```
[Load balancer] [MCP server] [AIStor tables] [EC:2] [NVMe+HDD]
```

- Each badge: `padding: 2px 7px`, `border-radius: 5px`, `font-size: 10px`
- Load balancer: blue accent (`bg-blue-50, text-blue-700, border-blue-200`)
- MCP server: purple accent
- AIStor tables: teal accent
- EC: neutral gray
- Disk type summary badge: shows `NVMe` if all pools same, `NVMe+HDD` if mixed — neutral gray
- Only render badges for enabled features. EC and disk type always shown.
- `display: flex; gap: 4px; flex-wrap: wrap; margin-bottom: 10px`

#### Pool Container (`PoolContainer.tsx`)

```
┌─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─┐  ← 1px dashed, zinc-400/50
│ ● Pool 1 — 4 × 12 NVMe drives       168 TB    │     border-radius: 10px
│                                                  │     padding: 10px
│  [NODE-1] [NODE-2] [NODE-3] [NODE-4]           │  ← node-row: flex, gap: 10px
│                                                  │
└─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─┘
```

Pool header left: green dot (6px) + "Pool N" (11px, semibold) + "— 4 × 12 NVMe drives" (11px, opacity 0.6)
Pool header right: "168 TB" (10px, muted)

**When `serverPools.length === 1`**: the pool container renders with `border: none`, `padding: 0`, no pool header. Just the node row. Visually identical to today.

**Disk type in pool header**: Append the disk type to the drives description. "4 × 12 NVMe drives" or "4 × 12 HDD drives" or "4 × 12 SSD drives". This uses the pool's `diskType` field.

#### Node Tile (`NodeTile.tsx`)

Each node tile is a self-contained component. It is NOT a React Flow node — it's a React component rendered inside the pool container.

```
     42px wide
    ┌──────────┐
    │    M     │  ← node-head: 42×28px, bg: #1d1d1d
    │          │     border-radius: 6px 6px 2px 2px (rounded top)
    ├──────────┤     color: #C72C48, font: 12px bold
    │ ■ ■ ■ ■ │  ← drive-grid: 42px wide, 4-column CSS grid
    │ ■ ■ ■ ■ │     gap: 1.5px, padding: 2px
    │ ■ ■ ■ ■ │     border-radius: 2px 2px 6px 6px (rounded bottom)
    └──────────┘     border: 0.5px solid zinc-300/20
      node-1         bg: zinc-100/50 (light surface)
    ↑ 8px font       
```

The node-head and drive-grid together form one visual unit (server head on top, disk shelf below).

**Drive grid column count is always 4.** Rows depend on drive count:
- 4 drives = 1 row (4×1)
- 8 drives = 2 rows (4×2)
- 12 drives = 3 rows (4×3)
- 16 drives = 4 rows (4×4)

Node tile height scales naturally with row count. This means a pool with 16 drives/node has taller tiles than one with 4 drives/node — which visually communicates "more drives."

**States:**
- Healthy (running): full opacity, drives colored by status
- Stopped node: 40% opacity, all drives gray
- Selected: 2px blue ring on node-head via `box-shadow: 0 0 0 2px`

#### Drive Cell (`DriveCell.tsx`)

```
  ┌────┐
  │    │  8px × 6px, border-radius: 1px
  └────┘
```

**Colors by status:**
- Healthy: `#1D9E75` (green)
- Failed: `#E24B4A` (red)
- Healing: `#EF9F27` (amber)
- Offline/stopped: `zinc-500` at 20% opacity

**Hover interaction:**
- `transform: scale(1.4)` — grows 40% on hover
- `box-shadow: 0 0 0 1px` (text-primary color) — outline ring appears
- `z-index: 2` — pops above adjacent drives
- `cursor: pointer`
- `transition: all 0.12s ease`

**Right-click (`onContextMenu`):**
- Calls `onDriveContextMenu(poolId, nodeIndex, driveIndex, event)` — event provides position for the menu

This hover + right-click behavior makes the 8×6px drive cells easily selectable despite their small size.

#### Capacity Bar (`CapacityBar.tsx`)

```
████████████████████████████░░░░░   ← 3px height, border-radius: 1.5px
336 TB / 384 TB raw     88% usable  ← 9px text, muted
```

Fill color: `#1D9E75` (green). Track: `zinc-300/20`. Width = `(usableTb / rawTb) * 100%`.

#### Add Pool Button (`AddPoolButton.tsx`)

```
┌─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─┐
│       + Add server pool           │  ← 10px text, zinc-500
└─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─┘
```

- `border: 1px dashed zinc-300/30`, `border-radius: 8px`, `padding: 5px`
- Hover: border darkens, text darkens
- Click: appends a new pool with cloned config from pool 1
- Only visible in config time (stopped). Hidden when running.

### 2.2 ClusterNode.tsx — Slim Orchestrator

After refactoring, `ClusterNode.tsx` should look approximately like this:

```tsx
export default function ClusterNode({ id, data, selected }: NodeProps) {
  const nodeData = migrateClusterData(data);
  const pools = nodeData.serverPools || [];
  const { instances, clusterHealth, activeDemoId } = useDemoStore();
  const isRunning = /* check demo status */;
  const clusterInstances = getClusterInstances(instances, id);
  const aggregates = computeClusterAggregates(pools);
  const [contextMenu, setContextMenu] = useState(/* ... */);

  return (
    <>
      <NodeResizer isVisible={selected} minWidth={240} minHeight={160} />
      <div className="cluster-shell" onClick={...} onContextMenu={...}>
        <Handles />
        <ClusterHeader label={nodeData.label} pools={pools} aggregates={aggregates} health={...} />
        <FeatureBadges loadBalancer={nodeData.loadBalancer} mcp={nodeData.mcpEnabled} aistor={nodeData.aistorTablesEnabled} pools={pools} />
        
        {pools.map((pool, idx) => (
          <PoolContainer key={pool.id} pool={pool} poolIndex={idx + 1}
            hidden={pools.length === 1} isRunning={isRunning}
            instances={getPoolInstances(clusterInstances, id, idx + 1, pools.length)}
            onPoolClick={() => selectPool(pool.id)}
            onPoolContextMenu={(e) => setContextMenu({ type: "pool", poolId: pool.id, x: e.clientX, y: e.clientY })}
          >
            {Array.from({ length: pool.nodeCount }, (_, ni) => (
              <NodeTile key={ni} poolId={pool.id} nodeIndex={ni + 1}
                drivesPerNode={pool.drivesPerNode} isRunning={isRunning}
                instance={/* match by container name */}
                onNodeContextMenu={(e) => setContextMenu({ type: "node", ... })}
                onDriveContextMenu={(driveIdx, e) => setContextMenu({ type: "drive", ... })}
              />
            ))}
          </PoolContainer>
        ))}

        {!isRunning && <AddPoolButton onClick={handleAddPool} />}
        <CapacityBar aggregates={aggregates} />
      </div>

      {contextMenu && <ClusterContextMenu {...contextMenu} isRunning={isRunning} onClose={() => setContextMenu(null)} />}
      {/* MinioAdminPanel + McpPanel modals — unchanged */}
    </>
  );
}
```

~80-100 lines. No inline menus, no erasure math, no instance filtering logic.

### 2.3 Validation

- [ ] Single-pool: screenshot comparison with current — no visual regression
- [ ] Drive grid correct for 1, 4, 8, 12, 16 drives (rows: 1, 1, 2, 3, 4)
- [ ] Drive cells: hover scale 1.4×, outline ring, right-clickable
- [ ] Multi-pool: dashed borders, pool headers with disk type label
- [ ] Feature badges: LB, MCP, AIStor, EC, disk type summary
- [ ] Pool header shows disk type: "4 × 12 NVMe drives"
- [ ] No header text wrapping
- [ ] Stopped nodes: 40% opacity, gray drives
- [ ] Health badge works when running
- [ ] `ClusterNode.tsx` is under 100 lines of JSX
- [ ] All subcomponents in `components/canvas/nodes/cluster/`
- [ ] No duplicated code between components

---

## Phase 3 — Properties Panel Refactor

### 3.1 Selection State

Add to `diagramStore.ts`:
```typescript
selectedClusterElement: null |
  { type: "cluster" } |
  { type: "pool"; poolId: string } |
  { type: "node"; poolId: string; nodeIndex: number } |
  { type: "drive"; poolId: string; nodeIndex: number; driveIndex: number }
```

### 3.2 Panel Mapping

| Click Target | Sub-panel Component | Fields |
|---|---|---|
| Cluster header | `ClusterPropertiesPanel.tsx` | Label, edition, image, credentials, LB toggle, MCP toggle, AIStor toggle, aggregate capacity |
| Pool container | `PoolPropertiesPanel.tsx` | Node count, drives/node, disk size, **disk type** (NVMe/SSD/HDD dropdown), EC parity, parity upgrade, volume path, erasure stats, pool health |
| Node tile | `NodePropertiesPanel.tsx` | Container name, status, pool, endpoint, drive health grid, log link |
| Drive cell | `DrivePropertiesPanel.tsx` | Drive path, mount, status, size, healing progress |

### 3.3 Disk Type Dropdown

In `PoolPropertiesPanel.tsx`, add between "Disk size per node" and "EC parity":

```
Disk type          [NVMe SSD ▼]
```

Options: `NVMe SSD`, `SSD`, `HDD`. Default: `SSD`.

This is display-only — it does not affect Docker Compose generation or container behavior. It's used for:
- Pool header label: "4 × 12 NVMe drives" vs "4 × 12 HDD drives"
- Feature badge: mixed disk type summary on cluster
- Demo storytelling: FA explains tiered storage (NVMe hot tier + HDD cold tier)

### 3.4 updatePool Function

```typescript
const updatePool = (poolId: string, patch: Partial<MinioServerPool>) => {
  setNodes(nodes.map(n => {
    if (n.id !== selectedNodeId) return n;
    const pools = (n.data.serverPools || []).map(p =>
      p.id === poolId ? { ...p, ...patch } : p
    );
    return { ...n, data: { ...n.data, serverPools: pools } };
  }));
};
```

### 3.5 Validation

- [ ] Click cluster header → shared fields panel
- [ ] Click pool → pool config with disk type dropdown
- [ ] Change disk type → pool header label updates immediately
- [ ] EC options recompute on topology change
- [ ] Aggregate capacity = sum of pools
- [ ] All properties sub-panels in `components/properties/cluster/`

---

## Phase 4 — Context Menus

### 4.1 Extract to `ClusterContextMenu.tsx`

**Create `frontend/src/components/canvas/nodes/cluster/ClusterContextMenu.tsx`:**

Props:
```typescript
interface Props {
  type: "cluster" | "pool" | "node" | "drive";
  poolId?: string;
  nodeIndex?: number;
  driveIndex?: number;
  x: number;
  y: number;
  clusterId: string;
  clusterData: ClusterNodeData;
  isRunning: boolean;
  demoId: string | null;
  instances: ContainerInstance[];
  consoleUrl: string | null;
  onClose: () => void;
  onOpenAdmin: () => void;
  onOpenMcp: (tab: string) => void;
  onSelectElement: (element: SelectedClusterElement) => void;
}
```

This single component renders the correct menu variant based on `type` and `isRunning`. Internally it can use helper functions or switch statements — but it's one file, one component.

### 4.2 Config-Time Menus (stopped)

| Layer | Actions |
|-------|---------|
| **Cluster** | Edit settings, Add pool, Configure LB, Toggle MCP, Toggle AIStor, *sep*, Delete cluster |
| **Pool** | Edit config, Duplicate pool, *sep*, Remove pool (blocked if only pool) |
| **Node** | View details, View logs *(disabled)*, Open terminal *(disabled)* |
| **Drive** | View details, Simulate failure *(disabled)* |

### 4.3 Runtime Menus (running)

| Layer | Actions |
|-------|---------|
| **Cluster** | Console, Admin, MCP, AI Chat, Instances, *sep*, Stop/Start/Restart all, *sep*, Reset cluster |
| **Pool** | Health, *sep*, Stop/Start/Restart pool, *sep*, Fail random drive, Fail N drives |
| **Node** | Logs, Terminal, Health, *sep*, Stop/Start/Restart, Network partition/Reconnect, *sep*, Fail/Heal all drives |
| **Drive** | Info, *sep*, Simulate failure, Trigger healing, Recover |

### 4.4 Rules

1. No "Remove node" or "Remove drive" — counts from pool config
2. Config: runtime actions disabled with "deploy first"
3. Runtime: structural actions hidden
4. Destructive: confirmation dialogs
5. Existing handlers preserved: `stopInstance`, `startInstance`, `resetCluster`, `stopDrive`, `startDrive`, `consoleUrl`, `MinioAdminPanel`, `McpPanel`

---

## Phase 5 — Stop/Start Lifecycle

### 5.1 Three Operations

| Action | Endpoint | Docker Command | Volumes |
|--------|----------|---------------|---------|
| Deploy | `POST /deploy` (existing) | `docker compose up -d` | Fresh |
| Stop | `POST /stop` (NEW) | `docker compose stop` | Preserved |
| Start | `POST /start` (NEW) | `docker compose start` | Preserved |
| Destroy | `POST /destroy` (rename) | `docker compose down -v` | Removed |

### 5.2 Toolbar

| Status | Buttons |
|--------|---------|
| `not_deployed` | Deploy (green) |
| `running` | Stop (amber), Destroy (red) |
| `stopped` | Start (green), Destroy (red) |

### 5.3 Dirty State

Stopped + canvas modified → warn, hide Start, show Destroy + Deploy only.

---

## Phase 6 — Compose Generation for Multi-Pool

### 6.1 Single Pool (backward compatible)

Unchanged. `get_pools()[0]` → same naming `{cluster_id}-node-{N}`, same expansion URL.

### 6.2 Multi-Pool

```python
pools = cluster.get_pools()
if len(pools) == 1:
    # Same as today
else:
    expansion_urls = []
    for p_idx, pool in enumerate(pools, start=1):
        pool_alias = f"{alias_prefix}pool{p_idx}"
        expansion_urls.append(f"http://{pool_alias}{{1...{pool.node_count}}}:9000/data{{1...{pool.drives_per_node}}}")
    server_cmd = ["server"] + expansion_urls + ["--console-address", ":9001"]
```

Container naming: `{cluster_id}-pool{P}-node-{N}` for multi-pool only.

Update: `_remove_cluster_volumes`, `.cluster-configs.json`, `instances.py` health override, LB upstream config.

---

## Phase 7 — Erasure per Pool

Already handled by Phase 1. Each pool calls `computePoolErasureStats()` independently. Cluster aggregates from `computeClusterAggregates()`.

---

## Implementation Order

```
Phase 0 → STOP & REVIEW risks
Phase 1 → Data model + migration + shared libs (foundation)
Phase 7 → Erasure per pool (trivial after Phase 1)
Phase 6 → Compose generation
Phase 2 → Visual refactor (biggest phase — follow layout spec exactly)
Phase 3 → Properties panel
Phase 4 → Context menus
Phase 5 → Stop/start lifecycle (independent, last)
```

## Phase 8 — Cluster Health Checking (Real MinIO API Health)

### 8.1 Problem with Current Approach

The current health check in `instances.py` uses `_check_cluster_early(cluster_id)` which checks Docker container status. A container can be `running` while MinIO is still initializing, has a quorum problem, or has degraded erasure sets. The health badge shows "healthy" when `mc admin info` would show errors.

**The health check must verify MinIO is actually responding and functional, not just that the Docker container process is alive.**

### 8.2 Health Check Strategy — Three Layers

| Layer | What it Checks | How | Frequency |
|-------|---------------|-----|-----------|
| **L1: Container alive** | Docker process running | `docker inspect` (existing) | Every poll cycle (~3s) |
| **L2: API responsive** | MinIO S3 API accepts requests | `HEAD /minio/health/live` on port 9000 | Every poll cycle (~3s) |
| **L3: Cluster quorum** | All erasure sets have quorum | `HEAD /minio/health/cluster` OR `mc admin info --json` | Every poll cycle (~3s) |

The health status should be the WORST of these three:
- All three pass → `healthy`
- L1 pass + L2 fail → `starting` (container up, API not ready)
- L1 pass + L2 pass + L3 fail → `degraded` (API works, quorum issues)
- L1 fail → `error`

### 8.3 MinIO Health Endpoints (Built-in)

MinIO exposes health endpoints that require NO authentication:

```
GET /minio/health/live     → 200 if server process is alive
GET /minio/health/ready    → 200 if server can serve requests (has quorum)
GET /minio/health/cluster  → 200 if cluster has write quorum on all erasure sets
                           → 503 if any erasure set lacks write quorum
```

These are HTTP endpoints on port 9000 — the same port as S3 API. They can be reached from the backend via Docker networking (using the container's internal hostname).

**Recommended approach: Use `/minio/health/cluster`** — it's the most comprehensive. A single HEAD request tells you if the cluster is truly functional.

### 8.4 Backend Implementation

**Update `backend/app/api/instances.py`** — replace or augment `_check_cluster_early`:

```python
import httpx

async def _check_cluster_health(cluster_id: str, project_name: str, pools: list, timeout: float = 2.0) -> str:
    """
    Check actual MinIO cluster health via /minio/health/cluster endpoint.
    Returns: "healthy" | "degraded" | "starting" | "error"
    """
    # Pick one node to query (LB or first node)
    lb_host = f"{project_name}-{cluster_id}-lb"
    health_url = f"http://{lb_host}:9000/minio/health/cluster"
    
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.head(health_url, timeout=timeout)
            if resp.status_code == 200:
                return "healthy"
            elif resp.status_code == 503:
                return "degraded"  # quorum issue
            else:
                return "starting"
    except httpx.ConnectError:
        return "starting"  # container up but MinIO not listening yet
    except httpx.TimeoutException:
        return "starting"
    except Exception:
        return "error"
```

**Fallback**: If the LB container isn't up yet, try querying the first MinIO node directly:
```python
    # Fallback to first node if LB unreachable
    first_node_host = f"{project_name}-{cluster_id}-node-1"
    health_url = f"http://{first_node_host}:9000/minio/health/cluster"
```

### 8.5 Per-Node Health

For individual node health (shown on node tiles), query each node's `/minio/health/live`:

```python
async def _check_node_health(container_name: str, timeout: float = 1.5) -> str:
    url = f"http://{container_name}:9000/minio/health/live"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.head(url, timeout=timeout)
            return "healthy" if resp.status_code == 200 else "degraded"
    except:
        return "error"
```

### 8.6 Drive Health

Drive health is detected by parsing `mc admin info --json` output or by monitoring the MinIO container logs for drive error messages. For the simulation use case (stopDrive/startDrive), the current approach of tracking `stopped_drives` on `ContainerInstance` is sufficient — the drive is "failed" because we explicitly stopped it.

For real drive status, the backend can periodically call:
```bash
docker exec {container} mc admin info local --json
```
And parse the `drives` array from the JSON output to get per-drive `state: "ok" | "offline"`.

### 8.7 Validation

- [ ] Deploy cluster → health shows "starting" briefly, then "healthy" once MinIO API responds
- [ ] Stop one node → cluster health shows "degraded" (L3 check fails or shows reduced quorum)
- [ ] Stop enough nodes to lose quorum → cluster health shows "degraded" with write quorum lost
- [ ] All nodes stopped → cluster health shows "error"
- [ ] Health status matches what `mc admin info` reports
- [ ] Individual node tiles reflect per-node health (not just cluster-level)

---

## Phase 9 — Erasure Configuration Verification

### 9.1 Problem

The properties panel computes erasure sets, usable capacity, and EC parity for display. But the Docker Compose generation must actually APPLY these settings to MinIO. If there's a mismatch between what the UI shows and what MinIO runs with, the demo is lying.

### 9.2 Where Erasure Settings Are Applied

MinIO erasure configuration is driven by THREE things:

| Setting | Source | Applied Via |
|---------|--------|------------|
| **Erasure set layout** | Determined automatically by MinIO from the server command (`{1...N}/data{1...M}`) | `server` command in compose |
| **EC parity level** | Set via env var `MINIO_STORAGE_CLASS_STANDARD=EC:N` | Container environment in compose |
| **Parity upgrade policy** | Set via env var `MINIO_STORAGE_CLASS_OPTIMIZE=upgrade\|ignore` | Container environment in compose |

### 9.3 Current Compose Generation (verify these are correct)

From `compose_generator.py`:
```python
cluster_credentials[node_id] = {
    "MINIO_STORAGE_CLASS_STANDARD": f"EC:{cluster.ec_parity}",
    "MINIO_STORAGE_CLASS_RRS": "EC:1",
    "MINIO_STORAGE_CLASS_OPTIMIZE": cluster.ec_parity_upgrade_policy,
}
```

**After multi-pool refactor**, this must use pool-level EC values:
```python
primary_pool = cluster.get_pools()[0]
cluster_credentials[node_id] = {
    "MINIO_STORAGE_CLASS_STANDARD": f"EC:{primary_pool.ec_parity}",
    "MINIO_STORAGE_CLASS_RRS": "EC:1",
    "MINIO_STORAGE_CLASS_OPTIMIZE": primary_pool.ec_parity_upgrade_policy,
}
```

Note: `MINIO_STORAGE_CLASS_STANDARD` is cluster-wide. If pools have different EC parity, the storage class env var uses pool 1's value. MinIO handles per-pool erasure set sizes internally based on the server command topology.

### 9.4 Verification After Deploy

After deploy, the backend should verify that MinIO actually applied the expected erasure config. Add a post-deploy verification step:

```python
async def _verify_erasure_config(cluster_id: str, project_name: str, expected_ec: int) -> bool:
    """Verify MinIO applied the correct EC parity after deploy."""
    container = f"{project_name}-{cluster_id}-node-1"
    try:
        result = await asyncio.create_subprocess_exec(
            "docker", "exec", container, "mc", "admin", "info", "local", "--json",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await asyncio.wait_for(result.communicate(), timeout=10)
        info = json.loads(stdout)
        # Check erasure set info matches expected
        # info.erasure.standard_parity should equal expected_ec
        return True
    except:
        return False  # verification failed, log warning but don't block
```

This is non-blocking — a failed verification logs a warning but doesn't stop the demo.

### 9.5 Frontend Erasure Consistency Check

The frontend `lib/erasure.ts` calculator and the compose generator MUST produce the same erasure set layout. The erasure set size is deterministic from `totalDrives`:

```
For totalDrives = nodeCount × drivesPerNode:
  setSize = largest divisor of totalDrives where divisor ≤ 16
  numSets = totalDrives / setSize
```

**Add a unit test** that runs the same test cases through both the frontend calculator and a Python equivalent to verify they match:

```
Input: 4 nodes × 12 drives = 48 drives → setSize=16, numSets=3, EC:2 → 14 data + 2 parity
Input: 4 nodes × 4 drives = 16 drives → setSize=16, numSets=1, EC:4 → 12 data + 4 parity
Input: 2 nodes × 1 drive = 2 drives → below 4 minimum, auto-adjusted
```

### 9.6 Validation

- [ ] Compose YAML contains correct `MINIO_STORAGE_CLASS_STANDARD=EC:N` matching pool config
- [ ] Compose YAML contains correct `MINIO_STORAGE_CLASS_OPTIMIZE` matching pool config
- [ ] After deploy, `mc admin info` shows matching erasure set layout
- [ ] Changing EC parity in properties panel → redeploy → `mc admin info` reflects new EC
- [ ] Frontend erasure calculator matches what MinIO actually applies
- [ ] Multi-pool: each pool's expansion URL produces the expected erasure set count

---

## Phase 10 — Toolbar & Lifecycle UI Visibility

### 10.1 Problem with Current Toolbar

Current state: ALL buttons visible ALL the time regardless of demo state.

```
[Diagram] [Instances] | [Save] [Deploy] [Stop] [Save as Template] | [icons...]
```

Issues:
- `Save` visible during runtime — FA shouldn't be editing canvas while running
- `Stop` visible when not deployed — confusing, does nothing
- `Deploy` visible when already running — could cause confusion
- `Save as Template` visible during runtime — shouldn't save a running state as template
- No visual distinction between design-time and runtime modes
- No `Start` (resume) button — doesn't exist yet
- No `Destroy` button — Stop does destroy today

### 10.2 New Toolbar — State-Driven

The toolbar buttons change based on demo lifecycle state. There are three states:

#### State: `not_deployed` (design time)

```
[Diagram] [Instances] | [💾 Save] [▶ Deploy] [📋 Save as Template] | [icons...]
                         green      green       outlined
```

- **Save**: GREEN, visible, enabled. This is design time — FA is building.
- **Deploy**: GREEN, visible, enabled. Ready to launch.
- **Save as Template**: OUTLINED, visible, enabled. Save current design.
- **Stop/Start/Destroy**: HIDDEN. Nothing to stop.
- **Status indicator**: `● not deployed` (gray dot) or no indicator

#### State: `running` (runtime)

```
[Diagram] [Instances] | [⏸ Stop] [💥 Destroy] | [icons...]
                         amber     red
```

- **Save**: HIDDEN. Can't edit while running. Canvas is read-only.
- **Deploy**: HIDDEN. Already running.
- **Stop**: AMBER, visible. Pauses containers, preserves data.
- **Destroy**: RED, visible. Tears down everything.
- **Save as Template**: HIDDEN. Don't save runtime state.
- **Status indicator**: `● running` (green dot, pulsing) in the header next to demo name
- **Canvas**: Interactions limited to VIEW + right-click (for runtime context menus). No drag, no add components, no delete. Properties panel shows info but config dropdowns are disabled.

#### State: `stopped` (paused, data preserved)

```
[Diagram] [Instances] | [▶ Start] [💥 Destroy] | [icons...]
                         green      red
```

- **Start**: GREEN, visible. Resume from where you left off.
- **Destroy**: RED, visible. Tear down and go back to design.
- **Save**: HIDDEN. Topology changes require destroy first.
- **Deploy**: HIDDEN. Use Start to resume, or Destroy + Deploy for fresh.
- **Save as Template**: HIDDEN.
- **Status indicator**: `● stopped` (amber dot) in header
- **Canvas**: Read-only (same as running). If FA modifies canvas → show dirty warning (see 10.3).

#### State: `stopped_dirty` (paused + canvas modified)

```
[Diagram] [Instances] | [💥 Destroy & Redeploy] | [icons...]
                         red
```

- When topology changes while stopped (pool added, node count changed), `Start` would resume the OLD topology. This is confusing.
- Hide `Start`. Show only `Destroy & Redeploy` as a combined action (destroys old, deploys new).
- Or: Show `Destroy` (red) + `Deploy` (green) separately.
- **Banner**: "Topology changed since last deploy. Destroy and redeploy to apply."

### 10.3 Toolbar Visual Design

```
DESIGN TIME:
┌─────────────────────────────────────────────────────────────────┐
│ [DF] DemoForge  user  demo-name  ● not deployed  ↕ Switch      │
│                                                                  │
│ [Diagram] [Instances] │ [💾 Save] [▶ Deploy] [📋 Template]  │ ⚙ │
│                        │  green     green       outlined      │    │
└─────────────────────────────────────────────────────────────────┘

RUNTIME:
┌─────────────────────────────────────────────────────────────────┐
│ [DF] DemoForge  user  demo-name  ● running  ↕ Switch            │
│                                    (green, pulsing)              │
│ [Diagram] [Instances] │ [⏸ Stop] [💥 Destroy]               │ ⚙ │
│                        │  amber    red                        │    │
└─────────────────────────────────────────────────────────────────┘

STOPPED:
┌─────────────────────────────────────────────────────────────────┐
│ [DF] DemoForge  user  demo-name  ● stopped  ↕ Switch            │
│                                    (amber)                       │
│ [Diagram] [Instances] │ [▶ Start] [💥 Destroy]               │ ⚙ │
│                        │  green     red                       │    │
└─────────────────────────────────────────────────────────────────┘
```

### 10.4 Status Indicator

Replace the current `● stopped` text-only indicator next to the demo name with a colored dot + label:

| State | Dot Color | Label | Animation |
|-------|-----------|-------|-----------|
| `not_deployed` | gray | `not deployed` | none |
| `deploying` | blue | `deploying...` | pulsing |
| `running` | green | `running` | subtle pulse (opacity 0.7→1.0, 2s cycle) |
| `stopping` | amber | `stopping...` | pulsing |
| `stopped` | amber | `stopped` | none |
| `destroying` | red | `destroying...` | pulsing |
| `error` | red | `error` | none |

### 10.5 Canvas Read-Only Mode

When demo is `running` or `stopped`:
- Disable drag-and-drop of components from palette
- Disable node deletion
- Disable edge creation/deletion
- Disable node position dragging (optional — some FAs like rearranging while running for presentation)
- Properties panel shows values but config dropdowns are disabled / read-only
- Right-click context menus still work (for runtime actions)

Implementation: Add a `isDesignTime` computed property to `demoStore` or `diagramStore`:
```typescript
const isDesignTime = !activeDemoId || demos.find(d => d.id === activeDemoId)?.status === "not_deployed";
```

Pass this to `DiagramCanvas.tsx` to conditionally set:
```tsx
<ReactFlow
  nodesDraggable={isDesignTime}
  nodesConnectable={isDesignTime}
  elementsSelectable={true}  // always — for viewing properties
  // ...
/>
```

### 10.6 Side Icon Bar Visibility

The right-side icons in the toolbar (terminal, settings, etc.) should also respect state:

| Icon | Design Time | Runtime | Stopped |
|------|------------|---------|---------|
| Terminal | Hidden (no containers) | Visible | Visible (can inspect stopped containers) |
| Debug | Dev mode only | Dev mode only | Dev mode only |
| Settings | Visible | Visible | Visible |
| Theme | Visible | Visible | Visible |
| Healthcheck | Hidden | Visible | Hidden |

### 10.7 Validation

- [ ] Not deployed: Save + Deploy + Template visible. Stop/Start/Destroy hidden.
- [ ] Running: Stop + Destroy visible. Save + Deploy + Template hidden.
- [ ] Stopped: Start + Destroy visible. Save + Deploy + Template hidden.
- [ ] Canvas read-only when running or stopped
- [ ] Properties panel read-only when running or stopped
- [ ] Status indicator shows correct color + label + animation
- [ ] Dirty state warning when canvas modified while stopped
- [ ] Debug button only visible in dev mode (never in FA mode)

---

## Updated Implementation Order

```
Phase 0  → STOP & REVIEW risks
Phase 1  → Data model + migration + shared libs
Phase 7  → Erasure per pool (trivial after Phase 1)
Phase 9  → Erasure config verification (ensures compose applies EC correctly)
Phase 6  → Compose generation multi-pool
Phase 8  → Health checking (real MinIO API health)
Phase 2  → Visual refactor (biggest — follow layout spec)
Phase 3  → Properties panel
Phase 4  → Context menus
Phase 10 → Toolbar & lifecycle UI visibility
Phase 5  → Stop/start lifecycle backend
```

Phase 10 and Phase 5 are tightly coupled — implement together. Phase 8 can be done alongside Phase 6 since both are backend. Phase 9 should follow Phase 6 immediately to verify compose output.

---

## Appendix: Template YAML Examples

### New format (2-pool with disk types):
```yaml
clusters:
- id: minio-cluster-1
  component: minio
  label: MinIO Tiered Cluster
  server_pools:
    - id: pool-1
      node_count: 4
      drives_per_node: 12
      disk_size_tb: 4
      disk_type: nvme
      ec_parity: 2
      ec_parity_upgrade_policy: upgrade
      volume_path: /data
    - id: pool-2
      node_count: 4
      drives_per_node: 16
      disk_size_tb: 16
      disk_type: hdd
      ec_parity: 4
      ec_parity_upgrade_policy: upgrade
      volume_path: /data
```

### Old format (auto-migrated on load):
```yaml
clusters:
- id: minio-cluster-1
  node_count: 4
  drives_per_node: 12
  ec_parity: 4
  # → migrated to server_pools[0] with diskType: "ssd" default
```
