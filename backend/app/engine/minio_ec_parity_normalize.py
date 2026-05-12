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
