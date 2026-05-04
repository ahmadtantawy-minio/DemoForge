"""Smoke tests for /status shape (2× DGX node model)."""

import asyncio
from types import MethodType

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.models import SimConfig
from app.simulation.engine import SimulationEngine


def test_status_has_nodes_and_memory_budget_keys():
    client = TestClient(app)
    r = client.get("/status")
    assert r.status_code == 200
    data = r.json()
    assert "nodes" in data and isinstance(data["nodes"], list)
    assert len(data["nodes"]) == 2
    ids = {n["node_id"] for n in data["nodes"]}
    assert ids == {"node-a", "node-b"}
    mb = data.get("memory_budget") or {}
    assert mb.get("node_count") == 2
    assert mb.get("gpus_per_node") == 8
    assert "node-a" in mb and "node-b" in mb
    for nid in ("node-a", "node-b"):
        row = mb[nid]
        assert row.get("g1_total_gb") == 640.0
        assert row.get("kv_capacity_gb") == 328.0

    cfg = data.get("config") or {}
    assert cfg.get("node_count") == 2
    assert cfg.get("gpus_per_node") == 8
    assert cfg.get("replica_count") == 8
    assert cfg.get("gpu_count") == 16
    assert "model_name" in cfg and cfg["model_name"]
    assert cfg.get("tensor_parallel") == 2
    assert "session_arrival_target" in cfg
    assert cfg["session_arrival_target"] == cfg["users"]
    assert cfg.get("queue_tracking_enabled") is True

    m = data.get("metrics") or {}
    assert m.get("node_count") == 2
    assert isinstance(m.get("node_utilizations"), list)
    assert len(m["node_utilizations"]) == 2
    assert m["node_utilizations"][0].get("node_id") == "node-a"
    assert "utilization" in m["node_utilizations"][0]

    cfg = data.get("config") or {}
    assert cfg.get("node_count") == 2
    assert cfg.get("gpus_per_node") == 8
    assert cfg.get("replica_count") == settings.replica_count
    assert cfg.get("gpu_count") == settings.gpu_count
    assert cfg.get("model_name")
    assert cfg.get("tensor_parallel") == 2
    assert cfg.get("kv_precision_note")

    metrics = data.get("metrics") or {}
    nu = metrics.get("node_utilizations")
    assert isinstance(nu, list) and len(nu) == 2
    assert {e["node_id"] for e in nu} == {"node-a", "node-b"}
    assert all(isinstance(e.get("utilization"), int) for e in nu)
    assert "queued_sessions" in metrics
    assert "queue_wait_ms_p95" in metrics


def test_tick_passes_arrival_target_to_request_generator(monkeypatch):
    monkeypatch.setattr(settings, "replica_count", 6)
    captured: list[int] = []

    def capture_generate(self, tick, num_users, context_tokens, current_active, current_idle, current_returning, current_queued=0):
        captured.append(num_users)
        return 0

    async def run_once():
        eng = SimulationEngine()
        eng.config = SimConfig(users=300, context_tokens=4096, scenario="minio-g4")
        eng.request_gen.generate = MethodType(capture_generate, eng.request_gen)
        loop = asyncio.get_event_loop()
        async with eng._lock:
            await eng._tick_once(loop)

    asyncio.run(run_once())
    assert captured == [300]


def test_live_session_count_respects_slider_not_replica_count(monkeypatch):
    """Slider caps live sessions; replica_count does not impose a cluster ceiling."""
    monkeypatch.setattr(settings, "replica_count", 4)
    monkeypatch.setattr("app.simulation.request_generator.random.random", lambda: 0.001)

    async def run_ticks():
        eng = SimulationEngine()
        eng.config = SimConfig(users=12, context_tokens=4096, scenario="minio-g4")
        eng._apply_scenario()
        loop = asyncio.get_event_loop()
        peak = 0
        for _ in range(120):
            async with eng._lock:
                await eng._tick_once(loop)
                active = len(eng.session_manager.get_active_sessions())
                idle = len(eng.session_manager.get_idle_sessions())
                ret = len(eng.session_manager.get_returning_sessions())
                peak = max(peak, active + idle + ret)
        return peak

    assert asyncio.run(run_ticks()) <= 12
