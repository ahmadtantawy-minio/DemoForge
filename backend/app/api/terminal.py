from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from ..state.store import state
from ..registry.loader import get_component
from ..engine.terminal_bridge import terminal_session

router = APIRouter()

@router.websocket("/api/demos/{demo_id}/instances/{node_id}/terminal")
async def terminal_endpoint(websocket: WebSocket, demo_id: str, node_id: str):
    running = state.get_demo(demo_id)
    if not running or node_id not in running.containers:
        await websocket.close(code=4004, reason="Instance not found")
        return

    container = running.containers[node_id]
    manifest = get_component(container.component_id)
    shell = manifest.terminal.shell if manifest else "/bin/sh"

    await terminal_session(websocket, container.container_name, shell)
