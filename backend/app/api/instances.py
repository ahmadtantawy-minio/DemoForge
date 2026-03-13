from fastapi import APIRouter, HTTPException
from ..state.store import state
from ..registry.loader import get_component
from ..engine.docker_manager import get_container_health, restart_container, exec_in_container
from ..models.api_models import (
    InstancesResponse, ContainerInstance, WebUILink,
    ExecRequest, ExecResponse,
)

router = APIRouter()

@router.get("/api/demos/{demo_id}/instances", response_model=InstancesResponse)
async def list_instances(demo_id: str):
    running = state.get_demo(demo_id)
    if not running:
        raise HTTPException(404, "Demo not running")

    instances = []
    for node_id, container in running.containers.items():
        manifest = get_component(container.component_id)
        health = get_container_health(container.container_name)
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

        instances.append(ContainerInstance(
            node_id=node_id,
            component_id=container.component_id,
            container_name=container.container_name,
            health=health,
            web_uis=web_uis,
            has_terminal=True,
            quick_actions=quick_actions,
        ))

    return InstancesResponse(demo_id=demo_id, status=running.status, instances=instances)

@router.post("/api/demos/{demo_id}/instances/{node_id}/restart")
async def restart_instance(demo_id: str, node_id: str):
    running = state.get_demo(demo_id)
    if not running or node_id not in running.containers:
        raise HTTPException(404, "Instance not found")
    await restart_container(running.containers[node_id].container_name)
    return {"status": "restarted"}

@router.post("/api/demos/{demo_id}/instances/{node_id}/exec", response_model=ExecResponse)
async def exec_command(demo_id: str, node_id: str, req: ExecRequest):
    running = state.get_demo(demo_id)
    if not running or node_id not in running.containers:
        raise HTTPException(404, "Instance not found")
    exit_code, stdout, stderr = await exec_in_container(
        running.containers[node_id].container_name, req.command
    )
    return ExecResponse(exit_code=exit_code, stdout=stdout, stderr=stderr)
