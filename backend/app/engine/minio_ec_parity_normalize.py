"""
Normalize MinIO STANDARD EC parity on demo clusters for backward compatibility.

Older YAML / React Flow payloads may store ec_parity that exceeds MinIO's rule
parity ≤ stripe_size/2 for the effective erasure stripe. Compose already clamps
MINIO_STORAGE_CLASS_STANDARD at render time; this module aligns persisted
``DemoCluster`` / ``DemoServerPool`` models so APIs (e.g. cluster health) and
the UI see consistent values — matching frontend ``computeErasureSetSize`` +
``clampParityToValidStripe`` and optional per-pool ``erasure_stripe_drives``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models.demo import DemoCluster, DemoDefinition, DemoServerPool

logger = logging.getLogger(__name__)

MAX_AUTO_STRIPE = 16


def compute_erasure_set_size(total_drives: int) -> int:
    """Largest d in 16..2 dividing total_drives; else total_drives (matches frontend)."""
    for d in range(16, 1, -1):
        if total_drives % d == 0:
            return d
    return total_drives


def valid_stripe_sizes_for_total(total_drives: int) -> list[int]:
    """Divisors of ``total_drives`` in ``4..min(16, total)`` with at least one valid STANDARD parity."""
    cap = min(MAX_AUTO_STRIPE, total_drives)
    out: list[int] = []
    for d in range(cap, 3, -1):
        if total_drives % d != 0:
            continue
        if valid_minio_standard_parities(d):
            out.append(d)
    return sorted(out, reverse=True)


def effective_stripe_drives(total_drives: int, preferred: int | None) -> int:
    """Stripe drive count for EC rules: ``preferred`` when valid, else ``compute_erasure_set_size``."""
    if preferred is not None and preferred > 0 and total_drives % preferred == 0:
        if valid_minio_standard_parities(preferred):
            return preferred
    return compute_erasure_set_size(total_drives)


def canonical_erasure_stripe_drives_pref(total_drives: int, preferred: int | None) -> int | None:
    """Persisted override only when it divides the pool and supports STANDARD EC; else ``None``."""
    if preferred is None or preferred <= 0 or total_drives % preferred != 0:
        return None
    if not valid_minio_standard_parities(preferred):
        return None
    return preferred


def valid_minio_standard_parities(stripe_size: int) -> list[int]:
    max_parity = stripe_size // 2
    return list(range(2, max_parity + 1))


def minio_default_standard_parity(stripe_size: int) -> int:
    opts = valid_minio_standard_parities(stripe_size)
    if not opts:
        return 1
    prefer = 2 if stripe_size <= 5 else 3 if stripe_size <= 7 else 4
    if prefer in opts:
        return prefer
    return opts[-1]


def compute_write_quorum(stripe_size: int, ec_parity: int) -> int:
    """MinIO write quorum for one erasure set (matches frontend ``computePoolErasureStats``)."""
    data_shards = max(0, stripe_size - ec_parity)
    if data_shards == ec_parity:
        return data_shards + 1
    return max(1, data_shards)


def compute_pool_erasure_stats(
    node_count: int,
    drives_per_node: int,
    ec_parity: int,
    erasure_stripe_drives: int | None = None,
) -> dict[str, int]:
    """Stripe geometry for one server pool (mirrors frontend ``computePoolErasureStats``)."""
    total_drives = node_count * drives_per_node
    set_size = effective_stripe_drives(total_drives, erasure_stripe_drives)
    num_sets = total_drives // set_size if set_size else 0
    data_shards = max(0, set_size - ec_parity)
    return {
        "set_size": set_size,
        "num_sets": num_sets,
        "data_shards": data_shards,
        "parity_shards": ec_parity,
        "write_quorum": compute_write_quorum(set_size, ec_parity),
        "total_drives": total_drives,
    }


def _cluster_ec_status_clusterwide(drives_online: int, drives_total: int, ec_parity: int) -> str:
    """Fallback when stripe layout cannot be inferred from the drive matrix."""
    if drives_total == 0:
        return "unknown"
    if drives_online >= drives_total:
        return "healthy"
    write_quorum = max(1, drives_total - ec_parity)
    if drives_online >= write_quorum:
        return "degraded"
    return "quorum_lost"


def cluster_ec_status_from_online_matrix(
    online: list[list[bool]],
    ec_parity: int,
    erasure_stripe_drives: int | None = None,
) -> str:
    """Per-stripe quorum using MinIO-style round-robin placement across nodes."""
    if not online:
        return "unknown"
    drives_per_node = len(online[0])
    if drives_per_node == 0 or any(len(row) != drives_per_node for row in online):
        flat = [d for row in online for d in row]
        return _cluster_ec_status_clusterwide(sum(flat), len(flat), ec_parity)

    num_nodes = len(online)
    total_drives = num_nodes * drives_per_node
    stats = compute_pool_erasure_stats(num_nodes, drives_per_node, ec_parity, erasure_stripe_drives)
    set_size = stats["set_size"]
    num_sets = stats["num_sets"]
    write_quorum = stats["write_quorum"]

    if num_sets < 1 or set_size * num_sets != total_drives:
        return _cluster_ec_status_clusterwide(sum(cell for row in online for cell in row), total_drives, ec_parity)

    if set_size % num_nodes != 0:
        return _cluster_ec_status_clusterwide(sum(cell for row in online for cell in row), total_drives, ec_parity)

    drives_per_node_per_set = set_size // num_nodes
    overall = "healthy"
    for set_idx in range(num_sets):
        online_in_set = 0
        for slot in range(set_size):
            node_idx = slot % num_nodes
            drive_slot = (slot // num_nodes) + drives_per_node_per_set * set_idx
            if online[node_idx][drive_slot]:
                online_in_set += 1
        if online_in_set < write_quorum:
            return "quorum_lost"
        if online_in_set < set_size:
            overall = "degraded"
    return overall


def worst_cluster_ec_status(statuses: list[str]) -> str:
    order = {"healthy": 0, "degraded": 1, "quorum_lost": 2, "unknown": 3}
    return max(statuses, key=lambda s: order.get(s, 3)) if statuses else "unknown"


def clamp_ec_parity_for_stripe(stripe_size: int, parity: int) -> int:
    opts = valid_minio_standard_parities(stripe_size)
    if not opts:
        return max(1, min(parity, max(1, stripe_size // 2)))
    if parity in opts:
        return parity
    return min(opts, key=lambda p: abs(p - parity))


def _normalize_server_pool_ec(pool: "DemoServerPool") -> "DemoServerPool":
    td = pool.node_count * pool.drives_per_node
    canonical = canonical_erasure_stripe_drives_pref(td, pool.erasure_stripe_drives)
    stripe = effective_stripe_drives(td, pool.erasure_stripe_drives)
    fixed = clamp_ec_parity_for_stripe(stripe, pool.ec_parity)
    updates: dict[str, object] = {}
    if fixed != pool.ec_parity:
        logger.debug(
            "Pool %s: ec_parity %s invalid for stripe %s drives → %s",
            pool.id,
            pool.ec_parity,
            stripe,
            fixed,
        )
        updates["ec_parity"] = fixed
    if canonical != pool.erasure_stripe_drives:
        updates["erasure_stripe_drives"] = canonical
    if updates:
        return pool.model_copy(update=updates)
    return pool


def normalize_demo_cluster(cluster: "DemoCluster") -> "DemoCluster":
    """Return a cluster with MinIO-valid ec_parity on each pool; sync top-level ec_parity to pool 1."""
    if cluster.server_pools:
        new_pools = [_normalize_server_pool_ec(p) for p in cluster.server_pools]
        p0 = new_pools[0]
        if new_pools == list(cluster.server_pools) and cluster.ec_parity == p0.ec_parity:
            return cluster
        return cluster.model_copy(update={"server_pools": new_pools, "ec_parity": p0.ec_parity})

    td = cluster.node_count * cluster.drives_per_node
    stripe = effective_stripe_drives(td, None)
    fixed = clamp_ec_parity_for_stripe(stripe, cluster.ec_parity)
    if fixed != cluster.ec_parity:
        logger.debug(
            "Cluster %s (legacy flat): ec_parity %s → %s for stripe %s",
            cluster.id,
            cluster.ec_parity,
            fixed,
            stripe,
        )
        return cluster.model_copy(update={"ec_parity": fixed})
    return cluster


def normalize_demo_definition(demo: "DemoDefinition") -> "DemoDefinition":
    """Apply EC normalization to every cluster (no-op if already valid)."""
    if not demo.clusters:
        return demo
    new_clusters = [normalize_demo_cluster(c) for c in demo.clusters]
    if new_clusters == demo.clusters:
        return demo
    return demo.model_copy(update={"clusters": new_clusters})
