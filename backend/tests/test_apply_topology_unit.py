"""Sanity checks for apply_saved_demo_topology error paths (no real Docker)."""
from unittest.mock import patch

import pytest

from app.models.demo import DemoCluster, DemoDefinition, DemoServerPool, NodePosition
from app.state.store import RunningDemo, StateStore


@pytest.mark.asyncio
async def test_apply_topology_requires_running_state() -> None:
    from app.engine import docker_manager as dm

    store = StateStore()
    with patch.object(dm, "state", store):
        with pytest.raises(ValueError, match="not in running"):
            await dm.apply_saved_demo_topology("x", "./data", "./components")


@pytest.mark.asyncio
async def test_apply_topology_requires_running_status() -> None:
    from app.engine import docker_manager as dm

    store = StateStore()
    store.running_demos["x"] = RunningDemo(demo_id="x", status="deploying", compose_project="demoforge-x")
    with patch.object(dm, "state", store):
        with pytest.raises(ValueError, match="must be running"):
            await dm.apply_saved_demo_topology("x", "./data", "./components")


@pytest.mark.asyncio
async def test_apply_topology_missing_yaml() -> None:
    from app.engine import docker_manager as dm

    store = StateStore()
    store.running_demos["x"] = RunningDemo(
        demo_id="x",
        status="running",
        compose_project="demoforge-x",
        compose_file_path="/tmp/fake.yml",
    )
    with patch.object(dm, "state", store):
        with patch("app.api.demos._load_demo", return_value=None):
            with pytest.raises(ValueError, match="YAML not found"):
                await dm.apply_saved_demo_topology("x", "./data", "./components")


@pytest.mark.asyncio
async def test_apply_topology_blocked_when_pool_decommissioning() -> None:
    from app.engine import docker_manager as dm

    store = StateStore()
    store.running_demos["x"] = RunningDemo(
        demo_id="x",
        status="running",
        compose_project="demoforge-x",
        compose_file_path="/tmp/fake.yml",
    )
    demo = DemoDefinition(
        id="x",
        name="t",
        networks=[],
        nodes=[],
        edges=[],
        clusters=[
            DemoCluster(
                id="c1",
                position=NodePosition(x=0, y=0),
                server_pools=[
                    DemoServerPool(id="pool-1", node_count=4, drives_per_node=2),
                ],
                pool_lifecycle={"pool-1": "decommissioning"},
            )
        ],
    )
    with patch.object(dm, "state", store):
        with patch("app.api.demos._load_demo", return_value=demo):
            with pytest.raises(ValueError, match="decommission"):
                await dm.apply_saved_demo_topology("x", "./data", "./components")
