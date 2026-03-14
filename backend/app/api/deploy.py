import os
import asyncio
import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from ..models.api_models import DeployResponse, ErrorDetail
from ..engine.docker_manager import deploy_demo, stop_demo
from ..state.store import state, DeployProgress
from ..config.license_store import license_store
from ..registry.loader import get_component
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

    # Validate required licenses
    for node in demo.nodes:
        manifest = get_component(node.component)
        if manifest:
            for lic_req in manifest.license_requirements:
                if lic_req.required and not license_store.get(lic_req.license_id):
                    raise HTTPException(400,
                        f"Component '{manifest.name}' requires license '{lic_req.label}'. "
                        f"Configure it in Settings > Licenses.")

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

        err_str = str(e).lower()
        if any(kw in err_str for kw in ("connection refused", "cannot connect", "docker daemon", "error while fetching server api")):
            error = ErrorDetail(code="DOCKER_NOT_RUNNING", message="Docker is not running or not reachable", details=str(e))
            status_code = 503
        elif "component" in err_str and ("not found" in err_str or "unknown" in err_str):
            error = ErrorDetail(code="COMPONENT_NOT_FOUND", message="One or more components could not be found", details=str(e))
            status_code = 400
        elif any(kw in err_str for kw in ("compose", "exit code", "exited with")):
            error = ErrorDetail(code="COMPOSE_FAILED", message="Docker Compose failed to start containers", details=str(e))
            status_code = 500
        else:
            error = ErrorDetail(code="UNKNOWN_ERROR", message="Deploy failed with an unexpected error", details=str(e))
            status_code = 500

        return JSONResponse(status_code=status_code, content=error.model_dump())

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
