import os
import time
import asyncio
import logging
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from ..models.api_models import DeployResponse, ErrorDetail, TaskStatusResponse
from ..engine.docker_manager import deploy_demo, stop_demo, pause_demo, resume_demo
from ..engine.task_manager import cancel_running_task as _cancel_running_task
from ..engine import task_manager
from ..state.store import state, DeployProgress
from ..config.license_store import license_store
from ..registry.loader import get_component
from .demos import _load_demo

logger = logging.getLogger(__name__)
router = APIRouter()
DATA_DIR = os.environ.get("DEMOFORGE_DATA_DIR", "./data")


async def wait_for_clean_state(demo_id: str, timeout: int = 30) -> bool:
    """Poll Docker until no containers labelled demoforge.demo_id={demo_id} remain."""
    def _check():
        import docker
        client = docker.from_env()
        containers = client.containers.list(
            all=True,
            filters={"label": f"demoforge.demo_id={demo_id}"}
        )
        client.close()
        return len(containers) == 0

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            clean = await asyncio.to_thread(_check)
            if clean:
                return True
        except Exception:
            return True  # Docker not available, skip check
        await asyncio.sleep(2)
    return False
COMPONENTS_DIR = os.environ.get("DEMOFORGE_COMPONENTS_DIR", "./components")


@router.post("/api/demos/{demo_id}/deploy", response_model=DeployResponse)
async def deploy(
    demo_id: str,
    fresh_volumes: bool = Query(
        False,
        description="Remove Docker volumes during pre-deploy cleanup (docker compose down -v). "
        "Use for a clean MinIO erasure layout when disks still hold an old cluster format.",
    ),
):
    """Queue full demo deploy."""
    demo = _load_demo(demo_id)
    if not demo:
        raise HTTPException(404, "Demo not found")
    if not demo.nodes and not demo.clusters:
        raise HTTPException(400, "Demo has no nodes to deploy")

    existing = state.get_demo(demo_id)
    if existing and existing.status == "running":
        raise HTTPException(409, "Demo is already running")

    if task_manager.is_operation_running(demo_id):
        raise HTTPException(409, "An operation is already in progress for this demo")

    # FA-mode readiness check
    mode = os.getenv("DEMOFORGE_MODE", "dev")
    if mode == "fa":
        from ..engine.readiness import readiness
        readiness.load()
        component_ids = [node.component for node in demo.nodes if node.component]
        component_ids += [cluster.component for cluster in (demo.clusters or []) if cluster.component]
        blocking = readiness.get_blocking_components(component_ids)
        if blocking:
            raise HTTPException(
                status_code=403,
                detail={
                    "message": "Demo contains components that are not yet available to Field Architects",
                    "blocking_components": blocking,
                },
            )
        from ..fa_permissions import permission_cache
        if not await permission_cache.check_permission("manual_demo_creation"):
            raise HTTPException(403, "Your account does not have permission to create demos manually.")

    # Drain guard: wait for previous containers to be fully removed
    if not await wait_for_clean_state(demo_id, timeout=30):
        raise HTTPException(409, "Previous deploy still cleaning up — retry in a few seconds")

    # Validate required licenses
    for node in demo.nodes:
        manifest = get_component(node.component)
        if manifest:
            for lic_req in manifest.license_requirements:
                if lic_req.required and not license_store.get(lic_req.license_id):
                    raise HTTPException(400,
                        f"Component '{manifest.name}' requires license '{lic_req.label}'. "
                        f"Configure it in Settings > Licenses.")

    # Create shared progress tracker (used by both /deploy/progress and /task/{task_id})
    progress = DeployProgress()
    state.deploy_progress[demo_id] = progress

    async def on_progress(step: str, status: str, detail: str = ""):
        progress.add(step, status, detail)

    async def _do_deploy():
        logger.info(
            f"Deploying demo {demo_id} with {len(demo.nodes)} nodes"
            + (" (fresh_volumes)" if fresh_volumes else "")
        )
        running = await deploy_demo(
            demo, DATA_DIR, COMPONENTS_DIR, on_progress=on_progress, fresh_volumes=fresh_volumes
        )
        logger.info(f"Demo {demo_id} deployed successfully: {running.status}")
        from ..telemetry import emit_event
        asyncio.create_task(emit_event("demo_deployed", {
            "demo_id": demo_id,
            "component_count": len(demo.nodes) + len(demo.clusters or []),
        }))

    task = await task_manager.submit_task(demo_id, "deploy", _do_deploy(), progress=progress)
    return JSONResponse(
        status_code=202,
        content={"demo_id": demo_id, "status": "queued", "task_id": task.task_id},
    )


@router.get("/api/demos/{demo_id}/deploy/progress")
async def deploy_progress(demo_id: str):
    """Poll deployment progress (legacy endpoint — prefer /task/{task_id})."""
    progress = state.deploy_progress.get(demo_id)
    if not progress:
        return {"steps": [], "finished": True}
    result = progress.to_dict()
    if progress.finished:
        state.deploy_progress.pop(demo_id, None)
    return result


@router.get("/api/demos/{demo_id}/task/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(demo_id: str, task_id: str):
    """Poll the status and progress of a background lifecycle task."""
    task = task_manager.get_task(task_id)
    if not task or task.demo_id != demo_id:
        raise HTTPException(404, "Task not found")
    return task.to_dict()


@router.post("/api/demos/{demo_id}/stop", response_model=DeployResponse)
async def stop(demo_id: str):
    """Stop containers (preserves volumes). Use /destroy to tear down completely."""
    if task_manager.is_operation_running(demo_id):
        raise HTTPException(409, "An operation is already in progress for this demo")
    logger.info(f"Pausing demo {demo_id}")
    running = state.get_demo(demo_id)
    if running:
        running.status = "stopping"

    async def _do_stop():
        try:
            await pause_demo(demo_id)
            if running:
                running.status = "stopped"
        except Exception:
            if running:
                running.status = "running"
            raise

    task = await task_manager.submit_task(demo_id, "stop", _do_stop())
    return JSONResponse(
        status_code=202,
        content={"demo_id": demo_id, "status": "queued", "task_id": task.task_id},
    )


@router.post("/api/demos/{demo_id}/destroy", response_model=DeployResponse)
async def destroy(demo_id: str):
    """Destroy containers and volumes. Full teardown."""
    # Cancel any in-progress deploy/stop task before proceeding — destroy must always work.
    if task_manager.is_operation_running(demo_id):
        logger.info(f"Cancelling in-progress task for demo {demo_id} before destroy")
        await _cancel_running_task(demo_id)
    logger.info(f"Destroying demo {demo_id}")
    running = state.get_demo(demo_id)
    if running:
        running.status = "stopping"

    async def _do_destroy():
        try:
            await stop_demo(demo_id, remove_volumes=True)
        finally:
            # Ensure demo is removed from state even if cleanup was cancelled or failed
            state.remove_demo(demo_id)
        logger.info(f"Demo {demo_id} destroyed and cleaned up")

    task = await task_manager.submit_task(demo_id, "destroy", _do_destroy())
    from ..telemetry import emit_event
    asyncio.create_task(emit_event("demo_stopped", {"demo_id": demo_id}))
    return JSONResponse(
        status_code=202,
        content={"demo_id": demo_id, "status": "queued", "task_id": task.task_id},
    )


@router.post("/api/demos/{demo_id}/start", response_model=DeployResponse)
async def start_stopped(demo_id: str):
    """Resume a previously stopped demo."""
    if task_manager.is_operation_running(demo_id):
        raise HTTPException(409, "An operation is already in progress for this demo")
    logger.info(f"Starting stopped demo {demo_id}")
    running = state.get_demo(demo_id)
    if not running:
        raise HTTPException(404, "Demo not found in state — use /deploy instead")
    running.status = "deploying"

    async def _do_start():
        try:
            await resume_demo(demo_id)
            running.status = "running"
        except Exception:
            running.status = "stopped"
            raise

    task = await task_manager.submit_task(demo_id, "start", _do_start())
    return JSONResponse(
        status_code=202,
        content={"demo_id": demo_id, "status": "queued", "task_id": task.task_id},
    )
