from prometheus_client import Counter, Gauge, generate_latest as _generate_latest

# Gauges
gpu_utilization = Gauge(
    "inference_gpu_utilization_ratio",
    "Average effective inference fraction across DGX nodes (G1 aggregate narrative)",
)
gpu_a_utilization = Gauge(
    "inference_gpu_a_utilization_ratio",
    "Effective inference fraction for first DGX node (G1 aggregate; metric name legacy)",
)
gpu_b_utilization = Gauge(
    "inference_gpu_b_utilization_ratio",
    "Effective inference fraction for second DGX node (G1 aggregate; metric name legacy)",
)
ttft_ms = Gauge(
    "inference_ttft_ms",
    "Simulated time-to-first-token in milliseconds",
)
cache_hit_rate = Gauge(
    "inference_cache_hit_rate_ratio",
    "Cache hit rate percentage",
)
kv_blocks_active = Gauge(
    "inference_kv_blocks_active_total",
    "Total KV blocks currently tracked across all tiers",
)
s3_ops_per_sec = Gauge(
    "inference_s3_ops_per_second",
    "Estimated S3 operations per second",
)
cross_gpu_migrations_gauge = Gauge(
    "inference_cross_gpu_migrations_total",
    "Total cross-node KV handoffs (legacy metric name; counts cross-node migrations)",
)

# Counters
recomputations_total = Counter(
    "inference_recomputations_total",
    "Total KV cache recomputations (block not found, latency=50 ticks)",
)
s3_operations_total = Counter(
    "inference_s3_operations_total",
    "Total S3 put/get/delete operations",
)


def update_metrics(sim_state: dict) -> None:
    """Update all gauges from a sim_state dict produced by SimulationEngine.get_state()."""
    metrics = sim_state.get("metrics", {})

    # Per-node utilization is a dict {active, io_stall, recompute, idle} (legacy keys gpu_a/b)
    gpu_a = metrics.get("node_a_utilization") or metrics.get("gpu_a_utilization", {})
    gpu_b = metrics.get("node_b_utilization") or metrics.get("gpu_b_utilization", {})
    eff_a = (gpu_a.get("active", 0) if isinstance(gpu_a, dict) else gpu_a) or 0
    eff_b = (gpu_b.get("active", 0) if isinstance(gpu_b, dict) else gpu_b) or 0
    gpu_a_utilization.set(eff_a / 100.0)
    gpu_b_utilization.set(eff_b / 100.0)
    gpu_utilization.set((eff_a + eff_b) / 200.0)
    ttft_ms.set(metrics.get("avg_ttft_ms", 0))
    cache_hit_rate.set(metrics.get("cache_hit_rate", 0) / 100.0)
    s3_ops_per_sec.set(metrics.get("s3_ops_per_sec", 0))
    cross_gpu_migrations_gauge.set(
        metrics.get("cross_node_migrations", metrics.get("cross_gpu_migrations", 0))
    )

    # Count total blocks across all nodes and shared tiers
    total_blocks = 0
    node_list = sim_state.get("nodes") or sim_state.get("gpus") or []
    for node_state in node_list:
        for tier_key in ("g1", "g2", "g3"):
            tier = node_state.get(tier_key, {})
            total_blocks += tier.get("block_count", 0)
    shared = sim_state.get("shared", {})
    for tier_key in ("g35", "g4"):
        tier = shared.get(tier_key, {})
        total_blocks += tier.get("block_count", 0)
    kv_blocks_active.set(total_blocks)


def generate_latest() -> bytes:
    """Return prometheus text format."""
    return _generate_latest()
