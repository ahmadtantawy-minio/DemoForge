# DemoForge — Template Connection Points, Prometheus Links & Failing Template Fixes

## Before starting

1. Read `plans/backlog.md`
2. Do NOT modify any backend engine or frontend canvas code — this spec is template YAML fixes only
3. Run `python tests/validate-templates-fast.py` and save the baseline output before touching anything
4. All 21 currently passing templates must still pass after your changes

---

## Step 0 — Discover handle naming convention (READ FIRST, code nothing yet)

Before touching any YAML, inspect the codebase to understand exactly what handle IDs are in use.

### 0a. Check the node component(s)

Look at `frontend/src/components/canvas/` — find the component(s) that render nodes (likely `DemoNode.tsx`, `ClusterNode.tsx`, or similar). Find every `<Handle>` element from `@xyflow/react`. Record:
- The `id` prop on each Handle
- The `position` prop (Top / Bottom / Left / Right)

Common patterns to look for:
```tsx
<Handle id="top"    position={Position.Top}    type="target" />
<Handle id="bottom" position={Position.Bottom} type="source" />
<Handle id="left"   position={Position.Left}   type="target" />
<Handle id="right"  position={Position.Right}  type="source" />
```

### 0b. Check existing template edges

Open 3–4 existing passing templates (e.g. `multi-site-replication.yaml`, `bi-dashboard-lakehouse.yaml`, `realtime-analytics.yaml`). In the `edges:` section, record the actual values of `sourceHandle` and `targetHandle` fields on existing edges.

### 0c. Build a reference map

Write down:
```
HANDLE_MAP = {
  "north": "<id used for top handle>",
  "south": "<id used for bottom handle>",
  "east":  "<id used for right handle>",
  "west":  "<id used for left handle>",
}
```

Use this map for all YAML edits in the steps below. Do not guess — derive it from the source.

---

## Step 1 — Write the analysis + fix script

### File: `scripts/fix_template_connections.py` (new)

This script does three things:
1. Analyses every template YAML and reports current connection point usage
2. Computes the correct handle for each edge based on relative node positions
3. Applies fixes (with `--dry-run` flag to preview without writing)

```
Usage:
  python scripts/fix_template_connections.py --dry-run     # preview all changes
  python scripts/fix_template_connections.py               # apply all changes
  python scripts/fix_template_connections.py --template dremio-lakehouse  # single template
```

### Logic for correct handle selection

For each edge in a template:

```python
def compute_handles(source_node, target_node, HANDLE_MAP):
    """
    Determine correct sourceHandle and targetHandle based on
    relative position of source and target nodes.
    """
    sx = source_node["position"]["x"]
    sy = source_node["position"]["y"]
    tx = target_node["position"]["x"]
    ty = target_node["position"]["y"]

    dx = tx - sx   # positive = target is to the right
    dy = ty - sy   # positive = target is below

    # Use the dominant axis — whichever delta is larger in absolute terms
    if abs(dx) >= abs(dy):
        # East/West connection — horizontal dominant
        if dx >= 0:
            # target is to the right of source
            source_handle = HANDLE_MAP["east"]
            target_handle = HANDLE_MAP["west"]
        else:
            # target is to the left of source
            source_handle = HANDLE_MAP["west"]
            target_handle = HANDLE_MAP["east"]
    else:
        # North/South connection — vertical dominant
        if dy >= 0:
            # target is below source
            source_handle = HANDLE_MAP["south"]
            target_handle = HANDLE_MAP["north"]
        else:
            # target is above source
            source_handle = HANDLE_MAP["north"]
            target_handle = HANDLE_MAP["south"]

    return source_handle, target_handle
```

### What to fix per edge

For each edge in each template:
- Compute correct handles using `compute_handles()`
- If current `sourceHandle` or `targetHandle` differs from computed → flag as needing fix
- On apply: update `sourceHandle` and `targetHandle` in the YAML
- Preserve ALL other edge fields exactly (connection_type, config, label, animated, etc.)

### Node position lookup

Nodes in templates have `position: {x: N, y: N}` at the top level.
For nodes inside clusters/groups, use the node's own `position` field — do not add cluster offsets (React Flow handles that at render time).

### Script output format

```
fix_template_connections.py — dry run
══════════════════════════════════════════════════════════

multi-site-replication.yaml
  edge: minio-1 → nginx-1
    sourceHandle: bottom → right    ← FIX
    targetHandle: top    → left     ← FIX
  edge: nginx-1 → prometheus-1
    sourceHandle: right  (correct)
    targetHandle: left   (correct)
  1 edge(s) to fix

realtime-analytics.yaml
  No changes needed

...

══════════════════════════════════════════════════════════
Templates to update: 14
Total edges to fix:  38
Run without --dry-run to apply.
```

---

## Step 2 — Fix orphaned Prometheus nodes

Add a second pass in the same script (or a separate `--fix-prometheus` flag):

### Prometheus fix logic

For each template that contains a node with `component: prometheus`:
1. Check if that prometheus node has at least one edge connecting it to a MinIO node (`component: minio` or `component: minio-aistor`)
2. If no such edge exists → add one
3. The new edge should be a `metrics` connection type
4. Use `compute_handles()` to set correct handles based on node positions
5. Generate edge ID following the existing pattern: `reactflow__edge-{sourceId}{sourceHandle}-{targetId}{targetHandle}`

### Edge template for new prometheus→minio metrics edge

```yaml
- id: reactflow__edge-{minio_id}{source_handle}-{prometheus_id}{target_handle}
  source: {minio_id}
  target: {prometheus_id}
  sourceHandle: {computed}
  targetHandle: {computed}
  type: connectionEdge
  data:
    connection_type: metrics
    config: {}
    label: "metrics"
    animated: false
    paused: false
```

Adjust field names/structure to exactly match existing edges in the template — inspect a working metrics edge (e.g. in `realtime-analytics.yaml` or `complete-analytics.yaml`) and use that as the canonical template.

### Script output for prometheus pass

```
Prometheus orphan check
  bi-dashboard-aistor-tables.yaml  — prometheus linked ✓
  complete-analytics.yaml          — prometheus linked ✓
  realtime-analytics.yaml          — prometheus linked ✓
  full-analytics-pipeline.yaml     — prometheus NOT linked → adding metrics edge (minio-1 → prometheus-1)
  ...
```

---

## Step 3 — Failing template fixes

Apply these fixes to the 5 failing templates. These are separate from the connection-point fixes above — apply them independently.

### 3a. Dremio Lakehouse, Streaming Lakehouse, Customer 360 — 409 race condition

These three fail because the validation script fires a second deploy before the previous one's containers have fully cleared.

**In `backend/app/engine/docker_manager.py`** (or wherever the deploy endpoint handler lives):

Add a drain guard at the very start of the deploy flow:

```python
async def wait_for_clean_state(demo_id: str, timeout: int = 30) -> bool:
    """
    Poll Docker until no containers labelled demoforge.demo_id={demo_id} remain.
    Returns True if clean, False if timed out.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        containers = docker_client.containers.list(
            all=True,
            filters={"label": f"demoforge.demo_id={demo_id}"}
        )
        if not containers:
            return True
        await asyncio.sleep(2)
    return False
```

Call at the top of the deploy handler:
```python
if not await wait_for_clean_state(demo_id, timeout=30):
    raise HTTPException(
        status_code=409,
        detail="Previous deploy still cleaning up — retry in a few seconds"
    )
```

Do NOT change stop logic, health monitor, or any other engine module.

**In `tests/validate-templates-fast.py`**:

Add retry-on-409 around deploy calls:
```python
async def deploy_with_retry(client, demo_id, max_retries=5, backoff=8):
    for attempt in range(max_retries):
        resp = await client.post(f"/api/demos/{demo_id}/deploy")
        if resp.status_code == 200:
            return resp
        if resp.status_code == 409:
            wait = backoff * (attempt + 1)
            print(f"    409 — still cleaning, retry {attempt+1}/{max_retries} in {wait}s")
            await asyncio.sleep(wait)
            continue
        resp.raise_for_status()
    raise RuntimeError(f"Deploy failed after {max_retries} retries for {demo_id}")
```

Add drain wait after stop:
```python
async def stop_and_drain(client, demo_id, drain_timeout=25):
    await client.post(f"/api/demos/{demo_id}/stop")
    deadline = time.time() + drain_timeout
    while time.time() < deadline:
        r = await client.get(f"/api/demos/{demo_id}/instances")
        if not r.json().get("containers"):
            return
        await asyncio.sleep(3)
```

Replace all bare stop calls in the test loop with `await stop_and_drain(client, demo_id)`.

### 3b. Enterprise Vector Search (Milvus) — etcd coordination timeout

**In `components/milvus/manifest.yaml`**:

Find the `init_scripts` or `health_check` section. Add or update the health check so it first waits for etcd to be ready before allowing Milvus to start its own initialization.

The etcd readiness endpoint is `http://etcd:2379/health` (returns `{"health":"true"}` when ready).

Add an init script step that runs before the Milvus readiness check:
```yaml
init_scripts:
  - name: wait-for-etcd
    order: 0
    command: |
      until curl -sf http://etcd:2379/health | grep -q '"health":"true"'; do
        echo "waiting for etcd..."; sleep 3;
      done
      echo "etcd ready"
```

Adjust the YAML structure to match the existing init_scripts format in this manifest exactly.

Also set in `demo-templates/enterprise-vector-search.yaml`:
```yaml
deploy_timeout_seconds: 600
```

Add `deploy_timeout_seconds` support to the template model and deploy logic:

**In `backend/app/models/demo.py`** (or wherever template-level metadata is defined):
```python
deploy_timeout_seconds: Optional[int] = None  # None = use global default
```

**In the deploy engine**: where the health-check polling timeout is currently hardcoded or uses a global constant, replace with:
```python
timeout = demo.deploy_timeout_seconds or settings.DEFAULT_DEPLOY_TIMEOUT
```

### 3c. MinIO AI Platform — 10-container stack timeout

Set in `demo-templates/minio-ai-platform.yaml`:
```yaml
deploy_timeout_seconds: 900
```

This template has 10 containers including Ollama (which loads a model on first start). 900s gives it enough headroom on a typical SE laptop.

---

## Step 4 — Run the script and apply

```bash
# Preview all connection-point changes
python scripts/fix_template_connections.py --dry-run

# Preview prometheus fixes
python scripts/fix_template_connections.py --dry-run --fix-prometheus

# Apply everything
python scripts/fix_template_connections.py --fix-prometheus

# Confirm no YAML is broken
python -c "
import yaml, glob
for f in glob.glob('demo-templates/*.yaml'):
    try:
        yaml.safe_load(open(f))
    except Exception as e:
        print(f'BROKEN: {f} — {e}')
print('All YAMLs parse OK')
"
```

---

## Step 5 — Validation

### Run targeted tests first (5 failing templates)
```bash
python tests/validate-templates-fast.py \
  --templates dremio-lakehouse streaming-lakehouse template-customer-360 \
              enterprise-vector-search minio-ai-platform
```
Expected: all 5 move from FAIL to PASS.

### Run full suite
```bash
python tests/validate-templates-fast.py
```
Expected:
- 26/26 templates pass (or at minimum all 21 previously passing still pass)
- No new failures introduced

### Visual spot-check (Playwright screenshot pass)
```bash
python tests/screenshot-templates.py
```

Open the generated HTML report. For 5–6 templates spanning different categories, verify:
- Horizontal node arrangements have edges entering/leaving from left and right handles
- Vertical node arrangements have edges entering/leaving from top and bottom handles
- No edges crossing through unrelated nodes
- Prometheus nodes have a visible metrics edge connecting to MinIO

---

## Done criteria

- [ ] `scripts/fix_template_connections.py` exists and runs with `--dry-run` and without
- [ ] All template YAML files still parse without error
- [ ] Connection handles are geometrically correct (dominant axis determines handle side)
- [ ] All Prometheus nodes in all templates have at least one metrics edge to a MinIO node
- [ ] `deploy_timeout_seconds` field supported in template model + deploy engine
- [ ] `enterprise-vector-search.yaml` has `deploy_timeout_seconds: 600`
- [ ] `minio-ai-platform.yaml` has `deploy_timeout_seconds: 900`
- [ ] Drain guard added to deploy endpoint (409 on timeout)
- [ ] Validation script uses `stop_and_drain()` and `deploy_with_retry()`
- [ ] Full validation suite: all 5 previously failing templates now pass
- [ ] All 21 previously passing templates still pass
- [ ] `plans/backlog.md` updated
