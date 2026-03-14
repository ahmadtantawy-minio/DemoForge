# DemoForge UI Library Evaluation Report

**Date:** 2026-03-13
**Context:** React 18 + TypeScript + Tailwind CSS v3 + Vite 6
**Goal:** Adopt a component library that delivers a polished dark-theme developer-tool aesthetic (Vercel/Linear/Raycast tier) without fighting Tailwind or bloating the bundle.

---

## 1. Project Snapshot

DemoForge is a diagram-driven tool for generating containerized demo environments. The frontend today is ~17 components of raw Tailwind with no component library. The pain points visible in the existing code:

- **Dropdowns** hand-rolled with `useRef` + `mousedown` listeners (Toolbar template menu)
- **Context menus** hand-rolled with fixed positioning (NodeContextMenu)
- **Modals** built inline with `fixed inset-0` divs (ComponentCard web-UI overlay)
- **Selects** using native `<select>` elements with `bg-gray-700` overrides
- **Color palette** is functional but not cohesive — light theme leaking in several components (`bg-white`, `border-gray-200`) while the toolbar is already dark

The right library must eliminate that boilerplate while keeping the Tailwind class approach intact, since the diagram canvas and xterm terminals are styled separately.

---

## 2. Libraries Evaluated

### 2.1 shadcn/ui

**Model:** Copy-paste. The CLI copies component source files into `src/components/ui/`. You own the code.
**Foundation:** Radix UI primitives (unstyled, accessible) + Tailwind CSS variables.
**React 18:** Full support. Vite-specific init template available (`shadcn@latest init -t vite`).
**Tailwind compatibility:** Native. Components are Tailwind class strings; no separate CSS layer.
**Dark mode:** CSS variable-based. A single `.dark` class on `<html>` flips every token. Eight curated themes (default, slate, rose, violet, blue, etc.) available as copy-paste CSS blocks.
**Bundle impact:** Near-zero. Each component is local source code; tree-shaking is automatic. Radix primitives are individually installed per component — `@radix-ui/react-dialog` only lands when you add `dialog`.
**Component coverage for DemoForge:**

| Need | Available |
|---|---|
| Context menu | `ContextMenu` (Radix) |
| Dropdown | `DropdownMenu` (Radix) |
| Select | `Select` (Radix) |
| Dialog/Modal | `Dialog` (Radix) |
| Tabs | `Tabs` (Radix) |
| Tooltip | `Tooltip` (Radix) |
| Toast | `Sonner` integration |
| Badge | `Badge` |
| Button | `Button` |
| Card | `Card` |
| Input | `Input` |
| Separator | `Separator` |

**@xyflow/react compatibility:** No conflict. shadcn components are standard DOM elements; they have no opinion about SVG or canvas.
**Community health:** 109,000+ GitHub stars (highest of any evaluated library). Actively maintained. The single most-referenced React component library in 2025–2026 developer surveys.
**DX:** Excellent TypeScript — components are local so types are always visible and editable. Autocomplete works perfectly.
**Migration effort from raw Tailwind:** Low. Existing Tailwind classes on non-replaced elements continue working unchanged.
**Known issues:** None relevant to this project. The copy-paste model means updates require re-running the CLI per component, but this is rarely needed.

---

### 2.2 HeroUI (formerly NextUI)

**Model:** Installed npm package. `@heroui/react` or individual `@heroui/<component>` packages.
**Foundation:** React Aria + Tailwind Variants.
**React 18:** Fully supported and explicitly documented.
**Tailwind compatibility:** Uses Tailwind as its styling engine. Requires adding a HeroUI plugin and content glob to `tailwind.config`. Uses `tailwind-variants` to manage class conflicts.
**Dark mode:** First-class. `dark` class on `<html>` or `<HeroUIProvider>`. The dark theme is genuinely polished — used by many developer-facing products.
**Bundle impact:** Moderate. `@heroui/react` is the full bundle (~177k weekly downloads). Individual packages available to reduce size. Uses Framer Motion for animations — this adds ~40 kB gzipped to any project that doesn't already have it.
**Component coverage:** 210+ components. All DemoForge needs are covered.
**@xyflow/react compatibility:** No structural conflicts, but Framer Motion animation context can occasionally interact with SVG transforms in edge cases.
**Community health:** 28,374 GitHub stars. Solid and growing. The NextUI → HeroUI rename in 2025 was cleanly executed.
**DX:** Good TypeScript. Components are not local code — customization is done via Tailwind variants and the `classNames` prop, not source edits.
**Migration effort:** Medium. Requires wrapping the app in `HeroUIProvider` and modifying `tailwind.config`.
**Known issues:** Framer Motion dependency adds bundle weight. The `tailwind-variants` conflict resolution occasionally produces specificity surprises with custom classes.

---

### 2.3 Tremor (Tremor Raw)

**Model:** Copy-paste (similar to shadcn). Uses Tailwind CSS v4.
**Foundation:** Headless UI primitives + Tailwind.
**React 18:** Required (v18.2.0+).
**Tailwind compatibility:** Native — but **requires Tailwind CSS v4**. DemoForge currently uses Tailwind v3. This is a hard blocker without a Tailwind upgrade.
**Dark mode:** Supported via Tailwind's dark variant.
**Bundle impact:** Low (copy-paste model).
**Component coverage:** Strong for dashboards — excellent charts, data tables, KPI cards. Adequate for standard UI (buttons, badges, dialogs, tabs). Context menus are absent from the component set.
**@xyflow/react compatibility:** No conflict.
**Community health:** Growing but smaller than shadcn. Dashboard-focused; the aesthetic leans more toward analytics UIs than dev tools.
**DX:** Good. Same ownership model as shadcn.
**Migration effort:** Medium — but the Tailwind v4 requirement makes this high-risk without a deliberate upgrade plan. Vite integration guide was marked "Updating Soon" at time of evaluation.
**Verdict:** Eliminated due to Tailwind v4 requirement and missing context menu component.

---

### 2.4 Mantine

**Model:** Full npm package library. `@mantine/core` + PostCSS plugin.
**Foundation:** Own CSS Modules system. No Tailwind dependency.
**React 18:** Fully supported.
**Tailwind compatibility:** Coexistence is possible but explicitly noted as requiring care. Mantine uses its own PostCSS preset (`postcss-preset-mantine`) which defines CSS variables in the `:root`. These can conflict with Tailwind's `preflight` reset and base layer. A "Mantine + Tailwind" template exists but requires deliberate configuration to prevent class conflicts. In practice, you end up with two styling systems operating in parallel — this creates cognitive overhead and can produce specificity fights.
**Dark mode:** Mature and polished. `ColorSchemeScript` prevents flash-of-wrong-theme on SSR. The dark palette is well-crafted.
**Bundle impact:** Highest of the group. `@mantine/core` is ~1.18M weekly downloads but the package itself is substantial — it brings its own animation system, CSS variables, and a full design token set.
**Component coverage:** Comprehensive. Every component DemoForge needs is present, plus extras (RichTextEditor, DatePicker, Carousel, Charts via `@mantine/charts`).
**@xyflow/react compatibility:** No structural conflict, but CSS variable namespacing may require careful attention to avoid `--color-*` token collisions.
**Community health:** Highest weekly downloads of any evaluated library (1.18M/week). Excellent long-term maintenance record.
**DX:** Very good. Comprehensive TypeScript. Components are not customizable at source level — customization via `styles` prop and CSS Modules overrides.
**Migration effort:** High. Must add PostCSS config, wrap app in `MantineProvider`, and carefully audit for CSS conflicts with existing Tailwind classes.
**Verdict:** Excellent library but the dual-styling-system overhead is not worth it for a project already invested in Tailwind.

---

### 2.5 Radix Themes

**Model:** npm package. `@radix-ui/themes`.
**Foundation:** Radix UI primitives with an opinionated design system on top.
**React 18:** Fully supported.
**Tailwind compatibility:** Poor fit. Radix Themes ships its own complete design token system via CSS custom properties and does not use Tailwind at all. Using both means two parallel token systems. Custom Tailwind utilities will not reference Radix tokens automatically.
**Dark mode:** Supported via `<Theme appearance="dark">`. The visual quality is good — clean, minimal, professional.
**Bundle impact:** Moderate. Single package with comprehensive styles.
**Component coverage:** Good. Context menu is present and well-built. Dialog, Select, Tabs, Tooltip, Badge, Button, Card all available.
**@xyflow/react compatibility:** No conflict.
**Community health:** Backed by WorkOS/Radix team. Stable.
**DX:** Good TypeScript. The `ThemePanel` dev tool for real-time tweaking is a nice touch.
**Migration effort:** High. Requires wholesale adoption of the Radix token system, which conflicts with Tailwind's approach. Either Tailwind becomes decoration-only or you don't use Radix Themes fully.
**Verdict:** Eliminated — CSS token system conflicts with Tailwind-first project.

---

### 2.6 Park UI

**Model:** Copy-paste (similar to shadcn).
**Foundation:** Ark UI primitives + **Panda CSS** (not Tailwind).
**Tailwind compatibility:** None. Park UI is built for Panda CSS. While a CSS-only variant exists, it does not integrate with Tailwind's utility class system.
**Verdict:** Immediately eliminated for a Tailwind-first project.

---

### 2.7 daisyUI

**Model:** Tailwind CSS plugin. Semantic class names (`btn`, `badge`, `card`, etc.).
**Foundation:** Pure Tailwind plugin. No JS dependency.
**React 18:** Framework-agnostic — works with any React version.
**Tailwind compatibility:** Perfect. It IS a Tailwind plugin.
**Dark mode:** 30+ themes including dedicated dark variants. Theme switching via `data-theme` attribute.
**Bundle impact:** Minimal. CSS-only. Zero JS added to the bundle.
**Component coverage:** 100+ components. However, **interactive components** (dropdowns, dialogs, context menus, select) require separate JS handling — daisyUI provides the CSS classes but not the behavior. For dropdowns, you'd still need a headless library like Radix or Floating UI.
**@xyflow/react compatibility:** No conflict.
**Community health:** 40,472 stars. Popular and maintained.
**DX:** Simple — apply semantic class names. TypeScript support is minimal since it's CSS-only. No component props, no composition patterns.
**Migration effort:** Very low. Add the plugin, add themes. Existing Tailwind classes continue to work.
**Verdict:** Strong for visual styling but the lack of behavioral primitives means you'd still hand-roll dropdowns, context menus, and modals — exactly the problem being solved.

---

## 3. Comparison Table

| Criteria | shadcn/ui | HeroUI | Tremor | Mantine | Radix Themes | Park UI | daisyUI |
|---|---|---|---|---|---|---|---|
| **Tailwind native** | Native | Plugin required | Native (v4 only) | Parallel system | Not compatible | Not compatible | Perfect (is a plugin) |
| **Dark theme quality** | Excellent | Excellent | Good | Excellent | Good | Good | Good (30+ themes) |
| **Dark theme model** | CSS vars + `.dark` class | `dark` class | Tailwind `dark:` | `ColorSchemeScript` | `<Theme appearance>` | System preference | `data-theme` attr |
| **Bundle impact** | Near-zero (per component) | Medium + Framer Motion | Low | High | Medium | N/A | Zero (CSS only) |
| **React 18 support** | Full | Full | Full | Full | Full | Full | N/A (CSS only) |
| **TypeScript quality** | Excellent (local code) | Good | Good | Very Good | Good | Good | None |
| **Context menu** | Yes (Radix) | Yes | No | Yes | Yes | Yes | CSS only |
| **Dialog/Modal** | Yes | Yes | Yes | Yes | Yes | Yes | CSS only |
| **Select** | Yes (Radix) | Yes | Yes | Yes | Yes | Yes | CSS only |
| **Tabs** | Yes | Yes | Yes | Yes | Yes | Yes | CSS only |
| **Toast** | Yes (Sonner) | Yes | Yes | Yes | No | Yes | CSS only |
| **Tooltip** | Yes | Yes | Yes | Yes | Yes | Yes | CSS only |
| **@xyflow compat** | Full | Full | Full | Full | Full | N/A | Full |
| **Customization model** | Own the source | `classNames` prop | Own the source | `styles` prop | CSS vars | Own the source | Class names |
| **Migration effort** | Low | Medium | High (Tw v4) | High | High | N/A | Very low |
| **GitHub stars** | 109k | 28k | ~5k | 31k | ~4k | ~2k | 40k |
| **Weekly downloads** | 121k | 177k | ~30k | 1.18M | ~50k | ~10k | 565k |
| **Verdict** | **Recommended** | Runner-up | Eliminated | Eliminated | Eliminated | Eliminated | Supplement only |

---

## 4. Top Recommendations

### Recommendation 1 (Primary): shadcn/ui

**Why it wins for DemoForge:**

1. **Zero Tailwind friction.** Every component is Tailwind class strings. The existing `bg-gray-900`, `border-gray-700`, `text-sm` patterns in the codebase map directly to the shadcn token system. There is no second styling system to fight.

2. **You own the code.** When @xyflow/react needs a context menu at a specific SVG coordinate, you can edit `context-menu.tsx` directly. No prop-drilling workarounds, no `classNames` escape hatches.

3. **Per-component installation means zero waste.** DemoForge needs roughly 10 components: Button, Select, Dialog, ContextMenu, DropdownMenu, Tabs, Tooltip, Badge, Card, Input. Only those Radix primitives land in the bundle.

4. **The dark theme is developer-tool quality.** The `zinc` or `slate` base palette with accent color overrides produces exactly the Vercel/Linear aesthetic — dark grays with sharp neutral borders and a single bright accent.

5. **Context menu is production-grade.** `NodeContextMenu` is currently a fixed-position div with manual coordinate math. The Radix `ContextMenu` handles positioning, overflow detection, keyboard navigation, and focus management automatically.

**Pros:**
- Native Tailwind: zero config changes to `tailwind.config`
- Radix primitives: best-in-class accessibility (ARIA, keyboard nav, focus traps)
- Copy-paste model: no breaking library updates
- 109k GitHub stars: largest community, best ecosystem
- Vite installation template exists

**Cons:**
- Manual CLI per component (not a single `npm install`)
- Updates require re-running CLI (rare in practice)
- No built-in animation system (you add Framer Motion or CSS transitions yourself)

---

### Recommendation 2 (Runner-up): HeroUI

**Why it's second:**

HeroUI's dark theme quality is excellent — arguably better out-of-the-box than shadcn's defaults, leaning more toward a "designed" look with subtle gradients and glassy effects. The 210+ component count means less DIY. The individual `@heroui/<component>` packages allow selective installation.

The reason it loses to shadcn for DemoForge specifically:

- **Framer Motion dependency** (~40 kB gzipped) — DemoForge has no existing animation library; adding one for UI chrome is heavy.
- **Tailwind Variants** layer adds complexity when you need to override styles on drag handles or canvas-adjacent elements.
- **Less code ownership** — when a component needs non-standard behavior (e.g., a context menu anchored to an SVG element's bounding box), you work through the `classNames` API rather than editing source.

**Best fit if:** You prioritize visual polish over code control, or if Framer Motion was already in the project.

---

### Recommendation 3 (Supplement): daisyUI

Not as a replacement for shadcn, but as a **complementary plugin** for utility classes on non-interactive elements. DaisyUI's `badge`, `kbd`, `tooltip` (CSS-only), and `table` classes are zero-JS and composable with Tailwind. Used selectively alongside shadcn/ui, it adds visual vocabulary without bundle cost.

**Use specifically for:** Status badges in the sidebar palette, keyboard shortcut displays, table layouts in the control plane.
**Do not use for:** Any interactive component (dropdown, dialog, select) — use shadcn primitives instead.

---

## 5. Final Recommendation

**Adopt shadcn/ui as the primary component library.**

The combination of Tailwind-native styling, Radix primitive accessibility, zero bundle overhead, and full code ownership makes it the correct choice for a developer-tool frontend. The copy-paste model aligns with DemoForge's architecture — components live alongside the codebase rather than being black-box npm dependencies.

The dark theme approach: use the **`zinc`** base palette (the same slate-gray register Vercel/Linear use) with **`blue`** as the accent color (already used for the DemoForge brand in `text-blue-400`). This requires zero migration of existing color choices.

---

## 6. Migration Plan

### Phase 0: Setup (1–2 hours)

```bash
# From frontend/
npx shadcn@latest init -t vite
```

During init, select:
- Style: **Default** (not New York — cleaner for dev tools)
- Base color: **Zinc**
- CSS variables: **Yes**

This creates `src/components/ui/` and modifies `tailwind.config.ts` and `src/index.css` to add CSS variable definitions. Existing components are untouched.

Add dark mode to `tailwind.config.ts`:
```ts
darkMode: ["class"],
```

Add `dark` class to `<html>` in `index.html` (or wire to a toggle via `localStorage`).

### Phase 1: High-Impact Interactive Components (2–4 hours)

These eliminate the most hand-rolled boilerplate:

1. **`ContextMenu`** — Replace `NodeContextMenu.tsx` entirely. The Radix primitive handles positioning relative to the trigger element, removing the `{ x, y }` coordinate props and the `fixed` positioning hack.

   ```bash
   npx shadcn@latest add context-menu
   ```

2. **`DropdownMenu`** — Replace the template menu in `Toolbar.tsx` (the `showTemplates` state + `mousedown` listener + `ref` pattern).

   ```bash
   npx shadcn@latest add dropdown-menu
   ```

3. **`Dialog`** — Replace the inline modal in `ComponentCard.tsx` (the `fixed inset-0 bg-black/50` pattern for `WebUIFrame`).

   ```bash
   npx shadcn@latest add dialog
   ```

4. **`Select`** — Replace the native `<select>` in `Toolbar.tsx` (demo picker) and `PropertiesPanel.tsx` (variant picker).

   ```bash
   npx shadcn@latest add select
   ```

### Phase 2: Visual Polish Components (2–3 hours)

5. **`Badge`** — Replace `HealthBadge.tsx` with shadcn Badge variants. Map health states to `variant` prop values.

   ```bash
   npx shadcn@latest add badge
   ```

6. **`Tabs`** — Replace the view switcher in `Toolbar.tsx` (the Diagram/Control Plane toggle).

   ```bash
   npx shadcn@latest add tabs
   ```

7. **`Tooltip`** — Add tooltips to palette items (currently uses the native `title` attribute).

   ```bash
   npx shadcn@latest add tooltip
   ```

8. **`Card`** — Replace `ComponentCard.tsx` base div with shadcn Card for consistent borders, shadows, and dark-mode-aware backgrounds.

   ```bash
   npx shadcn@latest add card
   ```

### Phase 3: Forms and Input (1–2 hours)

9. **`Input`** — Replace inline-styled `<input>` elements in Toolbar and PropertiesPanel.

   ```bash
   npx shadcn@latest add input
   ```

10. **`Button`** — Replace all `<button className="px-2 py-1 bg-gray-700 rounded ...">` patterns. The `variant` and `size` props handle the visual states.

    ```bash
    npx shadcn@latest add button
    ```

### Phase 4: Notifications (future)

11. **Sonner toast** — For deploy/stop operation feedback (currently no toast system exists).

    ```bash
    npx shadcn@latest add sonner
    ```

### What to leave as plain Tailwind

- `DiagramCanvas.tsx` — @xyflow/react renders its own SVG; Tailwind classes on the wrapper div are sufficient
- `TerminalPanel.tsx` / `TerminalTab.tsx` — xterm.js owns its DOM; the panel chrome is simple enough as plain Tailwind
- `ComponentPalette.tsx` item list — drag-and-drop items are custom and have no interactive primitive equivalent
- All layout structure in `App.tsx` — flex/grid layout is Tailwind's native domain

---

## 7. Component Examples

### 7.1 Toolbar — Before vs After

**Before (current):**
```tsx
// Hand-rolled template dropdown with ref + mousedown listener
const [showTemplates, setShowTemplates] = useState(false);
const templateMenuRef = useRef<HTMLDivElement>(null);

useEffect(() => {
  if (!showTemplates) return;
  const handler = (e: MouseEvent) => {
    if (templateMenuRef.current && !templateMenuRef.current.contains(e.target as Node)) {
      setShowTemplates(false);
    }
  };
  window.addEventListener("mousedown", handler);
  return () => window.removeEventListener("mousedown", handler);
}, [showTemplates]);

// In JSX:
<div className="relative" ref={templateMenuRef}>
  <button
    onClick={() => setShowTemplates((v) => !v)}
    className="px-2 py-1 bg-gray-700 rounded text-xs hover:bg-gray-600"
  >
    From Template
  </button>
  {showTemplates && (
    <div className="absolute top-full left-0 mt-1 z-50 bg-white border border-gray-200 rounded-lg shadow-lg py-1 min-w-[200px]">
      {templates.map((t) => (
        <button key={t.id} onClick={() => handleCreateFromTemplate(t.id)}
          className="w-full text-left px-3 py-2 hover:bg-gray-100">
          <div className="text-sm font-medium text-gray-800">{t.name}</div>
          <div className="text-xs text-gray-500">{t.description}</div>
        </button>
      ))}
    </div>
  )}
</div>
```

**After (shadcn/ui):**
```tsx
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

// Demo selector — replaces native <select>
<Select value={activeDemoId ?? ""} onValueChange={(v) => setActiveDemoId(v || null)}>
  <SelectTrigger className="w-40 h-7 text-xs">
    <SelectValue placeholder="Select demo" />
  </SelectTrigger>
  <SelectContent>
    {demos.map((d) => (
      <SelectItem key={d.id} value={d.id}>{d.name}</SelectItem>
    ))}
  </SelectContent>
</Select>

// Template dropdown — replaces the entire ref/mousedown pattern
<DropdownMenu>
  <DropdownMenuTrigger asChild>
    <Button variant="ghost" size="xs">From Template</Button>
  </DropdownMenuTrigger>
  <DropdownMenuContent align="start" className="w-52">
    {templates.length === 0 ? (
      <div className="px-2 py-1.5 text-xs text-muted-foreground">
        No templates available
      </div>
    ) : (
      templates.map((t) => (
        <DropdownMenuItem
          key={t.id}
          onSelect={() => handleCreateFromTemplate(t.id)}
        >
          <div>
            <div className="font-medium">{t.name}</div>
            <div className="text-xs text-muted-foreground">{t.description}</div>
          </div>
        </DropdownMenuItem>
      ))
    )}
  </DropdownMenuContent>
</DropdownMenu>
```

**What was eliminated:** `useState(showTemplates)`, `useRef(templateMenuRef)`, the entire `useEffect` with `window.addEventListener("mousedown")`, and 30 lines of positioning/z-index CSS. Keyboard navigation and ARIA attributes are now automatic.

---

### 7.2 ComponentCard — Before vs After

**Before (current):**
```tsx
<div
  className="bg-white border border-gray-200 rounded-lg shadow-sm p-3 mb-3 cursor-pointer hover:border-blue-300 transition-colors"
  onClick={() => setSelectedNode(instance.node_id)}
>
  <div className="flex items-center justify-between mb-2">
    <div>
      <div className="font-semibold text-sm text-gray-800">{instance.node_id}</div>
      <div className="text-xs text-gray-500">{instance.component_id}</div>
    </div>
    <HealthBadge health={instance.health} />
  </div>
  {/* ... */}

  {/* Hand-rolled modal */}
  {activeFrame && (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center">
      <div className="w-4/5 h-4/5 flex flex-col bg-white rounded-lg overflow-hidden shadow-xl">
        <WebUIFrame path={activeFrame.path} name={activeFrame.name} onClose={() => setActiveFrame(null)} />
      </div>
    </div>
  )}
</div>
```

**After (shadcn/ui):**
```tsx
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

const healthVariant: Record<HealthStatus, "default" | "secondary" | "destructive" | "outline"> = {
  healthy: "default",    // green accent via CSS var override
  starting: "secondary",
  degraded: "outline",
  error: "destructive",
  stopped: "secondary",
};

<Card
  className="mb-3 cursor-pointer transition-colors hover:border-primary/50"
  onClick={() => setSelectedNode(instance.node_id)}
>
  <CardHeader className="p-3 pb-2 flex-row items-center justify-between space-y-0">
    <div>
      <div className="font-semibold text-sm">{instance.node_id}</div>
      <div className="text-xs text-muted-foreground">{instance.component_id}</div>
    </div>
    <Badge variant={healthVariant[instance.health]}>{instance.health}</Badge>
  </CardHeader>
  <CardContent className="p-3 pt-0 space-y-2">
    {instance.web_uis.length > 0 && (
      <div className="flex flex-wrap gap-1">
        {instance.web_uis.map((ui) => (
          <Button
            key={ui.name}
            variant="outline"
            size="sm"
            className="h-5 text-xs px-2"
            onClick={(e) => { e.stopPropagation(); setActiveFrame({ name: ui.name, path: ui.proxy_url }); }}
          >
            {ui.name}
          </Button>
        ))}
      </div>
    )}
    <div className="flex gap-1">
      {instance.has_terminal && (
        <Button variant="secondary" size="sm" className="h-5 text-xs px-2"
          onClick={(e) => { e.stopPropagation(); onOpenTerminal(instance.node_id); }}>
          Terminal
        </Button>
      )}
      <Button variant="outline" size="sm" className="h-5 text-xs px-2"
        disabled={restarting} onClick={handleRestart}>
        {restarting ? "Restarting..." : "Restart"}
      </Button>
    </div>
    <CredentialDisplay credentials={instance.credentials ?? []} />
  </CardContent>
</Card>

{/* Dialog replaces the fixed-position overlay */}
<Dialog open={!!activeFrame} onOpenChange={() => setActiveFrame(null)}>
  <DialogContent className="w-4/5 h-4/5 max-w-none flex flex-col p-0">
    <DialogHeader className="px-4 py-2 border-b">
      <DialogTitle className="text-sm">{activeFrame?.name}</DialogTitle>
    </DialogHeader>
    {activeFrame && (
      <WebUIFrame path={activeFrame.path} name={activeFrame.name} onClose={() => setActiveFrame(null)} />
    )}
  </DialogContent>
</Dialog>
```

**What was eliminated:** The hand-rolled modal (fixed positioning, backdrop, z-index management, click-outside handling, scroll-lock). The `Dialog` handles all of it, plus adds proper focus trapping, `Escape` key handling, and ARIA `role="dialog"` / `aria-modal` attributes.

---

### 7.3 NodeContextMenu — Before vs After

**Before (current):**
```tsx
// Receives {x, y} pixel coordinates, positions with fixed CSS
<div
  className="fixed z-50 bg-white border border-gray-200 rounded-lg shadow-lg py-1 min-w-[160px]"
  style={{ top: y, left: x }}
>
  {/* ... */}
</div>
```

**After (shadcn/ui):**
```tsx
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuLabel,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";

// Wrap the node renderer in ContextMenu instead of tracking coordinates manually
<ContextMenu>
  <ContextMenuTrigger asChild>
    <div className="react-flow__node-default ...">
      {/* node content */}
    </div>
  </ContextMenuTrigger>
  <ContextMenuContent className="w-44">
    <ContextMenuLabel className="text-xs text-muted-foreground">
      {nodeId}
    </ContextMenuLabel>
    <ContextMenuSeparator />
    {instance?.web_uis.map((ui) => (
      <ContextMenuItem key={ui.name} onSelect={() => window.open(proxyUrl(ui.proxy_url), "_blank")}>
        Open {ui.name}
      </ContextMenuItem>
    ))}
    {instance?.has_terminal && (
      <ContextMenuItem onSelect={() => onOpenTerminal(nodeId)}>
        Open Terminal
      </ContextMenuItem>
    )}
    {instance && (
      <ContextMenuItem className="text-destructive" onSelect={() => restartInstance(demoId, nodeId)}>
        Restart Container
      </ContextMenuItem>
    )}
    {!instance && (
      <div className="px-2 py-1.5 text-xs text-muted-foreground">Not deployed yet</div>
    )}
  </ContextMenuContent>
</ContextMenu>
```

**What was eliminated:** The `onContextMenu` handler that computes `{ x, y }`, passing those coordinates as props, the `fixed` positioning, and all `onClose` callback plumbing. The Radix primitive positions itself relative to the right-click point automatically, with viewport overflow detection.

---

## 8. CSS Variable Dark Theme Setup

After `shadcn init`, add to `src/index.css`:

```css
@layer base {
  :root {
    --background: 0 0% 100%;
    --foreground: 240 10% 3.9%;
    --card: 0 0% 100%;
    --card-foreground: 240 10% 3.9%;
    --popover: 0 0% 100%;
    --popover-foreground: 240 10% 3.9%;
    --primary: 217 91% 60%;        /* blue-500 — matches current brand */
    --primary-foreground: 0 0% 98%;
    --secondary: 240 4.8% 95.9%;
    --secondary-foreground: 240 5.9% 10%;
    --muted: 240 4.8% 95.9%;
    --muted-foreground: 240 3.8% 46.1%;
    --accent: 240 4.8% 95.9%;
    --accent-foreground: 240 5.9% 10%;
    --destructive: 0 72% 51%;
    --destructive-foreground: 0 0% 98%;
    --border: 240 5.9% 90%;
    --input: 240 5.9% 90%;
    --ring: 217 91% 60%;
    --radius: 0.375rem;
  }

  .dark {
    --background: 240 10% 3.9%;          /* near-black, like Vercel */
    --foreground: 0 0% 98%;
    --card: 240 10% 5.9%;                /* slightly lighter than bg */
    --card-foreground: 0 0% 98%;
    --popover: 240 10% 7%;
    --popover-foreground: 0 0% 98%;
    --primary: 217 91% 60%;              /* blue-500 — unchanged */
    --primary-foreground: 240 5.9% 10%;
    --secondary: 240 3.7% 15.9%;
    --secondary-foreground: 0 0% 98%;
    --muted: 240 3.7% 15.9%;
    --muted-foreground: 240 5% 64.9%;
    --accent: 240 3.7% 15.9%;
    --accent-foreground: 0 0% 98%;
    --destructive: 0 62% 50%;
    --destructive-foreground: 0 0% 98%;
    --border: 240 3.7% 15.9%;
    --input: 240 3.7% 15.9%;
    --ring: 217 91% 60%;
  }
}
```

Then in `index.html`:
```html
<html lang="en" class="dark">
```

This gives the zinc/slate dark palette with blue accent — matching the current `text-blue-400` brand color and the gray-900/gray-700 existing palette, with zero visual regression on already-dark components.

---

## 9. Summary

| | Decision |
|---|---|
| **Primary library** | shadcn/ui |
| **Installation** | `npx shadcn@latest init -t vite` |
| **Base palette** | Zinc dark |
| **Accent** | Blue (matches current brand) |
| **Supplement** | daisyUI for static badge/kbd classes (optional) |
| **Migration order** | ContextMenu → DropdownMenu → Dialog → Select → Button → Badge → Card |
| **Timeline estimate** | 8–12 hours for full migration of ~17 components |
| **Risk** | Low — copy-paste model means zero breaking dependency updates |
