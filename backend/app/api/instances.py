import asyncio
import logging
import os
import shlex
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from ..state.store import state, EdgeConfigResult
from ..registry.loader import get_component
from ..engine.docker_manager import get_container_health, restart_container, exec_in_container, docker_client
from ..engine.edge_automation import (
    generate_edge_scripts, _get_credential, _safe, _find_cluster,
    _get_cluster_credentials, _resolve_cluster_endpoint,
)
from ..engine.compose_generator import generate_compose
from ..models.api_models import (
    InstancesResponse, ContainerInstance, WebUILink,
    ExecRequest, ExecResponse, NetworkMembership, CredentialInfo,
    EdgeConfigStatus,
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

    instances = []
    for node_id, container in running.containers.items():
        manifest = get_component(container.component_id)
        health = await get_container_health(container.container_name)
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
            init_status="completed",
        ))

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
        demo.nodes.append(DemoNode(id=lb_node_id, component="nginx", variant="load-balancer",
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

    alias = _re.sub(r"[^a-zA-Z0-9_]", "_", cluster.label)
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
    """Start the data-generator with the given scenario/format/rate_profile."""
    running = state.get_demo(demo_id)
    if not running or node_id not in running.containers:
        raise HTTPException(404, "Instance not found")
    container_name = running.containers[node_id].container_name
    # Stop any existing run first
    stop_cmd = "sh -c 'touch /tmp/gen.stop; [ -f /tmp/gen.pid ] && kill $(cat /tmp/gen.pid) 2>/dev/null; rm -f /tmp/gen.pid /tmp/gen.stop; sleep 0.5'"
    await exec_in_container(container_name, stop_cmd)
    # Start with the requested config as env vars
    start_cmd = (
        f"sh -c 'export DG_SCENARIO={shlex.quote(req.scenario)} "
        f"DG_FORMAT={shlex.quote(req.format)} "
        f"DG_RATE_PROFILE={shlex.quote(req.rate_profile)}; "
        f"nohup python3 /app/generate.py > /tmp/gen.log 2>&1 & PID=$!; echo $PID > /tmp/gen.pid; echo started'"
    )
    try:
        exit_code, stdout, stderr = await exec_in_container(container_name, start_cmd)
        if exit_code != 0:
            raise HTTPException(500, stderr or stdout)
        return {"state": "ramp_up", "scenario": req.scenario, "format": req.format, "rate_profile": req.rate_profile}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/api/demos/{demo_id}/generator-stop/{node_id}")
async def stop_generator(demo_id: str, node_id: str):
    """Stop the data-generator by touching /tmp/gen.stop and killing the PID."""
    running = state.get_demo(demo_id)
    if not running or node_id not in running.containers:
        raise HTTPException(404, "Instance not found")
    container_name = running.containers[node_id].container_name
    stop_cmd = "sh -c 'touch /tmp/gen.stop; [ -f /tmp/gen.pid ] && kill $(cat /tmp/gen.pid) 2>/dev/null; rm -f /tmp/gen.pid; echo stopped'"
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
        if n.component in ("minio", "minio-aistore")
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
