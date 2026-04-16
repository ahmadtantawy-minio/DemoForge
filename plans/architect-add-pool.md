# Architect assessment — MinIO Cluster “Add Pool” at runtime

**Status:** Draft for Sprint 5 review. **Blocks:** Sprint 6 “Add Pool” implementation until approved.

## 1. MinIO pool expansion — API / CLI behavior

- **Erasure coding:** A *server pool* in MinIO is a failure domain (set of drives / nodes). Adding a pool increases aggregate capacity; data is not automatically rebalanced across pools in the same way as expanding drives within a pool.
- **`mc admin service restart`** is often used after topology changes; **pool expansion** that introduces new hosts typically requires the new nodes to be reachable and formatted, then joined to the deployment. Online vs restart-required depends on edition and whether the change is “add empty pool” vs “replace failed node.”
- **Decommission** (`mc admin decommission start|status|cancel`) drains a pool for removal; **Add Pool** is the inverse direction (provision new hosts + new drives, then register as a new pool). DemoForge already exposes decommission endpoints in `backend/app/api/instances.py`.

**Implication for DemoForge:** Runtime “Add Pool” is a **provisioning** problem (new compose services + volumes + join URLs) plus **state** updates, not only an `mc` one-liner on an existing single container.

## 2. Compose / naming / networking (`compose_generator`)

**Current pattern** (see `backend/app/engine/compose_generator.py`):

- For each `DemoCluster`, `cluster.get_pools()` yields pools `p_idx = 1..N`.
- Node IDs: `{cluster.id}-pool{p_idx}-node-{i}`.
- Per-pool expansion URLs and drive paths are built from `pool.node_count`, `pool.drives_per_node`, disk size.

**Add Pool at runtime** implies:

1. **New pool index** `N+1` with default topology (copy from backlog: e.g. same node_count/drives as last pool or wizard defaults).
2. **New services** in the demo’s compose project: MinIO nodes for pool `N+1`, volumes, and network attachment to the same compose networks as existing cluster members.
3. **Cluster command line:** Distributed MinIO must include **all** peer URLs across **all** pools; adding a pool requires updating the server command / environment for **every** MinIO peer in that cluster (not only new containers). Today, compose generation encodes this at **deploy** time.

**Risk:** Docker Compose is file-based. True “add services while running” usually means **regenerate compose** and `docker compose up` for new services, or a dedicated orchestration path. The implementation choice is either:

- **Redeploy path:** Persist new pool in demo YAML → regenerate compose → targeted `up` for new services + rolling restart of existing peers with updated peer list, or  
- **Manual join API:** Use MinIO-supported APIs from mc-shell to add peers (if compatible with how DemoForge starts MinIO).

This doc does not pick the winner; implementation must spike against the MinIO version shipped in templates (CE vs AIStor).

## 3. `demo_state` / canvas — pool count and re-render

- **Source of truth:** `DemoCluster.server_pools` in `backend/app/models/demo.py` (`DemoServerPool` list). Frontend mirrors as `serverPools` on cluster nodes (`ClusterNode`, `clusterMigration`).
- **Canvas:** Pool rows are derived from `serverPools`; adding a pool updates node `data.serverPools` and must bump dimensions (`ClusterNode` + `ResizeObserver` / `updateNodeInternals` already handle height changes).
- **Running state:** Separate from diagram YAML — `state.get_demo` / cockpit payloads should expose **runtime** pool count and health. Add Pool must update **both** saved diagram (intent) and runtime discovery (actual containers).

## 4. Destroy / `_force_remove_containers` / variable pool counts

`_force_remove_containers` (`docker_manager.py`) removes containers by label `demoforge.demo=<demo_id>`. It does **not** enumerate pool indices explicitly.

**Implication:** As long as **every** cluster-related container carries the demo label (including `poolN-node-M`), destroy remains correct for arbitrary pool counts. **Volume cleanup** (`_remove_cluster_volumes`, topology change detection) already compares previous vs current pool lists in `_detect_changed_clusters` / `_save_cluster_configs`.

**Add Pool:** Ensure new services get the same `demoforge.demo` label and naming convention so teardown stays consistent.

## 5. Shared infrastructure with decommission / commission (Sprint 6)

- **Decommission flow** targets an **existing** pool index and uses `mc admin decommission` via pool endpoint args (`_build_pool_args` in `instances.py`).
- **Add Pool** introduces a **new** pool index; until the cluster reconciles, that pool may be `idle` from a lifecycle perspective.
- **Unified model (recommended):** For each pool id, persist:

  `lifecycle: idle | decommissioning | decommissioned | provisioning | active`

  - Decommission/commission transitions use existing mc commands.
  - Add Pool sets `provisioning` → `active` when MinIO reports the pool online (health poll).

Persist this in **backend demo runtime state** (or embedded in cluster section of saved YAML if we want portability). Frontend badges in Cockpit + canvas should read the same structure.

## 6. Open questions for implementation spike

1. Minimum MinIO version for adding a pool without full cluster stop (verify against `quay.io/minio/minio` / AIStor image tags used in manifests).
2. Whether LB/nginx in front of the cluster must be updated when pool count changes (new backend targets).
3. License / capacity flags for AIStor multi-pool if applicable.

---

**Approval**

| Role | Name | Date | Sign-off |
|------|------|------|----------|
| Architect | | | |
| MinIO SME | | | |
