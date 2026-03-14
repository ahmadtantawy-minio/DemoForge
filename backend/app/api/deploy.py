import os
import asyncio
import logging
from fastapi import APIRouter, HTTPException
from ..models.api_models import DeployResponse
from ..engine.docker_manager import deploy_demo, stop_demo
from ..state.store import state, DeployProgress
from .demos import _load_demo

logger = logging.getLogger(__name__)
router = APIRouter()
DATA_DIR = os.environ.get("DEMOFORGE_DATA_DIR", "./data")
COMPONENTS_DIR = os.environ.get("DEMOFORGE_COMPONENTS_DIR", "./components")

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

    # Create progress tracker
    progress = DeployProgress()
    state.deploy_progress[demo_id] = progress

    async def on_progress(step: str, status: str, detail: str = ""):
        progress.add(step, status, detail)

    try:
        logger.info(f"Deploying demo {demo_id} with {len(demo.nodes)} nodes")
        running = await deploy_demo(demo, DATA_DIR, COMPONENTS_DIR, on_progress=on_progress)
        progress.finished = True
        logger.info(f"Demo {demo_id} deployed successfully: {running.status}")
        return DeployResponse(demo_id=demo_id, status=running.status)
    except Exception as e:
        progress.add("error", "error", str(e))
        progress.finished = True
        logger.exception(f"Deploy failed for demo {demo_id}")
        return DeployResponse(demo_id=demo_id, status="error", message=str(e))

@router.get("/api/demos/{demo_id}/deploy/progress")
async def deploy_progress(demo_id: str):
    """Poll deployment progress."""
    progress = state.deploy_progress.get(demo_id)
    if not progress:
        return {"steps": [], "finished": True}
    result = progress.to_dict()
    # Clean up after client reads finished state
    if progress.finished:
        state.deploy_progress.pop(demo_id, None)
    return result

@router.post("/api/demos/{demo_id}/stop", response_model=DeployResponse)
async def stop(demo_id: str):
    """Stop a demo. Returns immediately; cleanup runs in background."""
    logger.info(f"Stopping demo {demo_id}")

    # Mark as stopped in state immediately so UI updates fast
    running = state.get_demo(demo_id)
    if running:
        running.status = "stopped"

    # Run actual cleanup in background (compose down, container removal, etc.)
    async def _bg_stop():
        try:
            await stop_demo(demo_id)
            logger.info(f"Demo {demo_id} stopped and cleaned up")
        except Exception as e:
            logger.exception(f"Background stop cleanup failed for {demo_id}")

    asyncio.create_task(_bg_stop())
    return DeployResponse(demo_id=demo_id, status="stopped")
