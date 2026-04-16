"""Event Processor: MinIO webhooks on :8090, event UI on :8091 (shared in-memory ring)."""
from __future__ import annotations

import asyncio
import json
import os
import time
from collections import deque
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from uvicorn import Config, Server

MAX_EVENTS = 500

_ring: deque[dict[str, Any]] = deque(maxlen=MAX_EVENTS)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _record_event(payload: dict[str, Any], content_type: str) -> None:
    rec = {
        "received_at_ms": _now_ms(),
        "content_type": content_type,
        "payload": payload,
        "mode": os.environ.get("EP_MODE", "process"),
        "scenario": os.environ.get("EP_ACTION_SCENARIO", ""),
    }
    _ring.appendleft(rec)


def create_webhook_app() -> FastAPI:
    app = FastAPI(title="DemoForge Event Processor (webhook)")

    @app.post("/webhook")
    async def receive_webhook(request: Request) -> JSONResponse:
        body = await request.body()
        try:
            payload = json.loads(body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            payload = {"_raw": body.decode("utf-8", errors="replace")}
        _record_event(payload, request.headers.get("content-type", ""))
        return JSONResponse({"status": "ok", "stored": True})

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


def _stats() -> dict[str, Any]:
    events = list(_ring)
    return {
        "total_stored": len(events),
        "mode": os.environ.get("EP_MODE", "process"),
        "scenario": os.environ.get("EP_ACTION_SCENARIO", ""),
    }


def _html_ui() -> str:
    return """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/><title>Event Processor</title>
<style>
  body { font-family: ui-sans-serif, system-ui, sans-serif; background:#0a0a0b; color:#e4e4e7; margin:0; padding:16px; }
  h1 { font-size:1rem; font-weight:600; margin:0 0 12px; }
  .meta { font-size:12px; color:#a1a1aa; margin-bottom:16px; }
  ul { list-style:none; padding:0; margin:0; }
  li { border:1px solid #27272a; border-radius:8px; margin-bottom:8px; overflow:hidden; }
  summary { cursor:pointer; padding:10px 12px; background:#18181b; font-size:13px; }
  summary:hover { background:#27272a; }
  pre { margin:0; padding:12px; font-size:11px; background:#09090b; overflow:auto; max-height:240px; white-space:pre-wrap; word-break:break-all; }
</style></head><body>
<h1>Event Processor</h1>
<p class="meta">Latest """ + str(MAX_EVENTS) + """ events · Webhook :8090 · UI/API :8091</p>
<ul id="list"></ul>
<script>
async function load() {
  const r = await fetch('/api/events');
  const j = await r.json();
  const el = document.getElementById('list');
  el.innerHTML = '';
  (j.events || []).forEach((ev, i) => {
    const li = document.createElement('li');
    const ts = new Date(ev.received_at_ms).toISOString();
    const summary = document.createElement('summary');
    summary.textContent = ts + ' — ' + (ev.content_type || 'no content-type');
    const pre = document.createElement('pre');
    pre.textContent = JSON.stringify(ev.payload, null, 2);
    const details = document.createElement('details');
    details.open = i === 0;
    details.appendChild(summary);
    details.appendChild(pre);
    li.appendChild(details);
    el.appendChild(li);
  });
}
load();
setInterval(load, 4000);
</script>
</body></html>"""


def create_ui_app() -> FastAPI:
    app = FastAPI(title="DemoForge Event Processor (UI)")

    @app.get("/api/events")
    async def list_events() -> JSONResponse:
        return JSONResponse({"events": list(_ring)})

    @app.get("/api/stats")
    async def stats() -> JSONResponse:
        return JSONResponse(_stats())

    @app.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        return HTMLResponse(_html_ui())

    return app


async def _run_servers() -> None:
    wh = create_webhook_app()
    ui = create_ui_app()
    s0 = Server(Config(wh, host="0.0.0.0", port=8090, log_level="info"))
    s1 = Server(Config(ui, host="0.0.0.0", port=8091, log_level="info"))
    await asyncio.gather(s0.serve(), s1.serve())


def main() -> None:
    asyncio.run(_run_servers())


if __name__ == "__main__":
    main()
