"""Background task that polls container health and reconciles state every 5 seconds."""
import asyncio
import logging
from ..state.store import state
from .docker_manager import get_container_health
from ..models.api_models import ContainerHealthStatus

logger = logging.getLogger(__name__)


async def health_monitor_loop():
    """Run forever, updating container health and reconciling state."""
    while True:
        try:
            for demo in state.list_demos():
                if demo.status not in ("running", "error"):
                    continue

                all_stopped = True
                stale_nodes = []

                for node_id, container in demo.containers.items():
                    health = await get_container_health(container.container_name)
                    container.health = health
                    if health == ContainerHealthStatus.STOPPED:
                        stale_nodes.append(node_id)
                    else:
                        all_stopped = False

                # If all containers are stopped, mark demo as stopped
                if demo.status == "running" and demo.containers and all_stopped:
                    logger.warning(f"Health reconciler: all containers for demo {demo.demo_id} are stopped — marking demo stopped")
                    demo.status = "stopped"

        except Exception as e:
            logger.warning(f"Health monitor error: {e}")

        await asyncio.sleep(5)
