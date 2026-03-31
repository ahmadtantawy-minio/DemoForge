# Claude Code — Fix Smart Tiering Template

## Context

The `template-smart-tiering.yaml` template has architectural problems. Currently it has 4 individual "minio single" nodes with incomplete tiering connections. This instruction replaces that with a proper 2-cluster topology that matches real production deployments.

## Pre-work

Read these files before making changes:

```
demo-templates/template-smart-tiering.yaml   # The template to fix
components/minio/manifest.yaml                # Check available cluster variants
components/nginx/manifest.yaml                # Load balancer config
demo-templates/site-replication.yaml          # Reference for how clusters are structured in other templates
demo-templates/bi-dashboard-lakehouse.yaml    # Reference for cluster node syntax
```

Also check: how are clusters defined in the template YAML? Look at the `clusters:` array in existing templates that use multi-node MinIO. Note the fields: `id`, `component`, `node_count`, `variant`, `position`, `display_name`, `config`, etc.

---

## What's wrong today

1. **Four independent "minio single" nodes** — not clusters. No erasure coding, no replication. This doesn't represent a real tiering deployment.
2. **Hot NVMe Node 2 has no tiering edge to any cold node** — half the data never gets tiered.
3. **Cold HDD Node 2 is completely orphaned** — no inbound data connections, only metrics out.
4. **No load balancer in front of the cold tier** — if tiering targets individual nodes, there's no redundancy on the cold side.
5. **The annotations mention ILM but the topology can't actually support it** — ILM tiering targets a remote tier endpoint (a cluster URL), not individual nodes.

## Target architecture

```
Data Generator
    ↓ (File Push, S3)
Hot Tier LB (nginx)
    ↓ (Load Balance)        ↓ (Load Balance)
┌─────────────────────────────────────┐
│  Hot NVMe Cluster (2 nodes)         │
│  Erasure coded, fast writes         │
│  ILM policy: transition after N days│
└──────────────┬──────────────────────┘
               │ (Tiering — S3 remote tier)
               ↓
┌─────────────────────────────────────┐
│  Cold HDD Cluster (2 nodes)         │
│  Erasure coded, cheap storage       │
│  Receives aged objects from hot tier│
└─────────────────────────────────────┘

Both clusters → Prometheus → Grafana
```

**Key change:** MinIO ILM remote tiering targets a cluster endpoint, not individual nodes. The hot cluster's ILM policy points to the cold cluster's S3 API. The cold cluster doesn't need its own LB for tiering (MinIO nodes communicate directly), but the cluster itself handles distribution internally.

---

## Task 1: Rewrite `demo-templates/template-smart-tiering.yaml`

Replace the current topology with the architecture above. Preserve the existing `_template` metadata block (name, tier, category, tags, description, objective, minio_value, estimated_resources, walkthrough, se_guide if present) — only change the topology (nodes, edges, clusters, annotations, sticky_notes, groups).

### 1A. Replace individual nodes with clusters

Remove the four "minio single" nodes:
- `hot-nvme-1` (Hot NVMe Node 1)
- `hot-nvme-2` (Hot NVMe Node 2)
- `cold-hdd-1` (Cold HDD Node 1)
- `cold-hdd-2` (Cold HDD Node 2)

Replace with two clusters. Use whatever cluster syntax the existing templates use (check `site-replication.yaml` or other multi-node templates). The cluster definition should look something like:

```yaml
clusters:
  - id: hot-cluster
    component: minio
    variant: cluster         # or whatever variant supports multi-node
    node_count: 2
    position:
      x: 550
      y: 280
    display_name: "Hot NVMe Cluster"
    config:
      MINIO_STORAGE_CLASS_STANDARD: "EC:1"    # 2-node cluster = EC:1 max
    # Add any cluster-specific fields your schema requires

  - id: cold-cluster
    component: minio
    variant: cluster
    node_count: 2
    position:
      x: 950
      y: 280
    display_name: "Cold HDD Cluster"
    config:
      MINIO_STORAGE_CLASS_STANDARD: "EC:1"
```

**Important:** Check how existing cluster templates define `node_count`, positions, and config. Match their pattern exactly. If clusters use a `nodes` array instead of `node_count`, adapt accordingly.

### 1B. Keep these existing nodes

- `data-gen` (Data Generator) — keep as-is
- `hot-lb` (Hot Tier LB, nginx) — keep as-is
- `prometheus` — keep as-is
- `grafana` — keep as-is

### 1C. Rewrite all edges

Remove all existing edges and replace with:

```yaml
edges:
  # Data Generator → Hot Tier LB
  - id: e-datagen-hotlb
    source: data-gen
    target: hot-lb
    connection_type: s3
    auto_configure: true
    label: "File push"
    connection_config:
      bucket: data-landing
      format: parquet

  # Hot Tier LB → Hot Cluster (load balance)
  - id: e-hotlb-hotcluster
    source: hot-lb
    target: hot-cluster
    connection_type: load-balance
    auto_configure: true
    label: "Load balance"
    connection_config:
      algorithm: round-robin
      backend_port: "9000"

  # Hot Cluster → Cold Cluster (ILM tiering)
  - id: e-hot-cold-tiering
    source: hot-cluster
    target: cold-cluster
    connection_type: tiering
    auto_configure: true
    label: "ILM tiering"
    connection_config:
      tiering_type: remote
      transition_days: 30
      storage_class: COLD
      # The hot cluster's ILM policy targets the cold cluster's S3 endpoint

  # Hot Cluster → Prometheus (metrics)
  - id: e-hot-prometheus
    source: hot-cluster
    target: prometheus
    connection_type: metrics
    auto_configure: true

  # Cold Cluster → Prometheus (metrics)
  - id: e-cold-prometheus
    source: cold-cluster
    target: prometheus
    connection_type: metrics
    auto_configure: true

  # Prometheus → Grafana
  - id: e-prom-grafana
    source: prometheus
    target: grafana
    connection_type: metrics-query
    auto_configure: true
```

**Check the edge naming and connection_type conventions** in existing templates. If `tiering` is not a recognized connection_type, check what the current template uses and adapt. The edge between the two tiers is the most important one — it must exist and have proper config.

### 1D. Update annotations

Replace the existing sticky notes / annotations with updated ones that match the new topology:

**Annotation 1 — Hot tier:**
```
Hot tier
Hot tier — 2-node NVMe cluster with erasure coding.
All new objects land here. Fast random I/O for active workloads.
```

**Annotation 2 — Cold tier:**
```
Cold tier
Cold tier — 2-node HDD cluster with erasure coding.
ILM automatically transitions objects here after the configured period.
Cost-effective for infrequently accessed data.
```

**Annotation 3 — ILM tiering (on the left side):**
```
ILM tiering
MinIO ILM (Information Lifecycle Management) moves data between
clusters based on age. The hot cluster's tiering policy targets
the cold cluster's S3 endpoint as a remote tier. Applications
continue using the same hot-tier endpoint — tiering is transparent.
```

**Annotation 4 — Transparent to applications:**
```
Transparent to applications
Applications always write to the Hot Tier LB endpoint.
They don't know or care that aged data moves to the cold cluster.
Reads are served transparently — MinIO fetches from the correct tier.
```

Position the annotations sensibly — hot tier annotation near the hot cluster, cold tier near the cold cluster, ILM annotation between the two, transparency note near the data generator / LB.

### 1E. Update `_template` metadata

Update these fields in the `_template` block to reflect the new topology:

```yaml
_template:
  # Keep existing name, tier, category, tags
  description: "Two MinIO clusters — hot (NVMe, 2-node) and cold (HDD, 2-node) — connected by ILM remote tiering. Data lands on the fast hot cluster and automatically transitions to the cost-effective cold cluster based on age policies."
  objective: "Demonstrate MinIO's ILM tiering between clusters — hot NVMe for active data, cold HDD for aged data, transparent to applications"
  minio_value: "MinIO's ILM tiering lets you mix storage tiers without changing your applications. Hot data gets NVMe performance, cold data gets HDD economics, and the transition is automatic and transparent."
  estimated_resources:
    memory: "4GB"        # 2-node hot + 2-node cold + LB + prometheus + grafana + data-gen
    cpu: 4
    containers: 8        # 4 MinIO (2+2) + nginx + prometheus + grafana + data-gen
  walkthrough:
    - step: "Deploy the demo"
      description: "Click Deploy. Two MinIO clusters start — hot tier (NVMe) and cold tier (HDD), each with 2 erasure-coded nodes, plus load balancer, data generator, and monitoring."
    - step: "Generate data on hot tier"
      description: "Start the data generator. Objects land on the hot NVMe cluster through the load balancer. Open the hot cluster's MinIO Console to see data arriving."
    - step: "Configure ILM tiering"
      description: "Open the hot cluster's MinIO Console. Go to Tiering → Add Tier. Configure the cold cluster as a remote S3 tier with its endpoint and credentials."
    - step: "Set an ILM transition rule"
      description: "Create a lifecycle rule on the data bucket: transition objects older than 1 day (for demo speed) to the COLD tier."
    - step: "Watch data migrate"
      description: "Wait for the transition period. Objects move from the hot cluster to the cold cluster. The cold cluster's MinIO Console shows objects appearing."
    - step: "Verify transparency"
      description: "Read objects through the hot-tier LB endpoint — they're served transparently even though the data now lives on the cold cluster. The application doesn't know."
    - step: "Monitor tiering metrics"
      description: "Open Grafana dashboards. See tiering throughput, object counts per tier, and storage utilization on both clusters."
```

If an `se_guide` (now `fa_guide`) block exists, update its talking points and demo flow to match the new 2-cluster topology.

### 1F. Update groups (if applicable)

If the template uses groups to visually cluster related nodes, create two groups:

```yaml
groups:
  - id: group-hot-tier
    label: "Hot tier (NVMe)"
    # Include: hot-cluster nodes, hot-lb
    # Check how groups reference child nodes in existing templates

  - id: group-cold-tier
    label: "Cold tier (HDD)"
    # Include: cold-cluster nodes
```

Check existing templates for group syntax. If groups reference node IDs, you'll need to know the generated IDs for cluster member nodes (e.g., `hot-cluster-node-0`, `hot-cluster-node-1`).

---

## Task 2: Verify edge/connection types

Before saving, verify that the connection types used in the new edges are registered in the system:

```bash
# Check what connection types exist
grep -rn "connection_type\|ConnectionType" backend/app/ --include="*.py" | head -20
grep -rn "tiering\|load-balance\|metrics" backend/app/engine/compose_generator.py | head -10
```

If `tiering` is not a recognized connection type in the edge resolution logic:
- Check what the old template used (it had a tiering edge between Node 1 and Cold Node 1)
- Use the same connection_type string
- If the compose generator has special handling for tiering edges (e.g., setting remote tier env vars), verify it will work with cluster-to-cluster edges (not just node-to-node)

---

## Task 3: Verify cluster support

```bash
# Check how clusters are defined in existing templates
grep -A 20 "clusters:" demo-templates/site-replication.yaml | head -30
grep -A 20 "clusters:" demo-templates/multi-site-replication.yaml | head -30

# Check the DemoCluster model
grep -A 30 "class DemoCluster" backend/app/models/demo.py

# Check how the compose generator handles clusters
grep -n "cluster" backend/app/engine/compose_generator.py | head -20
```

If clusters use a different syntax than what I've shown (e.g., they define member nodes explicitly, or use a `DemoCluster` model with different fields), adapt the YAML accordingly. The key requirement: 2 MinIO nodes per cluster, erasure coding enabled, each cluster reachable at a single S3 endpoint.

---

## Task 4: Position layout

Arrange nodes for clear left-to-right flow:

```
x:100  x:300    x:550           x:950
 DG → Hot LB → Hot Cluster ──→ Cold Cluster
                   ↓                ↓
              x:700, y:550    x:900, y:550
              Prometheus   →   Grafana
```

Approximate positions (adjust to fit without overlap):

| Node/Cluster | x | y |
|---|---|---|
| Data Generator | 100 | 280 |
| Hot Tier LB | 300 | 320 |
| Hot NVMe Cluster | 550 | 280 |
| Cold HDD Cluster | 950 | 280 |
| Prometheus | 700 | 550 |
| Grafana | 900 | 550 |
| Hot tier annotation | 500 | 80 |
| Cold tier annotation | 900 | 80 |
| ILM annotation | 40 | 100 |
| Transparency annotation | 40 | 380 |

---

## Task 5: Validate

After saving the template:

```bash
# 1. Template loads without errors
curl -s http://localhost:9210/api/templates/template-smart-tiering | python3 -m json.tool | head -20

# 2. Template has correct component count
curl -s http://localhost:9210/api/templates | python3 -c "
import sys, json
templates = json.load(sys.stdin)['templates']
t = next(t for t in templates if t['id'] == 'template-smart-tiering')
print(f\"Containers: {t['container_count']}, Components: {t['component_count']}\")
# Expected: Containers: 8, Components: 6 (data-gen, nginx, 2 clusters, prometheus, grafana)
"

# 3. Create a demo from the template
curl -s -X POST http://localhost:9210/api/demos/from-template/template-smart-tiering | python3 -m json.tool

# 4. Verify the demo has the right topology
DEMO_ID=$(curl -s http://localhost:9210/api/demos | python3 -c "import sys,json; demos=json.load(sys.stdin)['demos']; print(demos[-1]['id'])")
curl -s "http://localhost:9210/api/demos/${DEMO_ID}" | python3 -c "
import sys, json
demo = json.load(sys.stdin)
print(f\"Nodes: {len(demo.get('nodes',[]))}\")
print(f\"Clusters: {len(demo.get('clusters',[]))}\")
print(f\"Edges: {len(demo.get('edges',[]))}\")
# Expected: Nodes: 4 (data-gen, nginx, prometheus, grafana), Clusters: 2, Edges: 6
"

# 5. Open in browser — verify the diagram renders with two distinct clusters
# and the tiering edge between them
```

### Playwright E2E

```
1. Navigate to /templates
2. Find "Smart data tiering" template
3. Click to open detail
4. Verify description mentions "2-node" clusters
5. Verify container count is 8
6. Create demo from template
7. Verify diagram shows two cluster groups (hot and cold)
8. Verify tiering edge exists between hot cluster and cold cluster
9. Verify all 6 edges are present (data-gen→LB, LB→hot, hot→cold, hot→prom, cold→prom, prom→grafana)
10. Verify no orphaned nodes (every node has at least one connection)
```

---

## What NOT to do

- Do NOT keep individual "minio single" nodes — replace them with clusters
- Do NOT add a load balancer for the cold tier — the tiering connection goes directly from hot cluster to cold cluster's internal endpoint
- Do NOT change the template ID (`template-smart-tiering`) — other code may reference it
- Do NOT remove the `_template` metadata block — only update the fields listed above
- Do NOT remove Prometheus and Grafana — monitoring is part of the demo story
