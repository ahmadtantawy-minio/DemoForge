"""
In-memory state for running demos.
Tracks which demos are deployed, their container names, and network memberships.
No persistence needed — if backend restarts, demos are still running in Docker
and we can re-discover them via labels.
"""
from dataclasses import dataclass, field
from ..models.api_models import ContainerHealthStatus

@dataclass
class RunningContainer:
    node_id: str                      # e.g. "minio-1"
    component_id: str                 # e.g. "minio"
    container_name: str               # Docker container name
    networks: list[str]               # Docker network names this container is on
    health: ContainerHealthStatus = ContainerHealthStatus.STARTING

@dataclass
class RunningDemo:
    demo_id: str
    status: str = "stopped"           # "stopped", "deploying", "running", "error"
    compose_project: str = ""         # Docker Compose project name
    networks: list[str] = field(default_factory=list)
    containers: dict[str, RunningContainer] = field(default_factory=dict)  # node_id → RunningContainer
    compose_file_path: str = ""       # Path to generated docker-compose.yml

class StateStore:
    def __init__(self):
        self.running_demos: dict[str, RunningDemo] = {}   # demo_id → RunningDemo

    def get_demo(self, demo_id: str) -> RunningDemo | None:
        return self.running_demos.get(demo_id)

    def set_demo(self, demo: RunningDemo):
        self.running_demos[demo.demo_id] = demo

    def remove_demo(self, demo_id: str):
        self.running_demos.pop(demo_id, None)

    def list_demos(self) -> list[RunningDemo]:
        return list(self.running_demos.values())

# Singleton
state = StateStore()
