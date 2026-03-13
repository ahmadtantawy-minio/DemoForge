"""Background task that polls container health every 5 seconds."""
import asyncio
from ..state.store import state
from .docker_manager import get_container_health

async def health_monitor_loop():
    """Run forever, updating container health in the state store."""
    while True:
        for demo in state.list_demos():
            if demo.status != "running":
                continue
            for node_id, container in demo.containers.items():
                container.health = get_container_health(container.container_name)
        await asyncio.sleep(5)
