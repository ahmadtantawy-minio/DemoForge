"""Post-deploy init script runner."""
import asyncio
import logging
from ..registry.loader import get_component
from ..state.store import RunningDemo
from .docker_manager import exec_in_container, get_container_health
from ..models.api_models import ContainerHealthStatus

logger = logging.getLogger(__name__)


async def wait_for_healthy(container_name: str, timeout: int = 60) -> bool:
    elapsed = 0
    while elapsed < timeout:
        health = await get_container_health(container_name)
        if health == ContainerHealthStatus.HEALTHY:
            return True
        if health in (ContainerHealthStatus.ERROR, ContainerHealthStatus.STOPPED):
            return False
        await asyncio.sleep(2)
        elapsed += 2
    return False


async def _run_node_scripts(node_id: str, container_name: str, scripts: list, on_progress=None) -> list[dict]:
    """Run init scripts for a single node sequentially."""
    results = []
    for script in scripts:
        desc = script.description or script.command[:60]
        if script.wait_for_healthy:
            if on_progress:
                await on_progress("init_scripts", "running", f"{node_id}: waiting for healthy ({desc})")
            healthy = await wait_for_healthy(container_name, script.timeout)
            if not healthy:
                if on_progress:
                    await on_progress("init_scripts", "running", f"{node_id}: timed out waiting for healthy")
                results.append({
                    "node_id": node_id, "script": script.command,
                    "exit_code": -1, "stdout": "", "stderr": "Timed out waiting for healthy"
                })
                continue
        if on_progress:
            await on_progress("init_scripts", "running", f"{node_id}: {desc}")
        exit_code, stdout, stderr = await exec_in_container(container_name, script.command)
        logger.info(f"Init script on {node_id}: exit={exit_code}")
        results.append({
            "node_id": node_id, "script": script.command,
            "exit_code": exit_code, "stdout": stdout, "stderr": stderr,
        })
    return results


async def _run_node_scripts_with_timeout(
    node_id: str, container_name: str, scripts: list, timeout_s: float = 120.0, on_progress=None
) -> dict:
    """Run init scripts for a single node with an overall timeout."""
    try:
        results = await asyncio.wait_for(
            _run_node_scripts(node_id, container_name, scripts, on_progress),
            timeout=timeout_s,
        )
        return {"node_id": node_id, "timed_out": False, "results": results}
    except asyncio.TimeoutError:
        logger.error(f"Init scripts timed out after {timeout_s}s for node {node_id}")
        return {"node_id": node_id, "timed_out": True, "results": []}


async def run_init_scripts(demo: RunningDemo, on_progress=None) -> list[dict]:
    """Run init scripts for all nodes in parallel.

    Returns a list of per-node dicts:
        {"node_id": str, "timed_out": bool, "results": list[dict]}
    """
    # Group scripts by node_id, keeping intra-node order
    node_tasks: dict[str, tuple[str, list, float]] = {}
    for node_id, container in demo.containers.items():
        manifest = get_component(container.component_id)
        if not manifest or not manifest.init_scripts:
            continue
        scripts = sorted(manifest.init_scripts, key=lambda s: s.order)
        # Per-node timeout = max of individual script timeouts, minimum 120s
        node_timeout = max(max((s.timeout for s in scripts if s.timeout), default=0), 120.0)
        node_tasks[node_id] = (container.container_name, scripts, node_timeout)

    # Run each node's scripts in parallel across nodes
    per_node_results = await asyncio.gather(
        *[_run_node_scripts_with_timeout(node_id, container_name, scripts, timeout_s, on_progress)
          for node_id, (container_name, scripts, timeout_s) in node_tasks.items()]
    )

    return list(per_node_results)
