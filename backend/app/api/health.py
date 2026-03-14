import shutil
import asyncio
from fastapi import APIRouter, HTTPException
from ..state.store import state
from ..engine.docker_manager import get_container_health

router = APIRouter()

@router.get("/api/health")
async def global_health():
    return {"status": "ok"}

@router.get("/api/health/system")
async def system_health():
    """Check critical backend prerequisites for deployment."""
    checks = {}

    # Docker CLI available?
    checks["docker_cli"] = shutil.which("docker") is not None

    # Docker daemon reachable?
    try:
        import docker
        client = docker.from_env()
        client.ping()
        checks["docker_daemon"] = True
    except Exception as e:
        checks["docker_daemon"] = False
        checks["docker_daemon_error"] = str(e)

    # Docker Compose available?
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "compose", "version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        checks["docker_compose"] = proc.returncode == 0
        if proc.returncode == 0:
            checks["docker_compose_version"] = stdout.decode().strip()
    except Exception:
        checks["docker_compose"] = False

    # Docker socket mounted?
    import os
    checks["docker_socket"] = os.path.exists("/var/run/docker.sock")

    # Host path env vars set? (needed for bind mounts)
    checks["host_data_dir"] = bool(os.environ.get("DEMOFORGE_HOST_DATA_DIR"))
    checks["host_components_dir"] = bool(os.environ.get("DEMOFORGE_HOST_COMPONENTS_DIR"))

    # Components loaded?
    from ..registry.loader import get_registry
    registry = get_registry()
    checks["components_loaded"] = len(registry)

    all_ok = all([
        checks["docker_cli"],
        checks["docker_daemon"],
        checks["docker_compose"],
        checks["docker_socket"],
        checks["host_data_dir"],
        checks["host_components_dir"],
        checks["components_loaded"] > 0,
    ])

    return {"status": "ok" if all_ok else "degraded", "checks": checks}

@router.get("/api/demos/{demo_id}/instances/{node_id}/health")
async def get_health(demo_id: str, node_id: str):
    running = state.get_demo(demo_id)
    if not running or node_id not in running.containers:
        raise HTTPException(404, "Instance not found")
    container = running.containers[node_id]
    health = await get_container_health(container.container_name)
    return {"node_id": node_id, "health": health.value}
