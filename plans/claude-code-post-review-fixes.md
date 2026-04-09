# Post-Implementation Review — Bugs & Required Fixes

## Issue Summary

After reviewing the current implementation at `http://localhost:3000/demo/6ed58635`, the following issues were identified. These must be fixed before proceeding to further phases.

---

## BUG 1 — Cluster Container Does Not Auto-Size to Fit Content (CRITICAL)

**Problem:** The `+ Add server pool` button and the capacity bar (with "54 TB / 72 TB raw 75% usable" text) render OUTSIDE the cluster node's React Flow boundary. The React Flow selection border (blue dashed line) clips at the bottom of the node tiles, leaving the add-pool button and capacity bar floating below on the canvas.

**Root Cause:** The cluster node's React Flow dimensions (`width`/`height`) are likely not recalculating when the internal content grows. The `NodeResizer` sets a min size, but the actual content (header + badges + pools + add-button + capacity bar) exceeds the stored height.

**Fix:** The cluster component must auto-calculate its required height based on its content and update the React Flow node's dimensions accordingly. Options:

1. **Preferred**: Use a `ResizeObserver` on the cluster's inner content wrapper. When content size changes (pool added, node count changed), update the node's height via `setNodes`:
   ```typescript
   const contentRef = useRef<HTMLDivElement>(null);
   useEffect(() => {
     if (!contentRef.current) return;
     const observer = new ResizeObserver(([entry]) => {
       const newHeight = entry.contentRect.height + padding;
       // Update node dimensions in React Flow
       setNodes(nodes => nodes.map(n => 
         n.id === id ? { ...n, height: newHeight } : n
       ));
     });
     observer.observe(contentRef.current);
     return () => observer.disconnect();
   }, []);
   ```

2. **Alternative**: Compute height from `serverPools`, `nodeCount`, `drivesPerNode` deterministically:
   ```
   headerHeight = 80
   badgesHeight = 30
   poolHeight(pool) = poolHeaderHeight + ceil(pool.nodeCount / nodesPerRow) * (nodeHeight + gap)
   addButtonHeight = 36
   capacityBarHeight = 30
   totalHeight = sum + padding
   ```

**ALL visual children** of the cluster (header, badges, pool containers, node tiles, add-pool button, capacity bar) MUST be inside the React Flow node boundary. Nothing should render outside.

---

## BUG 2 — Save Button Missing (CRITICAL)

**Problem:** The toolbar shows only `▶ Start` and `Destroy`. The `Save` button is completely gone — not hidden, not disabled, but absent. FAs cannot save their canvas changes.

**Current toolbar (stopped state):** `[Diagram] [Instances] | [▶ Start] [Destroy]`

**Expected (from spec Phase 10):** For a `stopped` state, Save should be hidden. But this demo's state is wrong — it shows `stopped` even though it was never deployed ("No running containers available", "Not deployed yet" in old context menu). This is actually the `not_deployed` state, which should show:

```
[Diagram] [Instances] | [💾 Save] [▶ Deploy] [📋 Save as Template]
```

**Root Cause:** The lifecycle state machine is incorrect. The implementation appears to conflate `not_deployed` with `stopped`. A demo that has never been deployed is NOT stopped — it's in design mode.

**Fix:** Implement the correct state machine:

```
STATES:
  not_deployed  — never deployed, or destroyed. THIS IS DESIGN MODE.
  deploying     — deploy in progress
  running       — containers active
  stopping      — stop in progress
  stopped       — containers paused, volumes preserved
  destroying    — destroy in progress

TRANSITIONS:
  not_deployed → deploying → running
  running → stopping → stopped
  running → destroying → not_deployed
  stopped → running (via start)
  stopped → destroying → not_deployed
```

**A demo that has never been deployed must show status `not_deployed`, NOT `stopped`.**

---

## BUG 3 — Complete Toolbar Lifecycle Visibility Matrix

The toolbar buttons MUST follow this exact matrix. No exceptions.

| State | Save | Deploy | Start | Stop | Destroy | Save as Template |
|-------|------|--------|-------|------|---------|-----------------|
| `not_deployed` | ✅ GREEN | ✅ GREEN | ❌ hidden | ❌ hidden | ❌ hidden | ✅ outlined |
| `deploying` | ❌ hidden | ❌ disabled "deploying..." | ❌ hidden | ❌ hidden | ❌ hidden | ❌ hidden |
| `running` | ❌ hidden | ❌ hidden | ❌ hidden | ✅ AMBER | ✅ RED | ❌ hidden |
| `stopping` | ❌ hidden | ❌ hidden | ❌ hidden | ❌ disabled "stopping..." | ❌ hidden | ❌ hidden |
| `stopped` | ❌ hidden | ❌ hidden | ✅ GREEN | ❌ hidden | ✅ RED | ❌ hidden |
| `destroying` | ❌ hidden | ❌ hidden | ❌ hidden | ❌ hidden | ❌ disabled "destroying..." | ❌ hidden |

**Key rules:**
- `Save` appears ONLY in `not_deployed` (design mode). It's green with a floppy icon.
- `Deploy` appears ONLY in `not_deployed`. It's green.
- `Start` appears ONLY in `stopped`. It resumes paused containers.
- `Stop` appears ONLY in `running`. It's amber (not red — it's a pause, not destruction).
- `Destroy` appears in `running` AND `stopped`. It's red.
- `Save as Template` appears ONLY in `not_deployed`.
- During transitions (`deploying`, `stopping`, `destroying`), the active button shows disabled with "..." text.

**Validation test cases:**

1. Fresh demo (never deployed) → toolbar shows: Save, Deploy, Save as Template
2. Click Deploy → toolbar shows: deploying... (disabled) → then: Stop (amber), Destroy (red)
3. Click Stop → toolbar shows: stopping... → then: Start (green), Destroy (red)
4. Click Start → toolbar shows: starting... → then: Stop (amber), Destroy (red)
5. Click Destroy → toolbar shows: destroying... → then: Save, Deploy, Save as Template (back to design)
6. From running, click Destroy → destroying... → then: Save, Deploy, Save as Template

---

## BUG 4 — Cluster Background Too Transparent

**Problem:** The cluster container background is nearly invisible — almost indistinguishable from the canvas background. It looks like the node tiles are floating freely rather than being contained in a cluster.

**Current:** `bg-primary/5` — 5% opacity, practically invisible.

**Fix:** Increase the background opacity to make the cluster visually distinct:

```css
/* Cluster container background */
background: var(--color-background-secondary);  /* or bg-zinc-100 in light / bg-zinc-900 in dark */
/* Alternatively: */
background: hsl(0 0% 95%);  /* light mode */
background: hsl(0 0% 12%);  /* dark mode */
```

The cluster should be a clearly visible "card" on the canvas — not invisible. Use `bg-zinc-50` (light) / `bg-zinc-900` (dark) at minimum, or the Tailwind `bg-muted` / `bg-secondary` class. The border should also be slightly more visible: `border-zinc-300` instead of `border-primary/30`.

---

## BUG 5 — Node Selection Not Visually Clear

**Problem:** Clicking a node tile shows its properties in the right panel ("NODE 1 — POOL 1"), but there is NO visual indication on the canvas which node is selected. No highlight ring, no background change, no border change.

**Fix:** The selected node tile MUST show a visible selection ring:

```css
/* Selected node tile */
.node-tile.selected .node-head {
  box-shadow: 0 0 0 2px hsl(212 100% 48%);  /* blue ring */
}
```

Similarly, selected pool and selected drive should show visual indicators:
- **Selected pool**: pool container border becomes solid (not dashed) with blue color
- **Selected node**: blue 2px ring on the node-head
- **Selected drive**: drive cell gets a permanent scaled-up state with a blue ring (not just on hover)

---

## BUG 6 — Node Tiles Too Light / Low Contrast

**Problem:** The node heads are light gray instead of the dark `#1d1d1d` specified in the spec. The M letter is light pink instead of bold `#C72C48`. The drive cells are nearly invisible light gray.

**Expected (from spec):**
- Node head: `background: #1d1d1d`, `color: #C72C48` (dark background, red M)
- Drive cells (not deployed): light gray with visible border/shape — NOT nearly invisible

**Fix:** Ensure the dark mode / light mode styling applies the correct colors. The node heads should be DARK (nearly black) in both light and dark mode — they represent physical server hardware. The `M` letter should be the MinIO red. Drives in "offline" state should be visible but muted (opacity 0.3, not 0.1).

---

## BUG 7 — No Node Labels

**Problem:** The node tiles don't show "node-1", "node-2", etc. beneath them. From the spec: each node tile should have a `node-label` text (8px, muted) below the drive grid.

**Fix:** Add the node label text beneath each NodeTile component:
```tsx
<div className="node-label text-[8px] text-muted-foreground text-center">
  node-{nodeIndex}
</div>
```

---

## BUG 8 — Subtitle Text Truncated

**Problem:** The cluster subtitle shows "6 nodes × 6 drives · EC:3 · 54 TB us:..." — truncated with "us:..." instead of showing "54 TB usable". The container is wide enough to fit the text.

**Fix:** Either:
1. Make the subtitle text `white-space: nowrap` and ensure the cluster container is wide enough
2. Or truncate properly with `text-overflow: ellipsis` on the full "usable" word, not mid-word

Preferred: show the full text. The cluster container should be at least 400px wide by default to fit the subtitle.

---

## BUG 9 — Context Menu Still Uses Old Format

**Problem:** Right-clicking a node shows the OLD context menu: "minio-cluster-1-node-1", "View in Instances", "Reset Cluster (Remove All Buckets)", "MinIO Admin", "Cancel". This is the pre-refactor menu.

**Expected (from spec Phase 4):** Config-time node context menu should show:
- "node-1 (pool 1)" header
- View node details
- View logs *(disabled, "deploy first")*
- Open terminal *(disabled, "deploy first")*

**Fix:** The `ClusterContextMenu.tsx` component (from Phase 4) has not been implemented yet, OR it's not being rendered. The old inline context menus in `ClusterNode.tsx` should have been replaced. Verify that the old context menu code has been removed and the new `ClusterContextMenu` is wired up.

---

## BUG 10 — Drive Grid Layout Issues

**Problem:** The drive grid cells are too small and too light. With 6 drives per node, the grid should show 2 rows of 3 (since 6/4 columns = 1.5, rounds to 2 rows with 4+2). But visually the drives are barely distinguishable.

**Fix:** 
- Drive cells should be 8×6px with 1.5px gap (from spec)
- Grid should always be 4 columns
- 6 drives = row 1: [■ ■ ■ ■], row 2: [■ ■ _ _] — 2 rows
- Offline drives: use `opacity: 0.3` not `opacity: 0.1`
- Add a subtle background to the drive grid container so it's visible as a unit

---

## BUG 11 — EC Settings Not at Pool Level / Wrong Options

**Problem:** The EC parity config does not appear in the pool-level properties panel. When clicking a node, the properties show "NODE 1 — POOL 1" with container name, status, and a drives grid — but no topology configuration (node count, drives/node, EC parity). The cluster-level panel shows aggregate stats (EC:3, 36 drives) but no config dropdowns either.

The EC options should be computed per-pool based on THAT POOL's `nodeCount × drivesPerNode`, NOT the total cluster-wide drive count. Currently the EC badge shows EC:3 but it's unclear whether this was computed from the pool's 36 drives or from something else.

**Expected behavior:**
- Pool properties panel should show: Node Count dropdown, Drives per Node dropdown, Disk Size dropdown, Disk Type dropdown, **EC Parity dropdown** (computed from THIS pool's setSize), Parity Upgrade Policy, Volume Path
- EC options should be computed from `setSize = erasureSetSize(pool.nodeCount * pool.drivesPerNode)`
- Example: 6 nodes × 6 drives = 36 drives → setSize=12, EC options: EC:2 through EC:6

**Fix:** The pool selection must trigger the `PoolPropertiesPanel.tsx` which renders the full config form. Currently clicking in the pool area selects either a node or the cluster — there's no click target for the pool itself. See BUG 13.

---

## BUG 12 — Context Menus Not Updated for Design Time Layers

**Problem:** All right-click context menus still show the OLD pre-refactor format:
- Right-click node: "minio-cluster-1-node-1", "View in Instances", "Reset Cluster", "MinIO Admin", "Cancel"
- Right-click cluster background: "MinIO Cluster", "Not deployed yet", "Delete Cluster", "Cancel"
- Right-click drive: same as node menu (drive-level menu not implemented)

None of these match the spec (Phase 4). The new context menus have not been implemented.

**Expected (config time / not deployed):**

Cluster right-click should show:
- Edit cluster settings
- Add server pool
- Configure load balancer
- Toggle MCP server
- Toggle AIStor tables
- *(separator)*
- Delete cluster

Pool right-click should show:
- Edit pool config
- Duplicate pool
- *(separator)*
- Remove pool (with confirmation, blocked if only pool)

Node right-click should show:
- View node details
- View logs *(disabled, "deploy first")*
- Open terminal *(disabled, "deploy first")*

Drive right-click should show:
- View drive details
- Simulate failure *(disabled, "deploy first")*

**Fix:** Implement `ClusterContextMenu.tsx` (Phase 4 of main spec). The old inline context menus in `ClusterNode.tsx` must be replaced entirely.

---

## BUG 13 — No Way to Select a Pool

**Problem:** Clicking inside the cluster selects either a node tile (if clicking near one) or the cluster itself (if clicking on empty space). There is NO click target for selecting a pool. The pool container (single pool, hidden border) has no clickable region that triggers pool selection.

This means:
- The pool properties panel (with EC config, node count, drives) is unreachable
- There's no way to right-click a pool for pool-level context menu
- The `selectedClusterElement: { type: "pool", poolId }` state is never set

**Fix for single-pool (hidden border):** Even when the pool border is hidden (single pool), there must be a clickable pool header area. Options:

1. **Always show a minimal pool header** — even for single pool, show "Pool 1 — 6 × 6 SSD drives" as a subtle clickable text above the node row. Clicking it selects the pool. This doubles as the entry point for pool config.

2. **Pool tab/pill above the node row** — render small clickable pill `[Pool 1]` that selects the pool when clicked. When 2+ pools, each has its own pill.

3. **Click the gap between badges and first node row** — register this area as the pool's click target. Less discoverable but doesn't add visual elements.

**Recommended: Option 1.** Always show the pool header text (even for single pool). When single pool, no dashed border but the header text "Pool 1 — 6 × 6 SSD drives" is visible and clickable. This makes pool selection discoverable.

---

## BUG 14 — Cannot Remove a Pool

**Problem:** The "+ Add server pool" button exists but there is no way to REMOVE a pool. The spec says pool right-click should include "Remove pool" (with confirmation, blocked if it's the only pool). But since pool context menu and pool selection don't work (BUG 12, BUG 13), removal is impossible.

**Fix:** Once pool selection and context menus are working:
- Pool right-click → "Remove pool" action
- Blocked with toast message if only 1 pool remaining
- Confirmation dialog required: "Remove Pool 2? This will remove N nodes from the cluster."
- After removal: cluster header subtitle, capacity bar, and aggregates all update

---

## Summary of All Fixes Needed

| # | Priority | Issue | Fix |
|---|----------|-------|-----|
| 2 | **P0** | Save button missing / lifecycle state wrong | `not_deployed` ≠ `stopped`. Fix state machine. |
| 3 | **P0** | Wrong toolbar buttons per state | Implement exact visibility matrix |
| 11 | **P0** | EC settings not at pool level / wrong options | Pool properties panel must be reachable and show per-pool EC config |
| 13 | **P0** | No way to select a pool | Always show pool header (even single pool) as click target |
| 1 | **P0** | Content outside cluster bounds | Auto-size cluster height to contain all children |
| 12 | **P1** | Context menus still old format | Implement ClusterContextMenu.tsx per Phase 4 |
| 14 | **P1** | Cannot remove a pool | Add "Remove pool" to pool context menu |
| 4 | **P1** | Cluster background invisible | Use `bg-zinc-100` / `bg-zinc-900` |
| 5 | **P1** | No node/pool/drive selection indicator | Add blue ring on selected element |
| 6 | **P1** | Node tiles too light | Dark heads `#1d1d1d`, bolder drives |
| 7 | **P1** | No node labels | Add "node-N" text below tiles |
| 8 | **P2** | Subtitle truncated | Ensure full text or proper ellipsis |
| 9 | **P2** | Old context menus showing | Wire new ClusterContextMenu |
| 10 | **P2** | Drive cells barely visible | Increase opacity, use spec dimensions |

**Fix order:** BUG 2+3 (lifecycle — blocking, can't save) → BUG 13 (pool selection — needed for everything) → BUG 11 (EC config — depends on pool selection) → BUG 1 (overflow) → BUG 12+14 (context menus + remove pool) → BUG 4+5+6+7 (visual polish) → BUG 8+10 (minor)
