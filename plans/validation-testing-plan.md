# DemoForge Validation & Testing Plan

## Overview

This plan validates all DemoForge functionality using **Playwright MCP** for browser-based E2E tests and **Python scripts** for backend/manifest validation. Tests are organized into tiers:

- **Tier 0: Static validation** — manifests, templates, TypeScript, Python syntax (no Docker needed)
- **Tier 1: Platform smoke** — DemoForge backend + frontend start, API responds, UI loads
- **Tier 2: Component registry** — all 26 components load, connections render correctly
- **Tier 3: Template gallery** — all 28 templates load, create demos from templates
- **Tier 4: Deploy & health** — deploy templates, wait for healthy, verify containers
- **Tier 5: Feature-specific** — RAG pipeline, ML training, data generation, edge automation
- **Tier 6: UI interaction** — properties panel, node subtitles, edge config, connection picker

Prerequisites: DemoForge running at `http://localhost:9210` (backend) / `http://localhost:5173` (frontend dev) or `http://localhost:9210` (prod build).

---

## Tier 0: Static Validation (No Docker)

### T0-01: All manifests parse with required fields

```python
# Run: python3 plans/tests/t0_manifest_validation.py
import yaml, os, sys

COMPONENTS_DIR = "components"
REQUIRED_FIELDS = ["id", "name", "category", "image"]

errors = []
for entry in sorted(os.listdir(COMPONENTS_DIR)):
    path = os.path.join(COMPONENTS_DIR, entry, "manifest.yaml")
    if not os.path.isfile(path):
        continue
    with open(path) as f:
        m = yaml.safe_load(f)
    for field in REQUIRED_FIELDS:
        if not m.get(field):
            errors.append(f"{entry}: missing {field}")
    # Validate connections structure
    conns = m.get("connections", {})
    for p in conns.get("provides", []):
        if "type" not in p or "port" not in p:
            errors.append(f"{entry}: provides missing type/port")
    for a in conns.get("accepts", []):
        if "type" not in a:
            errors.append(f"{entry}: accepts missing type")
    print(f"  OK: {entry} (id={m['id']}, cat={m['category']})")

if errors:
    print(f"\nFAILED: {errors}")
    sys.exit(1)
print(f"\nPASSED: {len(os.listdir(COMPONENTS_DIR))} components validated")
```

### T0-02: All templates parse with correct structure

```python
# Run: python3 plans/tests/t0_template_validation.py
import yaml, os, sys

TEMPLATES_DIR = "demo-templates"
errors = []

for fname in sorted(os.listdir(TEMPLATES_DIR)):
    if not fname.endswith(".yaml"):
        continue
    path = os.path.join(TEMPLATES_DIR, fname)
    with open(path) as f:
        t = yaml.safe_load(f)

    # Check required fields
    for field in ["id", "name", "nodes", "edges", "networks"]:
        if field not in t:
            errors.append(f"{fname}: missing {field}")

    # Check _template metadata
    meta = t.get("_template", {})
    for field in ["name", "category", "description", "objective", "minio_value"]:
        if not meta.get(field):
            errors.append(f"{fname}: _template missing {field}")

    # Validate edges reference existing nodes
    node_ids = {n["id"] for n in t.get("nodes", [])}
    for edge in t.get("edges", []):
        if edge["source"] not in node_ids:
            errors.append(f"{fname}: edge {edge['id']} source '{edge['source']}' not in nodes")
        if edge["target"] not in node_ids:
            errors.append(f"{fname}: edge {edge['id']} target '{edge['target']}' not in nodes")

    # Validate node components exist
    existing_components = set(os.listdir("components"))
    for node in t.get("nodes", []):
        if node["component"] not in existing_components:
            errors.append(f"{fname}: node {node['id']} uses unknown component '{node['component']}'")

    nodes = len(t.get("nodes", []))
    edges = len(t.get("edges", []))
    edge_types = sorted(set(e.get("connection_type", "?") for e in t.get("edges", [])))
    print(f"  OK: {fname} ({nodes} nodes, {edges} edges, types: {edge_types})")

if errors:
    print(f"\nFAILED: {errors}")
    sys.exit(1)
print(f"\nPASSED: all templates validated")
```

### T0-03: All connection types are registered

```python
# Run: python3 plans/tests/t0_connection_types.py
import sys

# Collect all connection types used in templates
import yaml, os
template_types = set()
for fname in os.listdir("demo-templates"):
    if not fname.endswith(".yaml"):
        continue
    with open(os.path.join("demo-templates", fname)) as f:
        t = yaml.safe_load(f)
    for edge in t.get("edges", []):
        template_types.add(edge.get("connection_type", ""))

# Collect all connection types from manifests
manifest_types = set()
for entry in os.listdir("components"):
    path = os.path.join("components", entry, "manifest.yaml")
    if not os.path.isfile(path):
        continue
    with open(path) as f:
        m = yaml.safe_load(f)
    for p in m.get("connections", {}).get("provides", []):
        manifest_types.add(p["type"])
    for a in m.get("connections", {}).get("accepts", []):
        manifest_types.add(a["type"])

all_types = template_types | manifest_types

# Check edge_automation.py has all types registered
with open("backend/app/engine/edge_automation.py") as f:
    ea = f.read()
errors = []
for ct in sorted(all_types):
    if not ct:
        continue
    if f'@_register("{ct}")' in ea:
        print(f"  OK: {ct} registered in edge_automation")
    else:
        errors.append(ct)
        print(f"  FAIL: {ct} NOT registered in edge_automation")

# Check frontend types
with open("frontend/src/types/index.ts") as f:
    types = f.read()
with open("frontend/src/lib/connectionMeta.ts") as f:
    meta = f.read()

for ct in sorted(all_types):
    if not ct:
        continue
    if ct not in types:
        errors.append(f"frontend type: {ct}")
        print(f"  FAIL: {ct} NOT in ConnectionType union")
    if ct not in meta:
        errors.append(f"frontend meta: {ct}")
        print(f"  FAIL: {ct} NOT in connectionMeta")

if errors:
    print(f"\nFAILED: {errors}")
    sys.exit(1)
print(f"\nPASSED: {len(all_types)} connection types verified")
```

### T0-04: TypeScript compiles

```bash
cd frontend && ./node_modules/.bin/tsc --noEmit
# Expected: zero output (no errors)
```

### T0-05: Python syntax validation

```python
import ast, os
errors = []
for root, dirs, files in os.walk("backend"):
    for f in files:
        if f.endswith(".py"):
            path = os.path.join(root, f)
            with open(path) as fh:
                try:
                    ast.parse(fh.read())
                except SyntaxError as e:
                    errors.append(f"{path}: {e}")

for comp in ["rag-app", "ml-trainer"]:
    for root, dirs, files in os.walk(f"components/{comp}"):
        for f in files:
            if f.endswith(".py"):
                path = os.path.join(root, f)
                with open(path) as fh:
                    try:
                        ast.parse(fh.read())
                    except SyntaxError as e:
                        errors.append(f"{path}: {e}")
```

---

## Tier 1: Platform Smoke Tests (Playwright MCP)

### T1-01: Backend API responds

```
Playwright steps:
1. browser_navigate → http://localhost:9210/docs
2. browser_snapshot → verify "DemoForge API" title present
3. browser_navigate → http://localhost:9210/api/health/system
4. browser_snapshot → verify {"status": "ok"} in page content
```

### T1-02: Frontend loads

```
Playwright steps:
1. browser_navigate → http://localhost:5173 (or :9210 for prod)
2. browser_wait_for → selector "[data-testid='toolbar']" OR text "DemoForge"
3. browser_snapshot → verify main UI elements present:
   - Toolbar with Deploy/Stop buttons
   - Canvas area
   - Component palette or welcome screen
4. browser_take_screenshot → "t1-02-frontend-loaded.png"
```

### T1-03: Component registry API

```
Playwright steps:
1. browser_navigate → http://localhost:9210/api/registry/components
2. browser_snapshot → verify JSON contains all 26 component IDs:
   minio, minio-aistore, data-generator, file-generator,
   trino, iceberg-rest, clickhouse, metabase, grafana, prometheus,
   nginx, spark, hdfs, s3-file-browser, resilience-tester,
   ollama, qdrant, rag-app, mlflow, jupyterlab, ml-trainer,
   label-studio, milvus, etcd, airflow, litellm
```

---

## Tier 2: Component Registry UI Tests (Playwright MCP)

### T2-01: Component palette shows all components

```
Playwright steps:
1. browser_navigate → http://localhost:5173
2. browser_snapshot → find component palette/sidebar
3. Verify categories visible: storage, analytics, ai, database, infrastructure, tooling
4. Verify new AI components appear: MLflow, JupyterLab, Label Studio, Milvus, Airflow, LiteLLM, ML Trainer
5. browser_take_screenshot → "t2-01-component-palette.png"
```

### T2-02: Component manifest details load

```
For each new component [mlflow, jupyterlab, ml-trainer, label-studio, milvus, etcd, airflow, litellm]:
1. browser_navigate → http://localhost:9210/api/registry/components/{id}
2. browser_snapshot → verify:
   - "id" field matches
   - "connections.provides" has expected types
   - "connections.accepts" has expected types
   - "web_ui" entries present (where applicable)
   - "health_check" configured
```

---

## Tier 3: Template Gallery Tests (Playwright MCP)

### T3-01: Template gallery loads all templates

```
Playwright steps:
1. browser_navigate → http://localhost:5173
2. Click "Templates" or "New Demo" to open template gallery
3. browser_snapshot → verify template cards visible
4. Count template cards — expect 28
5. Verify new AI templates visible:
   - "RAG Pipeline — Enterprise AI on MinIO"
   - "ML Experiment Lab"
   - "AI Data Labeling Pipeline"
   - "Enterprise Vector Search (Milvus)"
   - "Automated ML Pipeline"
   - "MinIO AI Platform"
6. browser_take_screenshot → "t3-01-template-gallery.png"
```

### T3-02: Template detail view

```
For each new template [rag-pipeline, ml-experiment-lab, data-labeling-pipeline,
                        enterprise-vector-search, automated-ml-pipeline, minio-ai-platform]:
1. browser_navigate → http://localhost:9210/api/templates/{id}
2. browser_snapshot → verify:
   - name, description, category fields
   - walkthrough steps present
   - estimated_resources reasonable
   - nodes and edges arrays populated
```

### T3-03: Create demo from template

```
Playwright steps:
1. Open template gallery
2. Click "RAG Pipeline" template
3. Click "Create Demo" / "Use Template"
4. browser_wait_for → diagram view loads with 4 nodes
5. browser_snapshot → verify:
   - 4 nodes visible: MinIO, Ollama, Qdrant, RAG Pipeline
   - 4 edges connecting them
   - Node labels match template
6. browser_take_screenshot → "t3-03-rag-template-created.png"
```

### T3-04: Create ML Experiment Lab from template

```
Playwright steps:
1. Open template gallery
2. Click "ML Experiment Lab"
3. Click "Create Demo"
4. browser_wait_for → diagram with 5 nodes
5. browser_snapshot → verify:
   - Nodes: MinIO, Data Generator, MLflow, JupyterLab, ML Trainer
   - Edges: 6 connections with correct types (s3, mlflow-tracking)
6. browser_take_screenshot → "t3-04-ml-lab-created.png"
```

---

## Tier 4: Deploy & Health Tests (Playwright MCP + API)

> **Note**: These tests require Docker and take 30-120s per template. Run selectively.

### T4-01: Deploy RAG Pipeline template

```
Playwright steps:
1. Create demo from RAG Pipeline template (T3-03)
2. Click "Deploy" button
3. browser_wait_for → deploy progress modal/indicator
4. Wait for all nodes to show green health dots (timeout: 120s for Ollama model download)
5. browser_snapshot → verify:
   - MinIO: green (healthy)
   - Qdrant: green (healthy)
   - Ollama: green (healthy) — may take 60-120s on first run
   - RAG Pipeline: green (healthy)
6. browser_take_screenshot → "t4-01-rag-deployed.png"

API verification:
7. GET /api/demos/{id}/instances → all 4 instances health: "healthy"
8. Verify MinIO has buckets: documents, rag-audit-log
9. Verify Qdrant dashboard accessible via proxy
```

### T4-02: Deploy ML Experiment Lab

```
Playwright steps:
1. Create demo from ML Experiment Lab template
2. Click Deploy
3. Wait for 5 nodes healthy (timeout: 90s)
4. browser_snapshot → verify all green
5. browser_take_screenshot → "t4-02-ml-lab-deployed.png"

API verification:
6. GET /api/demos/{id}/instances → 5 instances healthy
7. MLflow dashboard accessible: GET /proxy/{demo}/mlflow-1/dashboard/ → 200
8. JupyterLab accessible: GET /proxy/{demo}/jupyter-1/lab/ → 200
9. ML Trainer accessible: GET /proxy/{demo}/trainer-1/dashboard/ → 200
```

### T4-03: Deploy single-minio (smoke test)

```
Simplest possible deploy — verifies core deploy pipeline works:
1. Create from single-minio template
2. Deploy
3. Wait for 1 node healthy
4. Verify MinIO Console accessible via proxy
5. Stop demo
6. Verify cleanup (no containers remain)
```

### T4-04: Deploy and stop cycle

```
For template "bi-dashboard-lakehouse":
1. Create → Deploy → wait healthy
2. GET /api/demos/{id}/instances → all healthy
3. Stop demo
4. GET /api/demos/{id}/instances → 404 or empty
5. Verify no orphaned containers: docker ps --filter label=demoforge.demo={id} → empty
```

---

## Tier 5: Feature-Specific Tests (Playwright MCP + API)

### T5-01: RAG Pipeline — ingest and query

```
Prerequisite: T4-01 (RAG Pipeline deployed and healthy)

Playwright steps:
1. Click RAG Pipeline node on canvas
2. In properties panel, verify RagAppPanel visible:
   - MinIO connection dot (green)
   - Qdrant connection dot (green)
   - Ollama connection dot (green or yellow/pulsing)
3. Click "Load sample docs" button
4. Wait 30s for ingestion
5. Verify properties panel shows "5 docs / ~100+ chunks"
6. browser_take_screenshot → "t5-01-rag-ingested.png"

7. Double-click RAG Pipeline node → opens Chat UI in proxy
8. In Chat UI:
   - Type "How many drive failures can MinIO tolerate with EC:4?"
   - Click Send
   - Wait for response (timeout: 60s for Ollama inference)
   - Verify answer contains "4" and references erasure-coding doc
9. browser_take_screenshot → "t5-01-rag-answer.png"

API verification:
10. GET /proxy/{demo}/rag-1/chat/status → documents_ingested: 5, chunks_stored > 100
11. POST /proxy/{demo}/rag-1/chat/ask → answer mentions "4 failures"
12. MinIO Console → rag-audit-log bucket → JSON audit files exist
```

### T5-02: RAG Pipeline — node subtitles

```
Prerequisite: T5-01 (data ingested)

Playwright steps:
1. On diagram canvas, verify RAG Pipeline node shows subtitle "5 docs / ~1XX chunks"
2. Verify Ollama node shows "Models ready" subtitle
3. browser_take_screenshot → "t5-02-node-subtitles.png"
```

### T5-03: ML Trainer — prepare data and train

```
Prerequisite: T4-02 (ML Experiment Lab deployed)

Playwright steps:
1. Right-click Data Generator → Start Generating (ecommerce-orders, parquet)
2. Wait 30s for data to accumulate in MinIO
3. Click ML Trainer node → properties panel
4. Open ML Trainer Web UI via double-click or proxy link
5. In Trainer dashboard:
   - Click "Prepare Data" → wait for success
   - Click "Quick Train (3 runs)" → wait for results table
   - Verify 3 rows in results: RandomForest, GradientBoosting, LinearRegression
   - Each row shows RMSE, MAE, R2 values (non-zero, reasonable)
6. browser_take_screenshot → "t5-03-ml-trainer-results.png"

7. Open MLflow UI via proxy:
   - Verify experiment "demoforge-experiment" exists
   - Verify 3 runs visible
   - Click best run → Artifacts tab → model file present
8. browser_take_screenshot → "t5-03-mlflow-runs.png"

API verification:
9. GET /proxy/{demo}/trainer-1/dashboard/status → status: "idle", last_result has runs
10. GET /proxy/{demo}/mlflow-1/dashboard/api/2.0/mlflow/experiments/search → experiments exist
```

### T5-04: ML Trainer — hyperparameter sweep

```
Prerequisite: T5-03 (data prepared)

Playwright steps:
1. Open Trainer dashboard
2. Click "Hyperparameter Sweep"
3. Wait for completion (may take 60s)
4. Verify sweep results show 12 runs with varying configs
5. Open MLflow → model registry → "best-ecommerce-model" registered
6. browser_take_screenshot → "t5-04-sweep-results.png"
```

### T5-05: JupyterLab — notebooks accessible

```
Prerequisite: T4-02 (ML Experiment Lab deployed)

Playwright steps:
1. Double-click JupyterLab node → opens JupyterLab in proxy
2. browser_wait_for → JupyterLab file browser loaded
3. Verify 5 notebooks visible:
   - 01-minio-basics.ipynb
   - 02-data-exploration.ipynb
   - 03-ml-training.ipynb
   - 04-feature-engineering.ipynb
   - 05-aistor-tables.ipynb
4. Click 01-minio-basics.ipynb → opens notebook
5. browser_take_screenshot → "t5-05-jupyterlab.png"
```

### T5-06: Data Generator — start/stop and properties panel

```
Prerequisite: any deployed demo with data-generator node

Playwright steps:
1. Click Data Generator node
2. Verify DataGeneratorPanel in properties:
   - Scenario selector (E-commerce Orders, IoT, Financial)
   - Format selector (Parquet, JSON, CSV, Iceberg)
   - Rate buttons (Low, Medium, High)
3. Right-click Data Generator → "Start Generating"
4. Wait 10s
5. Verify node shows "Generating..." badge (green, pulsing)
6. Verify properties panel shows live stats (rows generated, rate)
7. Right-click → "Stop Generating"
8. Verify node shows "Idle" badge
9. browser_take_screenshot → "t5-06-data-generator.png"
```

### T5-07: Edge properties and config schema

```
Playwright steps:
1. Create demo from ML Experiment Lab template
2. Click on the "mlflow-tracking" edge (jupyter → mlflow)
3. Verify edge properties panel shows:
   - Type: "MLflow Tracking" with correct color dot
   - Direction: JupyterLab → MLflow
   - Label field (editable)
   - Auto-configure checkbox
4. Click on the "s3" edge (data-gen → minio)
5. Verify config schema form shows:
   - Bucket field with value
   - Format field with options
6. browser_take_screenshot → "t5-07-edge-properties.png"
```

### T5-08: Ollama properties panel

```
Prerequisite: RAG Pipeline deployed, Ollama healthy

Playwright steps:
1. Click Ollama node
2. Verify OllamaPanel in properties:
   - "Ollama Models" section visible
   - nomic-embed-text listed with green dot
   - llama3.2:3b listed with green dot
3. browser_take_screenshot → "t5-08-ollama-panel.png"
```

### T5-09: Connection type picker

```
Playwright steps:
1. Create blank demo
2. Drag MinIO node onto canvas
3. Drag Qdrant node onto canvas
4. Draw edge from MinIO → Qdrant
5. Verify connection type picker appears (since MinIO provides s3 and Qdrant accepts s3)
6. Select "S3"
7. Verify edge created with S3 type
8. browser_take_screenshot → "t5-09-connection-picker.png"
```

---

## Tier 6: Advanced UI Tests (Playwright MCP)

### T6-01: Template walkthrough panel

```
Playwright steps:
1. Create from RAG Pipeline template → Deploy
2. Open walkthrough panel (if available via toolbar)
3. Verify 7 walkthrough steps display
4. browser_take_screenshot → "t6-01-walkthrough.png"
```

### T6-02: Control plane view

```
Playwright steps:
1. Deploy any template (e.g., bi-dashboard-lakehouse)
2. Switch to "Instances" / Control Plane view
3. Verify instance cards show:
   - Container name
   - Health status badge
   - Web UI links (clickable)
   - Terminal button
   - Credentials section
4. browser_take_screenshot → "t6-02-control-plane.png"
```

### T6-03: Web UI proxy access

```
Prerequisite: bi-dashboard-lakehouse deployed

Playwright steps:
For each component with web_ui:
1. Click Web UI link in control plane
2. browser_wait_for → page loads without error
3. Verify proxy rewrites work (no broken assets, no CORS errors)
4. Components to test:
   - MinIO Console (port 9001)
   - Grafana (port 3000)
   - Trino UI (port 8080)
   - Metabase (port 3000)
5. browser_take_screenshot for each
```

### T6-04: Terminal access

```
Playwright steps:
1. Deploy any demo
2. Open terminal for MinIO node
3. Verify terminal connects (PTY session)
4. Type quick action "mc ls" → verify output
5. browser_take_screenshot → "t6-04-terminal.png"
```

### T6-05: Deploy progress tracking

```
Playwright steps:
1. Create from a multi-node template (e.g., ml-experiment-lab)
2. Click Deploy
3. Observe deploy progress:
   - "Generating docker-compose..." step
   - "Starting containers..." step
   - "Running init scripts..." step
   - "Complete" step
4. Verify progress updates in real-time
5. browser_take_screenshot at each stage
```

---

## Tier 7: Stress & Edge Cases

### T7-01: Deploy and stop rapidly

```
1. Create from single-minio template
2. Deploy → immediately Stop (before healthy)
3. Verify clean shutdown (no orphaned containers)
4. Deploy again → wait for healthy → verify works
```

### T7-02: Multiple demos simultaneously

```
1. Create and deploy RAG Pipeline
2. Create and deploy ML Experiment Lab (while RAG still running)
3. Verify both demos run on isolated networks
4. Verify both accessible via separate proxy paths
5. Stop RAG → verify ML Lab unaffected
6. Stop ML Lab
```

### T7-03: Backend restart recovery

```
1. Deploy a demo
2. Restart the DemoForge backend (docker restart demoforge-backend)
3. Wait for backend to recover
4. GET /api/demos → verify demo recovered with status "running"
5. Verify instances accessible
```

---

## Test Execution Matrix

### Quick validation (5 min, no Docker)

| Test | Command | Expected |
|------|---------|----------|
| T0-01 | `python3 plans/tests/t0_manifest_validation.py` | 26 components OK |
| T0-02 | `python3 plans/tests/t0_template_validation.py` | 28 templates OK |
| T0-03 | `python3 plans/tests/t0_connection_types.py` | All types registered |
| T0-04 | `cd frontend && ./node_modules/.bin/tsc --noEmit` | Zero errors |
| T0-05 | `python3 plans/tests/t0_python_syntax.py` | Zero syntax errors |

### Smoke test (10 min, requires Docker)

| Test | Template | What it validates |
|------|----------|-------------------|
| T1-01 | — | Backend API responds |
| T1-02 | — | Frontend loads |
| T4-03 | single-minio | Basic deploy/stop cycle |

### Full regression (45-60 min, requires Docker + 16GB RAM)

| Test | Template | Key features validated |
|------|----------|----------------------|
| T4-01 | rag-pipeline | Ollama, Qdrant, RAG app, chat UI |
| T4-02 | ml-experiment-lab | MLflow, JupyterLab, ML Trainer |
| T5-01 | rag-pipeline | Document ingestion, Q&A, audit |
| T5-03 | ml-experiment-lab | Real sklearn training, MLflow logging |
| T5-05 | ml-experiment-lab | Notebook accessibility |
| T5-06 | any | Data generator start/stop |
| T5-07 | ml-experiment-lab | Edge properties, config schema |

### AI ecosystem full test (2+ hours, requires 32GB RAM)

| Test | Template | Validates |
|------|----------|-----------|
| All above | — | — |
| T4-02 + T5-03 + T5-04 | ml-experiment-lab | Full ML training lifecycle |
| Deploy | data-labeling-pipeline | Label Studio loads, S3 source config |
| Deploy | enterprise-vector-search | Milvus + etcd + MinIO storage |
| Deploy | automated-ml-pipeline | Airflow DAG + ML Trainer integration |
| Deploy | minio-ai-platform | 10-node combined platform (requires 12GB+) |

---

## Playwright MCP Command Reference

All Playwright tests use these MCP tools:

```
mcp__playwright__browser_navigate(url)           # Go to URL
mcp__playwright__browser_snapshot()               # Get page accessibility tree
mcp__playwright__browser_take_screenshot(name)    # Save screenshot
mcp__playwright__browser_click(element, ref)      # Click element
mcp__playwright__browser_fill_form(...)           # Fill form fields
mcp__playwright__browser_wait_for(selector/text)  # Wait for element
mcp__playwright__browser_press_key(key)           # Press keyboard key
mcp__playwright__browser_console_messages()       # Check for JS errors
mcp__playwright__browser_network_requests()       # Check for failed requests
```

### Screenshot naming convention

```
.artifacts/screenshots/t{tier}-{test_number}-{description}.png
```

### Error capture pattern

After every major step:
1. `browser_console_messages()` → check for JS errors
2. `browser_network_requests()` → check for failed HTTP requests (4xx/5xx)
3. On failure: `browser_take_screenshot("error-{test}-{step}.png")`

---

## Automated Test Runner

To run all Playwright tests programmatically, create a test orchestrator that:

1. Reads this plan
2. For each test section, issues the Playwright MCP commands in sequence
3. Captures screenshots at each step
4. Logs PASS/FAIL for each assertion
5. Generates a summary report

Example invocation:
```
# Run Tier 0 (static) — always first
python3 plans/tests/run_tier0.py

# Run Tier 1-3 (requires running DemoForge)
# Use Playwright MCP via Claude Code

# Run Tier 4-6 (requires Docker)
# Use Playwright MCP via Claude Code with deploy/stop management
```

---

## Success Criteria

| Tier | Pass condition |
|------|---------------|
| Tier 0 | All 26 manifests parse, all 28 templates validate, TypeScript compiles, all connection types registered |
| Tier 1 | Backend API responds, frontend loads, registry returns 26 components |
| Tier 2 | All components visible in palette, manifest details load |
| Tier 3 | All 28 templates load in gallery, demo creation works for all 6 new templates |
| Tier 4 | RAG Pipeline + ML Experiment Lab deploy with all nodes healthy |
| Tier 5 | RAG Q&A works, ML training logs to MLflow, data generator streams, edge config editable |
| Tier 6 | Walkthrough, control plane, proxy, terminal all functional |
| Tier 7 | No orphaned containers, multi-demo isolation, restart recovery |
