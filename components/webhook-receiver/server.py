"""Minimal webhook receiver for MinIO bucket notifications (Sprint 7 MVP)."""
from __future__ import annotations

import json
import time
from collections import deque
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

MAX_EVENTS = 500

_ring: deque[dict[str, Any]] = deque(maxlen=MAX_EVENTS)
app = FastAPI(title="DemoForge Webhook Receiver")


def _now_ms() -> int:
    return int(time.time() * 1000)


@app.post("/")
async def receive_root(request: Request) -> JSONResponse:
    body = await request.body()
    try:
        payload = json.loads(body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        payload = {"_raw": body.decode("utf-8", errors="replace")}
    rec = {
        "received_at_ms": _now_ms(),
        "content_type": request.headers.get("content-type", ""),
        "payload": payload,
    }
    _ring.appendleft(rec)
    return JSONResponse({"status": "ok", "stored": True})


@app.post("/webhook")
async def receive_webhook(request: Request) -> JSONResponse:
    return await receive_root(request)


@app.get("/api/events")
async def list_events() -> JSONResponse:
    return JSONResponse({"events": list(_ring)})


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


def _html_page() -> str:
    # Lightweight bundled UI (no build step)
    return """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/><title>Webhook Receiver</title>
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
<h1>Webhook Receiver</h1>
<p class="meta">Latest """ + str(MAX_EVENTS) + """ events (newest first). POST JSON to <code>/</code> or <code>/webhook</code>.</p>
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


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse(_html_page())
