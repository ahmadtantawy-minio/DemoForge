"""Failover status: checks which upstream the NGINX failover gateway is routing to."""
import logging
import socket
import httpx
from fastapi import APIRouter, HTTPException
from ..state.store import state

logger = logging.getLogger(__name__)
router = APIRouter()


def _resolve_upstream_to_node(demo_id: str, upstream_addr: str, containers: dict) -> str:
    """Resolve an upstream IP:port address back to a node_id.

    NGINX $upstream_addr returns the resolved IP (e.g. '192.168.117.2:80').
    We resolve each container name to its IP to find the matching node.
    """
    if not upstream_addr:
        return ""
    ip = upstream_addr.split(":")[0]
    prefix = f"demoforge-{demo_id}-"
    for node_id, container in containers.items():
        try:
            container_ip = socket.gethostbyname(container.container_name)
            if container_ip == ip:
                return node_id
        except (socket.gaierror, OSError):
            continue
    return upstream_addr


@router.get("/api/demos/{demo_id}/failover-status")
async def get_failover_status(demo_id: str):
    """Check which upstream the failover gateway is currently routing to.

    Probes the gateway with a HEAD request to / and reads the X-Upstream-Server header.
    Returns which edges are active vs standby.
    """
    running = state.get_demo(demo_id)
    if not running:
        raise HTTPException(404, "Demo not running")

    # Find failover gateway containers (nginx with failover-proxy variant)
    results = []
    for node_id, container in running.containers.items():
        if container.component_id != "nginx":
            continue
        container_name = container.container_name
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                # Probe / (not /health) to go through the proxy and get X-Upstream-Server
                resp = await client.head(f"http://{container_name}:80/")
                upstream_addr = resp.headers.get("x-upstream-server", "")
                # Resolve IP back to node_id for frontend matching
                active = _resolve_upstream_to_node(demo_id, upstream_addr, running.containers)
                results.append({
                    "gateway": node_id,
                    "active_upstream": active,
                    "healthy": resp.status_code < 500,
                })
        except Exception:
            results.append({
                "gateway": node_id,
                "active_upstream": "",
                "healthy": False,
            })

    return {"demo_id": demo_id, "failover": results}
