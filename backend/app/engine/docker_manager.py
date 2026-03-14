"""Docker operations: compose up/down, container inspection."""
import asyncio
import logging
import docker
from docker.errors import NotFound, APIError
from ..models.demo import DemoDefinition
from ..state.store import state, RunningDemo, RunningContainer
from ..models.api_models import ContainerHealthStatus
from .compose_generator import generate_compose
from .network_manager import join_network, leave_all_networks

logger = logging.getLogger(__name__)
docker_client = docker.from_env()

COMPOSE_TIMEOUT = 60  # seconds — max wait for compose up/down

# Per-demo locks to prevent concurrent deploy/stop race conditions
_demo_locks: dict[str, asyncio.Lock] = {}


def _get_lock(demo_id: str) -> asyncio.Lock:
    if demo_id not in _demo_locks:
        _demo_locks[demo_id] = asyncio.Lock()
    return _demo_locks[demo_id]


async def _compose_down(compose_path: str, project_name: str, timeout: int = COMPOSE_TIMEOUT, remove_volumes: bool = True):
    """Run docker compose down with timeout. Returns True if successful."""
    cmd = ["docker", "compose", "-f", compose_path, "-p", project_name, "down", "--remove-orphans"]
    if remove_volumes:
        cmd.append("-v")
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode == 0
    except asyncio.TimeoutError:
        logger.warning(f"compose down timed out for {project_name}, killing process")
        proc.kill()
        await proc.communicate()
        return False


async def _force_remove_containers(demo_id: str):
    """Force-remove all containers for a demo directly via Docker API. Fallback when compose down fails."""
    logger.info(f"Force-removing containers for demo {demo_id}")
    try:
        containers = await asyncio.to_thread(
            docker_client.containers.list,
            all=True,
            filters={"label": f"demoforge.demo={demo_id}"}
        )
        for c in containers:
            try:
                logger.info(f"Force-removing container {c.name}")
                await asyncio.to_thread(c.remove, force=True, v=True)
            except Exception as e:
                logger.warning(f"Failed to remove container {c.name}: {e}")
    except Exception as e:
        logger.warning(f"Failed to list containers for demo {demo_id}: {e}")


async def _cleanup_demo(demo_id: str, compose_path: str | None, project_name: str, networks: list[str], remove_volumes: bool = True):
    """Full cleanup: leave networks, compose down with timeout, force-remove as fallback."""
    # Disconnect backend from demo networks
    try:
        await asyncio.to_thread(leave_all_networks, networks)
    except Exception as e:
        logger.warning(f"Failed to leave networks for {demo_id}: {e}")

    # Try compose down first
    if compose_path:
        success = await _compose_down(compose_path, project_name, remove_volumes=remove_volumes)
        if not success:
            logger.warning(f"compose down failed for {demo_id}, falling back to force-remove")
            await _force_remove_containers(demo_id)
    else:
        # No compose file — force-remove directly
        await _force_remove_containers(demo_id)

    # Clean up any networks left behind (use prefix match for compose-created networks)
    try:
        all_networks = await asyncio.to_thread(docker_client.networks.list)
        demo_networks = [n for n in all_networks if n.name.startswith(project_name)]
        for net in demo_networks:
            try:
                await asyncio.to_thread(net.remove)
            except Exception:
                pass
    except Exception:
        pass


async def deploy_demo(demo: DemoDefinition, data_dir: str, components_dir: str = "./components", on_progress=None) -> RunningDemo:
    """Generate compose file, bring up containers, join networks.

    on_progress: optional async callback(step: str, status: str, detail: str)
    """
    lock = _get_lock(demo.id)
    async with lock:
        return await _deploy_demo_locked(demo, data_dir, components_dir, on_progress)


async def _deploy_demo_locked(demo: DemoDefinition, data_dir: str, components_dir: str, on_progress) -> RunningDemo:
    async def progress(step: str, status: str, detail: str = ""):
        logger.info(f"Deploy progress [{demo.id}]: {step} -> {status}: {detail}")
        if on_progress:
            await on_progress(step, status, detail)

    project_name = f"demoforge-{demo.id}"
    network_names = [f"{project_name}-{net.name}" for net in demo.networks]

    await progress("compose", "running", "Generating docker-compose file...")
    compose_path = generate_compose(demo, data_dir, components_dir)
    await progress("compose", "done", f"Generated {compose_path}")

    running = RunningDemo(
        demo_id=demo.id,
        status="deploying",
        compose_project=project_name,
        networks=network_names,
        compose_file_path=compose_path,
    )
    state.set_demo(running)

    # Clean up leftover containers (preserve volumes on redeploy)
    await progress("cleanup", "running", "Cleaning up previous containers...")
    await _cleanup_demo(demo.id, compose_path, project_name, network_names, remove_volumes=False)
    await progress("cleanup", "done", "Cleanup complete")

    # Run docker compose up with timeout
    await progress("containers", "running", f"Starting {len(demo.nodes)} containers...")
    proc = await asyncio.create_subprocess_exec(
        "docker", "compose", "-f", compose_path, "-p", project_name, "up", "-d",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=COMPOSE_TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        running.status = "error"
        running.error_message = f"docker compose up timed out after {COMPOSE_TIMEOUT}s"
        state.set_demo(running)
        await progress("containers", "error", running.error_message)
        raise TimeoutError(running.error_message)

    if proc.returncode != 0:
        error_text = stderr.decode()
        running.status = "error"
        running.error_message = error_text
        state.set_demo(running)
        await progress("containers", "error", error_text)
        raise RuntimeError(f"docker compose up failed: {error_text}")
    await progress("containers", "done", "Containers started")

    try:
        # Join backend container to all demo networks
        await progress("networks", "running", f"Joining {len(network_names)} network(s)...")
        for net_name in network_names:
            await asyncio.to_thread(join_network, net_name)
        await progress("networks", "done", "Networks connected")

        # Discover running containers
        await progress("discovery", "running", "Discovering containers...")
        containers = await asyncio.to_thread(
            docker_client.containers.list,
            filters={"label": f"demoforge.demo={demo.id}"}
        )
        for c in containers:
            node_id = c.labels.get("demoforge.node", "")
            component_id = c.labels.get("demoforge.component", "")
            running.containers[node_id] = RunningContainer(
                node_id=node_id,
                component_id=component_id,
                container_name=c.name,
                networks=network_names,
            )
        await progress("discovery", "done", f"Found {len(containers)} container(s)")

        # Run init scripts after containers are discovered
        await progress("init_scripts", "running", "Running init scripts...")
        from .init_runner import run_init_scripts
        init_results = await run_init_scripts(running)
        running.init_results = init_results

        failed_inits = [r for r in init_results if r.get("exit_code", 0) != 0]
        if failed_inits:
            logger.warning(f"Demo {demo.id}: {len(failed_inits)} init script(s) failed: {failed_inits}")
            await progress("init_scripts", "warning", f"{len(failed_inits)} init script(s) failed")
        else:
            await progress("init_scripts", "done", f"{len(init_results)} init script(s) completed")

        # Run edge automation scripts (connection-driven init)
        from .edge_automation import generate_edge_scripts
        edge_scripts = generate_edge_scripts(demo, project_name)
        if edge_scripts:
            await progress("edge_config", "running", f"Configuring {len(edge_scripts)} connection(s)...")
            for script in edge_scripts:
                try:
                    if script.wait_for_healthy:
                        from .init_runner import wait_for_healthy as wait_healthy
                        healthy = await wait_healthy(script.container_name, script.timeout)
                        if not healthy:
                            logger.warning(f"Edge script skipped for {script.edge_id}: container not healthy")
                            continue
                    exit_code, stdout, stderr = await exec_in_container(
                        script.container_name, f"sh -c '{script.command}'"
                    )
                    if exit_code != 0:
                        logger.warning(f"Edge script failed for {script.edge_id}: {stderr}")
                except Exception as e:
                    logger.warning(f"Edge script error for {script.edge_id}: {e}")
            await progress("edge_config", "done", f"{len(edge_scripts)} connection(s) configured")

        running.status = "running"
        state.set_demo(running)
        await progress("complete", "done", "Demo is running")
        return running

    except Exception as e:
        logger.exception(f"Post-compose setup failed for demo {demo.id}, rolling back")
        running.status = "error"
        running.error_message = str(e)
        state.set_demo(running)
        await progress("rollback", "running", "Rolling back...")
        await _cleanup_demo(demo.id, compose_path, project_name, network_names)
        state.remove_demo(demo.id)
        await progress("rollback", "error", str(e))
        raise


async def stop_demo(demo_id: str):
    """Bring down containers, disconnect from network, clean up."""
    lock = _get_lock(demo_id)
    async with lock:
        running = state.get_demo(demo_id)
        if not running:
            # No state — still try to force-remove any orphaned containers
            await _force_remove_containers(demo_id)
            return

        await _cleanup_demo(
            demo_id,
            running.compose_file_path or None,
            running.compose_project,
            running.networks,
            remove_volumes=True,
        )
        state.remove_demo(demo_id)


async def get_container_health(container_name: str) -> ContainerHealthStatus:
    """Check a container's health status via Docker API (non-blocking)."""
    try:
        c = await asyncio.to_thread(docker_client.containers.get, container_name)
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
    """Restart a single container (non-blocking)."""
    try:
        c = await asyncio.to_thread(docker_client.containers.get, container_name)
        await asyncio.to_thread(c.restart, timeout=10)
    except NotFound:
        raise ValueError(f"Container {container_name} not found")


async def exec_in_container(container_name: str, command: str) -> tuple[int, str, str]:
    """Run a one-shot command in a container. Returns (exit_code, stdout, stderr)."""
    try:
        c = await asyncio.to_thread(docker_client.containers.get, container_name)
        result = await asyncio.to_thread(c.exec_run, command, demux=True)
        stdout = result.output[0].decode() if result.output[0] else ""
        stderr = result.output[1].decode() if result.output[1] else ""
        return result.exit_code, stdout, stderr
    except NotFound:
        raise ValueError(f"Container {container_name} not found")
