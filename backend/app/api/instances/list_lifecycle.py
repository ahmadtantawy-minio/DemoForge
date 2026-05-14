from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import asyncio
import base64
import json
import logging
import os
import re
import shlex
import time as time_module
import uuid
import httpx
from ...state.store import state, EdgeConfigResult
from ...registry.loader import get_component
from ...engine.docker_manager import (
    get_container_health,
    restart_container,
    exec_in_container,
    docker_client,
    apply_saved_demo_topology,
)
from ...engine.proxy_gateway import get_http_client
from ...engine.edge_automation import (
    generate_edge_scripts, _get_credential, _safe, _find_cluster,
    _get_cluster_credentials, _resolve_cluster_endpoint,
)
from ...engine.compose_generator import generate_compose
from ...models.api_models import (
    InstancesResponse, ContainerInstance, WebUILink,
    ExecRequest, ExecResponse, NetworkMembership, CredentialInfo,
    EdgeConfigStatus, ExecLogRequest, LogResponse,
    ExternalSystemOnDemandMetaResponse, ExternalSystemOnDemandDataset,
    ExternalSystemOnDemandTriggerRequest,
)
from ..demos import _load_demo, _save_demo
from ..iam_reconcile_report import mc_shell_iam_integration_events_from_logs
from ...engine import task_manager
from .helpers import (
    _repl_cache,
    _resolve_components_dir,
    append_demo_integration_audit,
    _load_demo_integration_audit,
    _metabase_dashboard_rows,
    _check_live_replication_status,
    _build_replication_state_cmd,
    _expand_demo_for_edges,
    _get_first_cluster_alias,
    _external_system_on_demand_meta_dict,
    _METABASE_CHART_MAP,
    _build_superset_position_json,
    _build_superset_dashboard_specs,
)

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/api/demos/{demo_id}/instances", response_model=InstancesResponse)
async def list_instances(demo_id: str):
    running = state.get_demo(demo_id)
    if not running:
        raise HTTPException(404, "Demo not running")

    demo = _load_demo(demo_id)

    # Check cluster health FIRST so we can use it to override per-node Docker health.
    # The /minio/health/cluster endpoint is authoritative: if it returns 200, the cluster
    # is fully operational even if Docker's container healthcheck transiently reports unhealthy.
    cluster_health: dict[str, str] = {}
    cluster_node_health_override: dict[str, str] = {}
    if demo and demo.clusters:
        project_name = f"demoforge-{demo_id}"
        async_client = get_http_client()
        async def _check_cluster_early(cluster_id: str) -> tuple[str, str]:
            lb_host = f"{project_name}-{cluster_id}-lb"
            try:
                resp = await async_client.get(
                    f"http://{lb_host}:80/minio/health/cluster",
                    timeout=httpx.Timeout(3.0),
                )
                return cluster_id, "healthy" if resp.status_code == 200 else "degraded"
            except Exception:
                return cluster_id, "unreachable"
        results = await asyncio.gather(*[_check_cluster_early(c.id) for c in demo.clusters])
        cluster_health = dict(results)
        # Override cluster health with stopped_drives as authoritative source.
        # MinIO may not immediately report chmod'd drives as offline, so if we
        # have recorded stopped drives for any node in the cluster, force "degraded".
        for cluster in demo.clusters:
            stopped_count = sum(
                len(drives)
                for node_id, drives in running.stopped_drives.items()
                if node_id.startswith(f"{cluster.id}-")
            )
            if stopped_count > 0:
                cluster_health[cluster.id] = "degraded"
        # If cluster is healthy, all its nodes are healthy regardless of Docker healthcheck status.
        # This prevents false "error" badges when MinIO is up but Docker healthcheck is slow/transient.
        for cluster in demo.clusters:
            if cluster_health.get(cluster.id) == "healthy":
                for p_idx, pool in enumerate(cluster.get_pools(), start=1):
                    for i in range(1, pool.node_count + 1):
                        cluster_node_health_override[f"{cluster.id}-pool{p_idx}-node-{i}"] = "healthy"

    instances = []
    for node_id, container in running.containers.items():
        manifest = get_component(container.component_id) if not container.is_sidecar else None
        docker_health = await get_container_health(container.container_name)
        # Use cluster-level health override if available (cluster health endpoint is authoritative)
        health = cluster_node_health_override.get(node_id, docker_health)
        container.health = health  # Update cache

        web_uis = []
        if manifest:
            for ui in manifest.web_ui:
                web_uis.append(WebUILink(
                    name=ui.name,
                    proxy_url=f"/proxy/{demo_id}/{node_id}/{ui.name}/",
                    description=ui.description,
                ))

        quick_actions = []
        if manifest:
            quick_actions = [qa.model_dump() for qa in manifest.terminal.quick_actions]

        # Populate networks from RunningContainer and demo node config
        network_memberships = []
        node_networks = {}
        if demo:
            demo_node = next((n for n in demo.nodes if n.id == node_id), None)
            if demo_node:
                node_networks = demo_node.networks
        project_prefix = f"demoforge-{demo_id}-"

        # Fetch live Docker network IPs for this container
        docker_network_ips: dict[str, str] = {}
        try:
            docker_container = await asyncio.to_thread(docker_client.containers.get, container.container_name)
            docker_networks = docker_container.attrs.get("NetworkSettings", {}).get("Networks", {})
            for net_key, net_info in docker_networks.items():
                ip = net_info.get("IPAddress", "")
                if ip:
                    # Index by both full and logical name for lookup below
                    docker_network_ips[net_key] = ip
                    logical = net_key.replace(project_prefix, "") if net_key.startswith(project_prefix) else net_key
                    docker_network_ips[logical] = ip
        except Exception:
            pass  # Container may not be running; fall back to static config

        for net_name in container.networks:
            # Strip project prefix to get logical name for node.networks lookup
            logical_name = net_name.replace(project_prefix, "") if net_name.startswith(project_prefix) else net_name
            net_cfg = node_networks.get(logical_name)
            live_ip = docker_network_ips.get(net_name) or docker_network_ips.get(logical_name)
            membership = NetworkMembership(
                network_name=logical_name,
                ip_address=live_ip or (net_cfg.ip if net_cfg else None),
                aliases=net_cfg.aliases if net_cfg else [],
            )
            network_memberships.append(membership)

        # Populate credentials from manifest secrets, preferring node config overrides
        credentials = []
        node_config = {}
        if demo:
            demo_node = next((n for n in demo.nodes if n.id == node_id), None)
            if demo_node:
                node_config = demo_node.config
        if manifest:
            for secret in manifest.secrets:
                value = node_config.get(secret.key, secret.default)
                if value is not None:
                    credentials.append(CredentialInfo(
                        key=secret.key,
                        label=secret.label,
                        value=value,
                    ))

        instances.append(ContainerInstance(
            node_id=node_id,
            component_id=container.component_id,
            container_name=container.container_name,
            health=health,
            web_uis=web_uis,
            has_terminal=True,
            quick_actions=quick_actions,
            networks=network_memberships,
            credentials=credentials,
            init_status=container.init_status,
            stopped_drives=running.stopped_drives.get(node_id, []),
            is_sidecar=container.is_sidecar,
        ))

    # Poll file-generator containers for per-edge status
    if demo:
        fg_node_ids = {n.id for n in demo.nodes if n.component == "file-generator"}
        for fg_id in fg_node_ids:
            if fg_id not in running.containers:
                continue
            container_name = running.containers[fg_id].container_name
            try:
                import json as _json
                exit_code, stdout, _stderr = await exec_in_container(
                    container_name, "cat /tmp/gen_status.json 2>/dev/null"
                )
                if exit_code == 0 and stdout.strip():
                    status_map = _json.loads(stdout.strip())
                    for edge_id, status in status_map.items():
                        running.edge_configs[edge_id] = EdgeConfigResult(
                            edge_id=edge_id,
                            connection_type="file-push",
                            status=status,
                            description=f"File generator write: {status}",
                            error="Write failed" if status == "failed" else "",
                        )
            except Exception:
                pass

    # Event processor + metabase-init: runtime integration logs (local JSONL, offline)
    integration_events: list[dict] = []
    if demo:
        ep_node_ids = [n.id for n in demo.nodes if n.component == "event-processor"]
        for ep_id in ep_node_ids:
            if ep_id not in running.containers:
                continue
            cname = running.containers[ep_id].container_name
            try:
                exit_code, stdout, _stderr = await exec_in_container(
                    cname,
                    "sh -c 'test -f /tmp/demoforge_integration.jsonl && tail -n 500 /tmp/demoforge_integration.jsonl || true'",
                )
                if exit_code != 0 or not (stdout or "").strip():
                    continue
                for line in stdout.strip().splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        if isinstance(rec, dict):
                            rec["node_id"] = ep_id
                            integration_events.append(rec)
                    except json.JSONDecodeError:
                        continue
            except Exception:
                continue

        # Metabase init sidecar (setup-metabase.sh + provision.py) — same JSONL path
        if "metabase-init" in running.containers:
            rc = running.containers["metabase-init"]
            cname = rc.container_name
            try:
                exit_code, stdout, _stderr = await exec_in_container(
                    cname,
                    "sh -c 'test -f /tmp/demoforge_integration.jsonl && tail -n 500 /tmp/demoforge_integration.jsonl || true'",
                )
                if exit_code == 0 and (stdout or "").strip():
                    for line in stdout.strip().splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                            if isinstance(rec, dict):
                                rec.setdefault("node_id", "metabase-init")
                                integration_events.append(rec)
                        except json.JSONDecodeError:
                            continue
            except Exception:
                pass

        # external-system: dashboard seed intents + optional integration_log.py writes
        es_node_ids = [n.id for n in demo.nodes if n.component == "external-system"]
        for es_id in es_node_ids:
            if es_id not in running.containers:
                continue
            cname = running.containers[es_id].container_name
            try:
                exit_code, stdout, _stderr = await exec_in_container(
                    cname,
                    "sh -c 'test -f /tmp/demoforge_integration.jsonl && tail -n 500 /tmp/demoforge_integration.jsonl || true'",
                )
                if exit_code != 0 or not (stdout or "").strip():
                    continue
                for line in stdout.strip().splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        if isinstance(rec, dict):
                            rec["node_id"] = es_id
                            integration_events.append(rec)
                    except json.JSONDecodeError:
                        continue
            except Exception:
                continue

        # mc-shell: IAM simulation mc commands + DEMOFORGE_IAM_REPORT (docker logs; same lines as IAM reconcile API)
        if "mc-shell" in running.containers:
            mc_cname = running.containers["mc-shell"].container_name
            try:

                def _mc_logs() -> bytes:
                    return docker_client.containers.get(mc_cname).logs(tail=50000)

                mc_raw = await asyncio.to_thread(_mc_logs)
                integration_events.extend(mc_shell_iam_integration_events_from_logs(mc_raw, demo_id))
            except Exception as e:
                logger.debug("mc-shell integration log tail failed for %s: %s", demo_id, e)

        integration_events.extend(_load_demo_integration_audit(demo_id))

        integration_events.sort(key=lambda r: (r.get("ts_ms") or 0, r.get("id") or ""))

    # Build edge configs with live verification for site-replication
    edge_configs = []
    for ec in running.edge_configs.values():
        status = ec.status
        error = ec.error
        # For site-replication edges, verify actual status from MinIO
        if ec.connection_type in ("site-replication", "cluster-site-replication"):
            live = await _check_live_replication_status(running, demo_id)
            if live is not None:
                status = "applied" if live else ("failed" if ec.status == "applied" else ec.status)
                if not live and ec.status == "applied":
                    error = "Site replication not active on cluster"
                elif live and ec.status in ("paused", "failed"):
                    error = ""
        edge_configs.append(EdgeConfigStatus(
            edge_id=ec.edge_id,
            connection_type=ec.connection_type,
            status=status,
            description=ec.description,
            error=error,
        ))

    return InstancesResponse(
        demo_id=demo_id, status=running.status, instances=instances,
        init_results=running.init_results, edge_configs=edge_configs,
        cluster_health=cluster_health,
        integration_events=integration_events,
    )

@router.post("/api/demos/{demo_id}/instances/{node_id}/restart")
async def restart_instance(demo_id: str, node_id: str):
    running = state.get_demo(demo_id)
    if not running or node_id not in running.containers:
        raise HTTPException(404, "Instance not found")
    await restart_container(running.containers[node_id].container_name)
    return {"status": "restarted"}

@router.post("/api/demos/{demo_id}/instances/{node_id}/stop")
async def stop_instance(demo_id: str, node_id: str):
    """Stop a single container (for resilience demos)."""
    running = state.get_demo(demo_id)
    if not running or node_id not in running.containers:
        raise HTTPException(404, "Instance not found")
    container_name = running.containers[node_id].container_name
    c = await asyncio.to_thread(docker_client.containers.get, container_name)
    await asyncio.to_thread(c.stop, timeout=5)
    return {"status": "stopped", "node_id": node_id}

@router.post("/api/demos/{demo_id}/instances/{node_id}/start")
async def start_instance(demo_id: str, node_id: str):
    """Start a previously stopped container."""
    running = state.get_demo(demo_id)
    if not running or node_id not in running.containers:
        raise HTTPException(404, "Instance not found")
    container_name = running.containers[node_id].container_name
    c = await asyncio.to_thread(docker_client.containers.get, container_name)
    await asyncio.to_thread(c.start)
    return {"status": "started", "node_id": node_id}


@router.post("/api/demos/{demo_id}/instances/{node_id}/drives/{drive_num}/stop")
async def stop_drive(demo_id: str, node_id: str, drive_num: int):
    """Make a single drive inaccessible to simulate a drive failure."""
    running = state.get_demo(demo_id)
    if not running or node_id not in running.containers:
        raise HTTPException(404, "Instance not found")
    container_name = running.containers[node_id].container_name
    await exec_in_container(container_name, f"chmod 000 /data{drive_num}")
    if node_id not in running.stopped_drives:
        running.stopped_drives[node_id] = []
    if drive_num not in running.stopped_drives[node_id]:
        running.stopped_drives[node_id].append(drive_num)
    return {"status": "stopped", "node_id": node_id, "drive_num": drive_num}

@router.post("/api/demos/{demo_id}/instances/{node_id}/drives/{drive_num}/start")
async def start_drive(demo_id: str, node_id: str, drive_num: int):
    """Restore a previously stopped drive."""
    running = state.get_demo(demo_id)
    if not running or node_id not in running.containers:
        raise HTTPException(404, "Instance not found")
    container_name = running.containers[node_id].container_name
    await exec_in_container(container_name, f"chmod 755 /data{drive_num}")
    if node_id in running.stopped_drives and drive_num in running.stopped_drives[node_id]:
        running.stopped_drives[node_id].remove(drive_num)
    return {"status": "started", "node_id": node_id, "drive_num": drive_num}

