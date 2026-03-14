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


async def run_init_scripts(demo: RunningDemo) -> list[dict]:
    results = []
    tasks = []
    for node_id, container in demo.containers.items():
        manifest = get_component(container.component_id)
        if not manifest or not manifest.init_scripts:
            continue
        for script in sorted(manifest.init_scripts, key=lambda s: s.order):
            tasks.append((node_id, container.container_name, script))

    for node_id, container_name, script in tasks:
        if script.wait_for_healthy:
            healthy = await wait_for_healthy(container_name, script.timeout)
            if not healthy:
                results.append({
                    "node_id": node_id, "script": script.command,
                    "exit_code": -1, "stdout": "", "stderr": "Timed out waiting for healthy"
                })
                continue
        exit_code, stdout, stderr = await exec_in_container(container_name, script.command)
        logger.info(f"Init script on {node_id}: exit={exit_code}")
        results.append({
            "node_id": node_id, "script": script.command,
            "exit_code": exit_code, "stdout": stdout, "stderr": stderr,
        })
    return results
