"""Failover status: checks which upstream the NGINX failover gateway is routing to."""
import logging
import httpx
from fastapi import APIRouter, HTTPException
from ..state.store import state

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/demos/{demo_id}/failover-status")
async def get_failover_status(demo_id: str):
    """Check which upstream the failover gateway is currently routing to.

    Probes the gateway with a HEAD request and reads the X-Upstream-Server header.
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
        # Check if this is a failover proxy by probing for /health
        container_name = container.container_name
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.head(f"http://{container_name}:80/health")
                upstream = resp.headers.get("x-upstream-server", "")
                results.append({
                    "gateway": node_id,
                    "active_upstream": upstream,
                    "healthy": resp.status_code == 200,
                })
        except Exception:
            results.append({
                "gateway": node_id,
                "active_upstream": "",
                "healthy": False,
            })

    return {"demo_id": demo_id, "failover": results}
