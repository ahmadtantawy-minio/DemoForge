"""
Fire-and-forget telemetry emitter.
Sends events to the Hub API through the local hub connector.
Never blocks or fails the calling operation.
"""
import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from collections import deque
from typing import Optional

logger = logging.getLogger("demoforge.telemetry")

_emitter: Optional["TelemetryEmitter"] = None


class TelemetryEmitter:
    def __init__(self, hub_url: str, api_key: str, enabled: bool = True):
        self.hub_url = hub_url.rstrip("/")
        self.api_key = api_key
        self.enabled = enabled
        self._queue: deque = deque(maxlen=1000)
        self._client = None

    async def start(self):
        if not self.enabled:
            return
        try:
            import httpx
            self._client = httpx.AsyncClient(
                base_url=self.hub_url,
                headers={"X-Api-Key": self.api_key},
                timeout=5.0,
            )
        except Exception as e:
            logger.debug(f"Telemetry client init failed: {e}")

    async def stop(self):
        if self._client:
            await self._flush_queue()
            try:
                await self._client.aclose()
            except Exception:
                pass

    async def emit(self, event_type: str, payload: dict | None = None):
        if not self.enabled or not self._client:
            return
        event = {
            "event_type": event_type,
            "payload": payload or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            response = await self._client.post("/api/hub/events", json=event)
            if response.status_code == 201:
                logger.debug(f"Telemetry sent: {event_type}")
            elif response.status_code == 403:
                logger.warning(f"Telemetry permission denied: {event_type}")
            else:
                logger.debug(f"Telemetry failed ({response.status_code}): {event_type}")
                self._queue.append(event)
        except Exception as e:
            logger.debug(f"Telemetry send error: {e}")
            self._queue.append(event)

    async def _flush_queue(self):
        if not self._queue or not self._client:
            return
        events = list(self._queue)
        self._queue.clear()
        try:
            await self._client.post("/api/hub/events/batch", json={"events": events})
        except Exception as e:
            logger.debug(f"Batch flush failed: {e}")


async def init_telemetry(hub_url: str, api_key: str, enabled: bool):
    global _emitter
    _emitter = TelemetryEmitter(hub_url=hub_url, api_key=api_key, enabled=enabled)
    await _emitter.start()


async def shutdown_telemetry():
    global _emitter
    if _emitter:
        await _emitter.stop()


async def emit_event(event_type: str, payload: dict | None = None):
    """Fire-and-forget: call without awaiting if you don't want to wait."""
    if _emitter:
        try:
            await _emitter.emit(event_type, payload)
        except Exception:
            pass
