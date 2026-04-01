import os
import asyncio
import logging
import random
import time

from fastapi import FastAPI
import httpx
import uvicorn

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "info").upper())
logger = logging.getLogger("event-producer")

app = FastAPI()

SOLACE_REST_URL = os.environ.get("SOLACE_REST_URL", "http://localhost:8008")
TOPIC = os.environ.get("TOPIC", "sensor/data")
INTERVAL_MS = int(os.environ.get("INTERVAL_MS", "500"))
PORT = int(os.environ.get("PORT", "3600"))

_stats = {"sent": 0, "errors": 0}
_running = True


@app.on_event("startup")
async def start_producer():
    asyncio.create_task(_produce_loop())


async def _produce_loop():
    sensors = [f"sensor-{i:02d}" for i in range(1, 11)]
    units = ["°C", "kPa", "rpm", "A", "Hz"]
    async with httpx.AsyncClient(timeout=3.0) as client:
        while _running:
            payload = {
                "ts": time.time(),
                "sensor_id": random.choice(sensors),
                "value": round(random.uniform(0.0, 100.0), 2),
                "unit": random.choice(units),
            }
            try:
                resp = await client.post(
                    f"{SOLACE_REST_URL}/TOPIC/{TOPIC}",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                _stats["sent"] += 1
                logger.debug(f"Published to {TOPIC} — HTTP {resp.status_code}")
            except Exception as e:
                _stats["errors"] += 1
                logger.warning(f"Publish failed: {e}")
            await asyncio.sleep(INTERVAL_MS / 1000.0)


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/status")
async def status():
    return {"sent": _stats["sent"], "errors": _stats["errors"], "topic": TOPIC}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
