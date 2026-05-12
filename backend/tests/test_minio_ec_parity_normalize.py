"""Tests for MinIO EC parity normalization on loaded / saved demos."""

from app.engine.minio_ec_parity_normalize import (
    clamp_ec_parity_for_stripe,
    compute_erasure_set_size,
    effective_stripe_drives,
    normalize_demo_cluster,
    normalize_demo_definition,
)
from app.models.demo import DemoCluster, DemoDefinition, DemoServerPool, NodePosition


def test_compute_erasure_set_size_matches_small_totals() -> None:
    assert compute_erasure_set_size(4) == 4
    assert compute_erasure_set_size(8) == 8
    assert compute_erasure_set_size(16) == 16


def test_effective_stripe_drives_respects_override() -> None:
    assert effective_stripe_drives(16, 8) == 8
    assert effective_stripe_drives(16, None) == 16
    assert effective_stripe_drives(16, 99) == 16


def test_normalize_clears_invalid_erasure_stripe_pref() -> None:
    c = DemoCluster(
        id="c1",
        position=NodePosition(x=0, y=0),
        ec_parity=2,
        server_pools=[
            DemoServerPool(
                id="pool-1",
                node_count=2,
                drives_per_node=2,
                ec_parity=2,
                erasure_stripe_drives=8,
            ),
        ],
    )
    out = normalize_demo_cluster(c)
    assert out.server_pools[0].erasure_stripe_drives is None
    assert out.server_pools[0].ec_parity == 2


def test_normalize_keeps_valid_eight_drive_stripe_on_sixteen_disks() -> None:
    c = DemoCluster(
        id="c1",
        position=NodePosition(x=0, y=0),
        ec_parity=3,
        server_pools=[
            DemoServerPool(
                id="pool-1",
                node_count=4,
                drives_per_node=4,
                ec_parity=3,
                erasure_stripe_drives=8,
            ),
        ],
    )
    out = normalize_demo_cluster(c)
    assert out.server_pools[0].erasure_stripe_drives == 8
    assert out.server_pools[0].ec_parity == 3


def test_clamp_ec_parity_for_four_drive_stripe() -> None:
    assert clamp_ec_parity_for_stripe(4, 3) == 2
    assert clamp_ec_parity_for_stripe(4, 2) == 2


def test_normalize_demo_cluster_legacy_flat_fields() -> None:
    c = DemoCluster(
        id="hot",
        position=NodePosition(x=0, y=0),
        node_count=2,
        drives_per_node=2,
        ec_parity=3,
        server_pools=[],
    )
    out = normalize_demo_cluster(c)
    assert out.ec_parity == 2
    assert out.server_pools == []


def test_normalize_demo_cluster_multi_pool_syncs_top_level_ec() -> None:
    c = DemoCluster(
        id="c1",
        position=NodePosition(x=0, y=0),
        ec_parity=4,
        server_pools=[
            DemoServerPool(id="pool-1", node_count=2, drives_per_node=2, ec_parity=3),
            DemoServerPool(id="pool-2", node_count=4, drives_per_node=2, ec_parity=3),
        ],
    )
    out = normalize_demo_cluster(c)
    assert out.server_pools[0].ec_parity == 2
    assert out.server_pools[1].ec_parity == 3
    assert out.ec_parity == out.server_pools[0].ec_parity


def test_normalize_demo_definition_iterates_clusters() -> None:
    d = DemoDefinition(
        id="x",
        name="t",
        clusters=[
            DemoCluster(
                id="c1",
                position=NodePosition(x=0, y=0),
                ec_parity=3,
                server_pools=[DemoServerPool(id="pool-1", node_count=2, drives_per_node=2, ec_parity=3)],
            )
        ],
    )
    out = normalize_demo_definition(d)
    assert out.clusters[0].ec_parity == 2
