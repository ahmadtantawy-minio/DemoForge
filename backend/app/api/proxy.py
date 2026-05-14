"""Reverse proxy route: /proxy/{demo_id}/{node_id}/{ui_name}/{path:path}"""

from __future__ import annotations

# SPA recovery HTML — returned when the browser navigates to a Superset SPA path
# directly (e.g. after React Router pushState strips the proxy prefix from the URL
# and the user refreshes). Reads sessionStorage._dfproxy (set by the injected JS
# on first proxy load) and immediately redirects back through the correct proxy URL.
_SPA_RECOVERY_HTML = """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>DemoForge — Redirecting\u2026</title>
<style>body{font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;background:#f5f5f5}
.box{text-align:center;padding:2rem;background:#fff;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,.1)}</style>
<script>
(function(){
  var proxy = sessionStorage.getItem('_dfproxy');
  if (proxy) {
    var target = proxy + window.location.pathname + window.location.search + window.location.hash;
    window.location.replace(target);
  }
})();
</script>
</head>
<body>
<div class="box">
  <h2>\u23f3 Session not found</h2>
  <p>Navigate to your demo to open this panel, or <a href="/">return to DemoForge</a>.</p>
</div>
</body>
</html>"""
import asyncio
import logging
import httpx
import websockets
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from ..engine.proxy_gateway import forward_request, resolve_target

logger = logging.getLogger(__name__)
router = APIRouter()


async def _forward_or_error(request: Request, demo_id: str, node_id: str, ui_name: str, subpath: str):
    try:
        return await forward_request(request, demo_id, node_id, ui_name, subpath)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Component UI unreachable (is the demo running and is this backend on the demo Docker network?): {e}",
        ) from e


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
    return await _forward_or_error(request, demo_id, node_id, ui_name, subpath)

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
    return await _forward_or_error(request, demo_id, node_id, ui_name, "")


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

    # Forward cookies / Origin / subprotocols — MinIO Console validates these on upgrade.
    extra_headers: dict[str, str] = {}
    cookies = websocket.headers.get("cookie", "")
    if cookies:
        extra_headers["Cookie"] = cookies
    origin = websocket.headers.get("origin")

    sec_proto = websocket.headers.get("sec-websocket-protocol", "").strip()
    subprotocols: list[str] | None = None
    if sec_proto:
        subprotocols = [p.strip() for p in sec_proto.split(",") if p.strip()]

    connect_kwargs: dict = {
        "additional_headers": extra_headers if extra_headers else None,
        "ping_interval": None,
        "open_timeout": 30,
    }
    if origin:
        connect_kwargs["origin"] = origin
    if subprotocols:
        connect_kwargs["subprotocols"] = subprotocols

    try:
        async with websockets.connect(target_url, **connect_kwargs) as upstream_ws:
            async def client_to_upstream():
                try:
                    while True:
                        msg = await websocket.receive()
                        if msg["type"] == "websocket.disconnect":
                            break
                        if msg["type"] != "websocket.receive":
                            continue
                        if "bytes" in msg:
                            await upstream_ws.send(msg["bytes"])
                        elif "text" in msg:
                            await upstream_ws.send(msg["text"])
                except WebSocketDisconnect:
                    pass
                except Exception:
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
    except Exception as e:
        logger.warning("WebSocket proxy failed (target=%s): %s", target_url, e)
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# Catch-all for Superset SPA paths that escape the proxy after React Router
# strips the proxy prefix via history.replaceState / pushState.
# Returns a recovery page that reads sessionStorage._dfproxy (set by the proxy's
# injected JS) and immediately redirects back through the correct proxy URL.
from fastapi.responses import HTMLResponse

_SPA_PATHS = [
    "/superset/{path:path}",
    "/dashboard/{path:path}",
    "/chart/{path:path}",
    "/dataset/{path:path}",
    "/explore/{path:path}",
    "/tablemodelview/{path:path}",
    "/databaseview/{path:path}",
    "/savedqueryview/{path:path}",
    "/login",
    "/login/",
    "/logout",
    "/logout/",
]

for _spa_path in _SPA_PATHS:
    @router.get(_spa_path, response_class=HTMLResponse, include_in_schema=False)
    async def _spa_recovery(request: Request) -> HTMLResponse:
        return HTMLResponse(content=_SPA_RECOVERY_HTML, status_code=200)
