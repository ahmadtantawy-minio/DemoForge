import asyncio
import logging
import os
import shlex
from fastapi import APIRouter, HTTPException
from ..state.store import state, EdgeConfigResult
from ..registry.loader import get_component
from ..engine.docker_manager import get_container_health, restart_container, exec_in_container
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
        for net_name in container.networks:
            # Strip project prefix to get logical name for node.networks lookup
            logical_name = net_name.replace(project_prefix, "") if net_name.startswith(project_prefix) else net_name
            net_cfg = node_networks.get(logical_name)
            membership = NetworkMembership(
                network_name=logical_name,
                ip_address=net_cfg.ip if net_cfg else None,
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

    edge_configs = [
        EdgeConfigStatus(
            edge_id=ec.edge_id,
            connection_type=ec.connection_type,
            status=ec.status,
            description=ec.description,
            error=ec.error,
        )
        for ec in running.edge_configs.values()
    ]

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
    import docker
    client = docker.from_env()
    container_name = running.containers[node_id].container_name
    c = await asyncio.to_thread(client.containers.get, container_name)
    await asyncio.to_thread(c.stop, timeout=5)
    return {"status": "stopped", "node_id": node_id}

@router.post("/api/demos/{demo_id}/instances/{node_id}/start")
async def start_instance(demo_id: str, node_id: str):
    """Start a previously stopped container."""
    running = state.get_demo(demo_id)
    if not running or node_id not in running.containers:
        raise HTTPException(404, "Instance not found")
    import docker
    client = docker.from_env()
    container_name = running.containers[node_id].container_name
    c = await asyncio.to_thread(client.containers.get, container_name)
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

    # For site-replication and tiering, pause is not supported server-side
    if ec.connection_type in ("site-replication", "cluster-site-replication"):
        raise HTTPException(
            400,
            "Site replication cannot be paused. It must be fully removed and re-added.",
        )
    if ec.connection_type in ("tiering", "cluster-tiering"):
        raise HTTPException(
            400,
            "ILM tiering rules cannot be paused. The rule must be removed and re-created.",
        )

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
    return {"status": "paused", "edge_id": edge_id}

@router.post("/api/demos/{demo_id}/instances/{node_id}/exec", response_model=ExecResponse)
async def exec_command(demo_id: str, node_id: str, req: ExecRequest):
    running = state.get_demo(demo_id)
    if not running or node_id not in running.containers:
        raise HTTPException(404, "Instance not found")
    exit_code, stdout, stderr = await exec_in_container(
        running.containers[node_id].container_name, req.command
    )
    return ExecResponse(exit_code=exit_code, stdout=stdout, stderr=stderr)
