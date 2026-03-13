from fastapi import APIRouter, HTTPException
from ..state.store import state
from ..engine.docker_manager import get_container_health

router = APIRouter()

@router.get("/api/demos/{demo_id}/instances/{node_id}/health")
async def get_health(demo_id: str, node_id: str):
    running = state.get_demo(demo_id)
    if not running or node_id not in running.containers:
        raise HTTPException(404, "Instance not found")
    container = running.containers[node_id]
    health = get_container_health(container.container_name)
    return {"node_id": node_id, "health": health.value}
