from prometheus_client import Counter, Gauge, generate_latest as _generate_latest

# Gauges
gpu_utilization = Gauge(
    "inference_gpu_utilization_ratio",
    "Average fraction of G1 (GPU HBM) capacity in use across GPUs",
)
gpu_a_utilization = Gauge(
    "inference_gpu_a_utilization_ratio",
    "Fraction of GPU-A G1 capacity in use",
)
gpu_b_utilization = Gauge(
    "inference_gpu_b_utilization_ratio",
    "Fraction of GPU-B G1 capacity in use",
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
    "Total cross-GPU migrations",
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

    # GPU utilization is now a dict {active, io_stall, recompute, idle}
    gpu_a = metrics.get("gpu_a_utilization", {})
    gpu_b = metrics.get("gpu_b_utilization", {})
    eff_a = (gpu_a.get("active", 0) if isinstance(gpu_a, dict) else gpu_a) or 0
    eff_b = (gpu_b.get("active", 0) if isinstance(gpu_b, dict) else gpu_b) or 0
    gpu_a_utilization.set(eff_a / 100.0)
    gpu_b_utilization.set(eff_b / 100.0)
    gpu_utilization.set((eff_a + eff_b) / 200.0)
    ttft_ms.set(metrics.get("avg_ttft_ms", 0))
    cache_hit_rate.set(metrics.get("cache_hit_rate", 0) / 100.0)
    s3_ops_per_sec.set(metrics.get("s3_ops_per_sec", 0))
    cross_gpu_migrations_gauge.set(metrics.get("cross_gpu_migrations", 0))

    # Count total blocks across all GPUs and shared tiers
    total_blocks = 0
    for gpu_state in sim_state.get("gpus", []):
        for tier_key in ("g1", "g2", "g3"):
            tier = gpu_state.get(tier_key, {})
            total_blocks += tier.get("block_count", 0)
    shared = sim_state.get("shared", {})
    for tier_key in ("g35", "g4"):
        tier = shared.get(tier_key, {})
        total_blocks += tier.get("block_count", 0)
    kv_blocks_active.set(total_blocks)


def generate_latest() -> bytes:
    """Return prometheus text format."""
    return _generate_latest()
