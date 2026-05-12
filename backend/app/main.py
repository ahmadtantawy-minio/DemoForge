import os
import asyncio
import logging
import time as _time
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .registry.loader import load_registry
from .engine.health_monitor import health_monitor_loop
from .engine.network_manager import join_network
from .state.store import state
from .api import registry, demos, deploy, instances, proxy, terminal, health, settings, cockpit, minio_actions, config_export, templates, mcp_proxy, mcp_chat, failover_status, resilience_status, sql, playbook, images as images_router, readiness as readiness_router, fa_admin as fa_admin_router, connectivity as connectivity_router, version as version_router, cluster_health, iam_reconcile_report

logger = logging.getLogger(__name__)


async def docker_sync_loop():
    """Periodically reconcile in-memory state with Docker reality."""
    while True:
        await asyncio.sleep(10)
        try:
            await asyncio.to_thread(state.sync_with_docker)
            await asyncio.to_thread(state.reconcile_deploying_from_docker)
        except Exception as e:
            logger.warning(f"Docker sync error: {e}")


async def _rejoin_recovered_networks():
    """After recovery, rejoin backend to all recovered demo networks."""
    for demo in state.list_demos():
        if demo.status == "running":
            for net_name in demo.networks:
                try:
                    await asyncio.to_thread(join_network, net_name)
                    logger.info(f"Rejoined network {net_name} for recovered demo {demo.demo_id}")
                except Exception as e:
                    logger.warning(f"Failed to rejoin network {net_name}: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    components_dir = os.environ.get("DEMOFORGE_COMPONENTS_DIR", "./components")
    load_registry(components_dir)
    await asyncio.to_thread(state.recover_from_docker)
    await _rejoin_recovered_networks()

    from .fa_identity import init_fa_identity
    await asyncio.to_thread(init_fa_identity)

    # Sync templates from remote (non-blocking, best-effort)
    # Only run in dev mode — FA boots from local cache
    _mode = os.getenv("DEMOFORGE_MODE", "dev")
    _startup_sync_result = None
    if _mode not in ("fa", "standard"):
        from .engine.template_sync import sync_templates
        try:
            _startup_sync_result = await asyncio.to_thread(sync_templates)
            logger.info(f"Template sync on startup: {_startup_sync_result}")
        except Exception as e:
            logger.warning(f"Template sync failed on startup (continuing with local): {e}")

    # Telemetry init (fire-and-forget, FA mode only)
    from .telemetry import init_telemetry, shutdown_telemetry, emit_event
    _hub_url = os.getenv("DEMOFORGE_HUB_URL", "").rstrip("/")
    _api_key = os.getenv("DEMOFORGE_API_KEY", "")
    await init_telemetry(
        hub_url=_hub_url,
        api_key=_api_key,
        enabled=(_mode == "fa" and bool(_api_key)),
    )
    app.state.start_time = _time.time()
    asyncio.create_task(emit_event("app_started", {"mode": _mode}))
    if _startup_sync_result is not None and _startup_sync_result.get("status") == "ok":
        asyncio.create_task(emit_event("template_synced", {
            "method": _startup_sync_result.get("method", "s3"),
            "downloaded": _startup_sync_result.get("downloaded", 0),
            "unchanged": _startup_sync_result.get("unchanged", 0),
            "deleted": _startup_sync_result.get("deleted", 0),
            "errors": _startup_sync_result.get("errors", 0),
        }))

    monitor_task = asyncio.create_task(health_monitor_loop())
    sync_task = asyncio.create_task(docker_sync_loop())
    yield
    # Shutdown
    uptime = int(_time.time() - getattr(app.state, "start_time", _time.time()))
    await emit_event("app_stopped", {"uptime_seconds": uptime})
    await shutdown_telemetry()
    monitor_task.cancel()
    sync_task.cancel()

# redirect_slashes=False: behind nginx, slash redirects can emit Location with the internal
# backend host unless X-Forwarded-* are trusted (see FORWARDED_ALLOW_IPS in compose).
app = FastAPI(
    title="DemoForge API",
    version="0.1.0",
    lifespan=lifespan,
    redirect_slashes=False,
)

# Browser origins for SPA + Vite dev (FA :3000, dev :3001, fa-local :3002, Vite :5173).
# API is on a different port than the UI, so the page Origin must be listed here.
_cors_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
    "http://localhost:3002",
    "http://127.0.0.1:3002",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
_extra = os.getenv("DEMOFORGE_CORS_ORIGINS", "").strip()
if _extra:
    _cors_origins.extend(o.strip() for o in _extra.split(",") if o.strip())

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(registry.router)
app.include_router(demos.router)
app.include_router(deploy.router)
app.include_router(instances.router)
app.include_router(health.router)
app.include_router(terminal.router)
app.include_router(settings.router)
app.include_router(cockpit.router)
app.include_router(minio_actions.router)
app.include_router(config_export.router)
app.include_router(templates.router)
app.include_router(mcp_proxy.router)
app.include_router(mcp_chat.router)
app.include_router(failover_status.router)
app.include_router(resilience_status.router)
app.include_router(sql.router)
app.include_router(playbook.router)
app.include_router(images_router.router)
app.include_router(readiness_router.router)
app.include_router(fa_admin_router.router)
app.include_router(connectivity_router.router)
app.include_router(version_router.router)
app.include_router(cluster_health.router)
app.include_router(iam_reconcile_report.router)

# Proxy routes (must be last — catch-all pattern)
app.include_router(proxy.router)
