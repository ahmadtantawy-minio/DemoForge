"""Reverse proxy route: /proxy/{demo_id}/{node_id}/{ui_name}/{path:path}"""
import asyncio
import websockets
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from ..engine.proxy_gateway import forward_request, resolve_target

router = APIRouter()

@router.api_route(
    "/proxy/{demo_id}/{node_id}/{ui_name}/{subpath:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
)
async def proxy_handler(
    request: Request,
    demo_id: str,
    node_id: str,
    ui_name: str,
    subpath: str = "",
):
    return await forward_request(request, demo_id, node_id, ui_name, subpath)

# Also handle the root path (no subpath)
@router.api_route(
    "/proxy/{demo_id}/{node_id}/{ui_name}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
)
async def proxy_handler_root(
    request: Request,
    demo_id: str,
    node_id: str,
    ui_name: str,
):
    return await forward_request(request, demo_id, node_id, ui_name, "")


# WebSocket proxy — relay WS connections through to upstream containers
@router.websocket("/proxy/{demo_id}/{node_id}/{ui_name}/{subpath:path}")
async def proxy_ws_handler(
    websocket: WebSocket,
    demo_id: str,
    node_id: str,
    ui_name: str,
    subpath: str = "",
):
    base_url, ui_base_path = resolve_target(demo_id, node_id, ui_name)
    # Convert http:// to ws://
    ws_base = base_url.replace("http://", "ws://").replace("https://", "wss://")
    target_path = f"{ui_base_path.rstrip('/')}/{subpath}" if subpath else ui_base_path
    target_url = f"{ws_base}{target_path}"

    # Forward query params
    if websocket.url.query:
        target_url += f"?{websocket.url.query}"

    await websocket.accept()

    # Forward cookies from the client to upstream
    cookies = websocket.headers.get("cookie", "")
    extra_headers = {}
    if cookies:
        extra_headers["Cookie"] = cookies

    try:
        async with websockets.connect(
            target_url,
            additional_headers=extra_headers,
            ping_interval=None,
        ) as upstream_ws:
            async def client_to_upstream():
                try:
                    while True:
                        data = await websocket.receive_text()
                        await upstream_ws.send(data)
                except (WebSocketDisconnect, Exception):
                    pass

            async def upstream_to_client():
                try:
                    async for message in upstream_ws:
                        if isinstance(message, bytes):
                            await websocket.send_bytes(message)
                        else:
                            await websocket.send_text(message)
                except (WebSocketDisconnect, Exception):
                    pass

            await asyncio.gather(client_to_upstream(), upstream_to_client())
    except Exception:
        pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
