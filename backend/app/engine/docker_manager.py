"""Docker operations: compose up/down, container inspection."""
import asyncio
import logging
import os
import docker
from docker.errors import NotFound, APIError
from ..models.demo import DemoDefinition
from ..state.store import state, RunningDemo, RunningContainer
from ..models.api_models import ContainerHealthStatus
from .compose_generator import generate_compose
from .network_manager import join_network, leave_all_networks
from ..registry.loader import get_component

logger = logging.getLogger(__name__)
docker_client = docker.from_env()

COMPOSE_TIMEOUT = 180  # seconds — max wait for compose up/down
GCR_PREFIX = "gcr.io/minio-demoforge"

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


async def _build_custom_images(demo: DemoDefinition, components_dir: str, progress) -> int:
    """Pre-build Docker images for components that have build_context set.

    Uses the Docker SDK to build images directly, avoiding the need for
    docker compose buildx. Returns the number of images built.
    """
    built = set()
    for node in demo.nodes:
        manifest = get_component(node.component)
        if not manifest or not manifest.build_context or manifest.image in built:
            continue

        component_dir = os.path.join(components_dir, node.component)
        build_path = os.path.abspath(os.path.join(component_dir, manifest.build_context))

        if not os.path.isdir(build_path):
            logger.warning(f"Build context not found: {build_path}")
            continue

        # Skip build if image already exists (pre-built locally)
        try:
            existing = docker_client.images.get(manifest.image)
            built.add(manifest.image)
            logger.info(f"Image {manifest.image} already exists ({existing.short_id}), skipping build")
            continue
        except Exception:
            pass  # image not found, proceed to build
            pass

        await progress("images", "running", f"Building {manifest.image}...")
        logger.info(f"Building image {manifest.image} from {build_path}")

        try:
            image, build_logs = await asyncio.to_thread(
                docker_client.images.build,
                path=build_path,
                tag=manifest.image,
                rm=True,
            )
            built.add(manifest.image)
            logger.info(f"Built image {manifest.image} ({image.short_id})")
        except Exception as e:
            logger.error(f"Failed to build {manifest.image}: {e}")
            raise RuntimeError(f"Failed to build image {manifest.image}: {e}")

    return len(built)


async def _pull_missing_images(demo: DemoDefinition, progress) -> int:
    """Pull any missing component images from GCR before compose up."""
    pulled: set[str] = set()
    for node in demo.nodes:
        manifest = get_component(node.component)
        if not manifest or not manifest.image or manifest.image in pulled:
            continue
        image_ref = manifest.image
        try:
            docker_client.images.get(image_ref)
            continue  # already cached
        except Exception:
            pass
        gcr_ref = f"{GCR_PREFIX}/{image_ref}" if image_ref.startswith("demoforge/") else image_ref
        await progress("images", "running", f"Pulling {image_ref}...")
        logger.info(f"Pulling missing image from GCR: {gcr_ref}")
        try:
            await asyncio.to_thread(docker_client.images.pull, gcr_ref)
            img = docker_client.images.get(gcr_ref)
            img.tag(image_ref)
            pulled.add(image_ref)
            logger.info(f"Pulled and tagged {image_ref}")
        except Exception as e:
            logger.error(f"Failed to pull {image_ref}: {e}")
            raise RuntimeError(f"Failed to pull image {image_ref} from GCR: {e}")
    return len(pulled)


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
    compose_path, demo = generate_compose(demo, data_dir, components_dir)
    await progress("compose", "done", f"Generated {compose_path}")

    running = RunningDemo(
        demo_id=demo.id,
        status="deploying",
        compose_project=project_name,
        networks=network_names,
        compose_file_path=compose_path,
    )
    state.set_demo(running)

    # Pre-build custom images (components with build_context)
    await progress("images", "running", "Checking for custom images to build...")
    images_built = await _build_custom_images(demo, components_dir, progress)
    if images_built:
        await progress("images", "done", f"Built {images_built} custom image(s)")
    else:
        await progress("images", "done", "No custom images needed")

    # Pull any missing component images from GCR on-demand
    images_pulled = await _pull_missing_images(demo, progress)
    if images_pulled:
        await progress("images", "done", f"Pulled {images_pulled} missing image(s) from GCR")

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
    compose_timeout = demo.deploy_timeout_seconds or COMPOSE_TIMEOUT
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=compose_timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        running.status = "error"
        running.error_message = f"docker compose up timed out after {compose_timeout}s"
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
            details = "; ".join(
                f"{r.get('node_id','?')}: {r.get('stderr','') or r.get('stdout','') or 'exit code ' + str(r.get('exit_code','?'))}"
                for r in failed_inits
            )
            logger.warning(f"Demo {demo.id}: {len(failed_inits)} init script(s) failed: {details}")
            await progress("init_scripts", "warning", f"{len(failed_inits)} init script(s) failed: {details}")
        else:
            await progress("init_scripts", "done", f"{len(init_results)} init script(s) completed")

        # Register edge automation scripts — site-replication auto-activates, others start paused
        from .edge_automation import generate_edge_scripts
        from ..state.store import EdgeConfigResult
        edge_scripts = generate_edge_scripts(demo, project_name)
        auto_activate = []
        if edge_scripts:
            for script in edge_scripts:
                # Site replication should auto-activate on deploy
                is_site_repl = script.connection_type in ("site-replication", "cluster-site-replication")
                running.edge_configs[script.edge_id] = EdgeConfigResult(
                    edge_id=script.edge_id,
                    connection_type=script.connection_type,
                    status="pending" if is_site_repl else "paused",
                    description=script.description,
                )
                if is_site_repl:
                    auto_activate.append(script)
            state.set_demo(running)
            await progress("edge_config", "done", f"{len(edge_scripts)} connection(s) registered")

        # Auto-activate site replication edges
        for script in auto_activate:
            ec = running.edge_configs[script.edge_id]
            try:
                await progress("edge_config", "running", f"Activating {script.description}...")
                import shlex
                exit_code, stdout, stderr = await exec_in_container(
                    script.container_name, f"sh -c {shlex.quote(script.command)}",
                )
                if exit_code != 0:
                    ec.status = "failed"
                    ec.error = stderr[:500] if stderr else stdout[:500]
                else:
                    ec.status = "applied"
                    ec.error = ""
            except Exception as e:
                ec.status = "failed"
                ec.error = str(e)[:500]
            state.set_demo(running)

        # Post-deploy validation & reconciliation
        await progress("validation", "running", "Running post-deploy validation...")
        from .deploy_validator import validate_and_reconcile
        validation_results = await validate_and_reconcile(demo, project_name, progress)
        errors = [r for r in validation_results if r["status"] == "error"]
        warnings = [r for r in validation_results if r["status"] == "warning"]
        ok_count = len([r for r in validation_results if r["status"] == "ok"])
        summary = f"{ok_count} passed"
        if warnings:
            summary += f", {len(warnings)} warning(s)"
        if errors:
            summary += f", {len(errors)} error(s)"
        await progress("validation", "warning" if errors else "done", f"Validation complete: {summary}")

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

    # Clean up the lock after releasing it (outside the async with block)
    _demo_locks.pop(demo_id, None)


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
