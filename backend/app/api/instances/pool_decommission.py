"""Pool decommission and apply-topology endpoints for running MinIO clusters."""
import os
import re

from fastapi import APIRouter, HTTPException

from ..demos import _load_demo, _save_demo
from ...engine import task_manager
from ...engine.docker_manager import apply_saved_demo_topology, exec_in_container
from ...state.store import state

router = APIRouter()


def _parse_mc_decommission_status(stdout: str, stderr: str) -> tuple[str, str]:
    """Map ``mc admin decommission status`` output to UI status + one-line detail.

    Returns (status, detail) where status is ``active`` | ``decommissioning`` | ``decommissioned``.
    """
    text = (stdout or "").strip()
    err_t = (stderr or "").strip()
    blob = f"{text}\n{err_t}".lower()

    detail = ""
    for line in text.splitlines():
        s = line.strip()
        if s:
            detail = s[:500]
            break
    if not detail and text:
        detail = text[:500]

    # Pool not being drained — typical when no work in progress
    if "not decommissioning" in blob or "not being decommissioned" in blob:
        return "active", detail
    if "no active decommission" in blob:
        return "active", detail

    # Finished draining (wording varies by MinIO release)
    if "decommissioning complete" in blob or "decommission complete" in blob:
        return "decommissioned", detail
    if "successfully decommissioned" in blob:
        return "decommissioned", detail
    if "complete" in blob and "decommission" in blob and "not decommissioning" not in blob:
        return "decommissioned", detail

    # In progress
    if "decommissioning" in blob and "complete" not in blob:
        return "decommissioning", detail
    if "decommission" in blob and "in progress" in blob:
        return "decommissioning", detail
    if "draining" in blob or "drain" in blob:
        return "decommissioning", detail

    # Fallback: preserve previous loose behavior
    if "decommissioned" in blob:
        return "decommissioned", detail
    if "decommission" in blob:
        return "decommissioning", detail
    return "active", detail


def _persist_pool_lifecycle(demo_id: str, cluster_id: str, pool_id: str, lifecycle: str) -> None:
    """Persist per-pool lifecycle in the demo YAML (survives refresh / backend restart)."""
    demo = _load_demo(demo_id)
    if not demo:
        return
    cl = next((c for c in demo.clusters if c.id == cluster_id), None)
    if not cl:
        return
    if lifecycle == "idle":
        cl.pool_lifecycle.pop(pool_id, None)
    else:
        cl.pool_lifecycle[pool_id] = lifecycle
    _save_demo(demo)


def _get_mc_shell_and_alias(demo_id: str, cluster_id: str, running):
    """Return (mc_shell_container_name, alias, cluster) for the given cluster.

    Raises HTTPException if mc-shell is not available or cluster not found.
    """
    if "mc-shell" not in running.containers:
        raise HTTPException(404, "mc-shell container not found — redeploy the demo to enable decommission")

    mc_shell = f"demoforge-{demo_id}-mc-shell"

    demo = _load_demo(demo_id)
    if not demo:
        raise HTTPException(404, f"Demo {demo_id} not found on disk")

    cluster = next((c for c in demo.clusters if c.id == cluster_id), None)
    if not cluster:
        raise HTTPException(404, f"Cluster {cluster_id} not found in demo {demo_id}")

    alias = re.sub(r"[^a-zA-Z0-9_]", "_", cluster.label)
    return mc_shell, alias, cluster


def _build_pool_args(demo_id: str, cluster_id: str, pool_id: str, cluster) -> str:
    """Construct the MinIO pool args string for the given pool.

    Format: http://demoforge-{demo_id}-{cluster_id}-pool{N}-node-{1...nodeCount}:9000/mnt/data{1...drivesPerNode}
    """
    pools = cluster.get_pools()
    pool_num = next((i + 1 for i, p in enumerate(pools) if p.id == pool_id), None)
    if pool_num is None:
        raise HTTPException(404, f"Pool {pool_id} not found in cluster {cluster_id}")

    pool = pools[pool_num - 1]
    node_count = pool.node_count
    drives = pool.drives_per_node
    prefix = f"demoforge-{demo_id}-{cluster_id}-pool{pool_num}-node-"

    if node_count == 1:
        node_part = f"http://{prefix}1:9000"
    else:
        node_part = f"http://{prefix}{{1...{node_count}}}:9000"

    if drives == 1:
        drive_part = "/mnt/data1"
    else:
        drive_part = f"/mnt/data{{1...{drives}}}"

    return f"{node_part}{drive_part}"


@router.post("/api/demos/{demo_id}/clusters/{cluster_id}/pools/{pool_id}/decommission")
async def start_pool_decommission(demo_id: str, cluster_id: str, pool_id: str):
    """Start decommissioning a server pool via mc admin decommission start."""
    running = state.get_demo(demo_id)
    if not running:
        raise HTTPException(404, "Demo not running")

    mc_shell, alias, cluster = _get_mc_shell_and_alias(demo_id, cluster_id, running)
    pool_args = _build_pool_args(demo_id, cluster_id, pool_id, cluster)

    exit_code, stdout, stderr = await exec_in_container(
        mc_shell,
        f"mc admin decommission start {alias} '{pool_args}'"
    )
    if exit_code != 0:
        raise HTTPException(500, f"mc admin decommission start failed: {stderr.strip() or stdout.strip()}")

    _persist_pool_lifecycle(demo_id, cluster_id, pool_id, "decommissioning")

    return {"status": "started", "pool_id": pool_id, "output": stdout.strip()}


@router.get("/api/demos/{demo_id}/clusters/{cluster_id}/pools/{pool_id}/decommission/status")
async def get_pool_decommission_status(demo_id: str, cluster_id: str, pool_id: str):
    """Get the decommission status of a server pool."""
    running = state.get_demo(demo_id)
    if not running:
        raise HTTPException(404, "Demo not running")

    mc_shell, alias, cluster = _get_mc_shell_and_alias(demo_id, cluster_id, running)
    pool_args = _build_pool_args(demo_id, cluster_id, pool_id, cluster)

    _exit_code, stdout, stderr = await exec_in_container(
        mc_shell,
        f"mc admin decommission status {alias} '{pool_args}'"
    )

    raw = (stdout or "").strip() or (stderr or "").strip()
    parsed_status, detail = _parse_mc_decommission_status(stdout or "", stderr or "")

    if parsed_status == "decommissioned":
        _persist_pool_lifecycle(demo_id, cluster_id, pool_id, "decommissioned")

    return {"pool_id": pool_id, "raw": raw, "status": parsed_status, "detail": detail}


@router.post("/api/demos/{demo_id}/clusters/{cluster_id}/pools/{pool_id}/decommission/cancel")
async def cancel_pool_decommission(demo_id: str, cluster_id: str, pool_id: str):
    """Cancel an in-progress pool decommission via mc admin decommission cancel."""
    running = state.get_demo(demo_id)
    if not running:
        raise HTTPException(404, "Demo not running")

    mc_shell, alias, cluster = _get_mc_shell_and_alias(demo_id, cluster_id, running)
    pool_args = _build_pool_args(demo_id, cluster_id, pool_id, cluster)

    exit_code, stdout, stderr = await exec_in_container(
        mc_shell,
        f"mc admin decommission cancel {alias} '{pool_args}'"
    )
    if exit_code != 0:
        raise HTTPException(500, f"mc admin decommission cancel failed: {stderr.strip() or stdout.strip()}")

    _persist_pool_lifecycle(demo_id, cluster_id, pool_id, "idle")

    return {"status": "cancelled", "pool_id": pool_id, "output": stdout.strip()}


@router.post("/api/demos/{demo_id}/clusters/{cluster_id}/apply-topology")
async def apply_cluster_topology(demo_id: str, cluster_id: str):
    """Regenerate compose from saved demo YAML and ``docker compose up -d`` (runtime Add Pool).

    Persist the diagram (PUT /diagram) before calling so ``server_pools`` changes are on disk.
    """
    if task_manager.is_operation_running(demo_id):
        raise HTTPException(409, "Another lifecycle operation is in progress for this demo")
    running = state.get_demo(demo_id)
    if not running:
        raise HTTPException(404, "Demo not running")
    if running.status != "running":
        raise HTTPException(400, "Demo must be in running state")
    demo = _load_demo(demo_id)
    if not demo:
        raise HTTPException(404, "Demo not found on disk")
    if not any(c.id == cluster_id for c in (demo.clusters or [])):
        raise HTTPException(404, f"Cluster {cluster_id} not found in demo")

    data_dir = os.environ.get("DEMOFORGE_DATA_DIR", "./data")
    components_dir = os.environ.get("DEMOFORGE_COMPONENTS_DIR", "./components")
    try:
        result = await apply_saved_demo_topology(demo_id, data_dir, components_dir)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except TimeoutError as e:
        raise HTTPException(504, str(e)) from e
    except RuntimeError as e:
        raise HTTPException(500, str(e)) from e
    return {"demo_id": demo_id, "cluster_id": cluster_id, **result}
