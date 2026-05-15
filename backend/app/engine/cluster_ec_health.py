"""Shared MinIO cluster EC / quorum status from ``mc admin info`` (used by API + instances poll)."""

from __future__ import annotations

import json
import logging
import re
import shlex
from urllib.parse import urlparse

import httpx

from ..models.demo import DemoCluster
from ..state.store import RunningDemo
from .docker_manager import exec_in_container
from .minio_ec_parity_normalize import (
    cluster_ec_status_from_online_matrix,
    compute_pool_erasure_stats,
    worst_cluster_ec_status,
)

logger = logging.getLogger(__name__)

ClusterSummaryStatus = str  # healthy | degraded | quorum_lost | unreachable | unknown


def cluster_alias(cluster: DemoCluster) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", cluster.label)


def _hostname_from_endpoint(endpoint: str) -> str:
    try:
        url = endpoint if "://" in endpoint else f"http://{endpoint}"
        return urlparse(url).hostname or endpoint
    except Exception:
        return endpoint.split(":")[0]


def _endpoint_sort_key(endpoint: str, cluster_id: str) -> tuple[int, str]:
    hostname = _hostname_from_endpoint(endpoint)
    prefix = f"minio-{cluster_id.replace('-', '')}"
    if hostname.startswith(prefix):
        suffix = hostname[len(prefix) :]
        if suffix.isdigit():
            return int(suffix), hostname
    m = re.search(r"(\d+)$", hostname)
    if m:
        return int(m.group(1)), hostname
    return 0, hostname


def _drive_sort_key(path: str) -> int:
    m = re.search(r"data(\d+)", path, re.I)
    return int(m.group(1)) if m else 0


def _servers_to_online_matrix(servers: list[dict], drives_per_node: int) -> list[list[bool]]:
    matrix: list[list[bool]] = []
    for srv in servers:
        drives = sorted(srv.get("drives", []), key=lambda d: _drive_sort_key(d.get("path", "")))
        row = [d.get("state") == "ok" for d in drives]
        if drives_per_node > 0:
            if len(row) < drives_per_node:
                row.extend([False] * (drives_per_node - len(row)))
            elif len(row) > drives_per_node:
                row = row[:drives_per_node]
        matrix.append(row)
    return matrix


def _apply_stopped_drives_to_matrix(
    matrix: list[list[bool]],
    cluster_id: str,
    pool_idx: int,
    stopped_drives: dict[str, list[int]] | None,
) -> None:
    """Overlay DemoForge simulated drive failures (chmod) onto the mc drive matrix."""
    if not stopped_drives:
        return
    for row_idx, row in enumerate(matrix):
        node_id = f"{cluster_id}-pool{pool_idx}-node-{row_idx + 1}"
        for drive_num in stopped_drives.get(node_id, []):
            slot = drive_num - 1
            if 0 <= slot < len(row):
                row[slot] = False


def cluster_ec_status_from_servers(
    servers: list[dict],
    cluster: DemoCluster,
    stopped_drives: dict[str, list[int]] | None = None,
) -> tuple[str, int]:
    sorted_srv = sorted(servers, key=lambda s: _endpoint_sort_key(s.get("endpoint", ""), cluster.id))
    pools = cluster.get_pools()
    offset = 0
    statuses: list[str] = []
    erasure_sets = 0
    for pool_idx, pool in enumerate(pools, start=1):
        pool_servers = sorted_srv[offset : offset + pool.node_count]
        offset += pool.node_count
        if len(pool_servers) != pool.node_count:
            continue
        matrix = _servers_to_online_matrix(pool_servers, pool.drives_per_node)
        _apply_stopped_drives_to_matrix(matrix, cluster.id, pool_idx, stopped_drives)
        statuses.append(
            cluster_ec_status_from_online_matrix(
                matrix, pool.ec_parity, pool.erasure_stripe_drives
            )
        )
        erasure_sets += compute_pool_erasure_stats(
            pool.node_count,
            pool.drives_per_node,
            pool.ec_parity,
            pool.erasure_stripe_drives,
        )["num_sets"]
    if not statuses:
        matrix = _servers_to_online_matrix(sorted_srv, cluster.drives_per_node)
        _apply_stopped_drives_to_matrix(matrix, cluster.id, 1, stopped_drives)
        statuses.append(
            cluster_ec_status_from_online_matrix(matrix, cluster.ec_parity, None)
        )
        erasure_sets = compute_pool_erasure_stats(
            len(matrix), len(matrix[0]) if matrix else 0, cluster.ec_parity, None
        )["num_sets"]
    return worst_cluster_ec_status(statuses), max(1, erasure_sets)


def _overlay_stopped_drives_on_servers(
    servers: list[dict],
    cluster: DemoCluster,
    stopped_drives: dict[str, list[int]] | None,
) -> tuple[int, int]:
    """Apply DemoForge ``stopped_drives`` to parsed mc servers; return (online, total)."""
    if not servers:
        return 0, 0
    sorted_srv = sorted(servers, key=lambda s: _endpoint_sort_key(s.get("endpoint", ""), cluster.id))
    pools = cluster.get_pools()
    offset = 0
    online = 0
    total = 0
    for pool_idx, pool in enumerate(pools, start=1):
        chunk = sorted_srv[offset : offset + pool.node_count]
        offset += pool.node_count
        for row_idx, srv in enumerate(chunk):
            node_id = f"{cluster.id}-pool{pool_idx}-node-{row_idx + 1}"
            stopped_set = set(stopped_drives.get(node_id, [])) if stopped_drives else set()
            for drive in sorted(srv.get("drives", []), key=lambda d: _drive_sort_key(d.get("path", ""))):
                total += 1
                drive_num = _drive_sort_key(drive.get("path", "")) or total
                if drive_num in stopped_set:
                    drive["state"] = "offline"
                if drive.get("state") == "ok":
                    online += 1
    if total == 0:
        for srv in servers:
            for drive in srv.get("drives", []):
                total += 1
                if drive.get("state") == "ok":
                    online += 1
    return online, total


def parse_mc_admin_info(
    stdout: str,
    cluster: DemoCluster,
    stopped_drives: dict[str, list[int]] | None = None,
) -> dict:
    """Parse ``mc admin info --json`` into structured health (status uses per-stripe quorum)."""
    servers = []

    for line in stdout.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        info = obj.get("info", obj)
        for srv in info.get("servers", []):
            drive_list = []
            for d in srv.get("drives", []):
                d_state = d.get("state", "offline")
                drive_list.append({
                    "path": d.get("path", ""),
                    "state": d_state,
                    "used": d.get("usedSpace", 0),
                    "total": d.get("totalSpace", 0),
                })

            network_raw = srv.get("network", {})
            servers.append({
                "endpoint": srv.get("endpoint", ""),
                "state": srv.get("state", "offline"),
                "uptime": srv.get("uptime", 0),
                "drives": drive_list,
                "network": {
                    "online": network_raw.get("online", 0),
                    "total": network_raw.get("total", 0),
                },
            })

    drives_online, drives_total = _overlay_stopped_drives_on_servers(servers, cluster, stopped_drives)

    if drives_total == 0:
        status = "unknown"
        erasure_sets = 1
    else:
        status, erasure_sets = cluster_ec_status_from_servers(servers, cluster, stopped_drives)

    return {
        "cluster_id": cluster.id,
        "ec_parity": cluster.ec_parity,
        "servers": servers,
        "drives_online": drives_online,
        "drives_total": drives_total,
        "erasure_sets": erasure_sets,
        "status": status,
    }


async def fetch_mc_cluster_status(
    demo_id: str,
    cluster: DemoCluster,
    running: RunningDemo,
) -> str | None:
    """Run ``mc admin info`` and return healthy | degraded | quorum_lost, or None if unavailable."""
    if "mc-shell" not in running.containers:
        return None
    mc_shell = running.containers["mc-shell"].container_name
    alias = cluster_alias(cluster)
    try:
        exit_code, stdout, stderr = await exec_in_container(
            mc_shell, f"mc admin info {shlex.quote(alias)} --json"
        )
    except Exception as exc:
        logger.debug("mc admin info failed for %s/%s: %s", demo_id, cluster.id, exc)
        return None
    if exit_code != 0 or not stdout.strip():
        logger.debug(
            "mc admin info non-zero for %s/%s: %s",
            demo_id,
            cluster.id,
            (stderr or "")[:200],
        )
        return None
    parsed = parse_mc_admin_info(stdout, cluster, running.stopped_drives)
    status = parsed.get("status", "unknown")
    return status if status in ("healthy", "degraded", "quorum_lost") else None


async def _l3_cluster_status(
    cluster_id: str,
    project_name: str,
    http_client: httpx.AsyncClient,
) -> str:
    lb_host = f"{project_name}-{cluster_id}-lb"
    try:
        resp = await http_client.get(
            f"http://{lb_host}:80/minio/health/cluster",
            timeout=httpx.Timeout(3.0),
        )
        return "healthy" if resp.status_code == 200 else "degraded"
    except Exception:
        return "unreachable"


async def resolve_cluster_health_for_instances(
    demo_id: str,
    cluster: DemoCluster,
    running: RunningDemo,
    http_client: httpx.AsyncClient,
) -> ClusterSummaryStatus:
    """Cluster badge status for canvas: prefer ``mc admin info`` per-stripe quorum, else L3 HTTP."""
    prefix = f"{cluster.id}-"
    user_stopped = sum(1 for nid in running.user_stopped_nodes if nid.startswith(prefix))

    mc_status = await fetch_mc_cluster_status(demo_id, cluster, running)
    if mc_status:
        if user_stopped > 0 and mc_status == "healthy":
            return "degraded"
        return mc_status

    project_name = f"demoforge-{demo_id}"
    l3_status = await _l3_cluster_status(cluster.id, project_name, http_client)
    if user_stopped > 0 and l3_status == "healthy":
        return "degraded"
    return l3_status
