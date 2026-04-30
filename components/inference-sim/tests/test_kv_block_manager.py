"""KVBlockManager node topology (per-node G1/G2/G3, shared G3.5/G4)."""

import pytest

from app.simulation.kv_block_manager import KVBlockManager


@pytest.fixture
def dual_node_manager():
    return KVBlockManager(
        g1_cap=10.0,
        g2_cap=20.0,
        g3_cap=30.0,
        g35_cap=100.0,
        g4_cap=200.0,
        cmx_enabled=False,
        node_ids_override=["node-a", "node-b"],
    )


def test_node_ids_and_allocate(dual_node_manager):
    m = dual_node_manager
    assert m.node_ids == ("node-a", "node-b")
    m.allocate("s1", 1.0, "node-a")
    m.allocate("s2", 1.0, "node-b")
    assert m.get_block_node("s1") == "node-a"
    assert m.get_block_node("s2") == "node-b"
    assert m.get_block_tier("s1") == "G1"


def test_aggregate_node_tier_across_nodes(dual_node_manager):
    m = dual_node_manager
    m.allocate("a1", 2.0, "node-a")
    m.allocate("b1", 3.0, "node-b")
    agg = m.aggregate_node_tier_across_nodes("G1")
    assert agg["sessions_active"] == 2
    assert agg["used_gb"] == pytest.approx(5.0)
    assert agg["capacity_gb"] == pytest.approx(20.0)


def test_get_node_tier_state_keys():
    m = KVBlockManager(
        g1_cap=5.0,
        g2_cap=5.0,
        g3_cap=5.0,
        g35_cap=10.0,
        g4_cap=10.0,
        cmx_enabled=True,
        node_ids_override=["node-x"],
    )
    st = m.get_node_tier_state("node-x")
    assert len(st) == 3
    assert {t["name"] for t in st} == {"G1", "G2", "G3"}
