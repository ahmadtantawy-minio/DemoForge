import os
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .registry.loader import load_registry
from .engine.health_monitor import health_monitor_loop
from .api import registry, demos, deploy, instances, proxy, terminal, health

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    components_dir = os.environ.get("DEMOFORGE_COMPONENTS_DIR", "./components")
    load_registry(components_dir)
    monitor_task = asyncio.create_task(health_monitor_loop())
    yield
    # Shutdown
    monitor_task.cancel()

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

# Proxy routes (must be last — catch-all pattern)
app.include_router(proxy.router)
