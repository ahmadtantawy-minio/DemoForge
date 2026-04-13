from contextlib import asynccontextmanager

from fastapi import FastAPI

from .database import init_db
from .routers import admin, events, fa, licenses, templates, version


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="DemoForge Hub API", version="0.1.0", lifespan=lifespan)

app.include_router(fa.router, prefix="/api/hub/fa", tags=["fa"])
app.include_router(events.router, prefix="/api/hub", tags=["events"])
app.include_router(admin.router, prefix="/api/hub/admin", tags=["admin"])
app.include_router(templates.router, prefix="/api/hub/templates", tags=["templates"])
app.include_router(licenses.router, prefix="/api/hub/licenses", tags=["licenses"])
app.include_router(licenses.router, prefix="/licenses", tags=["licenses"])
app.include_router(version.router, prefix="/api/hub/version", tags=["version"])


@app.get("/api/hub/health")
async def health():
    return {"status": "ok", "service": "demoforge-hub-api"}
