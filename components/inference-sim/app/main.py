from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app.models import HealthResponse, SimConfig, SimStatus
from app.simulation.engine import engine
from app.simulation import metrics as sim_metrics


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure MinIO buckets exist on startup (non-blocking if disconnected)
    await engine.ensure_buckets()
    yield


app = FastAPI(title="Inference Memory Simulator", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        minio_g35_connected=engine.minio_g35.connected,
        minio_g4_connected=engine.minio_g4.connected,
    )


@app.get("/status", response_model=SimStatus)
async def status() -> SimStatus:
    return await engine.get_state()


@app.post("/sim/start", response_model=SimStatus)
async def sim_start(config: SimConfig | None = None) -> SimStatus:
    await engine.start(config)
    return await engine.get_state()


@app.post("/sim/stop", response_model=SimStatus)
async def sim_stop() -> SimStatus:
    await engine.stop()
    return await engine.get_state()


@app.post("/sim/config", response_model=SimStatus)
async def sim_config(request: Request) -> SimStatus:
    raw = await request.json()
    await engine.update_config_partial(raw)
    return await engine.get_state()


@app.post("/sim/reset", response_model=SimStatus)
async def sim_reset() -> SimStatus:
    await engine.reset()
    return await engine.get_state()


@app.websocket("/sim/stream")
async def sim_stream(websocket: WebSocket) -> None:
    await websocket.accept()
    engine.register_ws(websocket)
    try:
        while True:
            # Keep connection alive; engine broadcasts at 5 Hz
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass
    finally:
        engine.unregister_ws(websocket)


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics() -> str:
    state = await engine.get_state()
    sim_metrics.update_metrics(state.model_dump())
    return sim_metrics.generate_latest().decode("utf-8")


# Mount static files for the visualization UI (built by a separate agent)
import os

_static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(_static_dir):
    app.mount("/", StaticFiles(directory=_static_dir, html=True), name="static")
