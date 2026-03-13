"""Docker operations: compose up/down, network join, container inspection."""
import asyncio
import docker
from docker.errors import NotFound, APIError
from ..models.demo import DemoDefinition
from ..state.store import state, RunningDemo, RunningContainer
from ..models.api_models import ContainerHealthStatus
from .compose_generator import generate_compose

docker_client = docker.from_env()

def _find_self_container_id() -> str | None:
    """Find the DemoForge backend container by its label."""
    containers = docker_client.containers.list(
        filters={"label": "demoforge.role=backend"}
    )
    if containers:
        return containers[0].id
    # Fallback: we might be running outside Docker (dev mode)
    return None

async def deploy_demo(demo: DemoDefinition, data_dir: str) -> RunningDemo:
    """Generate compose file, bring up containers, join network."""
    project_name = f"demoforge-{demo.id}"
    network_name = f"{project_name}-net"
    compose_path = generate_compose(demo, data_dir)

    running = RunningDemo(
        demo_id=demo.id,
        status="deploying",
        compose_project=project_name,
        networks=[network_name],
        compose_file_path=compose_path,
    )
    state.set_demo(running)

    # Run docker compose up
    proc = await asyncio.create_subprocess_exec(
        "docker", "compose", "-f", compose_path, "-p", project_name, "up", "-d",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        running.status = "error"
        state.set_demo(running)
        raise RuntimeError(f"docker compose up failed: {stderr.decode()}")

    # Join backend container to demo network
    self_id = _find_self_container_id()
    if self_id:
        try:
            network = docker_client.networks.get(network_name)
            network.connect(self_id)
        except APIError:
            pass  # May already be connected

    # Discover running containers
    containers = docker_client.containers.list(
        filters={"label": f"demoforge.demo={demo.id}"}
    )
    for c in containers:
        node_id = c.labels.get("demoforge.node", "")
        component_id = c.labels.get("demoforge.component", "")
        running.containers[node_id] = RunningContainer(
            node_id=node_id,
            component_id=component_id,
            container_name=c.name,
            networks=[network_name],
        )

    running.status = "running"
    state.set_demo(running)
    return running

async def stop_demo(demo_id: str):
    """Bring down containers, disconnect from network, clean up."""
    running = state.get_demo(demo_id)
    if not running:
        return

    # Disconnect backend from demo network first
    self_id = _find_self_container_id()
    if self_id:
        for net_name in running.networks:
            try:
                network = docker_client.networks.get(net_name)
                network.disconnect(self_id)
            except (NotFound, APIError):
                pass

    # Docker compose down
    if running.compose_file_path:
        proc = await asyncio.create_subprocess_exec(
            "docker", "compose", "-f", running.compose_file_path,
            "-p", running.compose_project, "down", "-v",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

    state.remove_demo(demo_id)

def get_container_health(container_name: str) -> ContainerHealthStatus:
    """Check a container's health status via Docker API."""
    try:
        c = docker_client.containers.get(container_name)
        if c.status != "running":
            return ContainerHealthStatus.STOPPED
        health = c.attrs.get("State", {}).get("Health", {})
        health_status = health.get("Status", "none")
        if health_status == "healthy":
            return ContainerHealthStatus.HEALTHY
        elif health_status == "starting":
            return ContainerHealthStatus.STARTING
        elif health_status == "unhealthy":
            return ContainerHealthStatus.ERROR
        else:
            # No healthcheck defined — if running, assume healthy
            return ContainerHealthStatus.HEALTHY if c.status == "running" else ContainerHealthStatus.STOPPED
    except NotFound:
        return ContainerHealthStatus.STOPPED

async def restart_container(container_name: str):
    """Restart a single container."""
    try:
        c = docker_client.containers.get(container_name)
        c.restart(timeout=10)
    except NotFound:
        raise ValueError(f"Container {container_name} not found")

async def exec_in_container(container_name: str, command: str) -> tuple[int, str, str]:
    """Run a one-shot command in a container. Returns (exit_code, stdout, stderr)."""
    try:
        c = docker_client.containers.get(container_name)
        result = c.exec_run(command, demux=True)
        stdout = result.output[0].decode() if result.output[0] else ""
        stderr = result.output[1].decode() if result.output[1] else ""
        return result.exit_code, stdout, stderr
    except NotFound:
        raise ValueError(f"Container {container_name} not found")
