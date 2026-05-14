"""
MCP proxy: forwards MCP protocol requests from the frontend to MCP sidecar
containers running inside Docker (StreamableHTTP on port 8090, endpoint /mcp).

The MCP StreamableHTTP protocol requires:
1. An `initialize` handshake that returns a `Mcp-Session-Id` header
2. All subsequent requests must include that session ID header

Routes:
  POST /api/demos/{demo_id}/minio/{cluster_id}/mcp/tools/list
  POST /api/demos/{demo_id}/minio/{cluster_id}/mcp/tools/call
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..engine.proxy_gateway import get_http_client
from ..state.store import state

logger = logging.getLogger(__name__)

router = APIRouter()

# Cache of MCP sessions: container_name -> session_id
_sessions: dict[str, str] = {}


class ToolCallRequest(BaseModel):
    tool_name: str
    arguments: dict[str, Any] = {}


def _mcp_url(container_name: str) -> str:
    return f"http://{container_name}:8090/mcp"


def _resolve_mcp_container(demo_id: str, cluster_id: str) -> str:
    """Return the container_name for the MCP sidecar, or raise HTTPException."""
    running = state.get_demo(demo_id)
    if not running:
        raise HTTPException(404, "Demo not running")

    node_id = f"{cluster_id}-mcp"
    container_info = running.containers.get(node_id)
    if not container_info:
        raise HTTPException(
            404,
            f"MCP sidecar '{node_id}' not found — ensure the demo includes a MinIO component '{cluster_id}'",
        )
    return container_info.container_name


async def _ensure_session(container_name: str) -> str:
    """Send the MCP initialize handshake and return the session ID."""
    if container_name in _sessions:
        return _sessions[container_name]

    client = get_http_client()
    payload = {
        "jsonrpc": "2.0",
        "id": 0,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "demoforge-proxy", "version": "1.0"},
        },
    }
    url = _mcp_url(container_name)
    try:
        resp = await client.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise HTTPException(502, f"MCP initialize failed: {e.response.status_code}")
    except httpx.RequestError as e:
        raise HTTPException(502, f"MCP sidecar unreachable: {e}")

    session_id = resp.headers.get("mcp-session-id", "")
    if not session_id:
        raise HTTPException(502, "MCP server did not return a session ID")

    _sessions[container_name] = session_id
    logger.info(f"MCP session established for {container_name}: {session_id[:20]}...")
    return session_id


async def _mcp_request(container_name: str, payload: dict) -> Any:
    """Send a JSON-RPC request to the MCP sidecar and return the result."""
    session_id = await _ensure_session(container_name)

    client = get_http_client()
    url = _mcp_url(container_name)
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Mcp-Session-Id": session_id,
    }
    try:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        # Session may have expired — retry with fresh session
        if e.response.status_code == 400 and "session" in e.response.text.lower():
            _sessions.pop(container_name, None)
            session_id = await _ensure_session(container_name)
            headers["Mcp-Session-Id"] = session_id
            try:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
            except httpx.HTTPStatusError as e2:
                raise HTTPException(502, f"MCP request failed after session refresh: {e2.response.status_code}")
        else:
            raise HTTPException(502, f"MCP request failed: {e.response.status_code} {e.response.text[:200]}")
    except httpx.RequestError as e:
        raise HTTPException(502, f"MCP sidecar unreachable: {e}")

    data = resp.json()
    if "error" in data:
        raise HTTPException(500, f"MCP error: {data['error']}")
    return data.get("result")


@router.post("/api/demos/{demo_id}/minio/{cluster_id}/mcp/tools/list")
async def mcp_tools_list(demo_id: str, cluster_id: str):
    """Return the list of tools available from the MCP sidecar."""
    container_name = _resolve_mcp_container(demo_id, cluster_id)
    result = await _mcp_request(
        container_name,
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    return result


@router.post("/api/demos/{demo_id}/minio/{cluster_id}/mcp/tools/call")
async def mcp_tools_call(demo_id: str, cluster_id: str, req: ToolCallRequest):
    """Call a specific MCP tool and return its result."""
    container_name = _resolve_mcp_container(demo_id, cluster_id)
    result = await _mcp_request(
        container_name,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": req.tool_name, "arguments": req.arguments},
        },
    )
    return {"result": result}
