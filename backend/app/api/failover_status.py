"""Failover status: checks which upstream the NGINX failover gateway is routing to."""
import logging
import socket
import httpx
from fastapi import APIRouter, HTTPException
from ..state.store import state

logger = logging.getLogger(__name__)
router = APIRouter()


def _resolve_ip_to_cluster(demo_id: str, ip: str, containers: dict) -> str:
    """Resolve an upstream IP back to a cluster/node id.

    Returns the base cluster id (e.g. 'minio-site-b') by stripping the '-lb' or '-node-N'
    suffix from the matched container name so it aligns with the edge targetId.
    """
    if not ip:
        return ""
    import re
    for node_id, container in containers.items():
        try:
            container_ip = socket.gethostbyname(container.container_name)
            if container_ip == ip:
                # Strip -lb / -node-N suffix to get cluster id
                base = re.sub(r"(-lb|-node-\d+)$", "", node_id)
                return base
        except (socket.gaierror, OSError):
            continue
    return ""


@router.get("/api/demos/{demo_id}/failover-status")
async def get_failover_status(demo_id: str):
    """Check which upstream the failover gateway is currently routing to.

    Probes the gateway with a HEAD request to /minio/health/live and reads
    the X-Upstream-Server header. nginx may add multiple values (one per retry);
    we use the last one (= the upstream that actually served the request).
    """
    running = state.get_demo(demo_id)
    if not running:
        raise HTTPException(404, "Demo not running")

    results = []
    for node_id, container in running.containers.items():
        if container.component_id != "nginx":
            continue
        container_name = container.container_name
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.head(f"http://{container_name}:80/minio/health/live")
                # nginx may emit multiple X-Upstream-Server headers (one per retry)
                # The last one is the upstream that actually served the request
                all_upstreams = resp.headers.get_list("x-upstream-server")
                last_upstream = all_upstreams[-1].split(",")[-1].strip() if all_upstreams else ""
                ip = last_upstream.split(":")[0] if last_upstream else ""
                active = _resolve_ip_to_cluster(demo_id, ip, running.containers)
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
