import os
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .registry.loader import load_registry
from .engine.health_monitor import health_monitor_loop
from .engine.network_manager import join_network
from .state.store import state
from .api import registry, demos, deploy, instances, proxy, terminal, health, settings, cockpit, minio_actions, config_export, templates, mcp_proxy

logger = logging.getLogger(__name__)


async def docker_sync_loop():
    """Periodically reconcile in-memory state with Docker reality."""
    while True:
        await asyncio.sleep(10)
        try:
            await asyncio.to_thread(state.sync_with_docker)
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
    state.recover_from_docker()
    await _rejoin_recovered_networks()
    monitor_task = asyncio.create_task(health_monitor_loop())
    sync_task = asyncio.create_task(docker_sync_loop())
    yield
    # Shutdown
    monitor_task.cancel()
    sync_task.cancel()

app = FastAPI(title="DemoForge API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
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

# Proxy routes (must be last — catch-all pattern)
app.include_router(proxy.router)
