import asyncio
import logging
import os
import re
import shlex
import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from ..state.store import state, EdgeConfigResult
from ..registry.loader import get_component
from ..engine.docker_manager import get_container_health, restart_container, exec_in_container, docker_client
from ..engine.proxy_gateway import get_http_client
from ..engine.edge_automation import (
    generate_edge_scripts, _get_credential, _safe, _find_cluster,
    _get_cluster_credentials, _resolve_cluster_endpoint,
)
from ..engine.compose_generator import generate_compose
from ..models.api_models import (
    InstancesResponse, ContainerInstance, WebUILink,
    ExecRequest, ExecResponse, NetworkMembership, CredentialInfo,
    EdgeConfigStatus, ExecLogRequest, LogResponse,
)
from .demos import _load_demo

logger = logging.getLogger(__name__)

router = APIRouter()

# Cache for live replication checks (avoid hammering mc on every poll)
_repl_cache: dict[str, tuple[float, bool]] = {}


async def _check_live_replication_status(running, demo_id: str) -> bool | None:
    """Check if site replication is actually enabled by querying mc-shell.

    Returns True if enabled, False if not, None if we can't determine.
    Caches result for 10 seconds to avoid excessive Docker exec calls.
    """
    import time
    now = time.time()
    cached = _repl_cache.get(demo_id)
    if cached and now - cached[0] < 10:
        return cached[1]

    mc_shell_name = f"demoforge-{demo_id}-mc-shell"
    if mc_shell_name not in [c.container_name for c in running.containers.values()]:
        return None

    try:
        # Compute the alias name from demo definition (same as compose_generator)
        import re as _re
        demo_def = None
        try:
            from .demos import _load_demo
            demo_def = _load_demo(demo_id)
        except Exception:
            pass
        if demo_def and demo_def.clusters:
            alias = _re.sub(r"[^a-zA-Z0-9_]", "_", demo_def.clusters[0].label)
        elif demo_def:
            # Standalone MinIO nodes — site-replication uses "site1" alias
            minio_nodes = [n for n in demo_def.nodes if n.component == "minio"]
            if minio_nodes:
                alias = _re.sub(r"[^a-zA-Z0-9_]", "_", minio_nodes[0].display_name) if minio_nodes[0].display_name else minio_nodes[0].id
            else:
                return None
        else:
            return None
        exit_code, stdout, stderr = await exec_in_container(
            mc_shell_name,
            f"sh -c 'mc admin replicate info {alias} 2>&1 | head -1'",
        )
        # "SiteReplication enabled for:" vs "SiteReplication is not enabled"
        enabled = "enabled for" in stdout.lower() if exit_code == 0 else False
        _repl_cache[demo_id] = (now, enabled)
        return enabled
    except Exception:
        return None


def _build_replication_state_cmd(
    demo, edge_id: str, project_name: str, desired_state: str,
) -> dict | None:
    """Build an mc command to enable/disable bucket replication for an edge.

    Returns {"container": ..., "command": ...} or None if the edge type
    does not support pause/resume.

    Only 'replication' and 'cluster-replication' edges support this.
    Site-replication and tiering cannot be paused.
    """
    edge = next((e for e in demo.edges if e.id == edge_id), None)
    if not edge:
        return None

    config = edge.connection_config or {}

    if edge.connection_type == "replication":
        source_node = next((n for n in demo.nodes if n.id == edge.source), None)
        if not source_node:
            return None
        source_manifest = get_component(source_node.component)
        source_user = _get_credential(source_node, source_manifest, "MINIO_ROOT_USER", "minioadmin")
        source_pass = _get_credential(source_node, source_manifest, "MINIO_ROOT_PASSWORD", "minioadmin")
        source_host = f"{project_name}-{source_node.id}"
        source_bucket = _safe(config.get("source_bucket", "demo-bucket"))
        command = (
            f"mc alias set source http://{source_host}:9000 {_safe(source_user)} {_safe(source_pass)} && "
            f"mc replicate update source/{source_bucket} --state {desired_state}"
        )
        return {"container": f"{project_name}-{source_node.id}", "command": command}

    elif edge.connection_type == "cluster-replication":
        source_cluster_id = config.get("_source_cluster_id", "")
        if not source_cluster_id:
            for c in demo.clusters:
                if edge.source.startswith(f"{c.id}-node-") or edge.source == f"{c.id}-lb":
                    source_cluster_id = c.id
                    break
        source_cluster = _find_cluster(demo, source_cluster_id)
        if not source_cluster:
            return None
        source_user, source_pass = _get_cluster_credentials(source_cluster)
        source_host = _resolve_cluster_endpoint(source_cluster, project_name)
        source_bucket = _safe(config.get("source_bucket", "demo-bucket"))
        command = (
            f"mc alias set source http://{source_host}:80 {_safe(source_user)} {_safe(source_pass)} && "
            f"mc replicate update source/{source_bucket} --state {desired_state}"
        )
        return {"container": f"{project_name}-{source_cluster.id}-node-1", "command": command}

    return None

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
        manifest = get_component(container.component_id)
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

def _expand_demo_for_edges(demo):
    """Lightweight cluster edge expansion — same logic as compose_generator but
    only expands edges and injects synthetic nodes. Does NOT render templates or
    build compose files. Works even without component manifests loaded."""
    from ..models.demo import DemoNode, DemoEdge, NodePosition
    demo = demo.model_copy(deep=True)
    for cluster in demo.clusters:
        generated_ids = [f"{cluster.id}-node-{i}" for i in range(1, cluster.node_count + 1)]
        lb_node_id = f"{cluster.id}-lb"
        # Add synthetic nodes
        for i, node_id in enumerate(generated_ids):
            demo.nodes.append(DemoNode(
                id=node_id, component=cluster.component, variant="cluster",
                position=NodePosition(x=0, y=0),
                config={"MINIO_ROOT_USER": cluster.credentials.get("root_user", "minioadmin"),
                        "MINIO_ROOT_PASSWORD": cluster.credentials.get("root_password", "minioadmin")},
            ))
        demo.nodes.append(DemoNode(id=lb_node_id, component="nginx", variant="",
                                    config={"mode": "round-robin"},
                                    position=NodePosition(x=0, y=0)))
        # Expand edges referencing cluster ID
        original_edges = list(demo.edges)
        new_edges, edges_to_remove = [], []
        for edge in original_edges:
            is_cluster_level = edge.connection_type.startswith("cluster-")
            # Preserve the TRUE original edge ID across multiple cluster expansions
            true_original = edge.connection_config.get("_original_edge_id", edge.id)
            if edge.source == cluster.id:
                edges_to_remove.append(edge.id)
                new_edges.append(DemoEdge(
                    id=f"{edge.id}-cluster" if is_cluster_level else f"{edge.id}-lb",
                    source=lb_node_id, target=edge.target,
                    connection_type=edge.connection_type, network=edge.network,
                    connection_config={**edge.connection_config, "_source_cluster_id": cluster.id, "_original_edge_id": true_original},
                    auto_configure=edge.auto_configure, label=edge.label,
                ))
            elif edge.target == cluster.id:
                edges_to_remove.append(edge.id)
                new_edges.append(DemoEdge(
                    id=f"{edge.id}-cluster" if is_cluster_level else f"{edge.id}-lb",
                    source=edge.source, target=lb_node_id,
                    connection_type=edge.connection_type, network=edge.network,
                    connection_config={**edge.connection_config, "_target_cluster_id": cluster.id, "_original_edge_id": true_original},
                    auto_configure=edge.auto_configure, label=edge.label,
                ))
        demo.edges = [e for e in demo.edges if e.id not in edges_to_remove] + new_edges
        # Add LB → node edges
        for j, gen_id in enumerate(generated_ids):
            demo.edges.append(DemoEdge(
                id=f"{cluster.id}-lb-edge-{j+1}", source=lb_node_id, target=gen_id,
                connection_type="load-balance", network="default",
                connection_config={"algorithm": "least-conn", "backend_port": "9000"},
                auto_configure=True,
            ))
    return demo

@router.post("/api/demos/{demo_id}/edges/{edge_id}/activate")
async def activate_edge_config(demo_id: str, edge_id: str):
    """Activate a paused edge config (run the mc commands)."""
    running = state.get_demo(demo_id)
    if not running:
        raise HTTPException(404, "Demo not running")

    demo = _load_demo(demo_id)
    if not demo:
        raise HTTPException(404, "Demo definition not found")

    project_name = f"demoforge-{demo_id}"
    expanded_demo = _expand_demo_for_edges(demo)
    scripts = generate_edge_scripts(expanded_demo, project_name)

    # Build reverse mapping: original_edge_id → expanded_edge_id
    edge_id_map: dict[str, str] = {}
    for edge in expanded_demo.edges:
        orig = (edge.connection_config or {}).get("_original_edge_id")
        if orig:
            edge_id_map[orig] = edge.id

    # Find matching script — try exact match, then mapped ID from original
    script = next((s for s in scripts if s.edge_id == edge_id), None)
    if not script:
        mapped_id = edge_id_map.get(edge_id)
        if mapped_id:
            script = next((s for s in scripts if s.edge_id == mapped_id), None)
            if script:
                edge_id = mapped_id
    if not script:
        raise HTTPException(404, f"No automation script for edge '{edge_id}'")

    # Ensure edge config entry exists
    ec = running.edge_configs.get(edge_id)
    if not ec:
        ec = EdgeConfigResult(
            edge_id=edge_id,
            connection_type=script.connection_type,
            status="paused",
            description=script.description,
        )
        running.edge_configs[edge_id] = ec

    if ec.status == "applied":
        return {"status": "already_applied", "edge_id": edge_id}
    if not script:
        raise HTTPException(404, f"No automation script for edge '{edge_id}'")

    ec.status = "pending"
    ec.error = ""
    state.set_demo(running)

    try:
        exit_code, stdout, stderr = await exec_in_container(
            script.container_name, f"sh -c {shlex.quote(script.command)}"
        )
        if exit_code != 0:
            ec.status = "failed"
            ec.error = stderr[:500]
            state.set_demo(running)
            return {"status": "failed", "edge_id": edge_id, "error": stderr[:500]}
        else:
            ec.status = "applied"
            ec.previously_applied = True
            ec.error = ""
            state.set_demo(running)
            return {"status": "applied", "edge_id": edge_id}
    except Exception as e:
        ec.status = "failed"
        ec.error = str(e)[:500]
        state.set_demo(running)
        return {"status": "failed", "edge_id": edge_id, "error": str(e)[:500]}

@router.post("/api/demos/{demo_id}/edges/{edge_id}/pause")
async def pause_edge_config(demo_id: str, edge_id: str):
    """Pause an edge config.

    For bucket replication (replication, cluster-replication): executes
    ``mc replicate update ALIAS/BUCKET --state disable`` to actually stop
    replication on the server side.

    Site-replication cannot be paused — it is all-or-nothing.
    Tiering (ILM rules) cannot be paused without removing the rule entirely.
    """
    running = state.get_demo(demo_id)
    if not running:
        raise HTTPException(404, "Demo not running")

    # Look up edge config: try exact match, then search by original edge ID prefix
    ec = running.edge_configs.get(edge_id)
    if not ec:
        # The config may be stored under an expanded ID (with -cluster suffixes)
        # Search for any config whose ID starts with the frontend edge ID
        for key, val in running.edge_configs.items():
            if key.startswith(edge_id):
                ec = val
                edge_id = key
                break
    if not ec:
        raise HTTPException(404, f"Edge config '{edge_id}' not found")

    # For site-replication: remove via mc admin replicate remove
    if ec.connection_type in ("site-replication", "cluster-site-replication") and ec.status == "applied":
        _demo = _load_demo(demo_id)
        if _demo:
            expanded = _expand_demo_for_edges(_demo)
            project_name = f"demoforge-{demo_id}"
            edge = next((e for e in expanded.edges if e.id == edge_id), None)
            if edge:
                alias = _get_first_cluster_alias(expanded)
                if alias:
                    cmd = f"mc admin replicate remove {alias} --all --force"
                    try:
                        exit_code, stdout, stderr = await exec_in_container(
                            f"{project_name}-mc-shell", f"sh -c {shlex.quote(cmd)}"
                        )
                        if exit_code != 0:
                            logger.warning(f"Failed to remove site-replication: {stderr[:200]}")
                    except Exception as e:
                        logger.warning(f"Error removing site-replication: {e}")

    # For tiering: just mark as paused (ILM rules can't be easily removed without rule ID)
    if ec.connection_type in ("tiering", "cluster-tiering") and ec.status == "applied":
        pass  # Just mark as paused in state below

    # For bucket replication, disable the rule on the server
    if ec.connection_type in ("replication", "cluster-replication") and ec.status == "applied":
        _demo = _load_demo(demo_id)
        if _demo:
            expanded = _expand_demo_for_edges(_demo)
            project_name = f"demoforge-{demo_id}"
            try:
                pause_cmd = _build_replication_state_cmd(
                    expanded, edge_id, project_name, "disable",
                )
                if pause_cmd:
                    exit_code, stdout, stderr = await exec_in_container(
                        pause_cmd["container"],
                        f"sh -c {shlex.quote(pause_cmd['command'])}",
                    )
                    if exit_code != 0:
                        logger.warning(
                            f"Failed to disable replication for edge {edge_id}: {stderr[:200]}"
                        )
                        # Still mark as paused in state — the user asked to pause
            except Exception as e:
                logger.warning(f"Error disabling replication for edge {edge_id}: {e}")

    ec.status = "paused"
    state.set_demo(running)
    # Clear replication cache
    _repl_cache.pop(demo_id, None)
    return {"status": "paused", "edge_id": edge_id}


def _get_first_cluster_alias(demo) -> str | None:
    """Get the sanitized alias name of the first cluster (used for mc admin commands)."""
    import re as _re
    if demo.clusters:
        return _re.sub(r"[^a-zA-Z0-9_]", "_", demo.clusters[0].label)
    return None


@router.post("/api/demos/{demo_id}/edges/{edge_id}/resync")
async def resync_edge(demo_id: str, edge_id: str):
    """Trigger mc admin replicate resync on a site-replication edge."""
    running = state.get_demo(demo_id)
    if not running:
        raise HTTPException(404, "Demo not running")

    demo = _load_demo(demo_id)
    if not demo:
        raise HTTPException(404, "Demo definition not found")

    import re as _re
    expanded = _expand_demo_for_edges(demo)
    if len(expanded.clusters) < 2:
        raise HTTPException(400, "Need at least 2 clusters for resync")

    # mc admin replicate resync start requires exactly 2 aliases
    # Find the edge's source and target clusters
    edge = next((e for e in expanded.edges if e.id == edge_id or e.id.startswith(edge_id)), None)
    if edge:
        src_cid = (edge.connection_config or {}).get("_source_cluster_id", "")
        tgt_cid = (edge.connection_config or {}).get("_target_cluster_id", "")
        src_cluster = next((c for c in expanded.clusters if c.id == src_cid), None)
        tgt_cluster = next((c for c in expanded.clusters if c.id == tgt_cid), None)
        if src_cluster and tgt_cluster:
            alias1 = _re.sub(r"[^a-zA-Z0-9_]", "_", src_cluster.label)
            alias2 = _re.sub(r"[^a-zA-Z0-9_]", "_", tgt_cluster.label)
        else:
            # Fallback: use first two clusters
            alias1 = _re.sub(r"[^a-zA-Z0-9_]", "_", expanded.clusters[0].label)
            alias2 = _re.sub(r"[^a-zA-Z0-9_]", "_", expanded.clusters[1].label)
    else:
        alias1 = _re.sub(r"[^a-zA-Z0-9_]", "_", expanded.clusters[0].label)
        alias2 = _re.sub(r"[^a-zA-Z0-9_]", "_", expanded.clusters[1].label)

    project_name = f"demoforge-{demo_id}"
    mc_shell = f"{project_name}-mc-shell"

    cmd = f"mc admin replicate resync start {alias1} {alias2}"
    try:
        exit_code, stdout, stderr = await exec_in_container(
            mc_shell, f"sh -c {shlex.quote(cmd)}"
        )
        if exit_code != 0:
            return {"status": "failed", "edge_id": edge_id, "error": (stderr or stdout)[:500]}
        # Clear replication cache to force refresh
        _repl_cache.pop(demo_id, None)
        return {"status": "resync_started", "edge_id": edge_id, "output": stdout[:500]}
    except Exception as e:
        return {"status": "failed", "edge_id": edge_id, "error": str(e)[:500]}


@router.post("/api/demos/{demo_id}/clusters/{cluster_id}/reset")
async def reset_cluster(demo_id: str, cluster_id: str):
    """Remove all buckets from a MinIO cluster via mc-shell."""
    import re as _re
    running = state.get_demo(demo_id)
    if not running:
        raise HTTPException(404, "Demo not running")

    demo = _load_demo(demo_id)
    if not demo:
        raise HTTPException(404, "Demo definition not found")

    cluster = next((c for c in demo.clusters if c.id == cluster_id), None)
    if not cluster:
        raise HTTPException(404, f"Cluster '{cluster_id}' not found")

    alias = re.sub(r"[^a-zA-Z0-9_]", "_", cluster.label)
    project_name = f"demoforge-{demo_id}"
    mc_shell = f"{project_name}-mc-shell"

    # List buckets using only shell builtins (no grep/awk/cut available in minio/mc:latest)
    # Then remove each one. We count removed buckets via a counter written to a temp file.
    cmd = (
        f"count=0; "
        f"mc ls {alias}/ 2>/dev/null | while read line; do "
        f'b="${{line##* }}"; b="${{b%/}}"; '
        f'[ -n "$b" ] && mc rb --force {alias}/$b 2>/dev/null && count=$((count+1)); '
        f"done; "
        f"mc ls {alias}/ 2>/dev/null | while read line; do "
        f'b="${{line##* }}"; b="${{b%/}}"; '
        f'[ -n "$b" ] && echo "BUCKET:$b"; '
        f"done"
    )

    # First pass: remove buckets
    remove_cmd = (
        f"mc ls {alias}/ 2>/dev/null | while read line; do "
        f'b="${{line##* }}"; b="${{b%/}}"; '
        f'[ -n "$b" ] && mc rb --force {alias}/$b 2>/dev/null && echo "REMOVED:$b"; '
        f"done"
    )

    try:
        exit_code, stdout, stderr = await exec_in_container(
            mc_shell, f"sh -c {shlex.quote(remove_cmd)}"
        )
        if exit_code != 0:
            return {"status": "failed", "cluster_id": cluster_id, "error": (stderr or stdout)[:500]}

        removed = [line[len("REMOVED:"):] for line in stdout.splitlines() if line.startswith("REMOVED:")]
        return {"status": "reset", "cluster_id": cluster_id, "buckets_removed": len(removed)}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/api/demos/{demo_id}/generator-status/{node_id}")
async def get_generator_status(demo_id: str, node_id: str):
    """Read generator status from /tmp/gen.status inside the container."""
    running = state.get_demo(demo_id)
    if not running or node_id not in running.containers:
        raise HTTPException(404, "Instance not found")
    container_name = running.containers[node_id].container_name
    try:
        exit_code, stdout, stderr = await exec_in_container(
            container_name,
            "sh -c '[ -f /tmp/gen.status ] && cat /tmp/gen.status || echo STATE=idle'",
        )
        parsed: dict = {"state": "idle", "rows_generated": 0, "batches_sent": 0, "errors": 0}
        for line in stdout.splitlines():
            line = line.strip()
            if "=" in line:
                k, _, v = line.partition("=")
                parsed[k.lower()] = v
        # Normalise numeric fields
        for field in ("rows_generated", "batches_sent", "errors", "rows_per_sec"):
            if field in parsed:
                try:
                    parsed[field] = float(parsed[field]) if field == "rows_per_sec" else int(parsed[field])
                except (ValueError, TypeError):
                    parsed[field] = 0
        return parsed
    except Exception as e:
        raise HTTPException(500, str(e))


class GeneratorStartRequest(BaseModel):
    scenario: str = "ecommerce-orders"
    format: str = "parquet"
    rate_profile: str = "medium"


@router.post("/api/demos/{demo_id}/generator-start/{node_id}")
async def start_generator(demo_id: str, node_id: str, req: GeneratorStartRequest):
    """Start/resume the data-generator.

    If the generator is idle (paused via stop), touch /tmp/gen.start to resume.
    If no process is running at all, spawn a new one.
    """
    running = state.get_demo(demo_id)
    if not running or node_id not in running.containers:
        raise HTTPException(404, "Instance not found")
    container_name = running.containers[node_id].container_name
    # Check if the main generate.py process is alive (PID 1 in the container)
    # If it's alive but idle (no /tmp/gen.pid), just touch /tmp/gen.start to resume
    # If it's not alive, spawn a new one
    resume_cmd = "sh -c 'touch /tmp/gen.start; echo resumed'"
    try:
        exit_code, stdout, stderr = await exec_in_container(container_name, resume_cmd)
        return {"state": "streaming", "scenario": req.scenario, "format": req.format, "rate_profile": req.rate_profile}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/api/demos/{demo_id}/generator-stop/{node_id}")
async def stop_generator(demo_id: str, node_id: str):
    """Pause the data-generator by touching /tmp/gen.stop.

    The generator stays alive but enters idle mode (doesn't exit).
    """
    running = state.get_demo(demo_id)
    if not running or node_id not in running.containers:
        raise HTTPException(404, "Instance not found")
    container_name = running.containers[node_id].container_name
    stop_cmd = "sh -c 'touch /tmp/gen.stop; echo stopped'"
    try:
        await exec_in_container(container_name, stop_cmd)
        return {"state": "idle"}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/api/demos/{demo_id}/instances/{node_id}/exec", response_model=ExecResponse)
async def exec_command(demo_id: str, node_id: str, req: ExecRequest):
    running = state.get_demo(demo_id)
    if not running or node_id not in running.containers:
        raise HTTPException(404, "Instance not found")
    exit_code, stdout, stderr = await exec_in_container(
        running.containers[node_id].container_name, req.command
    )
    return ExecResponse(exit_code=exit_code, stdout=stdout, stderr=stderr)


@router.get("/api/demos/{demo_id}/instances/{node_id}/logs", response_model=LogResponse)
async def get_container_logs(demo_id: str, node_id: str, tail: int = 200, since: str = ""):
    """Fetch recent stdout/stderr from a container."""
    running = state.get_demo(demo_id)
    if not running or node_id not in running.containers:
        raise HTTPException(404, "Instance not found")
    container_name = running.containers[node_id].container_name
    try:
        def _fetch():
            c = docker_client.containers.get(container_name)
            kwargs: dict = {"tail": tail, "timestamps": True, "stream": False}
            if since:
                # Accept "60s", "5m", or raw int seconds
                if since.endswith("s"):
                    kwargs["since"] = int(since[:-1])
                elif since.endswith("m"):
                    kwargs["since"] = int(since[:-1]) * 60
                else:
                    kwargs["since"] = int(since)
            raw = c.logs(**kwargs)
            return raw

        raw = await asyncio.to_thread(_fetch)
        text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        lines = [l for l in text.split("\n") if l] if text.strip() else []
        return LogResponse(lines=lines, container=node_id, truncated=len(lines) >= tail)
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/api/demos/{demo_id}/instances/{node_id}/exec-log", response_model=LogResponse)
async def exec_container_log(demo_id: str, node_id: str, req: ExecLogRequest):
    """Run a read-only command inside a container and return its output as log lines."""
    running = state.get_demo(demo_id)
    if not running or node_id not in running.containers:
        raise HTTPException(404, "Instance not found")
    container_name = running.containers[node_id].container_name
    try:
        exit_code, stdout, stderr = await exec_in_container(container_name, f"sh -c {shlex.quote(req.command)}")
        combined = (stdout or "") + (stderr or "")
        lines = [l for l in combined.split("\n") if l]
        return LogResponse(lines=lines, container=node_id, truncated=False)
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/api/demos/{demo_id}/minio-commands")
async def get_minio_commands(demo_id: str):
    """Return all MinIO mc commands used to set up this demo, grouped by category."""
    import re as _re

    demo = _load_demo(demo_id)
    if not demo:
        raise HTTPException(404, "Demo definition not found")

    commands = []
    project_name = f"demoforge-{demo_id}"

    # --- Alias Setup commands (from init.sh pattern in compose_generator) ---
    for cluster in demo.clusters:
        alias_name = _re.sub(r"[^a-zA-Z0-9_]", "_", cluster.label)
        lb_url = f"http://{project_name}-{cluster.id}-lb:80"
        cred_user = cluster.credentials.get("root_user", "minioadmin")
        cred_pass = cluster.credentials.get("root_password", "minioadmin")
        commands.append({
            "category": "Alias Setup",
            "description": f"Configure mc alias for cluster: {cluster.label}",
            "command": f"mc alias set '{alias_name}' '{lb_url}' '{cred_user}' '{cred_pass}'",
        })

    # Standalone MinIO nodes
    standalone_minio = [
        n for n in demo.nodes
        if n.component == "minio"
        and not any(n.id.startswith(f"{c.id}-") for c in demo.clusters)
    ]
    for node in standalone_minio:
        alias_name = _re.sub(r"[^a-zA-Z0-9_]", "_", node.display_name) if getattr(node, "display_name", None) else node.id
        node_url = f"http://{project_name}-{node.id}:9000"
        cred_user = node.config.get("MINIO_ROOT_USER", "minioadmin")
        cred_pass = node.config.get("MINIO_ROOT_PASSWORD", "minioadmin")
        commands.append({
            "category": "Alias Setup",
            "description": f"Configure mc alias for node: {node.id}",
            "command": f"mc alias set '{alias_name}' '{node_url}' '{cred_user}' '{cred_pass}'",
        })

    # --- Edge-generated commands (replication, site-replication, tiering) ---
    expanded_demo = _expand_demo_for_edges(demo)
    scripts = generate_edge_scripts(expanded_demo, project_name)

    # Map connection_type → category label
    _category_map = {
        "replication": "Bucket Replication",
        "cluster-replication": "Bucket Replication",
        "site-replication": "Site Replication",
        "cluster-site-replication": "Site Replication",
        "tiering": "ILM Tiering",
        "cluster-tiering": "ILM Tiering",
    }

    for script in scripts:
        category = _category_map.get(script.connection_type, "Other mc Commands")
        # Split compound commands (joined with &&) into individual lines for readability
        # but show the full command as-is for copy/paste accuracy
        commands.append({
            "category": category,
            "description": script.description,
            "command": script.command,
        })

    return {"demo_id": demo_id, "commands": commands}


# ---------------------------------------------------------------------------
# SQL Editor endpoints
# ---------------------------------------------------------------------------

@router.get("/api/demos/{demo_id}/scenario-queries/{scenario_id}")
async def get_scenario_queries(demo_id: str, scenario_id: str):
    """Return pre-built queries for a scenario with placeholders resolved.

    When scenario_id is 'all', returns queries for all scenarios grouped:
      { "scenarios": [{ "id": ..., "name": ..., "queries": [...] }] }

    Otherwise returns the single-scenario format (backward compat):
      { "scenario_id": ..., "queries": [...] }
    """
    import yaml as _yaml

    components_dir = os.environ.get("DEMOFORGE_COMPONENTS_DIR", "./components")
    datasets_dir = os.path.join(os.path.abspath(components_dir), "data-generator", "datasets")

    # Build a map of scenario → (catalog, namespace) from running generators
    _scenario_catalog_map = {}
    running = state.get_demo(demo_id)
    if running:
        demos_dir = os.environ.get("DEMOFORGE_DEMOS_DIR", "./demos")
        demo_path = os.path.join(demos_dir, f"{demo_id}.yaml")
        if os.path.isfile(demo_path):
            with open(demo_path) as _df:
                demo_def = _yaml.safe_load(_df)
            for node in demo_def.get("nodes", []):
                if node.get("component") == "data-generator":
                    cfg = node.get("config", {})
                    sc = cfg.get("DG_SCENARIO", "ecommerce-orders")
                    wm = cfg.get("DG_WRITE_MODE", "iceberg")
                    is_sigv4 = any(
                        e.get("source") == node.get("id")
                        and e.get("connection_config", {}).get("write_mode") == "raw"
                        for e in demo_def.get("edges", [])
                    ) or wm == "raw"
                    if is_sigv4 or wm == "raw":
                        _scenario_catalog_map[sc] = ("hive", "raw")
                    else:
                        # Check if targeting AIStor (SigV4)
                        for e in demo_def.get("edges", []):
                            if e.get("source") == node.get("id") and e.get("connection_type") in ("structured-data", "s3"):
                                target = e.get("target", "")
                                for cl in demo_def.get("clusters", []):
                                    if cl.get("id") == target and cl.get("aistor_tables_enabled"):
                                        _scenario_catalog_map[sc] = ("aistor", "demo")
                                        break
                        # Check standalone AIStor nodes
                        if sc not in _scenario_catalog_map:
                            for n in demo_def.get("nodes", []):
                                if n.get("component") == "minio" and n.get("config", {}).get("MINIO_EDITION", "ce") == "aistor":
                                    _scenario_catalog_map[sc] = ("aistor", "demo")
                                    break
                        if sc not in _scenario_catalog_map:
                            _scenario_catalog_map[sc] = ("iceberg", "demo")

    def _load_queries_from_yaml(yaml_path: str, scenario_id_hint: str = "") -> list:
        with open(yaml_path, "r", encoding="utf-8") as fh:
            raw = _yaml.safe_load(fh)
        sid = raw.get("id", scenario_id_hint)
        catalog, namespace = _scenario_catalog_map.get(sid, ("iceberg", "demo"))

        # For Hive CSV tables, all columns are VARCHAR — wrap numeric/timestamp
        # references with CAST for compatibility
        schema_cols = raw.get("schema", {})
        col_types = {}
        if isinstance(schema_cols, dict):
            for col in schema_cols.get("columns", []):
                col_types[col["name"]] = col.get("type", "string")

        iceberg_cfg = raw.get("iceberg", {}) or {}
        table = iceberg_cfg.get("table", raw.get("id", "").replace("-", "_"))

        queries = []
        for q in raw.get("queries", []):
            sql = (q.get("sql", "")
                   .replace("{catalog}", catalog)
                   .replace("{namespace}", namespace)
                   .replace("{table}", table))

            # Auto-cast for Hive CSV: replace bare column refs with CAST
            if catalog == "hive":
                import re
                cast_map = {
                    "int32": "INTEGER", "int64": "BIGINT",
                    "float32": "REAL", "float64": "DOUBLE",
                    "boolean": "BOOLEAN",
                }
                for col_name, col_type in col_types.items():
                    if col_name not in sql:
                        continue
                    if col_type == "timestamp":
                        # Use from_iso8601_timestamp for ISO format timestamps
                        sql = re.sub(
                            rf'\b{re.escape(col_name)}\b(?!\s*\.)',
                            f"from_iso8601_timestamp({col_name})",
                            sql,
                        )
                    else:
                        trino_type = cast_map.get(col_type)
                        if trino_type:
                            sql = re.sub(
                                rf'\b{re.escape(col_name)}\b(?!\s*\.)',
                                f"CAST({col_name} AS {trino_type})",
                                sql,
                            )
            queries.append({
                "id": q.get("id", ""),
                "name": q.get("name", ""),
                "sql": sql.strip(),
                "chart_type": q.get("chart_type", ""),
            })
        return raw, queries

    if scenario_id == "all":
        if not os.path.isdir(datasets_dir):
            return {"scenarios": []}
        scenarios = []
        for fname in sorted(os.listdir(datasets_dir)):
            if not fname.endswith(".yaml"):
                continue
            sid = fname[: -len(".yaml")]
            yaml_path = os.path.join(datasets_dir, fname)
            try:
                raw, queries = _load_queries_from_yaml(yaml_path)
                scenarios.append({
                    "id": raw.get("id", sid),
                    "name": raw.get("name", sid),
                    "queries": queries,
                })
            except Exception:
                pass
        return {"scenarios": scenarios}

    yaml_path = os.path.join(datasets_dir, f"{scenario_id}.yaml")
    if not os.path.exists(yaml_path):
        raise HTTPException(404, f"Scenario '{scenario_id}' not found")

    raw, queries = _load_queries_from_yaml(yaml_path)
    return {"scenario_id": scenario_id, "queries": queries}


class TrinoQueryRequest(BaseModel):
    sql: str


@router.post("/api/demos/{demo_id}/trino-query")
async def execute_trino_query(demo_id: str, req: TrinoQueryRequest):
    """Execute a SQL query against the Trino container for this demo."""
    import time
    import json as _json

    running = state.get_demo(demo_id)
    if not running:
        raise HTTPException(404, "Demo not running")

    # Find the Trino container
    trino_container = None
    for node_id, container in running.containers.items():
        if container.component_id == "trino":
            trino_container = container.container_name
            break

    if not trino_container:
        raise HTTPException(404, "No Trino container found in this demo")

    sql = req.sql.strip()
    if not sql:
        raise HTTPException(400, "SQL query is empty")

    # Escape the SQL for shell: use shlex.quote on the full trino --execute arg
    trino_cmd = f"trino --output-format=JSON --execute {shlex.quote(sql)}"
    shell_cmd = f"sh -c {shlex.quote(trino_cmd)}"

    start_ms = time.time()
    try:
        exit_code, stdout, stderr = await exec_in_container(trino_container, shell_cmd)
    except Exception as e:
        raise HTTPException(500, f"Failed to exec in Trino container: {e}")

    duration_ms = int((time.time() - start_ms) * 1000)

    if exit_code != 0:
        error_msg = (stderr or stdout or "Query failed").strip()
        return {
            "columns": [],
            "rows": [],
            "row_count": 0,
            "duration_ms": duration_ms,
            "error": error_msg,
        }

    # Parse JSON output: each line is a JSON object (one row per line)
    # First line contains the header row with column names
    lines = [ln for ln in stdout.splitlines() if ln.strip()]
    if not lines:
        return {"columns": [], "rows": [], "row_count": 0, "duration_ms": duration_ms}

    columns: list[str] = []
    rows: list[list] = []
    for i, line in enumerate(lines[:1001]):  # cap at 1001 to detect overflow
        try:
            obj = _json.loads(line)
        except Exception:
            continue
        if i == 0:
            columns = list(obj.keys())
        rows.append([obj.get(col) for col in columns])

    truncated = len(rows) > 1000
    if truncated:
        rows = rows[:1000]

    return {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "duration_ms": duration_ms,
        "truncated": truncated,
    }


@router.post("/api/demos/{demo_id}/setup-tables")
async def setup_tables(demo_id: str):
    """Ensure all Iceberg tables exist for all dataset scenarios.

    Creates missing tables in Trino's iceberg.demo schema based on
    the scenario YAML definitions. Safe to call multiple times.
    """
    running = state.get_demo(demo_id)
    if not running:
        raise HTTPException(404, "Demo not running")

    # Find Trino container
    trino_container = None
    for node_id, container in running.containers.items():
        if container.component_id == "trino":
            trino_container = container.container_name
            break
    if not trino_container:
        raise HTTPException(404, "No Trino container found in this demo")

    # Detect primary catalog from demo definition
    import os as _os
    import yaml as _yaml
    demo_def = _load_demo(demo_id)
    primary_catalog = "iceberg"
    if demo_def:
        trino_node_id = next((n.id for n in demo_def.nodes if n.component == "trino"), None)
        if trino_node_id:
            for edge in demo_def.edges:
                if edge.target == trino_node_id:
                    cat = (edge.connection_config or {}).get("catalog_name")
                    if cat:
                        primary_catalog = cat
                        break
        if primary_catalog == "iceberg":
            # Also detect AIStor via node config
            for n in demo_def.nodes:
                if n.component == "minio" and n.config.get("MINIO_EDITION", "ce") == "aistor":
                    primary_catalog = "aistor"
                    break
            for c in demo_def.clusters:
                if getattr(c, 'aistor_tables_enabled', False):
                    primary_catalog = "aistor"
                    break

    # Load all scenario YAMLs
    datasets_dir = _os.path.join(
        _os.environ.get("DEMOFORGE_COMPONENTS_DIR", "./components"),
        "data-generator", "datasets"
    )

    results = []
    type_map = {
        "string": "VARCHAR", "int32": "INTEGER", "int64": "BIGINT",
        "float32": "REAL", "float64": "DOUBLE", "boolean": "BOOLEAN",
        "timestamp": "TIMESTAMP", "date": "DATE",
    }

    # Ensure schema exists
    schema_cmd = f'trino --execute "CREATE SCHEMA IF NOT EXISTS {primary_catalog}.demo"'
    await exec_in_container(trino_container, schema_cmd)

    if not _os.path.isdir(datasets_dir):
        return {"results": [{"table": "?", "status": "error", "detail": f"Datasets dir not found: {datasets_dir}"}]}

    for fname in sorted(_os.listdir(datasets_dir)):
        if not fname.endswith(".yaml"):
            continue
        fpath = _os.path.join(datasets_dir, fname)
        with open(fpath, "r") as f:
            scenario = _yaml.safe_load(f)

        iceberg_cfg = scenario.get("iceberg", {}) or {}
        table_name = iceberg_cfg.get("table", scenario.get("id", fname.replace(".yaml", "")).replace("-", "_"))
        table_schema = iceberg_cfg.get("namespace", "demo")
        full_table = f"{primary_catalog}.{table_schema}.{table_name}"

        # Check if table exists
        check_cmd = f'trino --execute "SELECT 1 FROM {full_table} LIMIT 1"'
        exit_code, _, _ = await exec_in_container(trino_container, check_cmd)
        if exit_code == 0:
            results.append({"table": full_table, "status": "exists"})
            continue

        # Build and create table
        schema_block = scenario.get("schema", {})
        columns = schema_block.get("columns", []) if isinstance(schema_block, dict) else schema_block
        if not columns:
            results.append({"table": full_table, "status": "skipped", "detail": "No columns in schema"})
            continue

        col_defs = ", ".join(
            f"{col['name']} {type_map.get(col.get('type', 'string'), 'VARCHAR')}"
            for col in columns
        )
        create_sql = f"CREATE TABLE IF NOT EXISTS {full_table} ({col_defs}) WITH (format = 'PARQUET')"

        create_cmd = f'trino --execute "{create_sql}"'
        exit_code, stdout, stderr = await exec_in_container(trino_container, create_cmd)
        clean_err = "\n".join(l for l in (stderr or "").splitlines() if "jline" not in l and "WARNING" not in l).strip()
        if exit_code == 0 or "already exists" in clean_err.lower():
            results.append({"table": full_table, "status": "created"})
        else:
            results.append({"table": full_table, "status": "error", "detail": clean_err[:200]})

    # Create Hive external tables for data generators in raw write mode
    try:
        raw_generators = [
            n for n in demo_def.nodes
            if n.component == "data-generator"
            and n.config.get("DG_WRITE_MODE", "iceberg").lower() == "raw"
        ]
        if raw_generators:
            await exec_in_container(
                trino_container,
                'trino --execute "CREATE SCHEMA IF NOT EXISTS hive.raw"',
            )
            for gen_node in raw_generators:
                gen_fmt = gen_node.config.get("DG_FORMAT", "parquet").upper()
                gen_scenario = gen_node.config.get("DG_SCENARIO", "ecommerce-orders")
                # Find target bucket from edges
                gen_bucket = gen_node.config.get("S3_BUCKET", "raw-data")
                for edge in demo_def.edges:
                    if edge.source == gen_node.id and edge.connection_type in ("s3", "structured-data"):
                        edge_cfg = edge.connection_config or {}
                        gen_bucket = edge_cfg.get("target_bucket") or edge_cfg.get("bucket") or gen_bucket
                        break

                # Load scenario YAML for columns
                scenario_path = _os.path.join(datasets_dir, f"{gen_scenario}.yaml")
                if not _os.path.isfile(scenario_path):
                    continue
                with open(scenario_path, "r") as f:
                    scenario_def = _yaml.safe_load(f)

                iceberg_cfg = scenario_def.get("iceberg", {}) or {}
                table_name = iceberg_cfg.get("table", gen_scenario.replace("-", "_"))
                hive_table = f"hive.raw.{table_name}"

                # Check if hive table already exists
                hive_check = f'trino --execute "SELECT 1 FROM {hive_table} LIMIT 1"'
                exit_hive, _, _ = await exec_in_container(trino_container, hive_check)
                if exit_hive == 0:
                    results.append({"table": hive_table, "status": "exists"})
                    continue

                schema_block = scenario_def.get("schema", {})
                columns = schema_block.get("columns", []) if isinstance(schema_block, dict) else schema_block
                if not columns:
                    continue

                # CSV format requires all VARCHAR columns in Hive
                if gen_fmt == "CSV":
                    col_defs = ", ".join(f"{col['name']} VARCHAR" for col in columns)
                else:
                    col_defs = ", ".join(
                        f"{col['name']} {type_map.get(col.get('type', 'string'), 'VARCHAR')}"
                        for col in columns
                    )
                hive_sql = (
                    f"CREATE TABLE IF NOT EXISTS {hive_table} ({col_defs}) "
                    f"WITH (format = '{gen_fmt}', external_location = 's3a://{gen_bucket}/'"
                    f"{', skip_header_line_count = 1' if gen_fmt == 'CSV' else ''}"
                    f")"
                )
                hive_cmd = f'trino --execute "{hive_sql}"'
                exit_h, _, stderr_h = await exec_in_container(trino_container, hive_cmd)
                clean_h = "\n".join(
                    l for l in (stderr_h or "").splitlines()
                    if "jline" not in l and "WARNING" not in l
                ).strip()
                if exit_h == 0 or "already exists" in clean_h.lower():
                    results.append({"table": hive_table, "status": "created"})
                else:
                    results.append({"table": hive_table, "status": "error", "detail": clean_h[:200]})
    except Exception as exc:
        logger.debug(f"Hive external table creation skipped: {exc}")

    return {"results": results}


@router.post("/api/demos/{demo_id}/setup-metabase")
async def setup_metabase_dashboards(demo_id: str):
    """Auto-create Metabase dashboards for all active data generator scenarios.

    Resolves the correct Trino catalog (iceberg/aistor/hive) for each scenario
    based on the generator's write mode and target cluster.
    """
    import yaml as _yaml

    running = state.get_demo(demo_id)
    if not running:
        raise HTTPException(404, "Demo not running")

    # Find Metabase container
    metabase_container = None
    for node_id, container in running.containers.items():
        if container.component_id == "metabase":
            metabase_container = container.container_name
            break
    if not metabase_container:
        raise HTTPException(404, "No Metabase container in this demo")

    # Load demo definition for catalog routing
    demos_dir = os.environ.get("DEMOFORGE_DEMOS_DIR", "./demos")
    demo_path = os.path.join(demos_dir, f"{demo_id}.yaml")
    if not os.path.isfile(demo_path):
        raise HTTPException(404, "Demo definition not found")
    with open(demo_path) as f:
        demo_def = _yaml.safe_load(f)

    # Build scenario → (catalog, namespace) map
    components_dir = os.environ.get("DEMOFORGE_COMPONENTS_DIR", "./components")
    datasets_dir = os.path.join(os.path.abspath(components_dir), "data-generator", "datasets")

    scenario_catalog = {}
    for node in demo_def.get("nodes", []):
        if node.get("component") != "data-generator":
            continue
        cfg = node.get("config", {})
        sc = cfg.get("DG_SCENARIO", "ecommerce-orders")
        wm = cfg.get("DG_WRITE_MODE", "iceberg")
        if wm == "raw":
            scenario_catalog[sc] = ("hive", "raw")
        else:
            # Check if targeting AIStor cluster
            is_aistor = False
            for e in demo_def.get("edges", []):
                if e.get("source") == node.get("id") and e.get("connection_type") in ("structured-data", "s3"):
                    target = e.get("target", "")
                    for cl in demo_def.get("clusters", []):
                        if cl.get("id") == target and cl.get("aistor_tables_enabled"):
                            is_aistor = True
                            break
            scenario_catalog[sc] = ("aistor", "demo") if is_aistor else ("iceberg", "demo")

    # Create dashboards via exec in Metabase container (it has requests + python)
    # Actually, call Metabase API from the backend directly since we're on the same network
    results = []

    # Find Metabase URL — resolve from container
    metabase_url = f"http://{metabase_container}:3000"

    # Wait for Metabase to be ready
    import httpx
    async with httpx.AsyncClient(timeout=10) as client:
        for attempt in range(6):
            try:
                r = await client.get(f"{metabase_url}/api/health")
                if r.status_code == 200:
                    break
            except Exception:
                pass
            import asyncio
            await asyncio.sleep(5)
        else:
            return {"results": [{"status": "error", "detail": "Metabase not ready"}]}

    # Authenticate
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            auth_resp = await client.post(
                f"{metabase_url}/api/session",
                json={"username": "admin@demoforge.local", "password": "DemoForge123!"},
            )
            auth_resp.raise_for_status()
            mb_token = auth_resp.json()["id"]
    except Exception as exc:
        return {"results": [{"status": "error", "detail": f"Metabase auth failed: {exc}"}]}

    headers = {"X-Metabase-Session": mb_token, "Content-Type": "application/json"}

    # Find Trino database ID
    async with httpx.AsyncClient(timeout=15) as client:
        db_resp = await client.get(f"{metabase_url}/api/database", headers=headers)
        databases = db_resp.json().get("data", [])
        trino_db_id = None
        for db in databases:
            if "trino" in db.get("name", "").lower():
                trino_db_id = db["id"]
                break
        if not trino_db_id:
            return {"results": [{"status": "error", "detail": f"No Trino database in Metabase. Available: {[d['name'] for d in databases]}"}]}

    # Process each active scenario
    for scenario_id, (catalog, namespace) in scenario_catalog.items():
        yaml_path = os.path.join(datasets_dir, f"{scenario_id}.yaml")
        if not os.path.isfile(yaml_path):
            results.append({"scenario": scenario_id, "status": "skipped", "detail": "YAML not found"})
            continue

        with open(yaml_path) as f:
            scenario = _yaml.safe_load(f)

        dashboard_cfg = scenario.get("metabase_dashboard", {})
        if not dashboard_cfg:
            results.append({"scenario": scenario_id, "status": "skipped", "detail": "No dashboard config"})
            continue

        # Resolve queries with correct catalog
        queries = []
        for q in scenario.get("queries", []):
            sql = q.get("sql", "").replace("{catalog}", catalog).replace("{namespace}", namespace)

            # Auto-cast for Hive CSV
            if catalog == "hive":
                import re
                schema_block = scenario.get("schema", {})
                col_types = {}
                if isinstance(schema_block, dict):
                    for col in schema_block.get("columns", []):
                        col_types[col["name"]] = col.get("type", "string")
                cast_map = {"int32": "INTEGER", "int64": "BIGINT", "float32": "REAL", "float64": "DOUBLE", "boolean": "BOOLEAN"}
                for col_name, col_type in col_types.items():
                    if col_name not in sql:
                        continue
                    if col_type == "timestamp":
                        sql = re.sub(rf'\b{re.escape(col_name)}\b(?!\s*\.)', f"from_iso8601_timestamp({col_name})", sql)
                    elif col_type in cast_map:
                        sql = re.sub(rf'\b{re.escape(col_name)}\b(?!\s*\.)', f"CAST({col_name} AS {cast_map[col_type]})", sql)

            queries.append({**q, "sql": sql.strip()})

        # Check if dashboard already exists
        async with httpx.AsyncClient(timeout=15) as client:
            dash_list = await client.get(f"{metabase_url}/api/dashboard", headers=headers)
            existing = [d for d in dash_list.json() if d.get("name") == dashboard_cfg.get("name")]
            if existing:
                results.append({"scenario": scenario_id, "status": "exists", "dashboard_id": existing[0]["id"]})
                continue

        # Create cards and dashboard
        try:
            card_ids = {}
            async with httpx.AsyncClient(timeout=30) as client:
                for q in queries:
                    chart_type = q.get("chart_type", "table")
                    display, viz = _METABASE_CHART_MAP.get(chart_type, ("table", {}))
                    card_body = {
                        "name": q.get("name", q.get("id", "Untitled")),
                        "display": display,
                        "visualization_settings": viz,
                        "dataset_query": {
                            "type": "native",
                            "native": {"query": q["sql"]},
                            "database": trino_db_id,
                        },
                    }
                    card_resp = await client.post(f"{metabase_url}/api/card", json=card_body, headers=headers)
                    if card_resp.status_code in (200, 202):
                        card_ids[q["id"]] = card_resp.json()["id"]

                # Create dashboard
                dash_name = dashboard_cfg.get("name", f"{scenario.get('name')} Dashboard")
                dash_resp = await client.post(
                    f"{metabase_url}/api/dashboard",
                    json={"name": dash_name, "description": dashboard_cfg.get("description", "")},
                    headers=headers,
                )
                dash_id = dash_resp.json()["id"]

                # Add cards with layout
                layout = dashboard_cfg.get("layout", [])
                dashcards = []
                for item in layout:
                    card_id = card_ids.get(item.get("query"))
                    if card_id:
                        dashcards.append({
                            "id": -(len(dashcards) + 1),
                            "card_id": card_id,
                            "row": item.get("row", 0),
                            "col": item.get("col", 0),
                            "size_x": item.get("width", 4),
                            "size_y": item.get("height", 4),
                        })
                await client.put(
                    f"{metabase_url}/api/dashboard/{dash_id}",
                    json={"dashcards": dashcards},
                    headers=headers,
                )

            results.append({
                "scenario": scenario_id,
                "status": "created",
                "dashboard_id": dash_id,
                "cards": len(card_ids),
            })
        except Exception as exc:
            results.append({"scenario": scenario_id, "status": "error", "detail": str(exc)[:200]})

    return {"results": results}


# Chart type mapping for Metabase (matches metabase_setup.py)
_METABASE_CHART_MAP = {
    "bar": ("bar", {}),
    "line": ("line", {}),
    "pie": ("pie", {}),
    "donut": ("pie", {"pie.show_legend": True, "pie.percent_visibility": "inside"}),
    "horizontal_bar": ("bar", {"graph.x_axis.axis_enabled": True, "bar.horizontal": True}),
    "scalar": ("scalar", {}),
    "stacked_area": ("area", {"stackable.stack_type": "stacked"}),
    "pivot_table": ("pivot", {}),
    "table": ("table", {}),
}


def _build_superset_position_json(chart_layout: list) -> dict:
    """Build Superset dashboard position JSON from a simplified layout spec."""
    import json as _json
    position = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
        "GRID_ID": {
            "type": "GRID",
            "id": "GRID_ID",
            "children": [],
            "parents": ["ROOT_ID"],
        },
        "HEADER_ID": {
            "type": "HEADER",
            "id": "HEADER_ID",
            "meta": {"text": ""},
        },
    }
    rows: dict = {}
    for item in chart_layout:
        r = item["row"]
        rows.setdefault(r, []).append(item)
    for row_idx in sorted(rows.keys()):
        row_id = f"ROW-row{row_idx}"
        position["GRID_ID"]["children"].append(row_id)
        position[row_id] = {
            "type": "ROW",
            "id": row_id,
            "children": [],
            "parents": ["ROOT_ID", "GRID_ID"],
            "meta": {"background": "BACKGROUND_TRANSPARENT"},
        }
        for item in sorted(rows[row_idx], key=lambda x: x["col"]):
            chart_key = f"CHART-{item['chart_id']}"
            position[row_id]["children"].append(chart_key)
            position[chart_key] = {
                "type": "CHART",
                "id": chart_key,
                "children": [],
                "parents": ["ROOT_ID", "GRID_ID", row_id],
                "meta": {
                    "width": item["width"],
                    "height": item["height"],
                    "chartId": item["chart_id"],
                    "sliceName": item.get("name", ""),
                },
            }
    return position


def _build_superset_dashboard_specs() -> dict:
    """Return dashboard specs for all 5 DemoForge scenarios."""
    return {
        "ecommerce-orders": {
            "title": "Live Orders Analytics",
            "slug": "live-orders",
            "schema": "demo",
            "table": "orders",
            "charts": [
                {"name": "Orders: Total Count", "viz_type": "big_number_total", "params": {"metric": {"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "Total Orders"}, "header_font_size": 0.4, "y_axis_format": "SMART_NUMBER"}},
                {"name": "Orders: Total Revenue", "viz_type": "big_number_total", "params": {"metric": {"expressionType": "SQL", "sqlExpression": "SUM(total_amount)", "label": "Revenue"}, "header_font_size": 0.4, "y_axis_format": "$,.2f"}},
                {"name": "Orders: Avg Order Value", "viz_type": "big_number_total", "params": {"metric": {"expressionType": "SQL", "sqlExpression": "AVG(total_amount)", "label": "Avg Order"}, "header_font_size": 0.4, "y_axis_format": "$,.2f"}},
                {"name": "Orders: Orders/min", "viz_type": "echarts_timeseries_line", "params": {"x_axis": "order_ts", "time_grain_sqla": "PT1M", "metrics": [{"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "orders/min"}], "row_limit": 1000, "show_legend": False, "x_axis_time_format": "%H:%M"}},
                {"name": "Orders: Revenue by Region", "viz_type": "dist_bar", "params": {"groupby": ["region"], "metrics": [{"expressionType": "SQL", "sqlExpression": "SUM(total_amount)", "label": "Revenue"}], "row_limit": 50, "y_axis_format": "$,.0f", "color_scheme": "supersetColors", "show_bar_value": True}},
                {"name": "Orders: Top Products", "viz_type": "dist_bar", "params": {"groupby": ["product_name"], "metrics": [{"expressionType": "SQL", "sqlExpression": "SUM(total_amount)", "label": "Revenue"}], "row_limit": 10, "order_bars": True, "y_axis_format": "$,.0f", "show_bar_value": True}},
                {"name": "Orders: Categories", "viz_type": "pie", "params": {"groupby": ["category"], "metric": {"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "Orders"}, "donut": True, "show_labels": True, "label_type": "key_percent", "color_scheme": "supersetColors"}},
                {"name": "Orders: Payment Methods", "viz_type": "pie", "params": {"groupby": ["payment_method"], "metric": {"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "Orders"}, "donut": True, "show_labels": True, "label_type": "key_percent", "color_scheme": "supersetColors"}},
            ],
            "layout": [
                {"row": 0, "col": 0, "width": 4, "height": 8, "name": "Total Orders"},
                {"row": 0, "col": 4, "width": 4, "height": 8, "name": "Total Revenue"},
                {"row": 0, "col": 8, "width": 4, "height": 8, "name": "Avg Order Value"},
                {"row": 1, "col": 0, "width": 12, "height": 12, "name": "Orders/min"},
                {"row": 2, "col": 0, "width": 6, "height": 12, "name": "Revenue by Region"},
                {"row": 2, "col": 6, "width": 6, "height": 12, "name": "Top Products"},
                {"row": 3, "col": 0, "width": 6, "height": 12, "name": "Categories"},
                {"row": 3, "col": 6, "width": 6, "height": 12, "name": "Payment Methods"},
            ],
        },
        "iot-telemetry": {
            "title": "IoT Sensor Monitoring",
            "slug": "iot-sensors",
            "schema": "demo",
            "table": "sensor_readings",
            "charts": [
                {"name": "IoT: Total Readings", "viz_type": "big_number_total", "params": {"metric": {"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "Readings"}, "header_font_size": 0.4, "y_axis_format": "SMART_NUMBER"}},
                {"name": "IoT: Active Sensors", "viz_type": "big_number_total", "params": {"metric": {"expressionType": "SQL", "sqlExpression": "COUNT(DISTINCT device_id)", "label": "Sensors"}, "header_font_size": 0.4, "y_axis_format": "SMART_NUMBER"}},
                {"name": "IoT: Critical Alerts", "viz_type": "big_number_total", "params": {"metric": {"expressionType": "SQL", "sqlExpression": "COUNT(*) FILTER (WHERE alert_level = 'critical')", "label": "Critical"}, "header_font_size": 0.4, "y_axis_format": "SMART_NUMBER"}},
                {"name": "IoT: Readings/min", "viz_type": "echarts_timeseries_line", "params": {"x_axis": "reading_ts", "time_grain_sqla": "PT1M", "metrics": [{"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "readings/min"}], "row_limit": 1000, "show_legend": False, "x_axis_time_format": "%H:%M"}},
                {"name": "IoT: Alert Levels", "viz_type": "pie", "params": {"groupby": ["alert_level"], "metric": {"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "Count"}, "donut": True, "show_labels": True, "label_type": "key_percent", "color_scheme": "supersetColors"}},
                {"name": "IoT: Temp by Facility", "viz_type": "dist_bar", "params": {"groupby": ["facility"], "metrics": [{"expressionType": "SQL", "sqlExpression": "ROUND(AVG(temperature_c), 1)", "label": "Avg Temp (°C)"}], "y_axis_format": ",.1f", "show_bar_value": True}},
                {"name": "IoT: Battery Levels", "viz_type": "dist_bar", "params": {"groupby": ["battery_pct"], "metrics": [{"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "Sensors"}], "row_limit": 100}},
            ],
            "layout": [
                {"row": 0, "col": 0, "width": 4, "height": 8, "name": "Total Readings"},
                {"row": 0, "col": 4, "width": 4, "height": 8, "name": "Active Sensors"},
                {"row": 0, "col": 8, "width": 4, "height": 8, "name": "Critical Alerts"},
                {"row": 1, "col": 0, "width": 12, "height": 12, "name": "Readings/min"},
                {"row": 2, "col": 0, "width": 4, "height": 12, "name": "Alert Levels"},
                {"row": 2, "col": 4, "width": 4, "height": 12, "name": "Temp by Facility"},
                {"row": 2, "col": 8, "width": 4, "height": 12, "name": "Battery Levels"},
            ],
        },
        "financial-txn": {
            "title": "Financial Transactions Monitor",
            "slug": "financial-txns",
            "schema": "demo",
            "table": "transactions",
            "charts": [
                {"name": "Fin: Total Transactions", "viz_type": "big_number_total", "params": {"metric": {"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "Transactions"}, "header_font_size": 0.4, "y_axis_format": "SMART_NUMBER"}},
                {"name": "Fin: Total Volume", "viz_type": "big_number_total", "params": {"metric": {"expressionType": "SQL", "sqlExpression": "SUM(amount)", "label": "Volume"}, "header_font_size": 0.4, "y_axis_format": "$,.0f"}},
                {"name": "Fin: Flagged %", "viz_type": "big_number_total", "params": {"metric": {"expressionType": "SQL", "sqlExpression": "ROUND(100.0 * COUNT(*) FILTER (WHERE flagged = true) / NULLIF(COUNT(*), 0), 2)", "label": "Flagged %"}, "header_font_size": 0.4, "y_axis_format": ",.2f"}},
                {"name": "Fin: Txns/min", "viz_type": "echarts_timeseries_line", "params": {"x_axis": "txn_ts", "time_grain_sqla": "PT1M", "metrics": [{"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "txns/min"}], "row_limit": 1000, "show_legend": False, "x_axis_time_format": "%H:%M"}},
                {"name": "Fin: Volume by Currency", "viz_type": "dist_bar", "params": {"groupby": ["currency"], "metrics": [{"expressionType": "SQL", "sqlExpression": "SUM(amount)", "label": "Volume"}], "order_bars": True, "y_axis_format": "$,.0f", "show_bar_value": True}},
                {"name": "Fin: Channels", "viz_type": "pie", "params": {"groupby": ["channel"], "metric": {"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "Txns"}, "donut": True, "show_labels": True, "label_type": "key_percent"}},
                {"name": "Fin: High-Risk Accounts", "viz_type": "table", "params": {"query_mode": "raw", "all_columns": ["account_from", "country", "risk_score", "compliance_status", "amount", "txn_type"], "adhoc_filters": [{"expressionType": "SQL", "sqlExpression": "risk_score > 0.65", "clause": "WHERE"}], "row_limit": 50, "page_length": 15}},
            ],
            "layout": [
                {"row": 0, "col": 0, "width": 4, "height": 8, "name": "Total Txns"},
                {"row": 0, "col": 4, "width": 4, "height": 8, "name": "Total Volume"},
                {"row": 0, "col": 8, "width": 4, "height": 8, "name": "Flagged %"},
                {"row": 1, "col": 0, "width": 12, "height": 12, "name": "Txns/min"},
                {"row": 2, "col": 0, "width": 6, "height": 12, "name": "Volume by Currency"},
                {"row": 2, "col": 6, "width": 6, "height": 12, "name": "Channels"},
                {"row": 3, "col": 0, "width": 12, "height": 14, "name": "High-Risk Accounts"},
            ],
        },
        "clickstream": {
            "title": "Real-time Clickstream",
            "slug": "clickstream",
            "schema": "demo",
            "table": "clickstream",
            "charts": [
                {"name": "Click: Total Events", "viz_type": "big_number_total", "params": {"metric": {"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "Events"}, "header_font_size": 0.4, "y_axis_format": "SMART_NUMBER"}},
                {"name": "Click: Unique Sessions", "viz_type": "big_number_total", "params": {"metric": {"expressionType": "SQL", "sqlExpression": "COUNT(DISTINCT session_id)", "label": "Sessions"}, "header_font_size": 0.4, "y_axis_format": "SMART_NUMBER"}},
                {"name": "Click: Events/min", "viz_type": "echarts_timeseries_line", "params": {"x_axis": "event_ts", "time_grain_sqla": "PT1M", "metrics": [{"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "events/min"}], "row_limit": 1000, "show_legend": False, "x_axis_time_format": "%H:%M"}},
                {"name": "Click: Device Types", "viz_type": "pie", "params": {"groupby": ["device_type"], "metric": {"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "Events"}, "donut": True, "show_labels": True, "label_type": "key_percent"}},
                {"name": "Click: Top Pages", "viz_type": "dist_bar", "params": {"groupby": ["page_url"], "metrics": [{"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "Hits"}], "row_limit": 10, "order_bars": True, "show_bar_value": True}},
            ],
            "layout": [
                {"row": 0, "col": 0, "width": 6, "height": 8, "name": "Total Events"},
                {"row": 0, "col": 6, "width": 6, "height": 8, "name": "Unique Sessions"},
                {"row": 1, "col": 0, "width": 12, "height": 12, "name": "Events/min"},
                {"row": 2, "col": 0, "width": 4, "height": 12, "name": "Device Types"},
                {"row": 2, "col": 4, "width": 8, "height": 12, "name": "Top Pages"},
            ],
        },
        "customer-360": {
            "title": "Customer 360 Overview",
            "slug": "customer-360",
            "schema": "default",
            "table": "customer_360",
            "charts": [
                {"name": "C360: Total Customers", "viz_type": "big_number_total", "params": {"metric": {"expressionType": "SQL", "sqlExpression": "COUNT(DISTINCT customer_id)", "label": "Customers"}, "header_font_size": 0.4, "y_axis_format": "SMART_NUMBER"}},
                {"name": "C360: Total Volume", "viz_type": "big_number_total", "params": {"metric": {"expressionType": "SQL", "sqlExpression": "SUM(amount)", "label": "Volume"}, "header_font_size": 0.4, "y_axis_format": "$,.0f"}},
                {"name": "C360: Avg Transaction", "viz_type": "big_number_total", "params": {"metric": {"expressionType": "SQL", "sqlExpression": "ROUND(AVG(amount), 2)", "label": "Avg Txn"}, "header_font_size": 0.4, "y_axis_format": "$,.2f"}},
                {"name": "C360: Spend by Segment", "viz_type": "dist_bar", "params": {"groupby": ["segment"], "metrics": [{"expressionType": "SQL", "sqlExpression": "SUM(amount)", "label": "Total Spend"}], "y_axis_format": "$,.0f", "show_bar_value": True}},
                {"name": "C360: Countries", "viz_type": "pie", "params": {"groupby": ["country"], "metric": {"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "Transactions"}, "donut": True, "show_labels": True, "label_type": "key_percent"}},
                {"name": "C360: Top Merchants", "viz_type": "dist_bar", "params": {"groupby": ["merchant"], "metrics": [{"expressionType": "SQL", "sqlExpression": "SUM(amount)", "label": "Revenue"}], "row_limit": 10, "order_bars": True, "y_axis_format": "$,.0f", "show_bar_value": True}},
            ],
            "layout": [
                {"row": 0, "col": 0, "width": 4, "height": 8, "name": "Total Customers"},
                {"row": 0, "col": 4, "width": 4, "height": 8, "name": "Total Volume"},
                {"row": 0, "col": 8, "width": 4, "height": 8, "name": "Avg Transaction"},
                {"row": 1, "col": 0, "width": 6, "height": 12, "name": "Spend by Segment"},
                {"row": 1, "col": 6, "width": 6, "height": 12, "name": "Countries"},
                {"row": 2, "col": 0, "width": 12, "height": 12, "name": "Top Merchants"},
            ],
        },
    }


@router.post("/api/demos/{demo_id}/setup-superset")
async def setup_superset_dashboards(demo_id: str):
    """Auto-create Superset dashboards for all active data generator scenarios.

    Authenticates to Superset via JWT, creates a Trino database connection,
    registers datasets, and provisions dashboards for each active scenario.
    """
    import yaml as _yaml
    import json as _json

    running = state.get_demo(demo_id)
    if not running:
        raise HTTPException(404, "Demo not running")

    # Find Superset container
    superset_container = None
    for node_id, container in running.containers.items():
        if container.component_id == "superset":
            superset_container = container.container_name
            break
    if not superset_container:
        raise HTTPException(404, "No Superset container in this demo")

    # Load demo definition for catalog routing
    demos_dir = os.environ.get("DEMOFORGE_DEMOS_DIR", "./demos")
    demo_path = os.path.join(demos_dir, f"{demo_id}.yaml")
    if not os.path.isfile(demo_path):
        raise HTTPException(404, "Demo definition not found")
    with open(demo_path) as f:
        demo_def = _yaml.safe_load(f)

    # Build scenario → (catalog, namespace) map (same logic as Metabase)
    scenario_catalog: dict = {}
    for node in demo_def.get("nodes", []):
        if node.get("component") != "data-generator":
            continue
        cfg = node.get("config", {})
        sc = cfg.get("DG_SCENARIO", "ecommerce-orders")
        wm = cfg.get("DG_WRITE_MODE", "iceberg")
        if wm == "raw":
            scenario_catalog[sc] = ("hive", "raw")
        else:
            is_aistor = False
            for e in demo_def.get("edges", []):
                if e.get("source") == node.get("id") and e.get("connection_type") in ("structured-data", "s3"):
                    target = e.get("target", "")
                    for cl in demo_def.get("clusters", []):
                        if cl.get("id") == target and cl.get("aistor_tables_enabled"):
                            is_aistor = True
                            break
            # Also detect AIStor via minio node MINIO_EDITION config
            if not is_aistor:
                for n in demo_def.get("nodes", []):
                    if n.get("component") == "minio" and n.get("config", {}).get("MINIO_EDITION", "ce") == "aistor":
                        is_aistor = True
                        break
            scenario_catalog[sc] = ("aistor", "demo") if is_aistor else ("iceberg", "demo")

    # Wait for Superset to be ready (up to 60s) via health endpoint
    import httpx
    superset_url = f"http://{superset_container}:8088"
    async with httpx.AsyncClient(timeout=10) as client:
        for attempt in range(12):
            try:
                r = await client.get(f"{superset_url}/health")
                if r.status_code == 200:
                    break
            except Exception:
                pass
            await asyncio.sleep(5)
        else:
            return {"results": [{"status": "error", "detail": "Superset not ready after 60s"}]}

    # Find Trino container for URI
    trino_container = None
    for node_id, container in running.containers.items():
        if container.component_id == "trino":
            trino_container = container.container_name
            break

    primary_catalog = next(
        (cat for cat, _ in scenario_catalog.values()), "iceberg"
    )
    trino_uri = f"trino://demoforge@{trino_container or 'trino'}:8080/{primary_catalog}"

    dashboard_specs = _build_superset_dashboard_specs()
    results = []

    # Process each active scenario via docker exec (avoids Flask-Login/JWT auth issues)
    for scenario_id, (catalog, namespace) in scenario_catalog.items():
        spec = dashboard_specs.get(scenario_id)
        if not spec:
            results.append({"scenario": scenario_id, "status": "skipped", "detail": "No Superset dashboard spec"})
            continue

        try:
            charts_json = _json.dumps(spec["charts"])
            layout_json = _json.dumps(spec["layout"])
            script = (
                "import os, json, sys\n"
                "os.environ['SUPERSET_CONFIG_PATH'] = '/app/superset_config.py'\n"
                "from superset.app import create_app\n"
                "app = create_app()\n"
                "with app.app_context():\n"
                "    from superset import db, security_manager\n"
                "    from superset.models.core import Database\n"
                "    from superset.connectors.sqla.models import SqlaTable\n"
                "    from superset.models.slice import Slice\n"
                "    from superset.models.dashboard import Dashboard\n"
                "    from flask_login import login_user\n"
                "    admin = security_manager.find_user('admin')\n"
                "    with app.test_request_context():\n"
                "        login_user(admin)\n"
                f"        trino_uri = {_json.dumps(trino_uri)}\n"
                f"        schema = {_json.dumps(spec['schema'])}\n"
                f"        table_name = {_json.dumps(spec['table'])}\n"
                f"        dash_title = {_json.dumps(spec['title'])}\n"
                f"        dash_slug = {_json.dumps(spec['slug'])}\n"
                f"        charts_spec = json.loads({_json.dumps(charts_json)})\n"
                f"        layout_spec = json.loads({_json.dumps(layout_json)})\n"
                "        database = db.session.query(Database).filter_by(database_name='DemoForge Trino').first()\n"
                "        if not database:\n"
                "            database = Database(database_name='DemoForge Trino', sqlalchemy_uri=trino_uri, expose_in_sqllab=True, allow_run_async=False)\n"
                "            db.session.add(database)\n"
                "            db.session.commit()\n"
                "        table = db.session.query(SqlaTable).filter_by(database_id=database.id, schema=schema, table_name=table_name).first()\n"
                "        if not table:\n"
                "            table = SqlaTable(table_name=table_name, schema=schema, database_id=database.id)\n"
                "            db.session.add(table)\n"
                "            db.session.commit()\n"
                "        chart_ids = []\n"
                "        for cs in charts_spec:\n"
                "            ch = db.session.query(Slice).filter_by(slice_name=cs['name']).first()\n"
                "            if not ch:\n"
                "                ch = Slice(slice_name=cs['name'], viz_type=cs['viz_type'], datasource_id=table.id, datasource_type='table', params=json.dumps(cs['params']))\n"
                "                db.session.add(ch)\n"
                "            else:\n"
                "                ch.params = json.dumps(cs['params'])\n"
                "            db.session.commit()\n"
                "            chart_ids.append(ch.id)\n"
                "        dash = db.session.query(Dashboard).filter_by(slug=dash_slug).first()\n"
                "        if not dash:\n"
                "            slices = [db.session.get(Slice, cid) for cid in chart_ids]\n"
                "            dash = Dashboard(dashboard_title=dash_title, slug=dash_slug, published=True, slices=slices)\n"
                "            db.session.add(dash)\n"
                "            db.session.commit()\n"
                "        meta = json.loads(dash.json_metadata or '{}')\n"
                "        meta['refresh_frequency'] = 60\n"
                "        meta['stagger_refresh'] = False\n"
                "        meta['timed_refresh_immune_slices'] = []\n"
                "        dash.json_metadata = json.dumps(meta)\n"
                "        db.session.commit()\n"
                "        # Grant Public role Admin-level permissions so unauthenticated users see dashboards\n"
                "        admin_role = security_manager.find_role('Admin')\n"
                "        public_role = security_manager.find_role('Public')\n"
                "        if admin_role and public_role:\n"
                "            public_role.permissions = list(admin_role.permissions)\n"
                "            db.session.commit()\n"
                "        print(json.dumps({'status': 'created', 'dashboard_id': dash.id, 'charts': len(chart_ids)}))\n"
            )
            proc = await asyncio.create_subprocess_exec(
                "docker", "exec", superset_container, "python3", "-c", script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=90)
            if proc.returncode == 0:
                output = stdout.decode().strip().splitlines()
                # Last line should be the JSON result
                for line in reversed(output):
                    try:
                        result = _json.loads(line)
                        results.append({"scenario": scenario_id, **result})
                        break
                    except Exception:
                        continue
                else:
                    results.append({"scenario": scenario_id, "status": "error", "detail": stdout.decode()[-200:]})
            else:
                results.append({"scenario": scenario_id, "status": "error", "detail": stderr.decode()[-300:]})
        except Exception as exc:
            results.append({"scenario": scenario_id, "status": "error", "detail": str(exc)[:200]})

    return {"results": results}


# ---------------------------------------------------------------------------
# Pool decommission endpoints
# ---------------------------------------------------------------------------

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

    return {"status": "started", "pool_id": pool_id, "output": stdout.strip()}


@router.get("/api/demos/{demo_id}/clusters/{cluster_id}/pools/{pool_id}/decommission/status")
async def get_pool_decommission_status(demo_id: str, cluster_id: str, pool_id: str):
    """Get the decommission status of a server pool."""
    running = state.get_demo(demo_id)
    if not running:
        raise HTTPException(404, "Demo not running")

    mc_shell, alias, cluster = _get_mc_shell_and_alias(demo_id, cluster_id, running)
    pool_args = _build_pool_args(demo_id, cluster_id, pool_id, cluster)

    exit_code, stdout, stderr = await exec_in_container(
        mc_shell,
        f"mc admin decommission status {alias} '{pool_args}'"
    )

    raw = stdout.strip()
    lower = raw.lower()
    if "complete" in lower or "decommissioned" in lower:
        parsed_status = "decommissioned"
    elif "decommission" in lower and exit_code == 0:
        parsed_status = "decommissioning"
    else:
        parsed_status = "active"

    return {"pool_id": pool_id, "raw": raw, "status": parsed_status}


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

    return {"status": "cancelled", "pool_id": pool_id, "output": stdout.strip()}
