"""
In-memory state for running demos.
Tracks which demos are deployed, their container names, and network memberships.
No persistence needed — if backend restarts, demos are still running in Docker
and we can re-discover them via labels.
"""
import logging
from dataclasses import dataclass, field
from ..models.api_models import ContainerHealthStatus

logger = logging.getLogger(__name__)

@dataclass
class RunningContainer:
    node_id: str                      # e.g. "minio-1"
    component_id: str                 # e.g. "minio"
    container_name: str               # Docker container name
    networks: list[str]               # Docker network names this container is on
    health: ContainerHealthStatus = ContainerHealthStatus.STARTING

@dataclass
class EdgeConfigResult:
    edge_id: str
    connection_type: str
    status: str = "pending"           # "pending", "applied", "failed"
    description: str = ""
    error: str = ""

@dataclass
class RunningDemo:
    demo_id: str
    status: str = "stopped"           # "stopped", "deploying", "running", "error"
    compose_project: str = ""         # Docker Compose project name
    networks: list[str] = field(default_factory=list)
    containers: dict[str, RunningContainer] = field(default_factory=dict)  # node_id → RunningContainer
    compose_file_path: str = ""       # Path to generated docker-compose.yml
    init_results: list[dict] = field(default_factory=list)  # Results from init script runner
    error_message: str = ""           # Error details if status == "error"
    edge_configs: dict[str, EdgeConfigResult] = field(default_factory=dict)  # edge_id → EdgeConfigResult

class DeployProgress:
    """Tracks deployment progress steps."""
    def __init__(self):
        self.steps: list[dict] = []
        self.finished: bool = False

    def add(self, step: str, status: str, detail: str = ""):
        for s in self.steps:
            if s["step"] == step:
                s["status"] = status
                s["detail"] = detail
                return
        self.steps.append({"step": step, "status": status, "detail": detail})

    def to_dict(self):
        return {"steps": self.steps, "finished": self.finished}

class StateStore:
    def __init__(self):
        self.running_demos: dict[str, RunningDemo] = {}   # demo_id → RunningDemo
        self.deploy_progress: dict[str, DeployProgress] = {}  # demo_id → DeployProgress

    def get_demo(self, demo_id: str) -> RunningDemo | None:
        return self.running_demos.get(demo_id)

    def set_demo(self, demo: RunningDemo):
        self.running_demos[demo.demo_id] = demo

    def remove_demo(self, demo_id: str):
        self.running_demos.pop(demo_id, None)

    def list_demos(self) -> list[RunningDemo]:
        return list(self.running_demos.values())

    def recover_from_docker(self):
        """Re-discover running demos from Docker containers using labels."""
        import docker
        from docker.errors import APIError
        try:
            client = docker.from_env()
            containers = client.containers.list(
                all=True,
                filters={"label": "demoforge.demo"}
            )
        except (APIError, Exception) as e:
            logger.warning(f"State recovery failed — cannot reach Docker: {e}")
            return

        demos_map: dict[str, RunningDemo] = {}
        for c in containers:
            demo_id = c.labels.get("demoforge.demo", "")
            node_id = c.labels.get("demoforge.node", "")
            component_id = c.labels.get("demoforge.component", "")
            if not demo_id or not node_id:
                continue

            if demo_id not in demos_map:
                project_name = f"demoforge-{demo_id}"
                # Discover networks from the container
                net_names = list(c.attrs.get("NetworkSettings", {}).get("Networks", {}).keys())
                demo_nets = [n for n in net_names if n.startswith(project_name)]
                demos_map[demo_id] = RunningDemo(
                    demo_id=demo_id,
                    status="running",
                    compose_project=project_name,
                    networks=demo_nets,
                )

            running = demos_map[demo_id]
            container_nets = list(c.attrs.get("NetworkSettings", {}).get("Networks", {}).keys())
            running.containers[node_id] = RunningContainer(
                node_id=node_id,
                component_id=component_id,
                container_name=c.name,
                networks=container_nets,
            )
            # Merge any new networks
            for n in container_nets:
                if n.startswith(running.compose_project) and n not in running.networks:
                    running.networks.append(n)

        for demo_id, running in demos_map.items():
            self.running_demos[demo_id] = running

        if demos_map:
            logger.info(f"Recovered {len(demos_map)} running demo(s) from Docker: {list(demos_map.keys())}")

    def sync_with_docker(self):
        """Reconcile in-memory state with actual Docker state.
        - Mark demos as stopped if their containers are gone
        - Detect new containers that appeared outside our control
        - Update container health status
        """
        import docker
        from docker.errors import APIError
        try:
            client = docker.from_env()
            containers = client.containers.list(
                all=True,
                filters={"label": "demoforge.demo"}
            )
        except (APIError, Exception) as e:
            logger.warning(f"State sync failed — cannot reach Docker: {e}")
            return

        # Build map of what Docker actually has
        docker_demos: dict[str, list] = {}
        for c in containers:
            demo_id = c.labels.get("demoforge.demo", "")
            if demo_id:
                docker_demos.setdefault(demo_id, []).append(c)

        # Check demos we think are running but Docker disagrees
        for demo_id, running in list(self.running_demos.items()):
            if running.status in ("deploying",):
                continue  # Don't interfere with active deploys

            docker_containers = docker_demos.get(demo_id, [])
            running_containers = [c for c in docker_containers if c.status == "running"]
            all_containers = docker_containers  # includes stopped

            if running.status == "running" and len(running_containers) == 0 and len(all_containers) == 0:
                logger.warning(f"Sync: demo {demo_id} marked running but has 0 containers — marking stopped")
                running.status = "stopped"
                running.containers.clear()

            elif running.status == "running":
                # Update container list — include ALL containers (running + stopped)
                # so stopped nodes can be started back via the UI
                current_nodes = set()
                for c in all_containers:
                    node_id = c.labels.get("demoforge.node", "")
                    component_id = c.labels.get("demoforge.component", "")
                    if node_id:
                        current_nodes.add(node_id)
                        if node_id not in running.containers:
                            container_nets = list(c.attrs.get("NetworkSettings", {}).get("Networks", {}).keys())
                            running.containers[node_id] = RunningContainer(
                                node_id=node_id,
                                component_id=component_id,
                                container_name=c.name,
                                networks=container_nets,
                            )
                # Remove containers that are completely gone (deleted, not just stopped)
                for node_id in list(running.containers.keys()):
                    if node_id not in current_nodes:
                        del running.containers[node_id]

        # Detect orphaned containers (in Docker but not in our state)
        for demo_id, containers in docker_demos.items():
            running_containers = [c for c in containers if c.status == "running"]
            if demo_id not in self.running_demos and running_containers:
                logger.info(f"Sync: found {len(running_containers)} orphaned container(s) for demo {demo_id} — recovering state")
                project_name = f"demoforge-{demo_id}"
                running = RunningDemo(
                    demo_id=demo_id,
                    status="running",
                    compose_project=project_name,
                )
                for c in running_containers:
                    node_id = c.labels.get("demoforge.node", "")
                    component_id = c.labels.get("demoforge.component", "")
                    container_nets = list(c.attrs.get("NetworkSettings", {}).get("Networks", {}).keys())
                    demo_nets = [n for n in container_nets if n.startswith(project_name)]
                    if node_id:
                        running.containers[node_id] = RunningContainer(
                            node_id=node_id,
                            component_id=component_id,
                            container_name=c.name,
                            networks=container_nets,
                        )
                    for n in demo_nets:
                        if n not in running.networks:
                            running.networks.append(n)
                self.running_demos[demo_id] = running

# Singleton
state = StateStore()
