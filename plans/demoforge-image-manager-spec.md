# DemoForge — UI Navigation Rework + Image Manager + Template Size Spec

## Overview

This spec covers two things that ship together:
1. A navigation rework that introduces a persistent left sidebar and a home landing page
2. The Image Manager as a dedicated page, plus template size indicators

Build in order. Validate each phase before starting the next.

---

## Context

- React 18 + TypeScript + Vite 6, `@xyflow/react` v12, Zustand v5, shadcn/ui + Tailwind zinc dark
- FastAPI backend port 9210, Pydantic v2
- Component manifests: `components/{name}/manifest.yaml`
- API routers: `backend/app/api/`
- Frontend stores: `frontend/src/stores/`
- Always read and update `plans/backlog.md` before and after each phase

---

## Phase 1 — App shell: left nav + routing

### Goal
Replace the current single-view layout with a multi-page shell. The existing canvas/designer view becomes one page within that shell.

### New routing structure

Use React state-based routing (no React Router needed — this is a single-user local tool). Add a `currentPage` field to `demoStore`.

Pages:
| Key | Component | Notes |
|-----|-----------|-------|
| `home` | `HomePage` | New — default on launch |
| `designer` | `DesignerPage` | Existing canvas, wrapped |
| `templates` | `TemplatesPage` | Promoted from modal/overlay |
| `images` | `ImagesPage` | New |
| `settings` | `SettingsPage` | Existing settings, wrapped |

### File: `frontend/src/stores/demoStore.ts`

Add to store state:
```typescript
currentPage: 'home' | 'designer' | 'templates' | 'images' | 'settings'
setCurrentPage: (page: PageKey) => void
```

Default: `'home'`

### File: `frontend/src/App.tsx`

Restructure the root layout:

```tsx
<div className="flex h-screen w-screen overflow-hidden bg-zinc-950">
  <AppNav />                          {/* new — 52px left strip */}
  <main className="flex-1 overflow-hidden">
    {currentPage === 'home'      && <HomePage />}
    {currentPage === 'designer'  && <DesignerPage />}
    {currentPage === 'templates' && <TemplatesPage />}
    {currentPage === 'images'    && <ImagesPage />}
    {currentPage === 'settings'  && <SettingsPage />}
  </main>
</div>
```

Remove any existing top-level toolbar that was used for navigation (keep canvas-specific toolbar — see Phase 2).

### File: `frontend/src/components/nav/AppNav.tsx` (new)

Narrow left nav strip, 52px wide, full height.

Structure (top to bottom):
- DemoForge logo mark (top, 30×30px teal square with 4-dot grid icon)
- Nav items (icon + label below, 36×36px clickable area):
  - Home — `Home` icon (lucide)
  - Designer — `LayoutDashboard` icon
  - Templates — `FileText` icon
  - Images — `Server` icon
- Spacer (flex-1)
- Settings — `Settings` icon (bottom)

Behaviour:
- Active item: `bg-zinc-800 border border-zinc-700 rounded-md`
- Hover: `bg-zinc-800/50 rounded-md`
- Icon: `stroke-zinc-400` default, `stroke-zinc-100` when active
- Label: 9px, `text-zinc-500` default, `text-zinc-200` when active
- Clicking any item calls `setCurrentPage(key)`

Add `data-testid="nav-item-{key}"` to each nav button.

### File: `frontend/src/pages/DesignerPage.tsx` (new wrapper)

Wrap the existing canvas layout. The canvas-specific toolbar (deploy, stop, walkthrough, cockpit, export, terminal) stays inside this page — it is NOT part of the global nav.

```tsx
export function DesignerPage() {
  return (
    <div className="flex flex-col h-full">
      <DesignerToolbar />     {/* existing Toolbar.tsx, renamed or wrapped */}
      <div className="flex flex-1 overflow-hidden">
        <ComponentPalette />  {/* existing palette */}
        <DiagramCanvas />     {/* existing canvas */}
        <PropertiesPanel />   {/* existing properties */}
      </div>
    </div>
  )
}
```

### File: `frontend/src/pages/SettingsPage.tsx` (thin wrapper)

Wrap existing settings content. No functional changes.

### Validation
1. App loads — Home page is visible, left nav is present
2. Clicking each nav item renders the correct page
3. Designer page looks identical to the pre-refactor canvas layout
4. No existing canvas features are broken

---

## Phase 2 — Data model: `image_size_mb` on ComponentManifest

### File: `backend/app/models/component.py`

Add optional field:
```python
image_size_mb: Optional[float] = None  # compressed pull size MB, None = unknown
```

### Populate known sizes in manifests

Edit each file below, adding `image_size_mb` at the top level of the manifest YAML:

```
components/minio/manifest.yaml           → image_size_mb: 110
components/minio-aistor/manifest.yaml    → image_size_mb: 180
components/nginx/manifest.yaml           → image_size_mb: 25
components/prometheus/manifest.yaml      → image_size_mb: 90
components/grafana/manifest.yaml         → image_size_mb: 120
components/trino/manifest.yaml           → image_size_mb: 650
components/spark/manifest.yaml           → image_size_mb: 900
components/clickhouse/manifest.yaml      → image_size_mb: 350
components/iceberg-rest/manifest.yaml    → image_size_mb: 80
components/hdfs/manifest.yaml            → image_size_mb: 450
components/metabase/manifest.yaml        → image_size_mb: 500
components/ollama/manifest.yaml          → image_size_mb: 1200
components/qdrant/manifest.yaml          → image_size_mb: 80
components/milvus/manifest.yaml          → image_size_mb: 400
components/mlflow/manifest.yaml          → image_size_mb: 300
components/jupyterlab/manifest.yaml      → image_size_mb: 800
components/redpanda/manifest.yaml        → image_size_mb: 200
components/nessie/manifest.yaml          → image_size_mb: 150
components/dremio/manifest.yaml          → image_size_mb: 600
```

Leave all other manifests without this field (defaults to `None`).

### Validation
```bash
cd backend && python -c "
from app.registry.loader import load_registry
reg = load_registry('.')
sized = [(n, m.image_size_mb) for n, m in reg.items() if m.image_size_mb]
print(f'{len(sized)} components with size data')
for n, s in sorted(sized): print(f'  {n}: {s} MB')
"
```
Expected: 19 lines printed.

---

## Phase 3 — Backend: `/api/images` router

### File: `backend/app/models/api_models.py`

Add:
```python
from typing import Literal, Optional
from pydantic import BaseModel

class ImageInfo(BaseModel):
    component_name: str
    image_ref: str
    category: Literal["vendor", "custom", "platform"]
    cached: bool
    local_size_mb: Optional[float] = None     # from Docker if cached
    manifest_size_mb: Optional[float] = None  # from manifest field
    hub_size_mb: Optional[float] = None       # from Docker Hub API, best-effort
    effective_size_mb: Optional[float] = None # manifest > hub > None
    pull_source: str                           # "docker.io", "ghcr.io", "hub-registry"
    status: Literal["cached", "missing", "unknown"]

class PullRequest(BaseModel):
    image_ref: str

class PullStatus(BaseModel):
    pull_id: str
    image_ref: str
    status: Literal["pulling", "complete", "error"]
    progress_pct: Optional[int] = None
    error: Optional[str] = None

class PullResponse(BaseModel):
    pull_id: str
```

### File: `backend/app/api/images.py` (new)

#### Category logic
```python
def categorise(manifest) -> str:
    ref = manifest.image or ""
    if "demoforge/" in ref or manifest.build_context:
        # platform = DemoForge's own services
        # custom = component images we build (build_context present)
        return "platform" if "demoforge/" in ref else "custom"
    return "vendor"
```

#### Docker Hub size lookup (best-effort, non-blocking)
```python
_hub_cache: dict[str, Optional[float]] = {}

async def fetch_hub_size(image_ref: str) -> Optional[float]:
    """Returns compressed size in MB from Docker Hub manifest API. Never raises."""
    if image_ref in _hub_cache:
        return _hub_cache[image_ref]
    try:
        # Parse image_ref → org/repo + tag
        # GET https://hub.docker.com/v2/repositories/{repo}/tags/{tag}
        # full_size field (bytes) / 1_000_000 → MB
        # timeout=3s
        ...
        _hub_cache[image_ref] = result
        return result
    except Exception:
        _hub_cache[image_ref] = None
        return None
```

Cache results in-memory for the process lifetime. Never block `/api/images/status` waiting for this — run all Hub lookups concurrently with `asyncio.gather` and include results that complete within 3s.

#### Endpoints

`GET /api/images/status`
- Load all manifests from registry
- For each manifest with an image field:
  - Check local Docker via `docker.from_env().images.get(image_ref)` (try/except ImageNotFound)
  - If cached: `local_size_mb = image.attrs['Size'] / 1_000_000`
  - Run Hub API lookup concurrently for all uncached images
  - Compute `effective_size_mb`: manifest_size_mb if set, else hub_size_mb, else None
  - Set `status`: "cached" / "missing" / "unknown" (unknown = cached but size data absent)
- Return `List[ImageInfo]`

`POST /api/images/pull`
- Body: `PullRequest`
- Start `docker pull` in a background task using `asyncio.create_task`
- Track progress in a module-level dict: `_pulls: dict[str, PullStatus]`
- Return `PullResponse(pull_id=str(uuid4()))`
- For custom/platform images with `pull_source == "hub-registry"`:
  - Attempt pull but expect failure
  - On failure set status "error" with message: "Custom image pull requires Hub registry — not yet configured. Run `make dev` to build locally."

`GET /api/images/pull/{pull_id}`
- Return current `PullStatus` from `_pulls` dict
- 404 if pull_id unknown

`POST /api/images/pull-all-missing`
- Get all images with status "missing"
- Kick off a pull task for each
- Return `{"pull_ids": [...]}`

#### Register in `backend/app/main.py`
```python
from app.api import images as images_router
app.include_router(images_router.router, prefix="/api/images", tags=["images"])
```

### Validation
```bash
# All images returned
curl -s http://localhost:9210/api/images/status | python -m json.tool | grep '"component_name"' | wc -l

# At least one cached
curl -s http://localhost:9210/api/images/status | python -m json.tool | grep '"cached": true' | head -3

# Trigger a pull (minio is small)
curl -s -X POST http://localhost:9210/api/images/pull \
  -H "Content-Type: application/json" \
  -d '{"image_ref":"minio/minio:latest"}' | python -m json.tool
```

---

## Phase 4 — `check_images.py` + Makefile

### File: `check_images.py` (repo root, new)

```
Usage: python check_images.py [--mode se|dev] [--fail-on-missing]
```

Logic:
1. Load all manifests from `components/`
2. Extract image refs; in `--mode dev` skip entries with `build_context`
3. Query local Docker for each
4. Print formatted table (no colour codes — runs in CI terminals too)
5. Print summary line: `N/M images cached (~X.X GB total estimated)`
6. With `--fail-on-missing`: exit 1 if any missing, print pull hint per image

Output format:
```
DemoForge image pre-flight check
─────────────────────────────────────────────────────────────────────
 Component           Image ref                        Status    Size
─────────────────────────────────────────────────────────────────────
 minio               minio/minio:latest               ✓ cached  110 MB
 trino               trinodb/trino:430                ✗ missing 650 MB
 grafana             grafana/grafana:latest            ✓ cached  120 MB
─────────────────────────────────────────────────────────────────────
 29/32 images cached. ~3.2 GB missing.

Missing images — run: make pull-missing
  trinodb/trino:430
  custom/spark-s3a:3.5
  hub-registry/data-generator:1.2
```

### File: `Makefile` — add targets

```makefile
.PHONY: start dev pull-all pull-missing check-images

## SE mode: pre-flight then start
start:
	@python check_images.py --mode se --fail-on-missing || \
	  (echo "\nRun 'make pull-missing' to fetch missing images." && exit 1)
	docker compose up -d

## Dev mode: skip checks, build from source, hub sync off
## TODO: add build: directives to docker-compose.yml under 'dev' profile
dev:
	DEMOFORGE_MODE=dev docker compose --profile dev up -d --build

## Pull all images (vendor + hub-registry when configured)
pull-all:
	@python check_images.py --mode se
	docker compose pull
	@echo "Custom/platform images: hub registry pull not yet configured."

## Pull only missing images (vendor only — hub registry images skipped)
pull-missing:
	@python check_images.py --mode se | grep "✗ missing" | \
	  grep -v "hub-registry" | awk '{print $$3}' | xargs -I{} docker pull {}

## Run image check only
check-images:
	@python check_images.py --mode se
```

### Validation
```bash
python check_images.py --mode se          # prints table, exits 0
python check_images.py --mode se --fail-on-missing  # exits 1 if any missing
make check-images                          # same via make
```

---

## Phase 5 — Frontend: Home page

### File: `frontend/src/pages/HomePage.tsx` (new)

Sections (top to bottom):

#### Header
- Greeting: "Good afternoon / morning / evening" based on time of day
- Subtitle: "DemoForge · local · Docker running" (check `/api/health` on mount)

#### Missing images warning banner
- Shown only when `missingImageCount > 0` (fetched from `/api/images/status`)
- Amber banner, full width, clickable → navigates to Images page
- Text: `"{N} image{s} missing — some templates may fail to deploy"`
- Right-aligned link: "View Images →"
- `data-testid="missing-images-banner"`

#### Stat row (4 cards)
- Active demos (count where status=running, from `/api/demos`)
- Saved demos (total count)
- Images missing (amber if >0) — from `/api/images/status`
- Templates available (from `/api/registry` or hardcoded 26)

#### Recent demos list
- Last 5 demos from `/api/demos`, sorted by last modified
- Each row: status dot (green=running, gray=stopped) + demo name + meta + badge
- Clicking a row: sets active demo in demoStore + navigates to Designer page
- `data-testid="recent-demo-row"`

#### Quick actions (2×2 grid)
- New demo → clears active demo, navigate to Designer
- From template → navigate to Templates
- Manage images → navigate to Images
- Import demo → file picker for YAML

### State wiring
On `HomePage` mount, fetch:
- `GET /api/demos` — for recent list + counts
- `GET /api/images/status` — for missing count + banner

Use `useEffect` with empty dep array. Show skeleton on load.

---

## Phase 6 — Frontend: Images page

### New files
- `frontend/src/pages/ImagesPage.tsx`
- `frontend/src/components/images/ImageRow.tsx`
- `frontend/src/components/images/ImageStatusBadge.tsx`
- `frontend/src/api/images.ts`

### File: `frontend/src/api/images.ts`

Mirror backend models as TypeScript interfaces. Add functions:
```typescript
export async function getImageStatus(): Promise<ImageInfo[]>
export async function pullImage(imageRef: string): Promise<{ pull_id: string }>
export async function getPullStatus(pullId: string): Promise<PullStatus>
export async function pullAllMissing(): Promise<{ pull_ids: string[] }>
```

Follow the pattern in `frontend/src/api/client.ts`.

### File: `frontend/src/components/images/ImageStatusBadge.tsx`

```
cached  → green dot + "Cached"
missing → red dot + "Missing"
pulling → spinner + "Pulling X%"
unknown → gray dot + "Unknown"
```

`data-testid="image-status-badge"`

### File: `frontend/src/pages/ImagesPage.tsx`

Layout:
```
Page header
  "Images"                       [↻ Refresh]  [Pull all missing]

Stats row (3 cards)
  Total | Cached | Missing

Category groups (collapsible, default open)
  ┌ Vendor images (18 cached · ~4.2 GB) ─────────────────┐
  │ minio/minio:latest      MinIO CE    ✓ Cached  110 MB  [Pull] │
  │ trinodb/trino:430        Trino       ✗ Missing 650 MB  [Pull] │
  └──────────────────────────────────────────────────────────────┘

  ┌ Custom images (2 cached · 1 missing) ────────────────┐
  │ ...                                                   │
  └───────────────────────────────────────────────────────┘

  ┌ Platform images (9 cached · 1 missing) ──────────────┐
  │ ...                                                   │
  └───────────────────────────────────────────────────────┘
```

Behaviour:
- On mount: call `getImageStatus()`, show skeleton
- Refresh button: re-calls `getImageStatus()`
- "Pull all missing": calls `pullAllMissing()`, polls each pull_id every 2s
- Per-row Pull button: calls `pullImage(ref)`, shows spinner inline, polls until done
- Missing Pull buttons: red border accent
- Toast on complete: `toast.success("Pulled {image_ref}")` (sonner)
- Toast on error: `toast.error("Failed to pull {ref}: {error}")`
- Group size totals: sum `effective_size_mb` for group; show "~X GB" or "~X GB+" if any null
- `data-testid` on: `"images-page"`, `"image-list"`, `"image-row"`, `"image-group-{vendor|custom|platform}"`, `"pull-spinner"`, `"pull-all-btn"`

---

## Phase 7 — Templates page (promoted from modal)

### File: `frontend/src/pages/TemplatesPage.tsx` (new, replaces modal)

The existing `TemplateGallery.tsx` component moves into this page. The modal/overlay trigger in the designer toolbar is replaced with a nav link.

Page layout:
```
Header row
  "Templates"                    [search input]

Filter pills (horizontal scroll if needed)
  All | Replication | Analytics | AI/ML | Streaming | Resilience | ...

Template cards grid (2 columns)
  ┌──────────────────────────────┐
  │ Lakehouse with Trino         │
  │ MinIO + Trino + Iceberg...   │
  │ [Professional]    ~1.4 GB   │
  └──────────────────────────────┘
```

### Template card image size badge

Add size computation to each card:

```typescript
function computeTemplateSize(template: DemoTemplate, registry: ComponentManifest[]): TemplateSizeInfo {
  const nodes = template.nodes ?? []
  let total = 0
  let hasUnknown = false
  for (const node of nodes) {
    const manifest = registry.find(m => m.name === node.component)
    if (manifest?.image_size_mb) {
      total += manifest.image_size_mb
    } else {
      hasUnknown = true
    }
  }
  return {
    total_mb: total,
    partial: hasUnknown,
    has_any: total > 0 || hasUnknown
  }
}
```

Display in card footer (right-aligned, muted):
- `~1.4 GB` — all sizes known
- `~1.4 GB+` — some unknown (amber tint)
- `unknown` — no data at all (gray)

`data-testid="template-size-badge"` on the badge element.

### Missing images warning on cards

If `ImageInfo[]` is loaded (shared via a lightweight context or fetched once at page level), check if any component in the template has `status === "missing"`. If so:
- Show a small amber warning dot in the card footer
- Tooltip: "Some images for this template are not cached"
- `data-testid="template-missing-warning"`

### Designer toolbar change

Remove the "Templates" button from the canvas toolbar. Navigation to templates is now via the left nav. If an SE wants a template while designing, they click Templates in the nav, which opens the Templates page. After selecting, the app navigates back to Designer with the chosen template loaded (existing behavior, just new navigation path).

---

## Phase 8 — Playwright validation scenarios

### Setup

Tests go in `tests/e2e/`. Backend must be running on port 9210, frontend on port 3000.

### File: `tests/e2e/navigation.spec.ts`

```typescript
// Nav renders and all pages load
test('left nav renders with all items', async ({ page }) => {
  await page.goto('http://localhost:3000')
  for (const key of ['home', 'designer', 'templates', 'images', 'settings']) {
    await expect(page.getByTestId(`nav-item-${key}`)).toBeVisible()
  }
})

test('nav items switch pages', async ({ page }) => {
  await page.goto('http://localhost:3000')
  await expect(page.getByTestId('home-page')).toBeVisible()

  await page.getByTestId('nav-item-designer').click()
  await expect(page.getByTestId('designer-page')).toBeVisible()
  await expect(page.getByTestId('home-page')).not.toBeVisible()

  await page.getByTestId('nav-item-templates').click()
  await expect(page.getByTestId('templates-page')).toBeVisible()

  await page.getByTestId('nav-item-images').click()
  await expect(page.getByTestId('images-page')).toBeVisible()
})
```

### File: `tests/e2e/home.spec.ts`

```typescript
test('home page loads with stats', async ({ page }) => {
  await page.goto('http://localhost:3000')
  await expect(page.getByTestId('home-page')).toBeVisible()
  // Stats row loads (may show 0)
  await expect(page.getByTestId('stat-active-demos')).toBeVisible({ timeout: 8000 })
  await expect(page.getByTestId('stat-templates')).toBeVisible()
})

test('missing images banner appears when images are missing', async ({ page }) => {
  // Mock the images status endpoint to return a missing image
  await page.route('**/api/images/status', route =>
    route.fulfill({
      json: [{ component_name: 'trino', image_ref: 'trinodb/trino:430',
               category: 'vendor', cached: false, status: 'missing',
               manifest_size_mb: 650, effective_size_mb: 650, pull_source: 'docker.io' }]
    })
  )
  await page.goto('http://localhost:3000')
  await expect(page.getByTestId('missing-images-banner')).toBeVisible({ timeout: 5000 })
})

test('missing images banner links to images page', async ({ page }) => {
  await page.route('**/api/images/status', route =>
    route.fulfill({ json: [{ status: 'missing', component_name: 'trino',
      image_ref: 'trinodb/trino:430', category: 'vendor', cached: false,
      manifest_size_mb: 650, effective_size_mb: 650, pull_source: 'docker.io' }] })
  )
  await page.goto('http://localhost:3000')
  await page.getByTestId('missing-images-banner').click()
  await expect(page.getByTestId('images-page')).toBeVisible()
  await expect(page.getByTestId('nav-item-images')).toHaveClass(/active/)
})

test('recent demo row navigates to designer', async ({ page }) => {
  await page.goto('http://localhost:3000')
  const demoRows = page.getByTestId('recent-demo-row')
  if (await demoRows.count() > 0) {
    await demoRows.first().click()
    await expect(page.getByTestId('designer-page')).toBeVisible()
  }
})
```

### File: `tests/e2e/images.spec.ts`

```typescript
test('images page loads image list', async ({ page }) => {
  await page.goto('http://localhost:3000')
  await page.getByTestId('nav-item-images').click()
  await expect(page.getByTestId('image-list')).toBeVisible({ timeout: 10000 })
  await expect(page.getByTestId('image-row').first()).toBeVisible()
})

test('image groups are visible', async ({ page }) => {
  await page.goto('http://localhost:3000')
  await page.getByTestId('nav-item-images').click()
  await expect(page.getByTestId('image-list')).toBeVisible({ timeout: 10000 })
  for (const group of ['vendor', 'custom', 'platform']) {
    await expect(page.getByTestId(`image-group-${group}`)).toBeVisible()
  }
})

test('pull button shows spinner and triggers pull', async ({ page }) => {
  await page.route('**/api/images/pull', route =>
    route.fulfill({ json: { pull_id: 'test-123' } })
  )
  await page.route('**/api/images/pull/test-123', route =>
    route.fulfill({ json: { pull_id: 'test-123', image_ref: 'trinodb/trino:430',
                             status: 'pulling', progress_pct: 30 } })
  )
  await page.goto('http://localhost:3000')
  await page.getByTestId('nav-item-images').click()
  await expect(page.getByTestId('image-list')).toBeVisible({ timeout: 10000 })
  await page.getByRole('button', { name: /^pull$/i }).first().click()
  await expect(page.getByTestId('pull-spinner').first()).toBeVisible()
})

test('pull all missing button exists and is clickable', async ({ page }) => {
  await page.goto('http://localhost:3000')
  await page.getByTestId('nav-item-images').click()
  await expect(page.getByTestId('pull-all-btn')).toBeVisible({ timeout: 8000 })
})
```

### File: `tests/e2e/templates.spec.ts`

```typescript
test('templates page shows cards with size badges', async ({ page }) => {
  await page.goto('http://localhost:3000')
  await page.getByTestId('nav-item-templates').click()
  await expect(page.getByTestId('templates-page')).toBeVisible()
  const cards = page.getByTestId('template-card')
  await expect(cards.first()).toBeVisible({ timeout: 8000 })
  // At least some cards have size badges
  await expect(page.getByTestId('template-size-badge').first()).toBeVisible()
})

test('category filter narrows template list', async ({ page }) => {
  await page.goto('http://localhost:3000')
  await page.getByTestId('nav-item-templates').click()
  await expect(page.getByTestId('templates-page')).toBeVisible()
  const totalBefore = await page.getByTestId('template-card').count()
  // Click a specific category (if it has any templates)
  const filterPills = page.getByTestId('filter-pill')
  if (await filterPills.count() > 1) {
    await filterPills.nth(1).click()
    const totalAfter = await page.getByTestId('template-card').count()
    expect(totalAfter).toBeLessThanOrEqual(totalBefore)
  }
})
```

### File: `tests/e2e/check-images.spec.ts`

```typescript
import { execSync } from 'child_process'

test('check_images.py runs and produces expected output', () => {
  const result = execSync('python check_images.py --mode se', {
    cwd: process.cwd(),
    encoding: 'utf8'
  })
  expect(result).toContain('DemoForge image pre-flight check')
  expect(result).toMatch(/\d+\/\d+ images cached/)
})
```

### Required `data-testid` attributes

Add these to the relevant components (do not rely on role/text selectors for structural elements):

| Attribute | Element |
|-----------|---------|
| `home-page` | `<HomePage>` root div |
| `designer-page` | `<DesignerPage>` root div |
| `templates-page` | `<TemplatesPage>` root div |
| `images-page` | `<ImagesPage>` root div |
| `nav-item-{key}` | Each nav button |
| `missing-images-banner` | Warning banner on home page |
| `stat-active-demos` | Active demos stat card |
| `stat-templates` | Templates stat card |
| `recent-demo-row` | Each demo row on home page |
| `image-list` | Scrollable list container in images page |
| `image-row` | Each image row |
| `image-group-vendor` | Vendor group container |
| `image-group-custom` | Custom group container |
| `image-group-platform` | Platform group container |
| `image-status-badge` | Each `<ImageStatusBadge>` |
| `pull-spinner` | Spinner shown during pull |
| `pull-all-btn` | "Pull all missing" button |
| `template-card` | Each template card |
| `template-size-badge` | Size badge on template card |
| `template-missing-warning` | Amber warning dot on card |
| `filter-pill` | Each category filter pill |

---

## Implementation notes and placeholders

### Hub registry (future)
In `images.py`, where `pull_source == "hub-registry"`: add comment `# TODO Phase 7: Hub API token brokering`. Pull attempts for these images should fail gracefully with message: `"Custom image pull requires Hub registry — not yet configured."` Surface this in the UI as an error state on the row (not a toast), with a note: `"Run make dev to build locally."`

### GCP Artifact Registry (future)
Same pattern. The endpoint structure is designed for it; credential injection is a later phase.

### Docker Hub rate limits
The Hub API size lookup is strictly best-effort with 3s timeout. `asyncio.gather` with `return_exceptions=True` — a timeout returns `None` for `hub_size_mb`, never blocks the status endpoint.

### make dev profile
The `dev` profile compose config is not built in this phase. The Makefile target includes a comment: `# TODO: add build: directives and dev profile to docker-compose.yml`.

---

## Done criteria

- [ ] Left nav renders, all 5 pages accessible, no existing canvas functionality broken
- [ ] `python check_images.py --mode se` prints formatted table, correct exit codes
- [ ] `GET /api/images/status` returns correct fields, 19+ components with manifest sizes
- [ ] Images page loads, groups by category, pull buttons functional (graceful fail for hub-registry)
- [ ] Home page shows missing-images banner when images are missing, banner links to Images page
- [ ] Templates page promoted from modal to full page, size badges on cards
- [ ] All Playwright scenarios pass
- [ ] `plans/backlog.md` updated
