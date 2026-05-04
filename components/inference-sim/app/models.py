from __future__ import annotations

from typing import Any
from pydantic import BaseModel


class SimConfig(BaseModel):
    users: int = 50
    context_tokens: int = 65536
    speed: float = 1.0
    cmx_enabled: bool = True       # Backward compat
    g35_mode: str = "accelerated"  # Backward compat — maps to scenario
    scenario: str = "file-g4"      # "file-g4" | "minio-g4" | "minio-full"


class TierState(BaseModel):
    name: str
    capacity_gb: float
    used_gb: float
    block_count: int
    latency_ms: float


class NodeTierState(BaseModel):
    node_id: str
    g1: TierState
    g2: TierState
    g3: TierState
    utilization: dict | None = None


class SharedTierState(BaseModel):
    g35: TierState
    g4: TierState


class SessionState(BaseModel):
    session_id: str
    tier: str
    status: str  # queued | active | idle | returning | terminated
    kv_size_gb: float
    idle_ticks: int
    node_id: str
    gpu_id: str | None = None  # deprecated mirror of node_id for older clients
    queue_wait_ticks: int = 0


class SimStatus(BaseModel):
    running: bool
    tick: int
    nodes: list[NodeTierState]
    gpus: list[NodeTierState] | None = None  # deprecated; mirror of nodes for older clients
    shared: SharedTierState
    sessions: list[SessionState]
    metrics: dict[str, Any]
    events: list[dict[str, Any]] = []
    backend_errors: list[str] = []
    eviction_policy: dict[str, Any] = {}
    config: dict[str, Any] = {}
    memory_budget: dict[str, Any] | None = None


class HealthResponse(BaseModel):
    status: str
    minio_g35_connected: bool
    minio_g4_connected: bool
