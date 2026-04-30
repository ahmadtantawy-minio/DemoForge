"""Tests for KV memory math (Llama-class demo constants)."""

from app.simulation import kv_memory_model as kvm


def test_kv_bytes_per_token_matches_spec():
    assert kvm.kv_bytes_per_token_full() == 327680
    assert kvm.kv_bytes_per_token_per_gpu_tp2() == 163840


def test_kv_per_session_gb_reference_points():
    # 32K context → ~5 GB per GPU KV at BF16
    assert abs(kvm.kv_per_session_gb(32768) - 5.0) < 0.06
    # 64K → ~10 GB
    assert abs(kvm.kv_per_session_gb(65536) - 10.0) < 0.06


def test_sessions_fit_g1_41gb():
    assert kvm.sessions_fit_in_kv_cap(41.0, 4096) == 65  # ~0.625 GB/sess
    assert kvm.sessions_fit_in_kv_cap(41.0, 32768) == 8
    # 64K → ~10 GB/sess; 41 GB fits 4 full sessions (not the old 7 GB HBM table).
    assert kvm.sessions_fit_in_kv_cap(41.0, 65536) == 4


def test_g1_kv_capacity():
    assert kvm.G1_KV_CAPACITY_GB == 41.0


def test_g1_layout_per_node_scales():
    lay = kvm.g1_layout_per_node(8)
    assert abs(lay["weights_gb"] - 280.0) < 1e-6
    assert abs(lay["overhead_gb"] - 32.0) < 1e-6
    assert abs(lay["kv_capacity_gb"] - 328.0) < 1e-6
    assert abs(lay["hbm_total_gb"] - 640.0) < 1e-6
