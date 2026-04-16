"""Event Processor: MinIO webhooks on :8090, event UI on :8091 (shared in-memory ring)."""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from collections import deque
from typing import Any

import boto3
from botocore.exceptions import ClientError
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from uvicorn import Config, Server

from integration_log import append as integration_log_append

MAX_EVENTS = 500

_ring: deque[dict[str, Any]] = deque(maxlen=MAX_EVENTS)

_s3_client: Any | None = None


def _now_ms() -> int:
    return int(time.time() * 1000)


def _s3_endpoint_url() -> str:
    ep = (os.environ.get("S3_ENDPOINT") or "").strip()
    if not ep:
        return ""
    return ep if ep.startswith("http") else f"http://{ep}"


def _parse_s3_bucket(raw: str) -> tuple[str, str]:
    """Split S3_BUCKET like `malware-vault/reports/` into bucket and key prefix."""
    s = (raw or "").strip().strip("/")
    if not s:
        return "", ""
    if "/" in s:
        b, rest = s.split("/", 1)
        p = rest.rstrip("/")
        return b, (p + "/") if p else ""
    return s, ""


def _get_s3_client():
    global _s3_client
    if _s3_client is not None:
        return _s3_client
    url = _s3_endpoint_url()
    key = os.environ.get("S3_ACCESS_KEY", "")
    sec = os.environ.get("S3_SECRET_KEY", "")
    if not url or not key or not sec:
        return None
    _s3_client = boto3.client(
        "s3",
        endpoint_url=url,
        aws_access_key_id=key,
        aws_secret_access_key=sec,
        region_name="us-east-1",
    )
    return _s3_client


def _reports_enabled() -> bool:
    return os.environ.get("EP_WRITE_EVENT_REPORTS", "true").lower() in (
        "1",
        "true",
        "yes",
    )


def _ensure_bucket(client, bucket: str) -> None:
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("404", "NoSuchBucket"):
            client.create_bucket(Bucket=bucket)
        else:
            raise


def _write_event_report_sync(rec: dict[str, Any]) -> str | None:
    """Write one JSON report per event to S3. Returns object key or None if skipped."""
    if not _reports_enabled():
        return None
    raw_bucket = os.environ.get("S3_BUCKET", "")
    bucket, prefix = _parse_s3_bucket(raw_bucket)
    if not bucket:
        return None
    client = _get_s3_client()
    if not client:
        return None

    extra = os.environ.get("EP_REPORTS_PREFIX")
    if extra is None:
        sub = "" if prefix else "reports/"
    else:
        sub = extra.strip()
    if sub and not sub.endswith("/"):
        sub += "/"

    rid = uuid.uuid4().hex
    key = f"{prefix}{sub}ep-event-{rec['received_at_ms']}-{rid[:8]}.json"
    body = json.dumps(rec, default=str).encode("utf-8")
    _ensure_bucket(client, bucket)
    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=body,
        ContentType="application/json",
    )
    return key


async def _write_event_report(rec: dict[str, Any]) -> tuple[str | None, str | None]:
    """Returns (s3_key, error_message)."""
    try:
        key = await asyncio.to_thread(_write_event_report_sync, rec)
        return key, None
    except Exception as exc:
        return None, str(exc)[:500]


def _payload_summary(payload: dict[str, Any]) -> str:
    try:
        s = json.dumps(payload, default=str)
        return s[:2000] + ("…" if len(s) > 2000 else "")
    except Exception:
        return str(payload)[:800]


def _record_event(payload: dict[str, Any], content_type: str) -> dict[str, Any]:
    rec = {
        "event_id": str(uuid.uuid4()),
        "received_at_ms": _now_ms(),
        "content_type": content_type,
        "payload": payload,
        "mode": os.environ.get("EP_MODE", "process"),
        "scenario": os.environ.get("EP_ACTION_SCENARIO", ""),
    }
    _ring.appendleft(rec)
    return rec


def create_webhook_app() -> FastAPI:
    app = FastAPI(title="DemoForge Event Processor (webhook)")

    @app.post("/webhook")
    async def receive_webhook(request: Request) -> JSONResponse:
        body = await request.body()
        try:
            payload = json.loads(body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            payload = {"_raw": body.decode("utf-8", errors="replace")}
        rec = _record_event(payload, request.headers.get("content-type", ""))
        ct = request.headers.get("content-type", "")
        integration_log_append(
            "info",
            "webhook_received",
            f"POST /webhook event_id={rec['event_id']} content_type={ct or '(none)'}",
            _payload_summary(payload),
        )
        out: dict[str, Any] = {"status": "ok", "stored": True, "event_id": rec["event_id"]}
        rkey, rerr = await _write_event_report(rec)
        if rkey:
            out["report_key"] = rkey
            out["report_written"] = True
            integration_log_append(
                "info",
                "webhook_report_written",
                f"S3 report written for event_id={rec['event_id']}",
                f"key={rkey}",
            )
        elif rerr:
            out["report_written"] = False
            out["report_error"] = rerr
            integration_log_append(
                "error",
                "webhook_report_failed",
                f"S3 report failed for event_id={rec['event_id']}",
                rerr,
            )
        else:
            if not _reports_enabled():
                integration_log_append(
                    "info",
                    "webhook_processing_no_report",
                    f"Reports disabled (EP_WRITE_EVENT_REPORTS) for event_id={rec['event_id']}",
                    "",
                )
            elif not (os.environ.get("S3_BUCKET") or "").strip():
                integration_log_append(
                    "warn",
                    "webhook_processing_no_report",
                    f"S3_BUCKET not set — no per-event report for event_id={rec['event_id']}",
                    "",
                )
            elif not _get_s3_client():
                integration_log_append(
                    "warn",
                    "webhook_processing_no_report",
                    f"S3 client unavailable (endpoint/credentials) for event_id={rec['event_id']}",
                    "",
                )
        return JSONResponse(out)

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
