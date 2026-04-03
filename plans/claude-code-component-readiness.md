# DemoForge Component Readiness & FA Visibility Control

## Goal

Add a component readiness system that controls which components and templates are visible to Field Architects. This enables controlled rollout — components must be explicitly flagged as "FA Ready" before FAs can see or use them. Developers see everything and manage readiness from a dedicated page.

**Key rules:**
- Component readiness is the **source of truth** — stored in a single config file
- Template readiness is **derived** — a template is FA-ready iff ALL its components are FA-ready
- FA mode: non-ready components and templates are **invisible** (not greyed out — invisible)
- Dev mode: everything is visible, with a management page to toggle readiness
- Safe default: components not listed in the readiness config are **not ready** (explicit opt-in)

---

## Phase 0 — Investigation (DO THIS FIRST)

Before writing ANY code, investigate the current codebase.

### 0.1 Understand component manifests

```bash
# Find all component manifests
find . -name "*.yaml" -o -name "*.yml" | xargs grep -l "component\|manifest" | head -30
find . -path "*/components/*" -name "*.yaml" | head -40
find . -path "*/manifests/*" -name "*.yaml" | head -40

# Look at a few manifests to understand the schema
# (pick 3 different ones to see the range of fields)
cat <first-manifest>
cat <second-manifest>
cat <third-manifest>

# How are manifests loaded?
grep -r "manifest\|load_component\|component_registry\|ComponentManifest" --include="*.py" -l | head -20
grep -r "manifest\|load_component\|component_registry\|ComponentManifest" --include="*.ts" --include="*.tsx" -l | head -20

# What fields does a manifest have?
grep -r "class.*Manifest\|interface.*Manifest\|type.*Manifest" --include="*.py" --include="*.ts" -l | head -10
```

### 0.2 Understand template structure

```bash
# Find template definitions
find . -path "*/demo-templates/*" -name "*.yaml" | head -30
find . -path "*/user-templates/*" -name "*.yaml" | head -10
find . -path "*/synced-templates/*" -name "*.yaml" | head -10

# Look at a template to understand how it references components
cat <a-template-yaml>

# How are templates loaded?
grep -r "load_template\|template_registry\|TemplateManifest" --include="*.py" --include="*.ts" --include="*.tsx" -l | head -20
```

### 0.3 Understand the frontend component/template browsing

```bash
# Find the component palette/panel (where FAs pick components to add to canvas)
grep -r "palette\|component.*panel\|component.*list\|component.*browser" --include="*.tsx" --include="*.ts" -l | head -20

# Find the template gallery
grep -r "template.*gallery\|template.*list\|template.*browser\|TemplateGallery" --include="*.tsx" --include="*.ts" -l | head -20

# Find how components are fetched/listed
grep -r "getComponents\|fetchComponents\|useComponents\|componentStore\|component.*store" --include="*.ts" --include="*.tsx" -l | head -20

# Find the backend API endpoints that serve component/template lists
grep -r "components\|templates" --include="*.py" -l | grep -i "router\|route\|api" | head -20
```

### 0.4 Understand DEMOFORGE_MODE and existing dev/fa branching

```bash
# How does the app currently distinguish dev vs FA mode?
grep -r "DEMOFORGE_MODE\|mode.*fa\|mode.*dev\|isDevMode\|isFAMode" --include="*.py" --include="*.ts" --include="*.tsx" --include="*.env*" -l | head -20

# Check what's already gated by mode
grep -rn "DEMOFORGE_MODE\|isDevMode\|isFAMode" --include="*.ts" --include="*.tsx" | head -30
```

### 0.5 Check for existing navigation/pages structure

```bash
# Find the router/navigation setup
grep -r "Route\|Router\|createBrowserRouter\|routes" --include="*.tsx" --include="*.ts" -l | head -10

# Find existing pages
find . -path "*/pages/*" -o -path "*/views/*" | grep -E "\.(tsx|ts)$" | head -20

# Find sidebar/nav component
grep -r "sidebar\|nav\|Sidebar\|NavItem\|navigation" --include="*.tsx" -l | head -10
```

**IMPORTANT**: After investigation, adapt all paths and patterns to match what you find. The code in later phases is illustrative — use the actual project structure.

---

## Phase 1 — Readiness Config File

### 1.1 Create the config file

Create `component-readiness.yaml` at the project root (or alongside the component manifests directory — use whichever location is most natural given the project structure):

```yaml
# component-readiness.yaml
#
# Controls which components are visible to Field Architects.
# Components NOT listed here default to fa_ready: false.
# A template is FA-ready only when ALL its components are FA-ready.
#
# To make a component available to FAs:
#   1. Add it here with fa_ready: true
#   2. Restart DemoForge (or refresh in dev mode)
#
# Fields:
#   fa_ready  (bool, required)   — whether FAs can see and use this component
#   notes     (string, optional) — why it is/isn't ready (shown in dev management page)
#   updated_at (string, optional) — ISO 8601 timestamp of last change
#   updated_by (string, optional) — who made the last change

components:
  minio:
    fa_ready: true
    notes: "Core component — always ready"
    updated_at: "2026-04-01T00:00:00Z"
    updated_by: "ahmad@minio.io"

  # Add entries for each of the 35+ components.
  # Start with everything as fa_ready: false (safe default),
  # then set the known-stable ones to true.
```

### 1.2 Create the readiness loader (backend)

Add a module to the backend that loads and serves readiness state.

```python
# readiness.py (or wherever backend utilities live)

import yaml
from pathlib import Path
from datetime import datetime, timezone

READINESS_CONFIG_PATH = Path(__file__).parent.parent / "component-readiness.yaml"

class ComponentReadiness:
    def __init__(self):
        self._config: dict = {}
        self._loaded_at: datetime | None = None
    
    def load(self, path: Path | None = None):
        """Load readiness config from YAML."""
        config_path = path or READINESS_CONFIG_PATH
        if config_path.exists():
            with open(config_path) as f:
                data = yaml.safe_load(f) or {}
            self._config = data.get("components", {})
        else:
            self._config = {}
        self._loaded_at = datetime.now(timezone.utc)
    
    def save(self, path: Path | None = None):
        """Write readiness config back to YAML."""
        config_path = path or READINESS_CONFIG_PATH
        with open(config_path, "w") as f:
            yaml.dump(
                {"components": self._config},
                f,
                default_flow_style=False,
                sort_keys=True,
            )
    
    def is_fa_ready(self, component_id: str) -> bool:
        """Check if a component is FA-ready. Default: False."""
        entry = self._config.get(component_id, {})
        return entry.get("fa_ready", False)
    
    def get_all(self) -> dict:
        """Return full readiness config."""
        return self._config
    
    def get_ready_component_ids(self) -> set[str]:
        """Return set of FA-ready component IDs."""
        return {
            cid for cid, entry in self._config.items()
            if entry.get("fa_ready", False)
        }
    
    def set_readiness(self, component_id: str, fa_ready: bool, notes: str = "", updated_by: str = ""):
        """Update readiness for a component."""
        if component_id not in self._config:
            self._config[component_id] = {}
        self._config[component_id]["fa_ready"] = fa_ready
        self._config[component_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
        if notes:
            self._config[component_id]["notes"] = notes
        if updated_by:
            self._config[component_id]["updated_by"] = updated_by
    
    def is_template_fa_ready(self, template_component_ids: list[str]) -> bool:
        """
        A template is FA-ready iff ALL its components are FA-ready.
        Empty component list = ready (edge case, shouldn't happen).
        """
        if not template_component_ids:
            return True
        return all(self.is_fa_ready(cid) for cid in template_component_ids)
    
    def get_blocking_components(self, template_component_ids: list[str]) -> list[str]:
        """Return list of component IDs that are NOT FA-ready in a template."""
        return [cid for cid in template_component_ids if not self.is_fa_ready(cid)]


# Singleton instance
readiness = ComponentReadiness()
```

### 1.3 Backend API endpoints

Add a new router for readiness management. These endpoints are dev-mode only.

```python
# routers/readiness.py

from fastapi import APIRouter, HTTPException, Depends

router = APIRouter(prefix="/api/readiness", tags=["readiness"])

def require_dev_mode():
    """Block access in FA mode."""
    if os.getenv("DEMOFORGE_MODE") == "fa":
        raise HTTPException(status_code=403, detail="Readiness management is only available in dev mode")

# --- Read endpoints (available in both modes) ---

@router.get("/components")
async def get_component_readiness():
    """
    Returns all components with their readiness status, plus
    which templates reference each component.
    """
    readiness.load()  # reload from disk
    all_components = get_all_component_manifests()  # existing function
    all_templates = get_all_templates()  # existing function
    
    result = []
    for component in all_components:
        component_id = component["id"]  # adapt to actual manifest schema
        
        # Find templates that use this component
        referencing_templates = []
        for template in all_templates:
            template_components = get_template_component_ids(template)
            if component_id in template_components:
                referencing_templates.append({
                    "template_id": template["id"],
                    "template_name": template.get("name", template["id"]),
                    "is_fa_ready": readiness.is_template_fa_ready(template_components),
                    "blocking_components": readiness.get_blocking_components(template_components),
                })
        
        entry = readiness.get_all().get(component_id, {})
        result.append({
            "component_id": component_id,
            "component_name": component.get("name", component_id),
            "category": component.get("category", "uncategorized"),
            "fa_ready": readiness.is_fa_ready(component_id),
            "notes": entry.get("notes", ""),
            "updated_at": entry.get("updated_at"),
            "updated_by": entry.get("updated_by"),
            "template_count": len(referencing_templates),
            "templates": referencing_templates,
        })
    
    return {
        "components": result,
        "summary": {
            "total": len(result),
            "fa_ready": sum(1 for c in result if c["fa_ready"]),
            "not_ready": sum(1 for c in result if not c["fa_ready"]),
        },
    }

@router.get("/templates")
async def get_template_readiness():
    """
    Returns all templates with their derived FA-readiness status.
    Supports filtering by readiness.
    """
    readiness.load()
    all_templates = get_all_templates()
    
    result = []
    for template in all_templates:
        template_components = get_template_component_ids(template)
        is_ready = readiness.is_template_fa_ready(template_components)
        blocking = readiness.get_blocking_components(template_components)
        
        result.append({
            "template_id": template["id"],
            "template_name": template.get("name", template["id"]),
            "source": template.get("source", "builtin"),  # builtin | synced | user
            "is_fa_ready": is_ready,
            "component_count": len(template_components),
            "components": template_components,
            "blocking_components": blocking,
            "ready_component_count": len(template_components) - len(blocking),
        })
    
    return {
        "templates": result,
        "summary": {
            "total": len(result),
            "fa_ready": sum(1 for t in result if t["is_fa_ready"]),
            "not_ready": sum(1 for t in result if not t["is_fa_ready"]),
        },
    }

# --- Write endpoints (dev mode only) ---

@router.put("/components/{component_id}", dependencies=[Depends(require_dev_mode)])
async def update_component_readiness(component_id: str, body: ReadinessUpdate):
    """Toggle FA-readiness for a component."""
    readiness.load()
    
    # Verify component exists
    if not component_exists(component_id):
        raise HTTPException(status_code=404, detail=f"Component not found: {component_id}")
    
    readiness.set_readiness(
        component_id=component_id,
        fa_ready=body.fa_ready,
        notes=body.notes or "",
        updated_by=body.updated_by or os.getenv("DEMOFORGE_FA_ID", "dev"),
    )
    readiness.save()
    
    # Return updated state including template impact
    return await get_component_readiness_detail(component_id)

@router.put("/components/batch", dependencies=[Depends(require_dev_mode)])
async def batch_update_readiness(body: BatchReadinessUpdate):
    """Update readiness for multiple components at once."""
    readiness.load()
    
    results = []
    for update in body.updates:
        if not component_exists(update.component_id):
            results.append({"component_id": update.component_id, "error": "not found"})
            continue
        
        readiness.set_readiness(
            component_id=update.component_id,
            fa_ready=update.fa_ready,
            notes=update.notes or "",
            updated_by=update.updated_by or os.getenv("DEMOFORGE_FA_ID", "dev"),
        )
        results.append({"component_id": update.component_id, "fa_ready": update.fa_ready})
    
    readiness.save()
    return {"results": results}

# --- Pydantic schemas ---

class ReadinessUpdate(BaseModel):
    fa_ready: bool
    notes: str | None = None
    updated_by: str | None = None

class BatchReadinessItem(BaseModel):
    component_id: str
    fa_ready: bool
    notes: str | None = None
    updated_by: str | None = None

class BatchReadinessUpdate(BaseModel):
    updates: list[BatchReadinessItem]
```

### 1.4 Integrate readiness filtering into existing API

Modify the existing endpoints that serve component and template lists to filter based on readiness in FA mode.

```python
# In the existing component list endpoint (find and modify)
@router.get("/api/components")
async def list_components():
    components = get_all_component_manifests()
    
    mode = os.getenv("DEMOFORGE_MODE", "dev")
    if mode == "fa":
        readiness.load()
        ready_ids = readiness.get_ready_component_ids()
        components = [c for c in components if c["id"] in ready_ids]
    
    return components

# In the existing template list endpoint (find and modify)
@router.get("/api/templates")
async def list_templates():
    templates = get_all_templates()
    
    mode = os.getenv("DEMOFORGE_MODE", "dev")
    if mode == "fa":
        readiness.load()
        templates = [
            t for t in templates
            if readiness.is_template_fa_ready(get_template_component_ids(t))
        ]
    
    return templates
```

### 1.5 Validation — Phase 1

```bash
# 1. Create the readiness config with a mix of ready/not-ready components
# (use actual component IDs from the manifests you found in Phase 0)

# 2. Start in dev mode and verify ALL components are returned
DEMOFORGE_MODE=dev make dev
curl -s http://localhost:<port>/api/components | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(f'Total components: {len(data)}')
"

# 3. Start in FA mode and verify only ready components are returned
DEMOFORGE_MODE=fa make start
curl -s http://localhost:<port>/api/components | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(f'FA-visible components: {len(data)}')
"
# Expected: fewer components than dev mode

# 4. Verify templates are filtered correctly
curl -s http://localhost:<port>/api/templates | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(f'FA-visible templates: {len(data)}')
# All returned templates should only contain FA-ready components
"

# 5. Test the readiness API
curl -s http://localhost:<port>/api/readiness/components | python3 -m json.tool
# Expected: all components with readiness status and template references

curl -s http://localhost:<port>/api/readiness/templates | python3 -m json.tool
# Expected: all templates with derived readiness and blocking components

# 6. Test readiness toggle (dev mode)
curl -s -X PUT http://localhost:<port>/api/readiness/components/<a-component-id> \
  -H "Content-Type: application/json" \
  -d '{"fa_ready": true, "notes": "Tested and verified"}' \
  | python3 -m json.tool
# Expected: updated readiness, plus impact on templates shown

# 7. Verify the YAML file was updated
cat component-readiness.yaml | grep <a-component-id>
# Expected: fa_ready: true

# 8. Test dev-mode-only restriction
DEMOFORGE_MODE=fa curl -s -X PUT http://localhost:<port>/api/readiness/components/<id> \
  -H "Content-Type: application/json" \
  -d '{"fa_ready": true}' \
  -w "\nHTTP %{http_code}\n"
# Expected: 403

# 9. Test derived template readiness
# Find a template with 3 components. Set 2 to ready, leave 1 not ready.
curl -s http://localhost:<port>/api/readiness/templates | python3 -c "
import sys, json
data = json.load(sys.stdin)
for t in data['templates']:
    if t['blocking_components']:
        print(f'{t[\"template_id\"]}: blocked by {t[\"blocking_components\"]}')
        break
"
# Expected: shows which component is blocking the template
```

---

## Phase 2 — Component Readiness Management Page (Dev Mode Only)

### 2.1 Page structure and behavior

Create a new page at route `/readiness` (or `/component-readiness` — match existing naming conventions). This page is only visible in dev mode navigation.

**Page layout — two tabs:**

#### Tab 1: Components

A table/list of all components with:

| Column | Description |
|---|---|
| Component Name | Display name from manifest |
| Category | Component category (e.g., Storage, Query Engine, Processing) |
| FA Ready | Toggle switch — green when ready, grey when not |
| Templates | Count badge (e.g., "5 templates") — expandable to show list |
| Notes | Editable text field — reason for readiness/non-readiness |
| Last Updated | Relative timestamp (e.g., "2 days ago") + who |

**Interactions:**
- Clicking the FA Ready toggle immediately calls `PUT /api/readiness/components/{id}` and updates the UI
- Expanding the templates column shows inline list of referencing templates with their own readiness status
- A search/filter bar at the top with:
  - Text search (component name)
  - Filter: All / FA Ready / Not Ready
  - Filter by category
- Bulk actions: "Mark selected as FA Ready" / "Mark selected as Not Ready"
- Summary bar at the top: "23 of 35 components FA Ready"

#### Tab 2: Templates

A table/list of all templates with:

| Column | Description |
|---|---|
| Template Name | Display name |
| Source | Builtin / Synced / User |
| FA Ready | Derived badge — green check or red X (not toggleable) |
| Components | Count (e.g., "4/4 ready" or "3/4 ready") |
| Blocking | List of non-ready component names (if any) |

**Interactions:**
- Filter bar: All / FA Ready / Not Ready
- Filter by source (builtin, synced, user)
- Clicking a blocking component name scrolls to / highlights it in the Components tab
- Summary bar: "18 of 26 templates FA Ready"

### 2.2 Frontend implementation

Use the existing stack: React, TypeScript, shadcn/ui zinc dark theme, Zustand.

```tsx
// pages/ComponentReadiness.tsx (or ReadinessPage.tsx)
// This is a high-level outline — adapt to project conventions

import { useState, useEffect } from 'react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Switch } from '@/components/ui/switch';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';

// Types
interface ComponentReadinessItem {
  component_id: string;
  component_name: string;
  category: string;
  fa_ready: boolean;
  notes: string;
  updated_at: string | null;
  updated_by: string | null;
  template_count: number;
  templates: TemplateRef[];
}

interface TemplateRef {
  template_id: string;
  template_name: string;
  is_fa_ready: boolean;
  blocking_components: string[];
}

interface TemplateReadinessItem {
  template_id: string;
  template_name: string;
  source: string;
  is_fa_ready: boolean;
  component_count: number;
  components: string[];
  blocking_components: string[];
  ready_component_count: number;
}

// Data fetching
async function fetchComponentReadiness(): Promise<{ components: ComponentReadinessItem[]; summary: any }> {
  const res = await fetch('/api/readiness/components');
  return res.json();
}

async function fetchTemplateReadiness(): Promise<{ templates: TemplateReadinessItem[]; summary: any }> {
  const res = await fetch('/api/readiness/templates');
  return res.json();
}

async function toggleReadiness(componentId: string, faReady: boolean, notes?: string): Promise<void> {
  await fetch(`/api/readiness/components/${componentId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ fa_ready: faReady, notes }),
  });
}
```

### 2.3 Add to navigation (dev mode only)

```tsx
// In the sidebar/navigation component
// Add the readiness page link, gated by dev mode

const isDevMode = import.meta.env.VITE_DEMOFORGE_MODE !== 'fa';

{isDevMode && (
  <NavItem
    href="/readiness"
    icon={<ShieldCheck />}  // or similar icon from lucide-react
    label="Component Readiness"
  />
)}
```

### 2.4 Design specifications

Follow the existing shadcn/ui zinc dark theme. Key visual elements:

- **FA Ready toggle**: Use shadcn `Switch` component. When ON (ready), the row has a subtle green left border. When OFF, no border.
- **Template readiness badge**: Green `Badge` variant for ready, destructive `Badge` for not ready.
- **Blocking components**: Shown as small red `Badge` pills (e.g., `spark` `iceberg-rest`).
- **Summary bar**: Sticky at top of each tab. Shows counts with a small progress bar.
- **Notes field**: Click-to-edit inline. Shows first 50 chars with "..." and expands on click.
- **Category grouping**: Optional — if the component list is long, group by category with collapsible sections. Or use a category filter dropdown.
- **Empty state**: If no components exist, show a helpful message.

### 2.5 Validation — Phase 2

```bash
# 1. Start in dev mode
make dev

# 2. Navigate to /readiness (or wherever the page was added)
# Expected: page loads with all components listed

# 3. Verify component data
# - All 35+ components should appear
# - fa_ready toggles should match component-readiness.yaml
# - Template references should be accurate

# 4. Toggle a component's readiness
# - Click the switch on a non-ready component
# - Expected: switch turns green, API call fires, YAML file updated
# - Check the YAML: cat component-readiness.yaml | grep <component-id>

# 5. Verify template tab
# - Switch to Templates tab
# - Expected: templates shown with correct derived readiness
# - A template with all-ready components should show green
# - A template with one non-ready component should show red + list the blocker

# 6. Test filters
# - Filter by "Not Ready" on Components tab
# - Expected: only non-ready components shown
# - Filter by "FA Ready" on Templates tab
# - Expected: only fully-ready templates shown

# 7. Test blocking component link
# - On Templates tab, click a blocking component name
# - Expected: navigates to Components tab with that component highlighted/filtered

# 8. Verify dev-mode-only visibility
# - Start in FA mode
# - Expected: no "Component Readiness" link in navigation
# - Navigating directly to /readiness should show 404 or redirect

# 9. Verify FA filtering is active
# - In FA mode, open the component palette/panel on the canvas
# - Expected: only FA-ready components are shown
# - Open the template gallery
# - Expected: only templates where ALL components are FA-ready are shown
```

---

## Phase 3 — Seed the Readiness Config

### 3.1 Generate initial config from existing manifests

Write a one-time script to generate the readiness config from all existing component manifests:

```bash
# scripts/seed-readiness.sh
# Reads all component manifests and creates component-readiness.yaml
# with every component set to fa_ready: false (safe default)

echo "components:" > component-readiness.yaml

for manifest in <path-to-manifests>/*.yaml; do
    component_id=$(grep -E "^id:|^  id:" "$manifest" | head -1 | awk '{print $2}' | tr -d '"')
    if [ -n "$component_id" ]; then
        echo "  ${component_id}:" >> component-readiness.yaml
        echo "    fa_ready: false" >> component-readiness.yaml
        echo "    notes: \"\"" >> component-readiness.yaml
    fi
done

echo ""
echo "Generated component-readiness.yaml with $(grep 'fa_ready' component-readiness.yaml | wc -l) components (all set to not ready)"
echo "Edit the file or use the management page to mark components as FA-ready."
```

**IMPORTANT**: Adapt the manifest parsing to match the actual manifest file structure found in Phase 0. The grep/awk above is illustrative — the actual field name and location may differ.

### 3.2 Set known-stable components to ready

After generating the config, manually (or via the management page) set the known-stable components to `fa_ready: true`. At minimum, start with the core components that FAs have been using successfully:

```yaml
# These are the components you know are stable — adapt to actual IDs
components:
  minio:
    fa_ready: true
    notes: "Core component"
  # ... set other stable ones
```

### 3.3 Validation — Phase 3

```bash
# 1. Run the seed script
bash scripts/seed-readiness.sh

# 2. Verify all components are listed
MANIFEST_COUNT=$(find <manifests-path> -name "*.yaml" | wc -l)
READINESS_COUNT=$(grep "fa_ready" component-readiness.yaml | wc -l)
echo "Manifests: $MANIFEST_COUNT, Readiness entries: $READINESS_COUNT"
# Expected: counts should match

# 3. Verify all default to false
grep "fa_ready: true" component-readiness.yaml | wc -l
# Expected: 0 (all start as not ready)

# 4. Mark some as ready and verify
# Edit the file or use the management page
# Then restart in FA mode and confirm only those components appear
```

---

## Phase 4 — Deploy Validation on FA Side

Add a deployment-time check to prevent FAs from deploying demos that contain non-ready components (defense-in-depth against UI bugs or API manipulation).

### 4.1 Backend deploy guard

In the deploy endpoint (find the actual function in Phase 0):

```python
# In the deploy handler
async def deploy_demo(request: DeployRequest):
    mode = os.getenv("DEMOFORGE_MODE", "dev")
    
    if mode == "fa":
        readiness.load()
        component_ids = [c.id for c in request.components]  # adapt to actual schema
        blocking = readiness.get_blocking_components(component_ids)
        
        if blocking:
            raise HTTPException(
                status_code=403,
                detail={
                    "message": "Demo contains components that are not yet available",
                    "blocking_components": blocking,
                },
            )
    
    # ... proceed with deploy
```

### 4.2 Validation — Phase 4

```bash
# 1. In FA mode, try to deploy a demo with a non-ready component via API
# (bypassing the UI filtering)
curl -s -X POST http://localhost:<port>/api/demos/deploy \
  -H "Content-Type: application/json" \
  -d '{"components": [{"id": "<non-ready-component>"}]}' \
  -w "\nHTTP %{http_code}\n"
# Expected: 403 with blocking_components list

# 2. Deploy with all-ready components
curl -s -X POST http://localhost:<port>/api/demos/deploy \
  -H "Content-Type: application/json" \
  -d '{"components": [{"id": "<ready-component>"}]}' \
  -w "\nHTTP %{http_code}\n"
# Expected: 200/201 success

# 3. In dev mode, deploy with non-ready components
# Expected: succeeds (no readiness check in dev mode)
```

---

## Phase 5 — Automated Tests

### 5.1 Backend tests

```python
# tests/test_readiness.py

class TestComponentReadiness:
    """Unit tests for the ComponentReadiness class."""
    
    def test_default_is_not_ready(self):
        """Component not in config should be not ready."""
        r = ComponentReadiness()
        r.load(empty_config_path)
        assert r.is_fa_ready("unknown-component") is False
    
    def test_fa_ready_true(self):
        """Component explicitly marked as ready."""
        r = ComponentReadiness()
        r._config = {"minio": {"fa_ready": True}}
        assert r.is_fa_ready("minio") is True
    
    def test_fa_ready_false(self):
        """Component explicitly marked as not ready."""
        r = ComponentReadiness()
        r._config = {"spark": {"fa_ready": False}}
        assert r.is_fa_ready("spark") is False
    
    def test_template_all_ready(self):
        """Template with all ready components is FA-ready."""
        r = ComponentReadiness()
        r._config = {
            "minio": {"fa_ready": True},
            "trino": {"fa_ready": True},
        }
        assert r.is_template_fa_ready(["minio", "trino"]) is True
    
    def test_template_one_not_ready(self):
        """Template with one non-ready component is not FA-ready."""
        r = ComponentReadiness()
        r._config = {
            "minio": {"fa_ready": True},
            "spark": {"fa_ready": False},
        }
        assert r.is_template_fa_ready(["minio", "spark"]) is False
    
    def test_template_with_unlisted_component(self):
        """Template with a component not in config is not FA-ready."""
        r = ComponentReadiness()
        r._config = {"minio": {"fa_ready": True}}
        assert r.is_template_fa_ready(["minio", "new-thing"]) is False
    
    def test_blocking_components(self):
        """Returns only the non-ready components."""
        r = ComponentReadiness()
        r._config = {
            "minio": {"fa_ready": True},
            "spark": {"fa_ready": False},
            "trino": {"fa_ready": True},
        }
        assert r.get_blocking_components(["minio", "spark", "trino"]) == ["spark"]
    
    def test_get_ready_component_ids(self):
        """Returns set of ready component IDs."""
        r = ComponentReadiness()
        r._config = {
            "minio": {"fa_ready": True},
            "spark": {"fa_ready": False},
            "trino": {"fa_ready": True},
        }
        assert r.get_ready_component_ids() == {"minio", "trino"}
    
    def test_set_readiness_new_component(self):
        """Setting readiness on unlisted component adds it."""
        r = ComponentReadiness()
        r._config = {}
        r.set_readiness("new-comp", True, "Ready now", "dev@localhost")
        assert r.is_fa_ready("new-comp") is True
        assert r._config["new-comp"]["notes"] == "Ready now"
    
    def test_set_readiness_preserves_existing_fields(self):
        """Updating readiness doesn't clobber unrelated fields."""
        r = ComponentReadiness()
        r._config = {"minio": {"fa_ready": False, "notes": "old note"}}
        r.set_readiness("minio", True, "new note")
        assert r._config["minio"]["fa_ready"] is True
        assert r._config["minio"]["notes"] == "new note"
    
    def test_save_and_load_roundtrip(self, tmp_path):
        """Config survives save → load cycle."""
        r = ComponentReadiness()
        r._config = {"minio": {"fa_ready": True, "notes": "test"}}
        config_file = tmp_path / "readiness.yaml"
        r.save(config_file)
        
        r2 = ComponentReadiness()
        r2.load(config_file)
        assert r2.is_fa_ready("minio") is True
        assert r2._config["minio"]["notes"] == "test"
    
    def test_empty_template_is_ready(self):
        """Edge case: template with no components is considered ready."""
        r = ComponentReadiness()
        assert r.is_template_fa_ready([]) is True


class TestReadinessAPI:
    """Integration tests for readiness API endpoints."""
    
    def test_get_components_returns_all(self, test_client):
        """GET /api/readiness/components returns all components with readiness."""
        response = test_client.get("/api/readiness/components")
        assert response.status_code == 200
        data = response.json()
        assert "components" in data
        assert "summary" in data
    
    def test_get_templates_returns_all(self, test_client):
        """GET /api/readiness/templates returns all templates with derived status."""
        response = test_client.get("/api/readiness/templates")
        assert response.status_code == 200
        data = response.json()
        assert "templates" in data
        for t in data["templates"]:
            assert "is_fa_ready" in t
            assert "blocking_components" in t
    
    def test_toggle_readiness_dev_mode(self, test_client_dev):
        """PUT in dev mode succeeds."""
        response = test_client_dev.put(
            "/api/readiness/components/minio",
            json={"fa_ready": True, "notes": "test"},
        )
        assert response.status_code == 200
    
    def test_toggle_readiness_fa_mode_blocked(self, test_client_fa):
        """PUT in FA mode returns 403."""
        response = test_client_fa.put(
            "/api/readiness/components/minio",
            json={"fa_ready": True},
        )
        assert response.status_code == 403
    
    def test_toggle_nonexistent_component(self, test_client_dev):
        """PUT for unknown component returns 404."""
        response = test_client_dev.put(
            "/api/readiness/components/does-not-exist",
            json={"fa_ready": True},
        )
        assert response.status_code == 404
    
    def test_batch_update(self, test_client_dev):
        """Batch update modifies multiple components."""
        response = test_client_dev.put(
            "/api/readiness/components/batch",
            json={"updates": [
                {"component_id": "minio", "fa_ready": True},
                {"component_id": "trino", "fa_ready": False},
            ]},
        )
        assert response.status_code == 200
        results = response.json()["results"]
        assert len(results) == 2


class TestFAModeFiltering:
    """Tests that FA mode correctly hides non-ready items."""
    
    def test_component_list_filtered_in_fa_mode(self, test_client_fa):
        """FA mode only returns ready components."""
        response = test_client_fa.get("/api/components")
        data = response.json()
        # All returned components should be FA-ready
        # (cross-check against readiness config)
    
    def test_template_list_filtered_in_fa_mode(self, test_client_fa):
        """FA mode only returns templates with all-ready components."""
        response = test_client_fa.get("/api/templates")
        data = response.json()
        # All returned templates should have 0 blocking components
    
    def test_deploy_blocked_for_non_ready_component(self, test_client_fa):
        """FA mode deploy rejects non-ready components."""
        response = test_client_fa.post("/api/demos/deploy", json={
            "components": [{"id": "non-ready-component"}],
        })
        assert response.status_code == 403
        assert "blocking_components" in response.json()["detail"]
    
    def test_dev_mode_returns_all_components(self, test_client_dev):
        """Dev mode returns all components regardless of readiness."""
        response = test_client_dev.get("/api/components")
        # Should include non-ready components
    
    def test_dev_mode_allows_non_ready_deploy(self, test_client_dev):
        """Dev mode deploy allows non-ready components."""
        response = test_client_dev.post("/api/demos/deploy", json={
            "components": [{"id": "non-ready-component"}],
        })
        assert response.status_code != 403
```

Run with:
```bash
pytest tests/test_readiness.py -v
```

**All tests must pass before moving to Phase 5 frontend validation.**

---

## Phase 6 — Telemetry Integration (Optional, if Hub API exists)

If the Hub API from `claude-code-hub-api.md` is implemented, extend telemetry to track readiness changes:

```python
# When readiness is toggled, emit an event
await emit_event("component_readiness_changed", {
    "component_id": component_id,
    "fa_ready": fa_ready,
    "notes": notes,
    "changed_by": updated_by,
    "affected_templates": [t["template_id"] for t in affected_templates],
})
```

Add `component_readiness_changed` to the Hub API's allowed event types.

This is a low-priority addition — implement only if the Hub API is already in place.

---

## Design Principles

### Non-negotiables

1. **Safe default** — unlisted components are NOT ready. Explicit opt-in only.
2. **Derived template readiness** — never stored, always computed. No sync drift.
3. **Invisible, not disabled** — FAs never see non-ready components or templates. No greyed-out items, no "coming soon" badges. They simply don't exist from the FA's perspective.
4. **Dev mode is unrestricted** — developers see everything, can deploy anything. Readiness is a release gate, not a dev blocker.
5. **Single file source of truth** — `component-readiness.yaml` is the only place readiness lives. Version-controlled, reviewable, auditable.
6. **Readiness management is dev-only** — the management page and write APIs are not available in FA mode.

### What NOT to build

- **No per-FA component visibility** — readiness is global. All FAs see the same set of ready components. Per-FA control is a future extension (via Hub API permissions).
- **No staging/preview mode** — a component is either ready or not. No "beta" state.
- **No automatic readiness detection** — readiness is a manual human decision. No test suite integration.
- **No readiness history/changelog** — the `updated_at` and `updated_by` fields are sufficient. Git history on the YAML file provides full audit trail.

---

## Summary of Changes by File/Area

| Area | What Changes | New Files |
|---|---|---|
| `component-readiness.yaml` | New config file listing all components | Yes (project root) |
| `backend/readiness.py` | Readiness loader/manager class | Yes |
| `backend/routers/readiness.py` | API endpoints for readiness CRUD | Yes |
| `backend/routers/components.py` | Add FA-mode filtering to component list | Modified |
| `backend/routers/templates.py` | Add FA-mode filtering to template list | Modified |
| `backend/routers/deploy.py` | Add deploy guard for non-ready components | Modified |
| `frontend/pages/ReadinessPage.tsx` | Management page with two tabs | Yes |
| `frontend/router` or `App.tsx` | Add /readiness route (dev mode only) | Modified |
| `frontend/navigation/Sidebar.tsx` | Add nav link (dev mode only) | Modified |
| `scripts/seed-readiness.sh` | One-time config generator | Yes |
| `tests/test_readiness.py` | Unit + integration tests | Yes |

---

## Implementation Order

**Do phases sequentially. Each phase must pass its validation before the next begins.**

1. **Phase 0** — Investigate (understand manifests, templates, mode gating, existing APIs)
2. **Phase 1** — Readiness config + backend loader + API endpoints + existing endpoint filtering
3. **Phase 2** — Frontend management page (dev mode only)
4. **Phase 3** — Seed the config from existing manifests
5. **Phase 4** — Deploy guard (defense-in-depth)
6. **Phase 5** — Automated tests
7. **Phase 6** — Telemetry integration (optional, if Hub API exists)
