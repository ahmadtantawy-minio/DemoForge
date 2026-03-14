# DemoForge Backlog Execution Plan

**Date:** 2026-03-13
**Scope:** 3 backlog items analyzed against current codebase state
**Codebase:** React 18 + TypeScript + @xyflow/react 12.6 + Zustand 5 + Tailwind CSS 3.4

---

## Executive Summary

Three backlog items were analyzed in order of implementation priority. Item #3 (edge removal) is the smallest and most self-contained change. Item #2 (component logos) is medium effort with a clear path. Item #1 (UI library) requires the most careful consideration -- the current Tailwind-only approach is adequate for this project's size, and a full UI library migration is not recommended; targeted improvements using shadcn/ui primitives are the better path.

**Recommended execution order:** #3 -> #2 -> #1 (or #3 and #2 in parallel, then #1)

---

## Item #3: Easy Way to Remove Connectors (Edges)

### Effort: Small (1-2 hours)

### Current State Analysis

- `DiagramCanvas.tsx:139-153` renders `<ReactFlow>` with `onEdgesChange={handleEdgesChange}` already wired up.
- `diagramStore.ts:26-27` already has `onEdgesChange` calling `applyEdgeChanges`, which natively handles edge removal changes.
- `AnimatedDataEdge.tsx:24-68` is a custom edge component but has **no delete button or interaction affordance**.
- There is **no** `deleteElements`, `onEdgesDelete`, or any edge deletion UI anywhere in the codebase.
- The existing `NodeContextMenu.tsx` handles node-level context menus but there is no equivalent for edges.

### Root Cause

@xyflow/react v12 supports edge deletion natively via two mechanisms:
1. **Keyboard:** Selecting an edge and pressing Backspace/Delete fires an `EdgeRemoveChange` through `onEdgesChange` -- this already works if edges are selectable.
2. **UI:** A delete button rendered inside the custom edge component using `EdgeLabelRenderer`.

The missing piece is that (a) the `<ReactFlow>` component does not pass props to make edges selectable/deletable by default, and (b) the custom `AnimatedDataEdge` has no delete affordance.

### Implementation Approach

**File changes:**

1. **`frontend/src/components/canvas/DiagramCanvas.tsx`** (lines 139-153)
   - Add `deleteKeyCode="Backspace"` (or `["Backspace", "Delete"]`) to `<ReactFlow>` props.
   - Edges become deletable on select + keypress. The existing `handleEdgesChange` at line 78 already calls `applyEdgeChanges` which handles `EdgeRemoveChange`.
   - Add `defaultEdgeOptions={{ selectable: true }}` if not already default.

2. **`frontend/src/components/canvas/edges/AnimatedDataEdge.tsx`** (lines 37-68)
   - Add a small "x" delete button inside the `<EdgeLabelRenderer>` block, positioned near the edge label.
   - On click, call `useReactFlow().deleteElements({ edges: [{ id }] })` (from `@xyflow/react`).
   - Show the button only on hover using CSS or a local state triggered by pointer events on the edge label area.

3. **`frontend/src/stores/diagramStore.ts`** -- No changes needed. `applyEdgeChanges` already handles removal.

**Minimal viable implementation (just keyboard delete):**

Only change #1 above -- add `deleteKeyCode` prop. This is a one-line change.

**Full implementation (keyboard + click button):**

Both changes #1 and #2. The edge delete button requires ~20 lines of JSX/CSS in `AnimatedDataEdge.tsx`.

### Risk Assessment

- **Low risk.** The store already handles edge removal via `applyEdgeChanges`. The only question is UX discoverability.
- **Testing:** Verify that `saveDiagram` is triggered after edge deletion (it will be, because `handleEdgesChange` at line 78 calls `debouncedSave`).

---

## Item #2: Download and Use Official Logos for Each Component

### Effort: Medium (3-5 hours)

### Current State Analysis

- **Component manifests** (`components/*/manifest.yaml`) all have an `icon` field with string values: `minio`, `nginx`, `prometheus`, `grafana`.
- **`ComponentSummary` type** (`frontend/src/types/index.ts:35-42`) already includes `icon: string` -- the backend returns this field.
- **`ComponentNode.tsx:36`** renders a hardcoded `<div className="text-2xl">📦</div>` emoji for ALL nodes -- the `icon` field is completely unused.
- **`ComponentPalette.tsx:46`** also renders a hardcoded `<span className="text-base">📦</span>` emoji.
- **No SVG/PNG assets exist** in `frontend/src/` -- zero image files found.
- **`ComponentCard.tsx`** in the control plane view also does not display any icon.

### Logo Sources (Official SVGs)

All four components have freely available official logos:

| Component  | Source | License | Format |
|-----------|--------|---------|--------|
| MinIO | https://min.io/resources (brand assets) or GitHub `minio/minio` repo | Apache 2.0 | SVG |
| NGINX | https://www.nginx.com/press/ (media resources) or Simple Icons | BSD-like / brand guidelines | SVG |
| Prometheus | https://github.com/cncf/artwork/tree/main/projects/prometheus | Apache 2.0 (CNCF) | SVG/PNG |
| Grafana | https://github.com/cncf/artwork/tree/main/projects/grafana or grafana.com/brand | Apache 2.0 (CNCF) | SVG/PNG |

**Recommended approach:** Use the CNCF artwork repository for Prometheus and Grafana (official, Apache-licensed). For MinIO and NGINX, use their official brand resources or Simple Icons (CC0).

### Implementation Approach

**File changes:**

1. **Create `frontend/src/assets/icons/` directory** with SVG files:
   - `minio.svg`
   - `nginx.svg`
   - `prometheus.svg`
   - `grafana.svg`

2. **Create `frontend/src/components/shared/ComponentIcon.tsx`** -- a mapping component:
   ```
   Props: { componentId: string; size?: "sm" | "md" | "lg" }
   ```
   - Import all SVGs statically (Vite handles SVG imports natively).
   - Map `componentId` -> SVG import.
   - Provide a fallback (the current 📦 emoji or a generic box icon) for unknown components.
   - This centralizes icon rendering for reuse across palette, canvas, control plane, and properties panel.

3. **`frontend/src/components/canvas/nodes/ComponentNode.tsx`** (line 36)
   - Replace `<div className="text-2xl">📦</div>` with `<ComponentIcon componentId={nodeData.componentId} size="md" />`.

4. **`frontend/src/components/palette/ComponentPalette.tsx`** (line 46)
   - Replace `<span className="text-base">📦</span>` with `<ComponentIcon componentId={c.id} size="sm" />`.

5. **`frontend/src/components/control-plane/ComponentCard.tsx`** (line 31-35)
   - Add `<ComponentIcon componentId={instance.component_id} size="md" />` in the header area.

6. **`frontend/src/components/properties/PropertiesPanel.tsx`** (line 52-55)
   - Add icon next to the component name display.

### Alternative: Dynamic Loading from Backend

Instead of bundling SVGs in the frontend, the backend could serve icons at `/api/registry/components/{id}/icon`. This would make adding new components automatic but adds an HTTP round-trip per icon. **Not recommended** for 4 components -- static imports are simpler and faster.

### Risk Assessment

- **Low risk.** This is purely additive -- no existing functionality changes.
- **License consideration:** CNCF artwork is Apache 2.0 (safe). MinIO logo is from their own repo (Apache 2.0). NGINX brand guidelines should be reviewed but SVG usage in a dev tool is generally fine.
- **Testing:** Visual verification only -- no logic changes.

### Dependencies

- None. Can be done in parallel with Item #3.

---

## Item #1: Consider Using a UI Library

### Effort: Large if full migration (2-4 days), Small-Medium if targeted (4-8 hours)

### Current State Analysis

The codebase uses **Tailwind CSS exclusively** with no component library. Key observations:

1. **Total UI components:** ~12 custom components, all hand-rolled with Tailwind utility classes.
2. **Pattern consistency:** The codebase has a consistent, simple visual language -- gray borders, rounded corners, basic hover states. No complex widgets.
3. **Interactive elements in use:**
   - Buttons (Toolbar, ComponentCard, NodeContextMenu) -- simple, styled inline
   - Select dropdowns (Toolbar:87-98, PropertiesPanel:60-67) -- native HTML `<select>`
   - Text inputs (Toolbar:102-108, PropertiesPanel:70-75) -- native HTML `<input>`
   - Context menus (NodeContextMenu) -- custom-built, minimal
   - Modals (ComponentCard:119-132) -- custom overlay for WebUI frames
   - Drag-and-drop cards (ComponentPalette:38-49) -- custom
4. **No complex UI patterns:** No tables, tabs (except terminal), dialogs with forms, toasts, tooltips, accordions, or other common library widgets.
5. **Bundle size:** Currently lean -- no UI lib overhead.

### Recommendation: Do NOT adopt a full UI library. Use shadcn/ui selectively.

**Rationale:**

The current codebase is ~12 components with simple UI needs. A full migration to Material UI, Chakra, or Ant Design would:
- Add 50-200KB to the bundle for widgets not needed
- Require restyling every component for marginal visual improvement
- Fight with the existing Tailwind approach rather than complementing it

**Instead, use shadcn/ui** -- which is not a library but a collection of copy-paste components built on Radix UI primitives + Tailwind CSS. This means:
- Zero runtime dependency (components are copied into your project)
- Full Tailwind compatibility (it IS Tailwind)
- Adopt only what you need, when you need it
- Easy to customize since you own the code

### Targeted Improvements (Recommended Scope)

Only adopt shadcn/ui primitives where the current UI has tangible gaps:

| Current Gap | shadcn/ui Component | Files Affected | Impact |
|------------|---------------------|----------------|--------|
| Context menus feel basic | `ContextMenu` (Radix) | `NodeContextMenu.tsx`, `DiagramCanvas.tsx` + new `EdgeContextMenu` | Better positioning, keyboard nav, animations |
| Native `<select>` looks inconsistent cross-browser | `Select` (Radix) | `Toolbar.tsx:87`, `PropertiesPanel.tsx:60` | Consistent styling |
| No toast/notification for deploy/stop actions | `Toast` / `Sonner` | `Toolbar.tsx` (deploy/stop handlers) | User feedback on async operations |
| Modal for WebUI is bare | `Dialog` (Radix) | `ComponentCard.tsx:119-132` | Proper focus trapping, esc-to-close, animation |
| No tooltips on icon-only elements | `Tooltip` (Radix) | Various buttons, palette items | Accessibility improvement |

### Implementation Approach (if proceeding)

**Phase 1: Setup (30 min)**

1. Install dependencies:
   ```
   npx shadcn@latest init
   ```
   This adds `tailwind-merge`, `clsx`, `class-variance-authority`, and configures `components.json`. It works with the existing Tailwind setup.

2. Configure `frontend/components.json` to output to `src/components/ui/`.

**Phase 2: Incremental adoption (pick 2-3 to start)**

1. **`npx shadcn@latest add context-menu`** -- Replace `NodeContextMenu.tsx` internals with Radix-based context menu. Add edge context menu for Item #3.
2. **`npx shadcn@latest add select`** -- Replace native `<select>` in `Toolbar.tsx` and `PropertiesPanel.tsx`.
3. **`npx shadcn@latest add dialog`** -- Replace the custom modal in `ComponentCard.tsx:119-132`.
4. **`npx shadcn@latest add tooltip`** -- Add tooltips to toolbar buttons and palette items.
5. **`npx shadcn@latest add sonner`** (toast) -- Add deployment success/failure notifications in `Toolbar.tsx`.

**Files modified per primitive:**

- `ContextMenu`: `NodeContextMenu.tsx`, new `EdgeContextMenu.tsx`, `DiagramCanvas.tsx`
- `Select`: `Toolbar.tsx`, `PropertiesPanel.tsx`
- `Dialog`: `ComponentCard.tsx`
- `Tooltip`: `Toolbar.tsx`, `ComponentPalette.tsx`, `ComponentNode.tsx`
- `Toast/Sonner`: `Toolbar.tsx`, `App.tsx` (provider)

### Risk Assessment

- **Medium risk** if doing full migration (scope creep, visual regression across all components).
- **Low risk** if doing targeted adoption (each primitive is independent, can be done incrementally).
- **Dependency concern:** shadcn/ui components are vendored (copied into project), so no runtime dependency risk. Radix primitives are stable and well-maintained.
- **Tailwind compatibility:** shadcn/ui is designed for Tailwind -- no conflicts with existing approach.

---

## Execution Order and Parallelization

```
                  Week 1
                  ------
  [Item #3: Edge Removal]  ||  [Item #2: Component Logos]
    (Small, 1-2 hrs)       ||    (Medium, 3-5 hrs)
           \                      /
            \                    /
             v                  v
        [Item #1: UI Library - Phase 1 Setup]
                   (30 min)
                      |
                      v
        [Item #1: UI Library - Phase 2 Selective Adoption]
                   (4-8 hrs, incremental)
```

### Dependency Map

| Item | Depends On | Blocks |
|------|-----------|--------|
| #3 Edge Removal | Nothing | Item #1 (context menu primitive can enhance the edge deletion UX) |
| #2 Component Logos | Nothing | Nothing (purely additive) |
| #1 UI Library | Ideally after #3 (so context menu work is not done twice) | Nothing |

### Parallelization

- **Items #3 and #2 CAN run in parallel.** They touch completely different files:
  - #3 touches: `DiagramCanvas.tsx`, `AnimatedDataEdge.tsx`
  - #2 touches: `ComponentNode.tsx`, `ComponentPalette.tsx`, `ComponentCard.tsx`, `PropertiesPanel.tsx`, new `assets/icons/` dir
  - Zero file overlap.

- **Item #1 should run AFTER #3.** If you adopt the shadcn/ui `ContextMenu` primitive, you would want to build the edge context menu with it from the start rather than building a custom one and then replacing it.

### Critical Path

```
Item #3 (edge removal, 1-2h) --> Item #1 Phase 2 (context-menu primitive, 2h)
Item #2 (logos, 3-5h)         --> independent, can slot anywhere
```

**Total estimated effort: 8-15 hours across all three items.**

---

## Summary Table

| # | Item | Effort | Risk | Priority | Parallelizable With |
|---|------|--------|------|----------|-------------------|
| 3 | Edge removal | Small (1-2h) | Low | 1 (highest) | #2 |
| 2 | Component logos | Medium (3-5h) | Low | 2 | #3 |
| 1 | UI library (targeted) | Medium (4-8h) | Low-Medium | 3 | None (after #3) |

---

## File Reference Index

All files analyzed for this plan:

- `frontend/package.json` -- current dependencies (no UI lib)
- `frontend/src/App.tsx` -- app layout structure
- `frontend/src/api/client.ts` -- API client, diagram save logic
- `frontend/src/types/index.ts:35-42` -- `ComponentSummary` with `icon: string` field
- `frontend/src/types/index.ts:82-88` -- `ComponentNodeData` (no icon field)
- `frontend/src/stores/diagramStore.ts:26-27` -- `onEdgesChange` with `applyEdgeChanges`
- `frontend/src/components/canvas/DiagramCanvas.tsx:139-153` -- ReactFlow mount, no `deleteKeyCode`
- `frontend/src/components/canvas/nodes/ComponentNode.tsx:36` -- hardcoded 📦 emoji
- `frontend/src/components/canvas/edges/AnimatedDataEdge.tsx:37-68` -- no delete affordance
- `frontend/src/components/canvas/nodes/NodeContextMenu.tsx` -- node-only context menu
- `frontend/src/components/palette/ComponentPalette.tsx:46` -- hardcoded 📦 emoji
- `frontend/src/components/toolbar/Toolbar.tsx:87-98` -- native `<select>` element
- `frontend/src/components/control-plane/ComponentCard.tsx` -- no component icon
- `frontend/src/components/properties/PropertiesPanel.tsx:52-55` -- no component icon
- `components/minio/manifest.yaml:4` -- `icon: minio`
- `components/nginx/manifest.yaml:4` -- `icon: nginx`
- `components/prometheus/manifest.yaml:4` -- `icon: prometheus`
- `components/grafana/manifest.yaml:4` -- `icon: grafana`
