"""Regression tests for package splits (instances router, compose_generator package)."""


def test_instances_router_exports_parse_and_pool_routes() -> None:
    from app.api.instances import _parse_mc_decommission_status, router

    status, _ = _parse_mc_decommission_status("The cluster is not decommissioning.", "")
    assert status == "active"

    paths = {getattr(r, "path", "") for r in router.routes}
    assert "/api/demos/{demo_id}/clusters/{cluster_id}/apply-topology" in paths
    assert "/api/demos/{demo_id}/clusters/{cluster_id}/pools/{pool_id}/decommission" in paths
    assert "/api/demos/{demo_id}/clusters/{cluster_id}/pools/{pool_id}/decommission/status" in paths


def test_compose_generator_package_exports_generate_compose() -> None:
    from app.engine import compose_generator as pkg
    from app.engine.compose_generator import generate_compose
    from app.engine.compose_generator.helpers import _mem_bytes

    assert callable(generate_compose)
    assert hasattr(pkg, "generate_compose")
    assert _mem_bytes("256m") > 0


def test_effective_standard_ec_parity_clamps_for_small_clusters() -> None:
    from app.engine.compose_generator.generate import (
        _effective_standard_ec_parity,
        _minio_parity_failure_env_pair,
    )

    # 2 nodes × 2 drives = 4 drives → max STANDARD parity 2 (EC:3 from templates is invalid)
    assert _effective_standard_ec_parity(3, 4) == 2
    assert _effective_standard_ec_parity(2, 4) == 2
    assert _effective_standard_ec_parity(4, 8) == 4
    assert _effective_standard_ec_parity(3, 6) == 3

    assert _minio_parity_failure_env_pair("upgrade") == ("upgrade", "availability")
    assert _minio_parity_failure_env_pair("ignore") == ("ignore", "capacity")
    assert _minio_parity_failure_env_pair("bogus") == ("upgrade", "availability")
