import os
import logging
from fastapi import FastAPI, Request, Response
import httpx

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "info").upper())
logger = logging.getLogger("event-bridge")

app = FastAPI()

SOLACE_REST_URL = os.environ.get("SOLACE_REST_URL", "http://localhost:8008")
TOPIC_PREFIX = os.environ.get("SOLACE_TOPIC_PREFIX", "minio/events")


@app.post("/webhook")
async def handle_minio_webhook(request: Request):
    try:
        payload = await request.json()
    except Exception:
        return Response(status_code=400, content="Invalid JSON")

    records = payload.get("Records", [])
    if not records:
        return {"status": "ok", "forwarded": 0}

    forwarded = 0
    async with httpx.AsyncClient(timeout=5.0) as client:
        for record in records:
            event_name = record.get("eventName", payload.get("EventName", "unknown"))
            bucket = record.get("s3", {}).get("bucket", {}).get("name", "unknown")
            key = record.get("s3", {}).get("object", {}).get("key", "unknown")
            topic = f"{TOPIC_PREFIX}/{bucket}/{event_name}"
            try:
                resp = await client.post(
                    f"{SOLACE_REST_URL}/TOPIC/{topic}",
                    json={"record": record, "source": "minio"},
                    headers={
                        "Content-Type": "application/json",
                        "Solace-delivery-mode": "persistent",
                    },
                )
                logger.info(f"Published to {topic} — HTTP {resp.status_code}")
                forwarded += 1
            except Exception as e:
                logger.error(f"Failed to publish to Solace: {e}")

    return {"status": "ok", "topic_prefix": TOPIC_PREFIX, "forwarded": forwarded}


@app.get("/health")
async def health():
    return {"status": "healthy"}
