"""Cluster health endpoints — mc admin info, healing status, drive failure simulation."""

from __future__ import annotations

import re
import json
import shlex
import asyncio
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from ..state.store import state
from ..engine.docker_manager import exec_in_container, docker_client
from ..engine.cluster_ec_health import cluster_alias, parse_mc_admin_info
from ..models.demo import DemoCluster
from .demos import _load_demo

logger = logging.getLogger(__name__)
router = APIRouter()


def _cluster_alias(cluster) -> str:
    return cluster_alias(cluster)


def _find_cluster_in_demo(demo, cluster_id: str):
    """Find a DemoCluster by ID."""
    return next((c for c in demo.clusters if c.id == cluster_id), None)


def _parse_admin_info(
    stdout: str,
    cluster: DemoCluster,
    stopped_drives: dict[str, list[int]] | None = None,
) -> dict:
    return parse_mc_admin_info(stdout, cluster, stopped_drives)


def _error_response(cluster_id: str) -> dict:
    return {
        "cluster_id": cluster_id,
        "error": "mc-shell not available",
        "servers": [],
        "drives_online": 0,
        "drives_total": 0,
        "status": "unknown",
    }


# ---------------------------------------------------------------------------
# GET /api/demos/{demo_id}/clusters/{cluster_id}/health
# ---------------------------------------------------------------------------

@router.get("/api/demos/{demo_id}/clusters/{cluster_id}/health")
async def get_cluster_health(demo_id: str, cluster_id: str) -> dict:
    """Return structured health data from mc admin info for a cluster."""
    running = state.get_demo(demo_id)
    if not running or "mc-shell" not in running.containers:
        return _error_response(cluster_id)

    demo = _load_demo(demo_id)
    if not demo:
        return _error_response(cluster_id)

    cluster = _find_cluster_in_demo(demo, cluster_id)
    if not cluster:
        return _error_response(cluster_id)

    alias = _cluster_alias(cluster)
    mc_shell = f"demoforge-{demo_id}-mc-shell"

    try:
        exit_code, stdout, stderr = await exec_in_container(
            mc_shell, f"mc admin info {shlex.quote(alias)} --json"
        )
    except Exception as e:
        logger.warning(f"cluster_health exec failed for {demo_id}/{cluster_id}: {e}")
        return _error_response(cluster_id)

    if exit_code != 0 or not stdout.strip():
        logger.warning(f"mc admin info failed for {demo_id}/{cluster_id}: {stderr[:200]}")
        return _error_response(cluster_id)

    return _parse_admin_info(stdout, cluster, running.stopped_drives)


# ---------------------------------------------------------------------------
# GET /api/demos/{demo_id}/clusters/{cluster_id}/health/quick
# ---------------------------------------------------------------------------

@router.get("/api/demos/{demo_id}/clusters/{cluster_id}/health/quick")
async def get_cluster_health_quick(demo_id: str, cluster_id: str) -> dict:
    """Quick cluster liveness check via MinIO health endpoint."""
    running = state.get_demo(demo_id)
    if not running or "mc-shell" not in running.containers:
        return {"healthy": False, "http_code": 0}

    demo = _load_demo(demo_id)
    if not demo:
        return {"healthy": False, "http_code": 0}

    cluster = _find_cluster_in_demo(demo, cluster_id)
    if not cluster:
        return {"healthy": False, "http_code": 0}

    mc_shell = f"demoforge-{demo_id}-mc-shell"
    project_name = f"demoforge-{demo_id}"
    lb_host = f"{project_name}-{cluster_id}-lb"

    try:
        exit_code, stdout, _ = await exec_in_container(
            mc_shell,
            f'sh -c \'curl -s -o /dev/null -w "%{{http_code}}" http://{lb_host}:80/minio/health/cluster\''
        )
    except Exception as e:
        logger.warning(f"cluster health quick check failed for {demo_id}/{cluster_id}: {e}")
        return {"healthy": False, "http_code": 0}

    http_code = 0
    try:
        http_code = int(stdout.strip())
    except (ValueError, AttributeError):
        pass

    return {"healthy": http_code == 200, "http_code": http_code}


# ---------------------------------------------------------------------------
# GET /api/demos/{demo_id}/clusters/{cluster_id}/healing
# ---------------------------------------------------------------------------

@router.get("/api/demos/{demo_id}/clusters/{cluster_id}/healing")
async def get_cluster_healing(demo_id: str, cluster_id: str) -> dict:
    """Return healing progress from mc admin heal --dry-run."""
    running = state.get_demo(demo_id)
    if not running or "mc-shell" not in running.containers:
        return {"active": False}

    demo = _load_demo(demo_id)
    if not demo:
        return {"active": False}

    cluster = _find_cluster_in_demo(demo, cluster_id)
    if not cluster:
        return {"active": False}

    alias = _cluster_alias(cluster)
    mc_shell = f"demoforge-{demo_id}-mc-shell"

    try:
        exit_code, stdout, _ = await exec_in_container(
            mc_shell,
            f"mc admin heal {shlex.quote(alias)} --recursive --dry-run --json"
        )
    except Exception as e:
        logger.warning(f"cluster healing check failed for {demo_id}/{cluster_id}: {e}")
        return {"active": False}

    if exit_code != 0 or not stdout.strip():
        return {"active": False}

    objects_total = 0
    objects_healed = 0
    objects_remaining = 0
    found_heal_data = False

    for line in stdout.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        # mc admin heal --json emits lines with "summary" or per-object results
        summary = obj.get("summary", {})
        if summary:
            found_heal_data = True
            objects_total = summary.get("objectsTotal", objects_total)
            objects_healed = summary.get("objectsHealed", objects_healed)
            objects_remaining = objects_total - objects_healed

    if not found_heal_data:
        return {"active": False}

    return {
        "active": objects_remaining > 0,
        "objects_total": objects_total,
        "objects_healed": objects_healed,
        "objects_remaining": objects_remaining,
    }


# ---------------------------------------------------------------------------
# Simulation helpers
# ---------------------------------------------------------------------------

class FailDriveRequest(BaseModel):
    node: str
    drive: str
    force: bool = False


class RestoreDriveRequest(BaseModel):
    node: str
    drive: str


class FailNodeRequest(BaseModel):
    node: str
    force: bool = False


class RestoreNodeRequest(BaseModel):
    node: str


def _container_name_for_node(demo_id: str, cluster_id: str, node: str) -> str:
    """Derive the Docker container name for a minio node in a cluster.

    Cluster nodes are named: demoforge-{demo_id}-{cluster_id}-node-{i}
    The `node` param is the logical name like 'minio1' or the node index name
    like 'node-1'. We accept both 'node-N' and 'minioN' formats.
    """
    project = f"demoforge-{demo_id}"
    # Normalize: "minio1" -> "node-1", "node-1" -> "node-1"
    minio_match = re.match(r'^minio(\d+)$', node)
    node_match = re.match(r'^node-(\d+)$', node)
    if minio_match:
        index = minio_match.group(1)
    elif node_match:
        index = node_match.group(1)
    else:
        # Try to treat as raw suffix
        index = node
    return f"{project}-{cluster_id}-node-{index}"


async def _get_current_offline_drives(demo_id: str, cluster_id: str, ec_parity: int) -> tuple[int, int]:
    """Return (offline_drives, total_drives) by running mc admin info."""
    running = state.get_demo(demo_id)
    if not running or "mc-shell" not in running.containers:
        return 0, 0
    demo = _load_demo(demo_id)
    if not demo:
        return 0, 0
    cluster = _find_cluster_in_demo(demo, cluster_id)
    if not cluster:
        return 0, 0
    alias = _cluster_alias(cluster)
    mc_shell = f"demoforge-{demo_id}-mc-shell"
    try:
        exit_code, stdout, _ = await exec_in_container(
            mc_shell, f"mc admin info {shlex.quote(alias)} --json"
        )
    except Exception:
        return 0, 0
    if exit_code != 0 or not stdout.strip():
        return 0, 0
    health = _parse_admin_info(stdout, cluster, running.stopped_drives)
    offline = health["drives_total"] - health["drives_online"]
    return offline, health["drives_total"]


async def _check_quorum_impact(
    demo_id: str,
    cluster_id: str,
    ec_parity: int,
    additional_offline: int,
) -> Optional[str]:
    """Return a warning string if failing additional_offline drives would exceed parity tolerance."""
    currently_offline, drives_total = await _get_current_offline_drives(demo_id, cluster_id, ec_parity)
    if drives_total == 0:
        return None
    if currently_offline + additional_offline > ec_parity:
        return (
            f"This will exceed EC:{ec_parity} tolerance. "
            f"Currently {currently_offline} drive(s) offline; failing {additional_offline} more "
            f"exceeds parity ({ec_parity}). The cluster will lose write quorum but reads may still work."
        )
    return None


# ---------------------------------------------------------------------------
# POST /api/demos/{demo_id}/clusters/{cluster_id}/simulate/fail-drive
# ---------------------------------------------------------------------------

@router.post("/api/demos/{demo_id}/clusters/{cluster_id}/simulate/fail-drive")
async def simulate_fail_drive(demo_id: str, cluster_id: str, body: FailDriveRequest) -> dict:
    demo = _load_demo(demo_id)
    if not demo:
        raise HTTPException(status_code=404, detail="Demo not found")
    cluster = _find_cluster_in_demo(demo, cluster_id)
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")

    if not body.force:
        warning = await _check_quorum_impact(demo_id, cluster_id, cluster.ec_parity, 1)
        if warning:
            return {"warning": warning, "proceed": False}

    container_name = _container_name_for_node(demo_id, cluster_id, body.node)
    drive_path = body.drive if body.drive.startswith("/") else f"/{body.drive}"
    try:
        c = await asyncio.to_thread(docker_client.containers.get, container_name)
        result = await asyncio.to_thread(c.exec_run, f"chmod 000 {drive_path}")
        if result.exit_code != 0:
            output = result.output.decode() if result.output else ""
            raise HTTPException(status_code=500, detail=f"chmod failed: {output}")
    except HTTPException:
        raise
    except Exception as e:
        if "404" in str(e) or "Not Found" in str(e) or "No such container" in str(e):
            raise HTTPException(status_code=404, detail=f"Container not found: {container_name}")
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "drive_failed", "node": body.node, "drive": body.drive}


# ---------------------------------------------------------------------------
# POST /api/demos/{demo_id}/clusters/{cluster_id}/simulate/restore-drive
# ---------------------------------------------------------------------------

@router.post("/api/demos/{demo_id}/clusters/{cluster_id}/simulate/restore-drive")
async def simulate_restore_drive(demo_id: str, cluster_id: str, body: RestoreDriveRequest) -> dict:
    demo = _load_demo(demo_id)
    if not demo:
        raise HTTPException(status_code=404, detail="Demo not found")
    cluster = _find_cluster_in_demo(demo, cluster_id)
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")

    container_name = _container_name_for_node(demo_id, cluster_id, body.node)
    drive_path = body.drive if body.drive.startswith("/") else f"/{body.drive}"
    try:
        c = await asyncio.to_thread(docker_client.containers.get, container_name)
        result = await asyncio.to_thread(c.exec_run, f"chmod 755 {drive_path}")
        if result.exit_code != 0:
            output = result.output.decode() if result.output else ""
            raise HTTPException(status_code=500, detail=f"chmod failed: {output}")
    except HTTPException:
        raise
    except Exception as e:
        if "404" in str(e) or "Not Found" in str(e) or "No such container" in str(e):
            raise HTTPException(status_code=404, detail=f"Container not found: {container_name}")
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "drive_restored", "node": body.node, "drive": body.drive}


# ---------------------------------------------------------------------------
# POST /api/demos/{demo_id}/clusters/{cluster_id}/simulate/fail-node
# ---------------------------------------------------------------------------

@router.post("/api/demos/{demo_id}/clusters/{cluster_id}/simulate/fail-node")
async def simulate_fail_node(demo_id: str, cluster_id: str, body: FailNodeRequest) -> dict:
    demo = _load_demo(demo_id)
    if not demo:
        raise HTTPException(status_code=404, detail="Demo not found")
    cluster = _find_cluster_in_demo(demo, cluster_id)
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")

    if not body.force:
        # Failing a node counts as drives_per_node additional offline drives
        warning = await _check_quorum_impact(
            demo_id, cluster_id, cluster.ec_parity, cluster.drives_per_node
        )
        if warning:
            return {"warning": warning, "proceed": False}

    container_name = _container_name_for_node(demo_id, cluster_id, body.node)
    try:
        c = await asyncio.to_thread(docker_client.containers.get, container_name)
        await asyncio.to_thread(c.stop)
    except Exception as e:
        if "404" in str(e) or "Not Found" in str(e) or "No such container" in str(e):
            raise HTTPException(status_code=404, detail=f"Container not found: {container_name}")
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "node_stopped", "node": body.node}


# ---------------------------------------------------------------------------
# POST /api/demos/{demo_id}/clusters/{cluster_id}/simulate/restore-node
# ---------------------------------------------------------------------------

@router.post("/api/demos/{demo_id}/clusters/{cluster_id}/simulate/restore-node")
async def simulate_restore_node(demo_id: str, cluster_id: str, body: RestoreNodeRequest) -> dict:
    demo = _load_demo(demo_id)
    if not demo:
        raise HTTPException(status_code=404, detail="Demo not found")
    cluster = _find_cluster_in_demo(demo, cluster_id)
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")

    container_name = _container_name_for_node(demo_id, cluster_id, body.node)
    try:
        c = await asyncio.to_thread(docker_client.containers.get, container_name)
        await asyncio.to_thread(c.start)
    except Exception as e:
        if "404" in str(e) or "Not Found" in str(e) or "No such container" in str(e):
            raise HTTPException(status_code=404, detail=f"Container not found: {container_name}")
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "node_started", "node": body.node}


# ---------------------------------------------------------------------------
# POST /api/demos/{demo_id}/clusters/{cluster_id}/simulate/restore-all
# ---------------------------------------------------------------------------

@router.post("/api/demos/{demo_id}/clusters/{cluster_id}/simulate/restore-all")
async def simulate_restore_all(demo_id: str, cluster_id: str) -> dict:
    demo = _load_demo(demo_id)
    if not demo:
        raise HTTPException(status_code=404, detail="Demo not found")
    cluster = _find_cluster_in_demo(demo, cluster_id)
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")

    restored = []
    for i in range(1, cluster.node_count + 1):
        node_label = f"node-{i}"
        container_name = _container_name_for_node(demo_id, cluster_id, node_label)

        # Restore all drives
        for d in range(1, cluster.drives_per_node + 1):
            drive_path = f"/data{d}"
            try:
                c = await asyncio.to_thread(docker_client.containers.get, container_name)
                await asyncio.to_thread(c.exec_run, f"chmod 755 {drive_path}")
                restored.append(f"minio{i}{drive_path}")
            except Exception:
                pass  # Container may not exist or drive may not be failed — skip silently

        # Start container if stopped
        try:
            c = await asyncio.to_thread(docker_client.containers.get, container_name)
            if c.status != "running":
                await asyncio.to_thread(c.start)
                restored.append(f"minio{i} (node)")
        except Exception:
            pass

    return {"restored": restored}
