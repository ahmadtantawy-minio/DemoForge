"""Docker operations: compose up/down, container inspection."""
import asyncio
import json
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


def _get_cluster_configs_path(data_dir: str, project_name: str) -> str:
    return os.path.join(data_dir, project_name, ".cluster-configs.json")


def _load_cluster_configs(data_dir: str, project_name: str) -> dict:
    """Load previously deployed cluster topology from disk."""
    path = _get_cluster_configs_path(data_dir, project_name)
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_cluster_configs(data_dir: str, project_name: str, clusters) -> None:
    """Persist current cluster topology to disk for next deploy comparison."""
    path = _get_cluster_configs_path(data_dir, project_name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    configs = {}
    for cluster in clusters:
        pools = cluster.get_pools() if hasattr(cluster, "get_pools") else []
        configs[cluster.id] = {
            "node_count": cluster.node_count,
            "drives_per_node": cluster.drives_per_node,
            "component": cluster.component,
            "edition": cluster.config.get("MINIO_EDITION", "ce") if hasattr(cluster, "config") else "ce",
            "pools": [
                {"node_count": p.node_count, "drives_per_node": p.drives_per_node}
                for p in pools
            ],
        }
    with open(path, "w") as f:
        json.dump(configs, f, indent=2)


def _detect_changed_clusters(demo, prev_configs: dict) -> list[str]:
    """Return IDs of clusters whose topology changed since last deploy."""
    changed = []
    for cluster in demo.clusters:
        prev = prev_configs.get(cluster.id)
        if prev is None:
            continue  # New cluster — no stale volumes to clear
        current_edition = cluster.config.get("MINIO_EDITION", "ce") if hasattr(cluster, "config") else "ce"
        pools = cluster.get_pools() if hasattr(cluster, "get_pools") else []
        current_pools = [{"node_count": p.node_count, "drives_per_node": p.drives_per_node} for p in pools]
        prev_pools = prev.get("pools", [])
        topology_changed = current_pools != prev_pools and (current_pools or prev_pools)
        if (
            (not topology_changed and prev["node_count"] != cluster.node_count)
            or (not topology_changed and prev["drives_per_node"] != cluster.drives_per_node)
            or topology_changed
            or prev.get("component", "minio") != cluster.component
            or prev.get("edition", "ce") != current_edition
        ):
            changed.append(cluster.id)
    return changed


async def _remove_cluster_volumes(
    project_name: str,
    cluster_id: str,
    old_pools: list[dict],
    new_pools: list[dict],
) -> list[str]:
    """Remove Docker volumes for a cluster whose topology changed.

    Handles both single-pool ({cluster_id}-node-{i}) and multi-pool
    ({cluster_id}-pool{p}-node-{i}) naming. Removes volumes for both
    old and new configurations so MinIO can reformat on next start.
    """
    candidates = []

    def _add_pool_vols(pools: list[dict]):
        multi = len(pools) > 1
        for p_idx, pool in enumerate(pools, start=1):
            for i in range(1, pool["node_count"] + 1):
                node_id = (
                    f"{cluster_id}-pool{p_idx}-node-{i}" if multi
                    else f"{cluster_id}-node-{i}"
                )
                vol_base = f"{project_name}-{node_id}-data"
                candidates.append(f"{project_name}_{vol_base}")
                candidates.append(vol_base)
                for d in range(1, pool["drives_per_node"] + 1):
                    candidates.append(f"{project_name}_{vol_base}{d}")
                    candidates.append(f"{vol_base}{d}")

    _add_pool_vols(old_pools)
    _add_pool_vols(new_pools)

    def _remove():
        import docker as _docker
        client = _docker.from_env()
        removed = []
        for vol_name in candidates:
            try:
                vol = client.volumes.get(vol_name)
                vol.remove()
                removed.append(vol_name)
            except Exception:
                pass
        client.close()
        return removed

    removed = await asyncio.to_thread(_remove)
    if removed:
        logger.info(
            f"Removed {len(removed)} stale volume(s) for reconfigured cluster '{cluster_id}': {removed}"
        )
    return removed

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
    cmd = ["docker", "compose", "-f", compose_path, "-p", project_name, "down", "--remove-orphans", "--timeout", "30"]
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

    # Load previous cluster topology to detect changes requiring volume reset
    prev_cluster_configs = _load_cluster_configs(data_dir, project_name)
    changed_clusters = _detect_changed_clusters(demo, prev_cluster_configs)
    if changed_clusters:
        logger.info(f"Demo {demo.id}: cluster topology changed for: {changed_clusters}")

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

    # Clean up leftover containers (preserve volumes unless cluster topology changed)
    await progress("cleanup", "running", "Cleaning up previous containers...")
    await _cleanup_demo(demo.id, compose_path, project_name, network_names, remove_volumes=False)

    # Remove volumes for clusters whose topology changed — MinIO erasure sets cannot be resized
    if changed_clusters:
        await progress("cleanup", "running", f"Resetting {len(changed_clusters)} reconfigured cluster(s)...")
        for cluster_id in changed_clusters:
            cluster = next((c for c in demo.clusters if c.id == cluster_id), None)
            prev = prev_cluster_configs[cluster_id]
            if cluster:
                old_pools = prev.get("pools") or [{"node_count": prev["node_count"], "drives_per_node": prev["drives_per_node"]}]
                new_pools = [{"node_count": p.node_count, "drives_per_node": p.drives_per_node} for p in cluster.get_pools()]
                await _remove_cluster_volumes(project_name, cluster_id, old_pools, new_pools)

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
        service_containers = []
        for c in containers:
            if c.labels.get("demoforge.sidecar") == "true":
                continue  # ephemeral run-once sidecars (e.g. metabase-init) — not tracked
            node_id = c.labels.get("demoforge.node", "")
            component_id = c.labels.get("demoforge.component", "")
            running.containers[node_id] = RunningContainer(
                node_id=node_id,
                component_id=component_id,
                container_name=c.name,
                networks=network_names,
            )
            service_containers.append(c)
        await progress("discovery", "done", f"Found {len(service_containers)} service container(s)")

        # Run init scripts after containers are discovered
        await progress("init_scripts", "running", "Running init scripts...")
        from .init_runner import run_init_scripts
        per_node_results = await run_init_scripts(running, on_progress=progress)

        # Update per-container init_status and flatten for legacy init_results
        flat_results = []
        failed_nodes = []
        for node_result in per_node_results:
            nid = node_result.get("node_id")
            timed_out = node_result.get("timed_out", False)
            script_results = node_result.get("results", [])
            flat_results.extend(script_results)
            if nid and nid in running.containers:
                any_failed = any(r.get("exit_code", 0) != 0 for r in script_results)
                if timed_out:
                    running.containers[nid].init_status = "timeout"
                    failed_nodes.append(nid)
                elif any_failed:
                    running.containers[nid].init_status = "failed"
                    failed_nodes.append(nid)
                else:
                    running.containers[nid].init_status = "completed"
        running.init_results = flat_results

        if failed_nodes:
            details = "; ".join(
                f"{nid}: {'timeout' if node_result.get('timed_out') else 'script error'}"
                for node_result in per_node_results
                for nid in [node_result.get("node_id", "?")]
                if nid in failed_nodes
            )
            logger.warning(f"Demo {demo.id}: init scripts failed for node(s): {details}")
            await progress("init_scripts", "warning", f"{len(failed_nodes)} node(s) had init failures: {details}")
        else:
            total = sum(len(r.get("results", [])) for r in per_node_results)
            await progress("init_scripts", "done", f"{total} init script(s) completed")

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

        # Persist cluster topology so next deploy can detect changes
        _save_cluster_configs(data_dir, project_name, demo.clusters)
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


async def stop_demo(demo_id: str, remove_volumes: bool = False):
    """Bring down containers, disconnect from network, clean up.

    Args:
        remove_volumes: If True, also delete Docker volumes (use for destroy, not stop).
    """
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
            remove_volumes=remove_volumes,
        )
        state.remove_demo(demo_id)

    # Clean up the lock after releasing it (outside the async with block)
    _demo_locks.pop(demo_id, None)


async def pause_demo(demo_id: str) -> None:
    """Stop containers without removing them or their volumes (docker compose stop)."""
    lock = _get_lock(demo_id)
    async with lock:
        running = state.get_demo(demo_id)
        if not running or not running.compose_file_path:
            return

        compose_file = running.compose_file_path
        if not os.path.exists(compose_file):
            return

        project_name = running.compose_project
        proc = await asyncio.create_subprocess_exec(
            "docker", "compose", "-f", compose_file, "-p", project_name, "stop",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise TimeoutError(f"docker compose stop timed out after 60s for {demo_id}")
        if proc.returncode != 0:
            raise RuntimeError(f"docker compose stop failed: {stderr.decode()}")


async def resume_demo(demo_id: str) -> None:
    """Start previously stopped containers (docker compose start)."""
    lock = _get_lock(demo_id)
    async with lock:
        running = state.get_demo(demo_id)
        if not running or not running.compose_file_path:
            raise RuntimeError(f"No compose file found for demo {demo_id}")

        compose_file = running.compose_file_path
        if not os.path.exists(compose_file):
            raise RuntimeError(f"Compose file not found for demo {demo_id}: {compose_file}")

        project_name = running.compose_project
        proc = await asyncio.create_subprocess_exec(
            "docker", "compose", "-f", compose_file, "-p", project_name, "start",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise TimeoutError(f"docker compose start timed out after 60s for {demo_id}")
        if proc.returncode != 0:
            raise RuntimeError(f"docker compose start failed: {stderr.decode()}")


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


async def exec_in_container(container_name: str, command: str, timeout: int = 60) -> tuple[int, str, str]:
    """Run a one-shot command in a container. Returns (exit_code, stdout, stderr).
    Raises asyncio.TimeoutError if the command takes longer than `timeout` seconds."""
    try:
        c = await asyncio.to_thread(docker_client.containers.get, container_name)
        result = await asyncio.wait_for(
            asyncio.to_thread(c.exec_run, command, demux=True),
            timeout=timeout,
        )
        stdout = result.output[0].decode() if result.output[0] else ""
        stderr = result.output[1].decode() if result.output[1] else ""
        return result.exit_code, stdout, stderr
    except asyncio.TimeoutError:
        logger.error(f"exec_in_container timed out after {timeout}s: {container_name}: {command[:80]}")
        return -1, "", f"Command timed out after {timeout}s"
    except NotFound:
        raise ValueError(f"Container {container_name} not found")
