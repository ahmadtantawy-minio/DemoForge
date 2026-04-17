"""Tests for deploying→running reconciliation (sidecar exclusion)."""
from unittest.mock import MagicMock, patch

import pytest

from app.state.store import RunningContainer, RunningDemo, StateStore


@pytest.fixture
def store() -> StateStore:
    return StateStore()


def _run_reconcile(store: StateStore, mock_client: MagicMock, *, operation_running: bool) -> None:
    with patch("docker.from_env", return_value=mock_client):
        with patch("app.engine.task_manager.is_operation_running", return_value=operation_running):
            store.reconcile_deploying_from_docker()


def test_reconcile_no_container_inspect_when_not_deploying(store: StateStore) -> None:
    store.running_demos["abc"] = RunningDemo(demo_id="abc", status="running", compose_project="demoforge-abc")
    mock_client = MagicMock()
    _run_reconcile(store, mock_client, operation_running=False)
    mock_client.containers.get.assert_not_called()


def test_reconcile_skips_when_task_running(store: StateStore) -> None:
    demo = RunningDemo(demo_id="abc", status="deploying", compose_project="demoforge-abc")
    demo.containers["n1"] = RunningContainer(
        node_id="n1",
        component_id="minio",
        container_name="demoforge-abc-n1",
        networks=[],
        is_sidecar=False,
    )
    store.running_demos["abc"] = demo
    mock_client = MagicMock()
    _run_reconcile(store, mock_client, operation_running=True)
    assert demo.status == "deploying"
    mock_client.containers.get.assert_not_called()


def test_reconcile_promotes_when_steady_containers_running(store: StateStore) -> None:
    demo = RunningDemo(demo_id="abc", status="deploying", compose_project="demoforge-abc")
    demo.containers["n1"] = RunningContainer(
        node_id="n1",
        component_id="minio",
        container_name="c1",
        networks=[],
        is_sidecar=False,
    )
    demo.containers["side"] = RunningContainer(
        node_id="side",
        component_id="metabase-init",
        container_name="c-side",
        networks=[],
        is_sidecar=True,
    )
    store.running_demos["abc"] = demo

    mock_ctr = MagicMock()
    mock_ctr.status = "running"
    mock_client = MagicMock()
    mock_client.containers.get.return_value = mock_ctr
    mock_client.close = MagicMock()

    _run_reconcile(store, mock_client, operation_running=False)

    assert demo.status == "running"
    mock_client.containers.get.assert_called_once_with("c1")


def test_reconcile_waits_if_steady_not_running(store: StateStore) -> None:
    demo = RunningDemo(demo_id="abc", status="deploying", compose_project="demoforge-abc")
    demo.containers["n1"] = RunningContainer(
        node_id="n1",
        component_id="minio",
        container_name="c1",
        networks=[],
        is_sidecar=False,
    )
    store.running_demos["abc"] = demo

    mock_ctr = MagicMock()
    mock_ctr.status = "exited"
    mock_client = MagicMock()
    mock_client.containers.get.return_value = mock_ctr
    mock_client.close = MagicMock()
    _run_reconcile(store, mock_client, operation_running=False)

    assert demo.status == "deploying"
