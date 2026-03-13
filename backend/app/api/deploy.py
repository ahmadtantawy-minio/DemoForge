import os
from fastapi import APIRouter, HTTPException
from ..models.api_models import DeployResponse
from ..engine.docker_manager import deploy_demo, stop_demo
from ..state.store import state
from .demos import _load_demo

router = APIRouter()
DATA_DIR = os.environ.get("DEMOFORGE_DATA_DIR", "./data")

@router.post("/api/demos/{demo_id}/deploy", response_model=DeployResponse)
async def deploy(demo_id: str):
    demo = _load_demo(demo_id)
    if not demo:
        raise HTTPException(404, "Demo not found")
    if not demo.nodes:
        raise HTTPException(400, "Demo has no nodes to deploy")

    existing = state.get_demo(demo_id)
    if existing and existing.status == "running":
        raise HTTPException(409, "Demo is already running")

    try:
        running = await deploy_demo(demo, DATA_DIR)
        return DeployResponse(demo_id=demo_id, status=running.status)
    except Exception as e:
        return DeployResponse(demo_id=demo_id, status="error", message=str(e))

@router.post("/api/demos/{demo_id}/stop", response_model=DeployResponse)
async def stop(demo_id: str):
    try:
        await stop_demo(demo_id)
        return DeployResponse(demo_id=demo_id, status="stopped")
    except Exception as e:
        return DeployResponse(demo_id=demo_id, status="error", message=str(e))
