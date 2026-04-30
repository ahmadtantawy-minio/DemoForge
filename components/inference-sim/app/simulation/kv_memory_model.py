"""Canonical KV cache math for Llama-class models (demo — aligned with Memory Budget panel).

Weights: FP8 70B split across TP=2 → 35 GB per GPU. KV cache: BF16 by default (2 bytes/element).
"""

from __future__ import annotations

import math

MODEL_NAME = "Llama 3.1 70B FP8"
MODEL_LAYERS = 80
MODEL_KV_HEADS = 8
MODEL_HEAD_DIM = 128
KV_PRECISION_BYTES = 2  # BF16 KV cache
TENSOR_PARALLEL = 2

GPU_TYPE = "H100 SXM"
GPU_TYPE_LABEL = GPU_TYPE  # alias for API/UI
# TP degree for KV shard math is TENSOR_PARALLEL — cluster GPU/node counts live in settings.
GPU_HBM_GB = 80.0

# FP8 model weights per GPU (TP shard)
G1_WEIGHTS_GB_PER_GPU = 35.0
G1_OVERHEAD_GB_PER_GPU = 4.0
G1_HBM_TOTAL_GB = GPU_HBM_GB
G1_KV_CAPACITY_GB = G1_HBM_TOTAL_GB - G1_WEIGHTS_GB_PER_GPU - G1_OVERHEAD_GB_PER_GPU  # 41.0

KV_PRECISION_NOTE = "BF16 KV cache (2 bytes/element)"


def kv_bytes_per_token_full() -> int:
    """Full-model KV bytes per token (K+V across all layers, all KV heads)."""
    return 2 * MODEL_LAYERS * MODEL_KV_HEADS * MODEL_HEAD_DIM * KV_PRECISION_BYTES


def kv_bytes_per_token_per_gpu_tp2() -> int:
    """Per-GPU KV bytes per token under tensor parallelism."""
    return kv_bytes_per_token_full() // TENSOR_PARALLEL


def kv_per_session_gb(context_tokens: int) -> float:
    """KV cache size (GB) for one session at context length `context_tokens` (per GPU shard)."""
    if context_tokens <= 0:
        return 0.0
    b = kv_bytes_per_token_per_gpu_tp2()
    return (float(context_tokens) * float(b)) / (1024.0**3)


def sessions_fit_in_kv_cap(kv_cap_gb: float, context_tokens: int) -> int:
    """Max full sessions fitting in a KV budget at `context_tokens`."""
    need = kv_per_session_gb(context_tokens)
    if need <= 0:
        return 0
    return int(math.floor(float(kv_cap_gb) / need))


def total_kv_demand_gb(users: int, context_tokens: int) -> float:
    """Naive upper bound: users × KV per session (FA narrative)."""
    return float(max(0, users)) * kv_per_session_gb(context_tokens)


def g1_layout_per_gpu() -> dict[str, float]:
    return {
        "g1_total_gb": G1_HBM_TOTAL_GB,
        "g1_weights_gb": G1_WEIGHTS_GB_PER_GPU,
        "g1_overhead_gb": G1_OVERHEAD_GB_PER_GPU,
        "g1_kv_capacity_gb": G1_KV_CAPACITY_GB,
    }


def g1_layout() -> dict[str, float]:
    """Per-GPU G1 memory breakdown (GB): HBM total, weights, overhead, KV allocatable slice."""
    return {
        "hbm_total_gb": G1_HBM_TOTAL_GB,
        "weights_gb": G1_WEIGHTS_GB_PER_GPU,
        "overhead_gb": G1_OVERHEAD_GB_PER_GPU,
        "kv_capacity_gb": G1_KV_CAPACITY_GB,
    }


def g1_layout_per_node(gpus_per_node: float) -> dict[str, float]:
    """Per-node G1 layout (GB): per-GPU constants × GPUs aggregated on one logical node."""
    n = float(max(1.0, gpus_per_node))
    weights_gb = G1_WEIGHTS_GB_PER_GPU * n
    overhead_gb = G1_OVERHEAD_GB_PER_GPU * n
    hbm_total_gb = G1_HBM_TOTAL_GB * n
    kv_capacity_gb = hbm_total_gb - weights_gb - overhead_gb
    return {
        "g1_total_gb": hbm_total_gb,
        "g1_weights_gb": weights_gb,
        "g1_overhead_gb": overhead_gb,
        "g1_kv_capacity_gb": kv_capacity_gb,
        "hbm_total_gb": hbm_total_gb,
        "weights_gb": weights_gb,
        "overhead_gb": overhead_gb,
        "kv_capacity_gb": kv_capacity_gb,
    }
