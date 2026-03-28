# DemoForge Enhancement Execution Plan — Complete Claude Code Instructions

## How to use this document

This is a single, self-contained instruction file. Each phase is independent. Complete all tasks in a phase before moving to the next. Each phase ends with unit tests and E2E validation.

Before starting ANY phase, read these files to understand conventions:
- `backend/app/models/demo.py` — DemoDefinition, DemoNode, DemoSchematicNode, DemoAnnotation models
- `backend/app/engine/compose_generator.py` — edge resolution patterns
- `frontend/src/types/index.ts` — all TypeScript types, ConnectionType union, SchematicNodeData
- `frontend/src/stores/diagramStore.ts` — React Flow state management, Experience mode filtering
- `frontend/src/stores/demoStore.ts` — demo state, active view
- `frontend/src/components/properties/PropertiesPanel.tsx` — sub-panel routing
- `frontend/src/components/canvas/DiagramCanvas.tsx` — node/edge type registration (includes schematic type)
- `frontend/src/components/canvas/nodes/SchematicNode.tsx` — visual-only node type
- `frontend/src/components/canvas/edges/AnimatedDataEdge.tsx` — edge rendering with protocol/latency pills
- `demo-templates/*.yaml` — template structure, `_template:` metadata block

---

## Phase 1: Template Cleanup, Gallery Tiers & SE Guides (2-3 days)

### 1A: Remove redundant templates

Delete these 8 template files from `demo-templates/`:

```bash
rm demo-templates/single-minio.yaml
rm demo-templates/load-balanced-minio.yaml
rm demo-templates/minio-with-monitoring.yaml
rm demo-templates/bucket-replication.yaml
rm demo-templates/template-minio-ai-assistant.yaml
rm demo-templates/template-cluster-resilience.yaml
```

For the anonymous templates (no `id` field or auto-generated names), search for files containing these names and remove:
- "MinIO Cluster (4-Node)"
- "Multi-Node MinIO Cluster"

**Verification:** Run `ls demo-templates/ | wc -l` — should drop from 32 to ~24.

### 1B: Merge tiering templates

Three tiering templates exist: `tiered-storage.yaml`, `template-ilm-tiering.yaml`, and the anonymous "ILM Tiered Storage (Hot to Cold Clusters)". Merge into one:

1. Keep `tiered-storage.yaml` as the base
2. Rename to `template-smart-tiering.yaml`
3. Adopt the richer topology from `template-ilm-tiering` (cluster-level tiering with Grafana + Prometheus)
4. Update `_template:` metadata with new customer-friendly name "Smart data tiering"
5. Delete the other two tiering templates

### 1C: Fix anonymous templates

For templates missing an `id` field:
1. "Multi-Cluster with Replication" → add `id: template-multi-cluster-replication`
2. "Site Replication (Bidirectional)" → add `id: template-site-replication-bidirectional`

### 1D: Rename all templates

Update the `_template.name` field in every remaining template to use customer-friendly names. This is the `name` shown in the gallery, not the `id`.

| Template file | New `_template.name` |
|---|---|
| `template-bi-dashboard-lakehouse.yaml` | "Lakehouse quickstart" |
| `template-bi-dashboard-aistor-tables.yaml` | "AIStor Tables analytics" |
| `template-realtime-analytics.yaml` | "Real-time analytics" |
| `template-smart-tiering.yaml` | "Smart data tiering" |
| `active-active-replication.yaml` | "Active-active replication" |
| `template-multi-site-replication.yaml` | "Site replication" |
| `template-site-replication-failover.yaml` | "Site replication with failover" |
| `template-rag-pipeline.yaml` | "Semantic document search" |
| `template-ml-experiment-lab.yaml` | "ML experiment tracker" |
| `template-streaming-lakehouse.yaml` | "Streaming lakehouse" |
| `template-dremio-lakehouse.yaml` | "Multi-engine lakehouse (Dremio + Trino)" |
| `template-versioned-data-lake.yaml` | "Versioned data lake (Nessie)" |
| `template-complete-analytics.yaml` | "Complete analytics platform" |
| `template-full-analytics-pipeline.yaml` | "Full analytics pipeline (Spark)" |
| `template-hadoop-migration.yaml` | "HDFS to MinIO migration" |
| `template-multi-site-replication-3way.yaml` | "Three-way site replication" |
| `template-data-labeling-pipeline.yaml` | "AI data labeling pipeline" |
| `template-enterprise-vector-search.yaml` | "Enterprise vector search (Milvus)" |
| `template-automated-ml-pipeline.yaml` | "Automated ML pipeline" |
| `template-minio-ai-platform.yaml` | "MinIO AI platform" |
| `experience-stx-inference.yaml` | "NVIDIA STX: inside inference memory" |

### 1E: Add `tier` and `category` to template metadata

File: `backend/app/models/demo.py`

Add to the `_template` metadata model (this is the YAML metadata parsed from templates):

```python
class SEGuideStep(BaseModel):
    step: int
    action: str                    # What to do
    say: str = ""                  # What to say to the customer
    show: str = ""                 # What to point at on screen

class SEGuideQuestion(BaseModel):
    q: str
    a: str

class SEGuideMcCommand(BaseModel):
    label: str
    command: str
    context: str = ""

class SEGuide(BaseModel):
    pitch: str                     # One-line elevator pitch for this demo
    audience: str = ""             # Who is this demo for
    before_demo: str = ""          # Context to set before starting
    talking_points: list[str] = [] # Key messages to convey
    demo_flow: list[SEGuideStep] = []
    common_questions: list[SEGuideQuestion] = []
    mc_commands: list[SEGuideMcCommand] = []

class TemplateMetadata(BaseModel):
    name: str
    tier: str = "essentials"        # "essentials" | "advanced"
    category: str = "general"       # "lakehouse" | "infrastructure" | "ai" | "simulation"
    mode: str = "standard"          # "standard" | "experience"
    tags: list[str] = []
    description: str = ""
    objective: str = ""
    minio_value: str = ""
    estimated_resources: dict = {}
    walkthrough: list[dict] = []
    external_dependencies: list[str] = []
    se_guide: SEGuide | None = None  # NEW: SE demo guide
```

Update every template YAML's `_template:` block with `tier:` and `category:`.

**Essentials tier assignment:**
- Lakehouse quickstart → `tier: essentials`, `category: lakehouse`
- AIStor Tables analytics → `tier: essentials`, `category: lakehouse`
- Real-time analytics → `tier: essentials`, `category: lakehouse`
- Smart data tiering → `tier: essentials`, `category: infrastructure`
- Active-active replication → `tier: essentials`, `category: infrastructure`
- Site replication → `tier: essentials`, `category: infrastructure`
- Site replication with failover → `tier: essentials`, `category: infrastructure`
- Semantic document search → `tier: essentials`, `category: ai`
- ML experiment tracker → `tier: essentials`, `category: ai`

**Everything else → `tier: advanced`** with appropriate `category`.
**Experiences → `tier: experience`** (already marked with `mode: experience`).

### 1F: Template Gallery UI — Essentials/Advanced/Experiences tabs

File: `frontend/src/components/gallery/TemplateGallery.tsx` (or wherever the template gallery/list is rendered)

**Changes:**

1. Add three tab buttons at the top: `Essentials` (default active), `Advanced`, `Experiences`
2. Parse the `tier` field from template metadata returned by the API
3. Filter templates by selected tier
4. Within each tier, group templates by `category` with a section header:
   ```
   ── Lakehouse ───────────────
   ● Lakehouse quickstart     7 containers
   ● AIStor Tables analytics  4 containers
   
   ── Infrastructure ──────────
   ● Smart data tiering       4 containers
   ● Active-active replication 5 containers
   ```
5. Each template card shows: name, container count, description (first line), and category badge
6. Clicking a template loads it onto the canvas as before
7. The Experience tab shows templates with a distinct visual: purple "Experience" badge, description includes "read-only simulation"

**Backend change:** Ensure `GET /api/templates` returns `tier` and `category` from the `_template:` metadata.

File: `backend/app/api/templates.py`

Update the template list endpoint to include tier and category in the response:

```python
class TemplateSummary(BaseModel):
    id: str
    name: str
    tier: str              # "essentials" | "advanced" | "experience"
    category: str          # "lakehouse" | "infrastructure" | "ai" | "simulation"
    mode: str              # "standard" | "experience"
    description: str
    node_count: int
    tags: list[str]
    estimated_resources: dict
    has_se_guide: bool     # NEW: indicates if SE guide is available
```


### 1G: SE Guide Panel (NEW)

#### Where it appears

The SE guide is accessible from two places:

**1. Gallery card** — Before deploying. When the SE selects a template in the gallery, a "SE Guide" button appears in the template detail view. Clicking it opens a slide-out panel showing the guide.

**2. Deployed demo sidebar** — During the demo. A "Guide" tab appears alongside "Properties" and "Playbook" in the right sidebar when a demo is running. The SE can glance at talking points and demo_flow steps mid-demo.

#### SE Guide Panel component

File: `frontend/src/components/guide/SEGuidePanel.tsx` (new file)

Renders four tabbed sections:
- **Demo flow** — numbered steps with `action` (what to click), `say` (what to tell the customer), `show` (what to point at)
- **Talking points** — bullet list of quotable key messages
- **Q&A** — expandable accordion of common customer questions with ready answers
- **Commands** — copyable `mc` CLI commands with context labels

The pitch is always visible at the top as a teal-highlighted card.

#### Backend — SE guide API

File: `backend/app/api/templates.py`

Add a detail endpoint:

```python
@router.get("/api/templates/{template_id}/guide")
async def get_template_guide(template_id: str):
    """Return the SE guide for a template."""
    template = load_template(template_id)
    if not template:
        raise HTTPException(404, "Template not found")
    meta = template._template
    if not meta.get("se_guide"):
        raise HTTPException(404, "No SE guide for this template")
    return meta["se_guide"]
```

### 1H: Write SE guides for all Essentials templates (NEW)

Every template with `tier: essentials` must have a complete `se_guide` in its `_template:` block. Each guide must include:
- `pitch` — one-line elevator pitch
- `audience` — who this demo is for
- `talking_points` — 4-6 quotable key messages (phrased as actual speech)
- `demo_flow` — 3-6 numbered steps with `action`, `say`, and `show`
- `common_questions` — 3-5 Q&A pairs for objection handling
- `mc_commands` — 3-5 useful `mc` CLI commands with context

Templates requiring SE guides:

| Template | Pitch focus |
|----------|------------|
| Lakehouse quickstart | MinIO + Iceberg + Trino = queryable data lake in 5 min |
| AIStor Tables analytics | Native Iceberg tables in MinIO — no external catalog needed |
| Real-time analytics | Streaming data into MinIO, live queries via Trino |
| Smart data tiering | ILM lifecycle rules — automatic hot/warm/cold migration |
| Active-active replication | Bidirectional replication between two MinIO clusters |
| Site replication | Full IAM + bucket sync across sites |
| Site replication with failover | DR scenario — primary fails, secondary takes over |
| Semantic document search | RAG pipeline — documents, embeddings, semantic search |
| ML experiment tracker | MLflow + MinIO — model versioning and artifact storage |

Advanced templates get stubs (`pitch` only). Experience templates (STX) already have guided demo mode in the simulator UI, so their `se_guide` focuses on how to launch and what to expect.

#### Example SE guide (for Lakehouse quickstart)

```yaml
_template:
  name: "Lakehouse quickstart"
  # ... existing fields ...
  se_guide:
    pitch: "Show how MinIO + Iceberg + Trino creates a fully queryable data lakehouse in under 5 minutes."
    audience: "Data engineers, analytics leads, or CTOs evaluating object storage for analytics."
    before_demo: |
      Make sure the customer understands why object storage instead of HDFS or a warehouse.
      Key points: S3 API compatibility, separation of compute and storage, Iceberg providing ACID on object storage.
    talking_points:
      - "MinIO is the storage layer — all data lands here as Parquet files via the S3 API."
      - "Iceberg provides the table format — schema evolution, time travel, partition pruning without moving data."
      - "Trino queries the data directly from MinIO — no ETL, no copying to a separate warehouse."
      - "This same MinIO cluster could serve your ML training data, model weights, and application assets."
    demo_flow:
      - step: 1
        action: "Deploy the template and wait for all nodes to turn green (~60 seconds)."
        say: "This spins up a complete lakehouse stack — MinIO, Iceberg catalog, Trino, and Metabase."
      - step: 2
        action: "Open the SQL Playbook panel. Run step 1 (verify data)."
        say: "The data generator writes synthetic e-commerce orders as Parquet to MinIO via S3. Trino queries them through Iceberg."
      - step: 3
        action: "Run playbook step 2 (revenue by region)."
        say: "Standard SQL aggregation — but the data lives in object storage. No data movement, no ETL pipeline."
        show: "Point at the query execution time."
      - step: 4
        action: "Open MinIO Console (click Web UI link on the MinIO node)."
        say: "Here is what the data looks like in MinIO — Parquet files organized by Iceberg partition scheme."
        show: "Navigate to the iceberg bucket, show data/ and metadata/ directories."
      - step: 5
        action: "Open Metabase dashboard."
        say: "Metabase connects to Trino which connects to MinIO. Dashboard updates as new data lands."
    common_questions:
      - q: "How does this compare to Snowflake/Databricks?"
        a: "Same architecture (compute separated from storage) but you own the storage layer. No vendor lock-in — open Parquet files on S3-compatible storage."
      - q: "What about performance at scale?"
        a: "MinIO scales linearly — add nodes, get more throughput. Trino scales independently by adding workers."
      - q: "Can we use existing S3 tools?"
        a: "Yes — any tool that speaks S3 API works. aws-cli, boto3, Spark S3A connector, all of them."
    mc_commands:
      - label: "List buckets"
        command: "mc ls minio/"
        context: "Shows all buckets including the iceberg warehouse bucket."
      - label: "Check bucket size"
        command: "mc du minio/warehouse"
        context: "Total data size — useful for demonstrating data growth."
      - label: "View Iceberg metadata"
        command: "mc ls minio/warehouse/default/ecommerce_orders/metadata/"
        context: "Shows Iceberg metadata files — manifest lists, manifests, snapshots."
```

### Phase 1 tests

**Unit tests** (`backend/tests/test_phase1.py`):

```python
def test_template_count():
    """After cleanup, should have ~22 templates (not 32)."""
    templates = load_all_templates(TEMPLATES_DIR)
    assert 20 <= len(templates) <= 24

def test_all_templates_have_id():
    """Every template must have a non-empty id field."""
    templates = load_all_templates(TEMPLATES_DIR)
    for t in templates:
        assert t.id, f"Template '{t.name}' has no id"

def test_all_templates_have_tier():
    """Every template must have a tier in its metadata."""
    templates = load_all_templates(TEMPLATES_DIR)
    for t in templates:
        meta = t._template if hasattr(t, '_template') else {}
        assert meta.get("tier") in ("essentials", "advanced", "experience"), \
            f"Template '{t.name}' has invalid tier: {meta.get('tier')}"

def test_all_templates_have_category():
    """Every template must have a category."""
    templates = load_all_templates(TEMPLATES_DIR)
    valid_categories = {"lakehouse", "infrastructure", "ai", "simulation", "general"}
    for t in templates:
        meta = t._template if hasattr(t, '_template') else {}
        assert meta.get("category") in valid_categories

def test_removed_templates_gone():
    """Verify redundant templates were actually deleted."""
    import os
    removed = ["single-minio.yaml", "load-balanced-minio.yaml", 
               "minio-with-monitoring.yaml", "bucket-replication.yaml",
               "template-minio-ai-assistant.yaml", "template-cluster-resilience.yaml"]
    for name in removed:
        assert not os.path.exists(os.path.join(TEMPLATES_DIR, name))

def test_templates_api_returns_tier():
    """API response includes tier and category."""
    response = client.get("/api/templates")
    templates = response.json()["templates"]
    for t in templates:
        assert "tier" in t
        assert "category" in t
```


def test_essentials_templates_have_se_guide():
    """Every essentials template must have a complete SE guide."""
    templates = load_all_templates(TEMPLATES_DIR)
    for t in templates:
        meta = t._template
        if meta.get("tier") == "essentials":
            guide = meta.get("se_guide")
            assert guide is not None, f"'{meta['name']}' missing SE guide"
            assert guide.get("pitch"), f"'{meta['name']}' guide missing pitch"
            assert len(guide.get("talking_points", [])) >= 3
            assert len(guide.get("demo_flow", [])) >= 3
            assert len(guide.get("common_questions", [])) >= 2

def test_se_guide_api_endpoint():
    """GET /api/templates/{id}/guide should return guide content."""
    response = client.get("/api/templates/template-bi-dashboard-lakehouse/guide")
    assert response.status_code == 200
    data = response.json()
    assert "pitch" in data
    assert "demo_flow" in data

def test_template_list_includes_has_se_guide():
    """Template list should indicate which have guides."""
    response = client.get("/api/templates")
    templates = response.json()["templates"]
    for t in templates:
        assert "has_se_guide" in t

**Playwright E2E** (`e2e/phase1.spec.ts`):

```typescript
import { test, expect } from '@playwright/test';

test.describe('Phase 1: Template Gallery', () => {
  test('gallery shows three tier tabs', async ({ page }) => {
    await page.goto('/');
    // Open template gallery (click the gallery/template button)
    await page.click('[data-testid="template-gallery-btn"]');
    
    await expect(page.locator('[data-testid="tier-tab-essentials"]')).toBeVisible();
    await expect(page.locator('[data-testid="tier-tab-advanced"]')).toBeVisible();
    await expect(page.locator('[data-testid="tier-tab-experiences"]')).toBeVisible();
  });

  test('essentials tab shows correct templates', async ({ page }) => {
    await page.goto('/');
    await page.click('[data-testid="template-gallery-btn"]');
    await page.click('[data-testid="tier-tab-essentials"]');
    
    // Should show ~10 essentials templates
    const cards = page.locator('[data-testid="template-card"]');
    await expect(cards).toHaveCount({ minimum: 8, maximum: 12 });
    
    // Should have category sections
    await expect(page.locator('text=Lakehouse')).toBeVisible();
    await expect(page.locator('text=Infrastructure')).toBeVisible();
  });

  test('advanced tab shows more complex templates', async ({ page }) => {
    await page.goto('/');
    await page.click('[data-testid="template-gallery-btn"]');
    await page.click('[data-testid="tier-tab-advanced"]');
    
    const cards = page.locator('[data-testid="template-card"]');
    await expect(cards).toHaveCount({ minimum: 10 });
  });

  test('experience tab shows read-only templates', async ({ page }) => {
    await page.goto('/');
    await page.click('[data-testid="template-gallery-btn"]');
    await page.click('[data-testid="tier-tab-experiences"]');
    
    // Should show experience templates with "Experience" badge
    await expect(page.locator('[data-testid="experience-badge"]').first()).toBeVisible();
  });

  test('template names are customer-friendly', async ({ page }) => {
    await page.goto('/');
    await page.click('[data-testid="template-gallery-btn"]');
    
    // Should NOT see internal names
    await expect(page.locator('text=template-bi-dashboard-lakehouse')).not.toBeVisible();
    // Should see customer-friendly names
    await expect(page.locator('text=Lakehouse quickstart')).toBeVisible();
  });


  test('SE guide indicator on essentials templates', async ({ page }) => {
    await page.goto('/');
    await page.click('[data-testid="template-gallery-btn"]');
    await page.click('[data-testid="tier-tab-essentials"]');
    await expect(page.locator('[data-testid="se-guide-indicator"]').first()).toBeVisible();
  });

  test('clicking SE guide opens guide panel', async ({ page }) => {
    await page.goto('/');
    await page.click('[data-testid="template-gallery-btn"]');
    await page.locator('[data-testid="template-card"]').first().click();
    await page.click('[data-testid="se-guide-btn"]');
    await expect(page.locator('[data-testid="se-guide-pitch"]')).toBeVisible();
  });

  test('guide has all section tabs', async ({ page }) => {
    // Open guide for a template
    await expect(page.locator('text=Demo flow')).toBeVisible();
    await expect(page.locator('text=Talking points')).toBeVisible();
    await expect(page.locator('text=Q&A')).toBeVisible();
    await expect(page.locator('text=Commands')).toBeVisible();
  });

  test('guide tab visible when demo is deployed', async ({ page }) => {
    // Deploy a template, then check sidebar
    await expect(page.locator('[data-testid="sidebar-tab-guide"]')).toBeVisible();
  });

  test('loading a template populates the canvas', async ({ page }) => {
    await page.goto('/');
    await page.click('[data-testid="template-gallery-btn"]');
    await page.click('[data-testid="tier-tab-essentials"]');
    
    // Click the first template
    await page.locator('[data-testid="template-card"]').first().click();
    
    // Canvas should have nodes
    await expect(page.locator('.react-flow__node')).toHaveCount({ minimum: 3 });
  });
});
```

---

## Phase 2: SQL Playbook Panel (3-4 days)
> **SE guide requirement:** After implementing each template in this phase, write its `se_guide` in the `_template:` block. The guide lives in the template YAML — no separate docs.


This is the highest-priority enhancement. It enables guided SQL execution for Scenarios 1, 2, 3, 5, and 8.

### 2A: Backend — SQL execution endpoint

File: `backend/app/api/sql.py` (new file)

```python
"""Execute SQL statements against Trino containers in a running demo."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import httpx

from ..state.store import state
from ..registry.loader import get_component

router = APIRouter()

class SqlExecuteRequest(BaseModel):
    sql: str
    catalog: str = "iceberg"
    schema_name: str = "default"

class SqlColumn(BaseModel):
    name: str
    type: str

class SqlExecuteResponse(BaseModel):
    success: bool
    columns: list[SqlColumn] = []
    rows: list[list] = []
    row_count: int = 0
    error: str = ""
    execution_time_ms: int = 0

@router.post("/api/demos/{demo_id}/sql", response_model=SqlExecuteResponse)
async def execute_sql(demo_id: str, req: SqlExecuteRequest):
    """
    Execute SQL against the Trino node in a running demo.
    Finds the Trino container by looking for a node with component=trino.
    Uses Trino's HTTP API (port 8080, /v1/statement).
    """
    running = state.get_demo(demo_id)
    if not running:
        raise HTTPException(404, "Demo not running")
    
    # Find the Trino node
    trino_container = None
    for node_id, container in running.containers.items():
        if container.component_id == "trino":
            trino_container = container
            break
    
    if not trino_container:
        raise HTTPException(400, "No Trino node found in this demo")
    
    # Trino HTTP API endpoint
    trino_url = f"http://{trino_container.container_name}:8080"
    
    import time
    start = time.time()
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Submit query
            resp = await client.post(
                f"{trino_url}/v1/statement",
                content=req.sql,
                headers={
                    "X-Trino-User": "demoforge",
                    "X-Trino-Catalog": req.catalog,
                    "X-Trino-Schema": req.schema_name,
                }
            )
            result = resp.json()
            
            # Poll for results (Trino is async)
            columns = []
            rows = []
            while True:
                if "columns" in result and not columns:
                    columns = [
                        SqlColumn(name=c["name"], type=c.get("type", "unknown"))
                        for c in result["columns"]
                    ]
                if "data" in result:
                    rows.extend(result["data"])
                
                next_uri = result.get("nextUri")
                if not next_uri:
                    break
                
                resp = await client.get(next_uri)
                result = resp.json()
            
            elapsed = int((time.time() - start) * 1000)
            
            # Check for error
            if result.get("error"):
                return SqlExecuteResponse(
                    success=False,
                    error=result["error"].get("message", "Unknown error"),
                    execution_time_ms=elapsed,
                )
            
            return SqlExecuteResponse(
                success=True,
                columns=columns,
                rows=rows,
                row_count=len(rows),
                execution_time_ms=elapsed,
            )
    
    except Exception as e:
        return SqlExecuteResponse(
            success=False,
            error=str(e),
            execution_time_ms=int((time.time() - start) * 1000),
        )
```

Register in `backend/app/main.py`:

```python
from .api import sql
app.include_router(sql.router)
```

### 2B: Dataset scenario — playbook YAML format

Add a `playbook` section to the dataset scenario YAML schema.

File: Update the data-generator's scenario schema (wherever dataset YAMLs are parsed):

```yaml
# Example: add to ecommerce-orders.yaml
playbook:
  - step: 1
    title: "Verify data landed"
    description: "Check that the data generator has written Parquet files to MinIO."
    sql: |
      SELECT count(*) as total_rows FROM iceberg.default.ecommerce_orders
    expected: "Should return a positive count."

  - step: 2
    title: "Revenue by region"
    description: "Aggregate revenue by region to see geographic distribution."
    sql: |
      SELECT region, SUM(total_amount) as revenue, COUNT(*) as orders
      FROM iceberg.default.ecommerce_orders
      GROUP BY region
      ORDER BY revenue DESC
    expected: "Shows revenue breakdown across regions."

  - step: 3
    title: "Top customers"
    description: "Find the highest-spending customers."
    sql: |
      SELECT customer_id, COUNT(*) as order_count, SUM(total_amount) as total_spend
      FROM iceberg.default.ecommerce_orders
      GROUP BY customer_id
      ORDER BY total_spend DESC
      LIMIT 20
    expected: "Top 20 customers by total spend."
```

Each playbook step has: `step` (number), `title`, `description`, `sql`, and optional `expected` (description of expected output).

### 2C: Backend — playbook endpoint

File: `backend/app/api/playbook.py` (new file)

```python
"""Fetch playbook steps for a demo's active dataset scenario."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

class PlaybookStep(BaseModel):
    step: int
    title: str
    description: str
    sql: str
    expected: str = ""

class PlaybookResponse(BaseModel):
    scenario_id: str
    scenario_name: str
    steps: list[PlaybookStep]

@router.get("/api/demos/{demo_id}/playbook", response_model=PlaybookResponse)
async def get_playbook(demo_id: str):
    """
    Return the SQL playbook for the demo's data generator scenario.
    Reads from the dataset scenario YAML.
    """
    # Find the data-generator node in the demo
    # Read its DG_SCENARIO config
    # Load the matching scenario YAML
    # Parse the playbook section
    # Return PlaybookResponse
    ...
```

### 2D: Frontend — SqlPlaybookPanel component

File: `frontend/src/components/properties/SqlPlaybookPanel.tsx` (new file)

**What it renders:**

```
┌─ SQL playbook ─────────────────────────────────────┐
│                                                     │
│  E-commerce orders                                  │
│  ───────────────────────────────────────────────    │
│                                                     │
│  ● Step 1: Verify data landed              ✓ Done  │
│  ┌─────────────────────────────────────────────┐    │
│  │ Check that the data generator has written   │    │
│  │ Parquet files to MinIO.                     │    │
│  │                                             │    │
│  │ ┌───────────────────────────────────────┐   │    │
│  │ │ SELECT count(*) as total_rows         │   │    │
│  │ │ FROM iceberg.default.ecommerce_orders │   │    │
│  │ └───────────────────────────────────────┘   │    │
│  │                                             │    │
│  │ Result: 1,247 rows                          │    │
│  │                                   [▶ Run]   │    │
│  └─────────────────────────────────────────────┘    │
│                                                     │
│  ○ Step 2: Revenue by region               Pending  │
│  ┌─────────────────────────────────────────────┐    │
│  │ Aggregate revenue by region...              │    │
│  │ ┌───────────────────────────────────────┐   │    │
│  │ │ SELECT region, SUM(total_amount)...   │   │    │
│  │ └───────────────────────────────────────┘   │    │
│  │                                   [▶ Run]   │    │
│  └─────────────────────────────────────────────┘    │
│                                                     │
│  ○ Step 3: Top customers                   Pending  │
│  (collapsed — click to expand)                      │
│                                                     │
└─────────────────────────────────────────────────────┘
```

**Implementation details:**

```typescript
interface PlaybookStep {
  step: number;
  title: string;
  description: string;
  sql: string;
  expected: string;
}

interface StepState {
  status: "pending" | "running" | "success" | "error";
  result?: { columns: string[]; rows: any[][]; row_count: number; execution_time_ms: number };
  error?: string;
}

export function SqlPlaybookPanel({ demoId }: { demoId: string }) {
  const [steps, setSteps] = useState<PlaybookStep[]>([]);
  const [stepStates, setStepStates] = useState<Record<number, StepState>>({});
  const [expandedStep, setExpandedStep] = useState<number>(1);

  useEffect(() => {
    // Fetch playbook from /api/demos/{demoId}/playbook
    fetchPlaybook(demoId).then(data => setSteps(data.steps));
  }, [demoId]);

  async function runStep(step: PlaybookStep) {
    setStepStates(prev => ({ ...prev, [step.step]: { status: "running" } }));
    try {
      const result = await executeSql(demoId, step.sql);
      setStepStates(prev => ({
        ...prev,
        [step.step]: {
          status: result.success ? "success" : "error",
          result: result.success ? result : undefined,
          error: result.error || undefined,
        }
      }));
      // Auto-expand next step
      if (result.success) setExpandedStep(step.step + 1);
    } catch (e) {
      setStepStates(prev => ({
        ...prev,
        [step.step]: { status: "error", error: String(e) }
      }));
    }
  }

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-medium">SQL playbook</h3>
      {steps.map(step => (
        <PlaybookStepCard
          key={step.step}
          step={step}
          state={stepStates[step.step] || { status: "pending" }}
          expanded={expandedStep === step.step}
          onToggle={() => setExpandedStep(expandedStep === step.step ? -1 : step.step)}
          onRun={() => runStep(step)}
        />
      ))}
    </div>
  );
}
```

**Where it appears:** In PropertiesPanel, show SqlPlaybookPanel when:
1. The demo is running AND
2. The demo has a data-generator node with a scenario that has a `playbook` section AND
3. The demo has a Trino node

File: `frontend/src/components/properties/PropertiesPanel.tsx`

Add a check:

```typescript
// After existing sub-panel checks
if (demoIsRunning && hasTrinoNode && hasPlaybook) {
  return <SqlPlaybookPanel demoId={activeDemoId} />;
}
```

Alternatively, show it as a tab alongside the existing properties — "Properties | Playbook".

### 2E: Add playbook to existing scenarios

Add a `playbook:` section to each of the 4 existing data-generator scenarios:

1. `ecommerce-orders.yaml` — 5 steps: verify data, revenue by region, top customers, order trends, status distribution
2. `iot-telemetry.yaml` — 4 steps: verify data, avg readings by sensor, alert distribution, readings over time
3. `financial-txn.yaml` — 4 steps: verify data, volume by type, large transactions, daily summary
4. `clickstream.yaml` — 4 steps: verify data, events per minute, conversion funnel, device breakdown

### Phase 2 tests

**Unit tests** (`backend/tests/test_phase2.py`):

```python
def test_sql_execute_endpoint_requires_running_demo():
    """POST /api/demos/{id}/sql should 404 if demo not running."""
    response = client.post("/api/demos/nonexistent/sql", json={"sql": "SELECT 1"})
    assert response.status_code == 404

def test_sql_execute_endpoint_requires_trino():
    """POST /api/demos/{id}/sql should 400 if no Trino node exists."""
    # Create and deploy a demo with only MinIO (no Trino)
    # Attempt to execute SQL → should return 400
    ...

def test_playbook_endpoint_returns_steps():
    """GET /api/demos/{id}/playbook should return playbook steps."""
    # Load a template with data-generator + ecommerce-orders scenario
    response = client.get(f"/api/demos/{demo_id}/playbook")
    data = response.json()
    assert len(data["steps"]) >= 3
    assert data["steps"][0]["step"] == 1
    assert "sql" in data["steps"][0]

def test_all_scenarios_have_playbooks():
    """Every dataset scenario YAML should have a playbook section."""
    import yaml, glob
    for path in glob.glob("components/data-generator/datasets/*.yaml"):
        with open(path) as f:
            scenario = yaml.safe_load(f)
        assert "playbook" in scenario, f"Scenario {path} missing playbook"
        assert len(scenario["playbook"]) >= 3, f"Scenario {path} has too few playbook steps"
```

**Playwright E2E** (`e2e/phase2.spec.ts`):

```typescript
test.describe('Phase 2: SQL Playbook', () => {
  test.beforeAll(async () => {
    // Deploy "Lakehouse quickstart" template
    // Wait for all nodes healthy
  });

  test('playbook panel appears when demo is running', async ({ page }) => {
    await page.goto('/');
    // Load and deploy lakehouse template
    // ...
    
    // Playbook panel or tab should be visible
    await expect(page.locator('[data-testid="sql-playbook-panel"]')).toBeVisible();
  });

  test('playbook shows ordered steps', async ({ page }) => {
    const steps = page.locator('[data-testid="playbook-step"]');
    await expect(steps).toHaveCount({ minimum: 3 });
    
    // First step should be expanded
    await expect(page.locator('[data-testid="playbook-step-1"]')).toHaveAttribute('data-expanded', 'true');
  });

  test('running a step shows results', async ({ page }) => {
    // Click Run on step 1
    await page.click('[data-testid="playbook-run-1"]');
    
    // Should show loading state
    await expect(page.locator('[data-testid="playbook-step-1-status"]')).toHaveText('running');
    
    // Wait for result (up to 30s for Trino)
    await expect(page.locator('[data-testid="playbook-step-1-status"]')).toHaveText('success', { timeout: 30000 });
    
    // Result should show row count
    await expect(page.locator('[data-testid="playbook-step-1-result"]')).toContainText('rows');
  });

  test('completing a step auto-expands the next', async ({ page }) => {
    // After step 1 succeeds...
    await expect(page.locator('[data-testid="playbook-step-2"]')).toHaveAttribute('data-expanded', 'true');
  });

  test('step SQL is read-only but copyable', async ({ page }) => {
    const sqlBlock = page.locator('[data-testid="playbook-sql-1"]');
    await expect(sqlBlock).toBeVisible();
    
    // Should have a copy button
    await expect(page.locator('[data-testid="playbook-copy-1"]')).toBeVisible();
  });

  test.afterAll(async () => {
    // Stop the demo
  });
});
```

---

## Phase 3: Quick-Win Templates — Time Travel & Tiering Enhancement (0.5 day)
> **SE guide requirement:** After implementing each template in this phase, write its `se_guide` in the `_template:` block. The guide lives in the template YAML — no separate docs.


### 3A: Create "Time travel & data auditing" template

File: `demo-templates/template-time-travel.yaml`

Topology: Data Generator → MinIO → Iceberg REST Catalog → Trino → Metabase (+ Prometheus)

Structurally identical to `template-bi-dashboard-lakehouse` but with:
- Different `_template` metadata (name, description, walkthrough focused on time travel)
- `tier: essentials`, `category: lakehouse`
- A dedicated playbook in the ecommerce-orders scenario (or a new scenario variant) with time-travel-specific SQL:

Add a new playbook variant or extend ecommerce-orders with time-travel steps:

```yaml
playbook:
  - step: 1
    title: "Load initial data"
    description: "Start the data generator and verify data arrives."
    sql: "SELECT count(*) as rows FROM iceberg.default.ecommerce_orders"
    
  - step: 2
    title: "Make a change"
    description: "Update order statuses — this creates a new Iceberg snapshot."
    sql: |
      UPDATE iceberg.default.ecommerce_orders
      SET status = 'cancelled'
      WHERE region = 'EMEA' AND total_amount < 50

  - step: 3
    title: "View snapshot history"
    description: "Iceberg tracks every change as a snapshot with full metadata."
    sql: |
      SELECT snapshot_id, committed_at, operation, summary
      FROM iceberg.default."ecommerce_orders$snapshots"
      ORDER BY committed_at DESC

  - step: 4
    title: "Time travel query"
    description: "Query the table as it was before the update."
    sql: |
      SELECT status, count(*) as orders
      FROM iceberg.default.ecommerce_orders
      FOR VERSION AS OF {previous_snapshot_id}
      GROUP BY status

  - step: 5
    title: "Compare versions"
    description: "See what changed between the current and previous version."
    sql: |
      SELECT 'current' as version, count(*) as rows, sum(total_amount) as total
      FROM iceberg.default.ecommerce_orders
      UNION ALL
      SELECT 'previous', count(*), sum(total_amount)
      FROM iceberg.default.ecommerce_orders
      FOR VERSION AS OF {previous_snapshot_id}

  - step: 6
    title: "Rollback"
    description: "Restore the table to its previous state."
    sql: |
      CALL iceberg.system.rollback_to_snapshot('default', 'ecommerce_orders', {previous_snapshot_id})
```

Note: `{previous_snapshot_id}` is a placeholder. The playbook UI needs to handle this by either:
- Running step 3 first and auto-substituting the snapshot ID from the result
- Showing a text input where the user pastes the snapshot ID from step 3's output

**Implementation choice:** After step 3 runs, parse the first result row's `snapshot_id` column and auto-substitute it into steps 4, 5, 6. Store as a "playbook variable" in the panel's state.

### 3B: Enhance "Smart data tiering" template

Update the merged tiering template to include:
1. An annotation explaining ILM lifecycle rules
2. A playbook step showing how to configure ILM via `mc` commands
3. A step demonstrating Iceberg data files tiering from hot to warm

### Phase 3 tests

**Unit tests:**
```python
def test_time_travel_template_loads():
    """Time travel template should load without errors."""
    template = load_template("template-time-travel")
    assert template is not None
    assert template._template.tier == "essentials"
    assert template._template.category == "lakehouse"

def test_time_travel_template_has_playbook():
    """Time travel template's scenario should have a playbook."""
    template = load_template("template-time-travel")
    # Find the data-generator node's scenario
    # Verify playbook exists with >= 5 steps
    ...
```

**Playwright E2E:**
```typescript
test('time travel template deploys and runs playbook', async ({ page }) => {
  // Load "Time travel & data auditing" from Essentials
  // Deploy
  // Wait for healthy
  // Start data generator
  // Wait for data (step 1)
  // Run step 2 (UPDATE)
  // Run step 3 (list snapshots)
  // Verify step 4 auto-substitutes snapshot_id
  // Run step 4 (time travel query)
  // Verify results differ from current
});
```

---

## Phase 4: Multi-Table Data Generation + Customer 360 (4-5 days)
> **SE guide requirement:** After implementing each template in this phase, write its `se_guide` in the `_template:` block. The guide lives in the template YAML — no separate docs.


### 4A: Data generator — multi-table support

This is the most significant data-generator architecture change. The scenario YAML currently has a single `schema:` block. Add support for a `tables:` list.

**Scenario YAML format change:**

```yaml
# datasets/customer-360.yaml
id: customer-360
name: "Customer 360"
description: "Three related tables with consistent foreign keys."

tables:
  - name: customers
    bucket: "bronze/customers"
    generation_mode: "seed"       # "seed" = generate once at start, "continuous" = ongoing
    seed_count: 500               # Generate 500 customer rows at start
    schema:
      columns:
        - {name: customer_id, type: string, generator: {type: sequential, prefix: "CUST-", width: 6}}
        - {name: name, type: string, generator: fake_name}
        - {name: email, type: string, generator: fake_email}
        - {name: segment, type: string, generator: {type: weighted_enum, values: {retail: 0.5, business: 0.3, premium: 0.15, vip: 0.05}}}
        - {name: country, type: string, generator: {type: weighted_enum, values: {AE: 0.4, SA: 0.2, EG: 0.15, UK: 0.1, US: 0.15}}}
        - {name: created_date, type: date, generator: {type: date_range, start: "2020-01-01", end: "2025-12-31"}}

  - name: accounts
    bucket: "bronze/accounts"
    generation_mode: "seed"
    seed_count: 1200
    schema:
      columns:
        - {name: account_id, type: string, generator: {type: sequential, prefix: "ACC-", width: 8}}
        - {name: customer_id, type: string, generator: {type: fk_ref, table: customers, column: customer_id}}
        - {name: account_type, type: string, generator: {type: weighted_enum, values: {savings: 0.4, checking: 0.3, investment: 0.2, loan: 0.1}}}
        - {name: balance, type: float64, generator: {type: lognormal, mean: 9.0, sigma: 2.0, min: 0, max: 5000000}}
        - {name: currency, type: string, generator: {type: weighted_enum, values: {AED: 0.5, SAR: 0.2, EGP: 0.15, USD: 0.15}}}

  - name: transactions
    bucket: "bronze/transactions"
    generation_mode: "continuous"
    schema:
      columns:
        - {name: txn_id, type: string, generator: uuid}
        - {name: account_id, type: string, generator: {type: fk_ref, table: accounts, column: account_id}}
        - {name: amount, type: float64, generator: {type: lognormal, mean: 4.5, sigma: 1.5, min: 0.01, max: 500000}}
        - {name: txn_type, type: string, generator: {type: weighted_enum, values: {purchase: 0.4, transfer: 0.25, withdrawal: 0.2, deposit: 0.15}}}
        - {name: merchant, type: string, generator: {type: weighted_enum, values: {Amazon: 0.15, Carrefour: 0.12, ADNOC: 0.08, Emirates: 0.06, Noon: 0.05, Other: 0.54}}}
        - {name: txn_date, type: timestamp, generator: now_jitter}
    volume:
      default_rows_per_batch: 50
      default_batches_per_minute: 10

playbook:
  - step: 1
    title: "Verify all three tables"
    sql: |
      SELECT 'customers' as tbl, count(*) as rows FROM iceberg.default.customers
      UNION ALL SELECT 'accounts', count(*) FROM iceberg.default.accounts
      UNION ALL SELECT 'transactions', count(*) FROM iceberg.default.transactions

  - step: 2
    title: "Customer 360 view"
    sql: |
      SELECT c.customer_id, c.name, c.segment, c.country,
             COUNT(DISTINCT a.account_id) as accounts,
             COUNT(t.txn_id) as transactions,
             COALESCE(SUM(t.amount), 0) as total_spend
      FROM iceberg.default.customers c
      LEFT JOIN iceberg.default.accounts a ON c.customer_id = a.customer_id
      LEFT JOIN iceberg.default.transactions t ON a.account_id = t.account_id
      GROUP BY c.customer_id, c.name, c.segment, c.country
      ORDER BY total_spend DESC
      LIMIT 20

  - step: 3
    title: "Revenue by country and account type"
    sql: |
      SELECT c.country, a.account_type, 
             SUM(t.amount) as revenue, COUNT(*) as txn_count
      FROM iceberg.default.customers c
      JOIN iceberg.default.accounts a ON c.customer_id = a.customer_id
      JOIN iceberg.default.transactions t ON a.account_id = t.account_id
      GROUP BY c.country, a.account_type
      ORDER BY revenue DESC

  - step: 4
    title: "Schema evolution — add risk score"
    sql: "ALTER TABLE iceberg.default.customers ADD COLUMN risk_score DOUBLE"
    description: "Add a new column without rewriting existing data. Iceberg handles this natively."

  - step: 5
    title: "Verify schema change"
    sql: "DESCRIBE iceberg.default.customers"
    description: "The new risk_score column appears. Existing rows have NULL for this column."
```

### 4B: Data generator — implementation changes

The data-generator needs:

1. **fk_ref generator type**: When generating a row, `fk_ref` samples a random ID from the parent table's ID buffer.

2. **ID buffer**: When generating a "seed" table, buffer all generated primary key values in memory. When `fk_ref` references that table, sample from the buffer.

3. **Generation order**: Tables generate in dependency order. A table referencing another via `fk_ref` must wait until the referenced table is fully generated.

4. **Multi-bucket output**: Each table writes to its own bucket/prefix as specified in `bucket:`.

5. **Backward compatibility**: If a scenario has `schema:` instead of `tables:`, treat it as a single-table scenario (existing behavior).

### 4C: Template — Customer 360 analytics

File: `demo-templates/template-customer-360.yaml`

```yaml
_template:
  name: "Customer 360 analytics"
  tier: advanced
  category: lakehouse
  tags: ["customer-360", "joins", "schema-evolution", "multi-table"]
  description: "Three related tables (customers, accounts, transactions) with cross-table analytics and schema evolution."
  objective: "Demonstrate MinIO + Iceberg as the foundation for consolidated customer analytics"
  ...

nodes:
  - {id: data-gen, component: data-generator, position: {x: -200, y: 200}, display_name: "Data Generator", config: {DG_SCENARIO: "customer-360"}}
  - {id: minio-1, component: minio, position: {x: 100, y: 200}, display_name: "MinIO"}
  - {id: iceberg-rest, component: iceberg-rest, position: {x: 350, y: 50}, display_name: "Iceberg Catalog"}
  - {id: trino-1, component: trino, position: {x: 600, y: 200}, display_name: "Trino"}
  - {id: metabase-1, component: metabase, position: {x: 900, y: 200}, display_name: "Metabase"}
  - {id: prometheus-1, component: prometheus, position: {x: 350, y: 400}, display_name: "Prometheus"}
```

### Phase 4 tests

**Unit tests:**
```python
def test_multi_table_scenario_loads():
    """customer-360 scenario with tables: list should parse correctly."""
    scenario = load_scenario("customer-360")
    assert len(scenario.tables) == 3
    assert scenario.tables[0].name == "customers"
    assert scenario.tables[0].generation_mode == "seed"
    assert scenario.tables[2].name == "transactions"
    assert scenario.tables[2].generation_mode == "continuous"

def test_fk_ref_generator():
    """fk_ref should sample from parent table's ID buffer."""
    parent_ids = ["CUST-000001", "CUST-000002", "CUST-000003"]
    gen = FkRefGenerator(table="customers", column="customer_id", id_buffer=parent_ids)
    for _ in range(100):
        val = gen.generate()
        assert val in parent_ids

def test_dependency_order():
    """Tables should generate in dependency order."""
    scenario = load_scenario("customer-360")
    order = resolve_generation_order(scenario.tables)
    assert order[0].name == "customers"  # No dependencies
    assert order[1].name == "accounts"   # Depends on customers
    assert order[2].name == "transactions"  # Depends on accounts

def test_backward_compatibility_single_table():
    """Scenarios with schema: (no tables:) should still work."""
    scenario = load_scenario("ecommerce-orders")
    assert scenario.tables is None or len(scenario.tables) == 0
    # Should fall back to single-table behavior
```

**Playwright E2E:**
```typescript
test('customer 360 generates three tables', async ({ page }) => {
  // Load Customer 360 template, deploy
  // Start data generator
  // Wait 30 seconds for seed data
  // Open SQL playbook
  // Run step 1 (verify all three tables)
  // Check that customers, accounts, transactions all have rows
  // Run step 2 (Customer 360 view with JOINs)
  // Verify results include customer names with transaction totals
});
```

---

## Phase 5: Medallion Architecture Experience (1 day)

### 5A: Create Medallion Experience template

File: `demo-templates/experience-medallion.yaml`

```yaml
_template:
  name: "Medallion architecture walkthrough"
  tier: experience
  category: lakehouse
  mode: experience
  ...

mode: experience

nodes:
  - {id: data-gen, component: data-generator, position: {x: -200, y: 200}, display_name: "Data Source"}
  - {id: minio-1, component: minio, position: {x: 200, y: 200}, display_name: "MinIO Data Lake"}
  - {id: iceberg-rest, component: iceberg-rest, position: {x: 500, y: 50}, display_name: "Iceberg Catalog"}
  - {id: trino-1, component: trino, position: {x: 800, y: 200}, display_name: "Trino"}
  - {id: metabase-1, component: metabase, position: {x: 1100, y: 200}, display_name: "Metabase"}

annotations:
  - id: ann-bronze
    position: {x: -50, y: 50}
    width: 250
    title: "Bronze layer"
    body: "Raw data lands in MinIO as Parquet files.\nNo transformation — just append."
    style: step
    step_number: 1
    pointer_target: minio-1

  - id: ann-silver
    position: {x: 550, y: 400}
    width: 280
    title: "Silver layer"
    body: "Trino transforms Bronze → Silver via **CREATE TABLE AS SELECT**.\nClean, deduplicate, cast types."
    style: step
    step_number: 2
    pointer_target: trino-1

  - id: ann-gold
    position: {x: 850, y: 400}
    width: 250
    title: "Gold layer"
    body: "Aggregate Silver → Gold for business KPIs.\nDashboard-ready data."
    style: step
    step_number: 3
    pointer_target: metabase-1

  - id: ann-iceberg
    position: {x: 500, y: -80}
    width: 280
    title: "Iceberg: the table format"
    body: "Provides **ACID transactions**, schema evolution, and time travel across all three layers."
    style: callout
    pointer_target: iceberg-rest
```

The playbook for this Experience uses the ecommerce-orders scenario with medallion-specific steps:

```yaml
playbook:
  - step: 1
    title: "Generate Bronze data"
    description: "Start the data generator. Raw data lands in MinIO."
    sql: "SELECT count(*) FROM iceberg.default.ecommerce_orders"

  - step: 2
    title: "Bronze → Silver: clean and deduplicate"
    sql: |
      CREATE TABLE iceberg.default.silver_orders AS
      SELECT DISTINCT order_id,
             CAST(order_ts AS TIMESTAMP) as order_ts,
             TRIM(UPPER(region)) as region,
             total_amount, status, customer_id
      FROM iceberg.default.ecommerce_orders
      WHERE order_id IS NOT NULL AND total_amount > 0

  - step: 3
    title: "Silver → Gold: daily revenue by region"
    sql: |
      CREATE TABLE iceberg.default.gold_daily_revenue AS
      SELECT region,
             date_trunc('day', order_ts) as day,
             SUM(total_amount) as revenue,
             COUNT(*) as order_count,
             AVG(total_amount) as avg_order_value
      FROM iceberg.default.silver_orders
      GROUP BY region, date_trunc('day', order_ts)

  - step: 4
    title: "Query the Gold layer"
    sql: |
      SELECT * FROM iceberg.default.gold_daily_revenue
      ORDER BY day DESC, revenue DESC
      LIMIT 20
```

### Phase 5 tests

```typescript
test('medallion experience allows layout changes but blocks editing', async ({ page }) => {
  // Load Medallion Experience
  
  // CAN drag/reposition nodes (cosmetic change allowed)
  const node = page.locator('.react-flow__node').first();
  const initialBox = await node.boundingBox();
  await node.dragTo(page.locator('.react-flow__pane'), {
    targetPosition: { x: initialBox!.x + 100, y: initialBox!.y + 50 }
  });
  const newBox = await node.boundingBox();
  expect(newBox!.x).not.toBe(initialBox!.x);
  
  // CANNOT delete nodes (structural change blocked)
  await page.click('.react-flow__node');
  await page.keyboard.press('Backspace');
  await expect(page.locator('.react-flow__node')).toHaveCount({ minimum: 5 });
  
  // CANNOT add nodes (palette hidden in Experience mode)
  await expect(page.locator('[data-testid="component-palette"]')).not.toBeVisible();
  
  // CAN see annotations
  await expect(page.locator('[data-testid^="rf-node-ann-"]')).toHaveCount({ minimum: 3 });
  
  // Deploy button still works
  await expect(page.locator('[data-testid="deploy-btn"]')).toBeEnabled();
  
  // Properties panel is READ-ONLY (no edit controls)
  await page.click('.react-flow__node');
  await expect(page.locator('[data-testid="variant-select"]')).not.toBeVisible();
  await expect(page.locator('[data-testid="delete-node-btn"]')).not.toBeVisible();
});

test('medallion experience has step annotations', async ({ page }) => {
  // Load Medallion Experience
  // Verify 3 step annotations visible (numbered 1, 2, 3)
  // Verify callout annotation about Iceberg
  // Verify leader lines to target nodes
});

test('medallion playbook transforms data', async ({ page }) => {
  // Deploy Medallion, start data gen, wait for data
  // Run step 1 (verify bronze)
  // Run step 2 (create silver)
  // Run step 3 (create gold)
  // Run step 4 (query gold)
  // Verify gold results have aggregated data
});
```

---

## Phase 6: Nested JSON + Semi-Structured (3 days)

### 6A: Data generator — struct/array column types

Add `struct` and `array` types to the column type system:

```yaml
- name: device
  type: struct
  generator:
    type: struct
    fields:
      id: {type: pattern, template: "sensor-{seq:04d}", seq_range: [1, 500]}
      location:
        type: struct
        fields:
          lat: {type: gaussian, mean: 25.2, sigma: 0.5}
          lon: {type: gaussian, mean: 55.3, sigma: 0.5}
          zone: {type: enum, values: ["A", "B", "C", "D"]}

- name: readings
  type: array
  generator:
    type: array
    length: {min: 1, max: 5}
    element:
      type: struct
      fields:
        metric: {type: enum, values: ["temperature", "humidity", "pressure"]}
        value: {type: gaussian, mean: 45, sigma: 15}
```

**JSON output:** Naturally nested.
**Parquet output:** Nested Parquet types (`struct<>`, `list<>`).
**Iceberg output:** `ROW(...)` and `ARRAY(...)` types.

### 6B: New scenario: `nested-events`

File: `components/data-generator/datasets/nested-events.yaml`

With playbook steps that demonstrate Trino's nested query capabilities:
- `json_extract_scalar`
- `UNNEST(readings) AS t(r)`
- Nested field access: `device.location.zone`
- Partition evolution DDL

### 6C: Template: "Semi-structured data explorer"

New advanced template with annotation highlighting nested query patterns.

### Phase 6 tests

```python
def test_struct_column_generates_nested_json():
    """struct type should produce nested dict in JSON output."""
    ...

def test_array_column_generates_list():
    """array type should produce list in JSON output."""
    ...

def test_nested_parquet_has_correct_schema():
    """Parquet output should have nested struct/list types."""
    ...
```

---

## Phase 7: CDC + Document OCR (2 weeks, optional based on timeline)

### 7A: CDC generator mode

New format option `DG_FORMAT=cdc-json`:
- Wraps rows in change event envelopes
- Maintains ID buffer for UPDATE/DELETE references
- ~70% INSERT, ~25% UPDATE, ~5% DELETE

### 7B: CDC template + playbook with MERGE INTO

### 7C: OCR pipeline component (Tesseract)

New custom container `components/ocr-pipeline/` with:
- Tesseract OCR + PyPDF2
- FastAPI app with processing endpoints
- Sample document bundle (15 PDFs)
- Iceberg metadata table registration

### 7D: Document Intelligence template

---


---

## Phase 8: STX Simulator (COMPLETED — tracking only)

This phase tracks STX inference simulator work already implemented via separate instruction files. No new work needed.

### Instruction files applied (in order):

| # | File | What it implemented |
|---|------|---------------------|
| 1 | `claude-code-stx-experience-enhancement.md` | Experience mode: drag allowed, edit blocked. GroupNode for GPU Server. AnnotationNode with leader lines. Inference-client component. `parent_group` on DemoNode. Layout auto-save endpoint. Base STX template. |
| 2 | `claude-code-inference-sim-complete.md` | Dual-GPU simulation engine (2 GPUs, private G1/G2/G3, shared G3.5/G4). Three-mode G3.5 selector (disabled/standard/accelerated). Simulation UI rewrite (dual columns, fixed metrics, event stream, eviction policy panel). SchematicNode. Edge protocol/latency labels. Four scenario buttons. |
| 3 | `claude-code-gpu-util-g4-impact.md` | GPUTimeTracker (active/stall/recompute/idle). Stacked GPU utilization bars. G4 stress indicator. Live mode comparison strip. Cross-GPU return path diagram. |
| 4 | `claude-code-guided-demo-and-onboarding.md` | Guided demo mode (tell-show-tell, 12 steps, auto-runs all three modes). SE onboarding overlay (product tour, 8 stops). G4 storage backend insight callout (object vs file/block). |

### Models added during STX work (already in codebase):

- `DemoSchematicNode` — visual-only canvas node (GPU internals)
- `DemoEdge.protocol`, `.latency`, `.bandwidth` — edge label metadata
- `DemoNode.parent_group` — React Flow parent/child grouping
- `SchematicChild` — nested tier display inside SchematicNode

---

## SE Guide Maintainability

### The rule: guide lives in the template YAML

The SE guide is part of the `_template:` metadata block in the template YAML file. No separate doc, no wiki, no Google Doc. When you change the template topology, the guide is right there — update it or the CI check fails.

### CI validation

```python
def test_essentials_guides_complete():
    """Every essentials template must have a complete SE guide."""
    templates = load_all_templates(TEMPLATES_DIR)
    for t in templates:
        meta = t._template
        if meta.get("tier") != "essentials":
            continue
        guide = meta.get("se_guide")
        assert guide, f"\'{meta[\'name\']}\' missing se_guide"
        assert guide.get("pitch")
        assert len(guide.get("talking_points", [])) >= 3
        assert len(guide.get("demo_flow", [])) >= 3
        assert len(guide.get("common_questions", [])) >= 2
        assert len(guide.get("mc_commands", [])) >= 2
```

### When to update the guide

- **Template topology changes** (nodes added/removed) → update `demo_flow` steps
- **New playbook steps added** → update `demo_flow` to reference them
- **Customer feedback** ("they asked X and I had no answer") → add to `common_questions`
- **New MinIO feature** relevant to the demo → add talking point

### Review process

PRs that change a template YAML should include guide updates. The CI check fails if an essentials template loses its guide. Code review should verify that `demo_flow` steps match the actual template topology.


## Global test infrastructure

### Backend test setup

File: `backend/tests/conftest.py`

```python
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.registry.loader import load_registry

@pytest.fixture(scope="session")
def client():
    load_registry("./components")
    return TestClient(app)

@pytest.fixture
def templates_dir():
    return "./demo-templates"
```

### Playwright setup

File: `e2e/playwright.config.ts`

```typescript
import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  timeout: 120000,  // 2 min per test (demos take time to deploy)
  retries: 1,
  use: {
    baseURL: 'http://localhost:3000',
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: 'docker compose up',
    port: 3000,
    reuseExistingServer: true,
  },
});
```

### Running tests

```bash
# Unit tests
cd backend && python -m pytest tests/ -v

# E2E tests (requires DemoForge running)
npx playwright test e2e/phase1.spec.ts
npx playwright test e2e/phase2.spec.ts
# etc.
```

---

## Execution summary

| Phase | Scope | Effort | Status | PoC scenarios |
|-------|-------|--------|--------|---------------|
| 1 | Template cleanup + gallery + SE guides | 2-3 days | Pending | UX + SE enablement |
| 2 | SQL Playbook panel | 3-4 days | Pending | Enables 5 scenarios |
| 3 | Time travel + tiering templates | 0.5 day | Pending | Scenarios 5, 6 |
| 4 | Multi-table data gen + Customer 360 | 4-5 days | Pending | Scenario 1 |
| 5 | Medallion Experience | 1 day | Pending | Scenario 3 |
| 6 | Nested JSON + semi-structured | 3 days | Pending | Scenario 2 |
| 7 | CDC + OCR (if timeline permits) | 2 weeks | Pending | Scenarios 8, 9 |
| 8 | STX Simulator (4 instruction files) | — | Done | Inference demo |

After Phase 5, you cover 6/9 PoC scenarios + the STX inference demo. Scenario 7 (Generative Search) is already covered by the RAG pipeline template.
