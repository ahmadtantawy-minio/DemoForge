import asyncio
from fastapi import APIRouter, HTTPException
from ..state.store import state
from ..registry.loader import get_component
from ..engine.docker_manager import get_container_health, restart_container, exec_in_container
from ..models.api_models import (
    InstancesResponse, ContainerInstance, WebUILink,
    ExecRequest, ExecResponse, NetworkMembership, CredentialInfo,
    EdgeConfigStatus,
)
from .demos import _load_demo

router = APIRouter()

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

@router.post("/api/demos/{demo_id}/edges/{edge_id}/activate")
async def activate_edge_config(demo_id: str, edge_id: str):
    """Activate a paused edge config (run the mc commands)."""
    running = state.get_demo(demo_id)
    if not running:
        raise HTTPException(404, "Demo not running")

    # Load demo definition and regenerate scripts
    from .demos import _load_demo
    demo = _load_demo(demo_id)
    if not demo:
        raise HTTPException(404, "Demo definition not found")

    from ..engine.edge_automation import generate_edge_scripts
    from ..engine.compose_generator import generate_compose
    from ..state.store import EdgeConfigResult
    import os
    project_name = f"demoforge-{demo_id}"
    # Run compose generation to expand clusters (modifies demo.nodes/edges in-place)
    data_dir = os.environ.get("DEMOFORGE_DATA_DIR", "./data")
    components_dir = os.environ.get("DEMOFORGE_COMPONENTS_DIR", "./components")
    try:
        generate_compose(demo, data_dir, components_dir)
    except Exception:
        pass  # We only need the edge expansion, not the file output
    scripts = generate_edge_scripts(demo, project_name)

    # Find matching script — try exact match, then with -cluster suffix, then stripped
    script = next((s for s in scripts if s.edge_id == edge_id), None)
    if not script:
        script = next((s for s in scripts if s.edge_id == f"{edge_id}-cluster"), None)
        if script:
            edge_id = f"{edge_id}-cluster"
    if not script:
        # Try stripping -cluster suffix from input
        stripped = edge_id
        while stripped.endswith("-cluster"):
            stripped = stripped[:-8]
        script = next((s for s in scripts if s.edge_id == stripped or s.edge_id.startswith(stripped)), None)
        if script:
            edge_id = script.edge_id
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
            script.container_name, f"sh -c '{script.command}'"
        )
        if exit_code != 0:
            ec.status = "failed"
            ec.error = stderr[:500]
            state.set_demo(running)
            return {"status": "failed", "edge_id": edge_id, "error": stderr[:500]}
        else:
            ec.status = "applied"
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
    """Pause an edge config."""
    running = state.get_demo(demo_id)
    if not running:
        raise HTTPException(404, "Demo not running")

    # Fuzzy match: try exact, then with -cluster suffixes, then partial match
    ec = running.edge_configs.get(edge_id)
    if not ec:
        # Try appending -cluster repeatedly
        candidate = edge_id
        for _ in range(3):
            candidate = f"{candidate}-cluster"
            ec = running.edge_configs.get(candidate)
            if ec:
                edge_id = candidate
                break
    if not ec:
        # Try partial match — find any config whose ID starts with the input
        for key, val in running.edge_configs.items():
            if key.startswith(edge_id) or edge_id.startswith(key):
                ec = val
                edge_id = key
                break
    if not ec:
        raise HTTPException(404, f"Edge config '{edge_id}' not found")

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
