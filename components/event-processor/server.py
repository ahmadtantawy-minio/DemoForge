"""Event Processor: MinIO webhooks on :8090, event UI on :8091 (shared in-memory ring)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from typing import Any

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from uvicorn import Config, Server

from integration_log import append as integration_log_append
from pipeline import load_processing_config, run_malware_pipeline

logger = logging.getLogger(__name__)

MAX_EVENTS = 500

_ring: deque[dict[str, Any]] = deque(maxlen=MAX_EVENTS)

_s3_client: Any | None = None

# MinIO / AIStor behind LB: virtual-hosted bucket DNS often fails; path-style matches `mc` and avoids 403.
_S3_BOTO_CONFIG = BotoConfig(
    signature_version="s3v4",
    s3={"addressing_style": "path"},
)

# Latest MinIO bucket-notification probe (startup + optional refresh)
_notify_health: dict[str, Any] = {}


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
        config=_S3_BOTO_CONFIG,
    )
    return _s3_client


def _client_error_full_text(exc: ClientError) -> str:
    err = exc.response.get("Error") or {}
    msg = err.get("Message") or ""
    return f"{msg} {exc}".strip()


def _is_ai_stor_license_denial(text: str) -> bool:
    """AIStor returns AccessDenied with a license message when the term license has expired."""
    t = text.lower()
    if "license" not in t:
        return False
    return any(
        p in t
        for p in (
            "expired",
            "valid license",
            "fully expired",
            "restore service",
            "install a valid",
        )
    )


def _license_expired_user_message() -> str:
    return (
        "AIStor reports the storage license has expired or is invalid. The cluster rejects S3 calls "
        "(including bucket checks and notification reads) until a valid license is installed. "
        "This is not caused by Event Processor bucket/prefix settings or path-style addressing."
    )


def _probe_bucket_access(client: Any, bucket: str) -> tuple[bool, str | None]:
    """
    head_bucket is the usual check; some proxies return 403 for HEAD but allow GET list on the bucket.
    Returns (ok, note_if_heuristic).
    """
    try:
        client.head_bucket(Bucket=bucket)
        return True, None
    except ClientError as exc:
        err = exc.response.get("Error") or {}
        code = str(err.get("Code", "") or "")
        status = (exc.response.get("ResponseMetadata") or {}).get("HTTPStatusCode")
        err_txt = str(exc)
        is_403 = (
            status == 403
            or code in ("403", "AccessDenied")
            or "403" in err_txt
        )
        if is_403:
            try:
                client.list_objects_v2(Bucket=bucket, MaxKeys=1)
                return True, "head_bucket returned 403/Forbidden; list_objects_v2 succeeded (common behind nginx/LB)"
            except ClientError as exc2:
                combined = f"{err_txt}; list_objects_v2: {_client_error_full_text(exc2)}"
                return False, combined
        return False, err_txt


def _ep_webhook_env() -> dict[str, str]:
    """Canvas webhook edge → compose → EP_* (what register-webhook.sh uses)."""
    return {
        "webhook_bucket": (os.environ.get("EP_WEBHOOK_BUCKET") or "").strip(),
        "webhook_prefix": (os.environ.get("EP_WEBHOOK_PREFIX") or "").strip(),
        "webhook_suffix": (os.environ.get("EP_WEBHOOK_SUFFIX") or "").strip(),
        "webhook_events": (os.environ.get("EP_WEBHOOK_EVENTS") or "put").strip(),
    }


def _filter_prefix_from_rule(rule: dict[str, Any]) -> str | None:
    """Extract prefix string from S3 notification Filter / legacy Prefix."""
    if not isinstance(rule, dict):
        return None
    filt = rule.get("Filter") or {}
    if isinstance(filt, dict):
        key = filt.get("Key") or {}
        if isinstance(key, dict):
            for fr in key.get("FilterRules") or []:
                if isinstance(fr, dict) and str(fr.get("Name", "")).lower() == "prefix":
                    return str(fr.get("Value") or "")
    legacy = rule.get("Filter") if isinstance(rule.get("Filter"), str) else None
    if legacy:
        return legacy
    p = rule.get("Prefix")
    return str(p) if p else None


def _notification_rules_summary(ncfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten Queue/Lambda/Topic configs into comparable rows."""
    rows: list[dict[str, Any]] = []
    for group_key in (
        "QueueConfigurations",
        "TopicConfigurations",
        "LambdaFunctionConfigurations",
        "CloudFunctionConfigurations",
    ):
        for rule in ncfg.get(group_key) or []:
            if not isinstance(rule, dict):
                continue
            ev = rule.get("Events") or rule.get("Event") or []
            if isinstance(ev, str):
                ev = [ev]
            rows.append(
                {
                    "id": rule.get("Id"),
                    "group": group_key,
                    "events": ev,
                    "prefix": _filter_prefix_from_rule(rule),
                    "suffix": None,
                    "destination": rule.get("QueueArn")
                    or rule.get("TopicArn")
                    or rule.get("CloudFunction")
                    or rule.get("InvocationRole"),
                }
            )
            # Suffix sometimes in FilterRules as "suffix"
            filt = (rule.get("Filter") or {}).get("Key") or {}
            for fr in filt.get("FilterRules") or []:
                if isinstance(fr, dict) and str(fr.get("Name", "")).lower() == "suffix":
                    rows[-1]["suffix"] = str(fr.get("Value") or "")
    return rows


def _prefix_matches_config(rows: list[dict[str, Any]], expected_prefix: str) -> bool:
    if not expected_prefix:
        return True
    for r in rows:
        p = (r.get("prefix") or "").strip()
        if not p:
            return True
        if expected_prefix.startswith(p.rstrip("/")) or p.startswith(expected_prefix.rstrip("/")):
            return True
    return False


def run_minio_notification_check() -> dict[str, Any]:
    """
    Verify S3 connectivity and that the webhook bucket has notification rules.
    Uses GetBucketNotificationConfiguration (same rules mc event add applies server-side).
    """
    cfg = _ep_webhook_env()
    bucket = cfg["webhook_bucket"]
    out: dict[str, Any] = {
        "configured": cfg,
        "s3_endpoint": _s3_endpoint_url() or None,
        "s3_client_available": False,
        "bucket_exists": None,
        "notification_rules": [],
        "notification_rule_count": 0,
        "prefix_matches": None,
        "ready": False,
        "issues": [],
        "blocking_reason": None,
    }
    client = _get_s3_client()
    if not client:
        out["issues"].append("S3 client unavailable — set S3_ENDPOINT, S3_ACCESS_KEY, S3_SECRET_KEY")
        return out
    out["s3_client_available"] = True
    if not bucket:
        out["issues"].append(
            "EP_WEBHOOK_BUCKET is empty — connect Event Processor to MinIO with a webhook edge (bucket/prefix/events)",
        )
        return out
    ok_access, access_note = _probe_bucket_access(client, bucket)
    out["bucket_access_probe_ok"] = ok_access
    out["bucket_exists"] = ok_access
    if access_note:
        out["access_note"] = access_note
    if access_note and _is_ai_stor_license_denial(access_note):
        out["blocking_reason"] = "license_expired"
        out["bucket_exists"] = False
        out["issues"] = [_license_expired_user_message(), f"S3 detail: {access_note[:1200]}"]
        return out
    try:
        raw = client.get_bucket_notification_configuration(Bucket=bucket)
        raw.pop("ResponseMetadata", None)
        out["bucket_exists"] = True
        rows = _notification_rules_summary(raw)
        out["notification_rules"] = rows
        out["notification_rule_count"] = len(rows)
        out["prefix_matches"] = _prefix_matches_config(rows, cfg["webhook_prefix"])
        if not ok_access and access_note:
            out.setdefault("warnings", []).append(access_note)
        if not rows:
            out["issues"].append(
                "No notification rules on this bucket — init script (register-webhook.sh) may not have run yet "
                "or failed; objects in the prefix will not call the webhook",
            )
        elif cfg["webhook_prefix"] and not out["prefix_matches"]:
            out["issues"].append(
                f"No rule filter covers EP_WEBHOOK_PREFIX={cfg['webhook_prefix']!r} — verify mc event add --prefix",
            )
        else:
            out["ready"] = True
    except ClientError as exc:
        full = _client_error_full_text(exc)
        if _is_ai_stor_license_denial(full):
            out["blocking_reason"] = "license_expired"
            out["bucket_exists"] = False
            out["issues"] = [_license_expired_user_message(), f"S3 detail: {full[:1200]}"]
            return out
        out["issues"].append(f"get_bucket_notification_configuration failed: {exc}")
        out["bucket_exists"] = ok_access
        if not ok_access:
            out["issues"].append(f"Bucket {bucket!r} not accessible (head/list): {access_note}")
            if access_note and not _is_ai_stor_license_denial(access_note or ""):
                out["issues"].append(
                    "S3 client uses path-style addressing + SigV4 (same as MinIO mc). "
                    "Virtual-hosted requests often get 403 behind an LB.",
                )
    return out


async def _startup_notify_probe(*, log_to_integration: bool = True) -> None:
    global _notify_health
    try:
        _notify_health = await asyncio.to_thread(run_minio_notification_check)
        summary = (
            f"bucket={_notify_health.get('configured', {}).get('webhook_bucket')!r} "
            f"prefix={_notify_health.get('configured', {}).get('webhook_prefix')!r} "
            f"suffix={_notify_health.get('configured', {}).get('webhook_suffix')!r} "
            f"rules={_notify_health.get('notification_rule_count')} "
            f"ready={_notify_health.get('ready')}"
        )
        if log_to_integration:
            logger.info("MinIO notification check: %s", summary)
            integration_log_append(
                "info" if _notify_health.get("ready") else "warn",
                "minio_notify_check",
                summary,
                json.dumps(_notify_health, default=str)[:8000],
            )
        else:
            logger.debug("MinIO notification check (poll): %s", summary)
    except Exception as exc:
        logger.exception("MinIO notification check failed: %s", exc)
        _notify_health = {
            "configured": _ep_webhook_env(),
            "issues": [str(exc)],
            "ready": False,
        }
        integration_log_append("error", "minio_notify_check", "probe crashed", str(exc)[:500])


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


@asynccontextmanager
async def _webhook_lifespan(_: FastAPI):
    await _startup_notify_probe()
    yield


def create_webhook_app() -> FastAPI:
    app = FastAPI(title="DemoForge Event Processor (webhook)", lifespan=_webhook_lifespan)

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
        proc_cfg = load_processing_config()
        pl: dict[str, Any] = {}
        if proc_cfg:
            pl = await asyncio.to_thread(run_malware_pipeline, payload, proc_cfg, _get_s3_client())
            rec["malware_pipeline"] = pl
            out["malware_pipeline"] = pl
            if pl.get("matched"):
                integration_log_append(
                    "info",
                    "malware_pipeline",
                    f"sha256={pl.get('sha256')} report_key={pl.get('report_key')} trino_ok={pl.get('trino_ok')}",
                    pl.get("trino_error") or "",
                )

        skip_generic = bool(pl.get("skip_generic_audit"))
        rkey, rerr = None, None
        if not skip_generic:
            rkey, rerr = await _write_event_report(rec)
        elif pl.get("report_key"):
            rkey = pl["report_key"]
        if rkey:
            rec["report_key"] = rkey
            rec["report_written"] = True
            out["report_key"] = rkey
            out["report_written"] = True
            integration_log_append(
                "info",
                "webhook_report_written",
                (
                    f"Malware pipeline JSON report for event_id={rec['event_id']}"
                    if pl.get("skip_generic_audit")
                    else f"S3 report written for event_id={rec['event_id']}"
                ),
                f"key={rkey}",
            )
        elif rerr:
            rec["report_error"] = rerr
            rec["report_written"] = False
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
    async def health() -> dict[str, Any]:
        """Liveness + cached MinIO bucket-notification probe (bucket / prefix / suffix from EP_WEBHOOK_*)."""
        return {
            "status": "ok",
            "notify": _notify_health or {"ready": False, "message": "notification probe not run yet"},
        }

    @app.post("/health/notify/refresh")
    async def refresh_notify_health() -> JSONResponse:
        """Re-run GetBucketNotificationConfiguration against MinIO (e.g. after fixing init)."""
        await _startup_notify_probe()
        return JSONResponse(_notify_health)

    return app


def _stats() -> dict[str, Any]:
    events = list(_ring)
    return {
        "total_stored": len(events),
        "mode": os.environ.get("EP_MODE", "process"),
        "scenario": os.environ.get("EP_ACTION_SCENARIO", ""),
        "minio_notify": _notify_health,
    }


def _html_ui() -> str:
    return """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/><title>Event Processor</title>
<style>
  body { font-family: ui-sans-serif, system-ui, sans-serif; background:#0a0a0b; color:#e4e4e7; margin:0; padding:16px; }
  h1 { font-size:1rem; font-weight:600; margin:0 0 12px; }
  .meta { font-size:12px; color:#a1a1aa; margin-bottom:16px; }
  ul { list-style:none; padding:0; margin:0; }
  li { border:1px solid #27272a; border-radius:8px; margin-bottom:8px; overflow:hidden; transition: border-color 0.35s ease, box-shadow 0.35s ease; }
  li.is-new { border-color: #ea580c; box-shadow: 0 0 0 1px rgba(234, 88, 12, 0.65), 0 0 12px rgba(234, 88, 12, 0.12); }
  summary { cursor:pointer; padding:10px 12px; background:#18181b; font-size:12px; line-height:1.45; }
  summary:hover { background:#27272a; }
  .sum-main { color: #e4e4e7; }
  .sum-files { display:block; margin-top:4px; font-size:11px; color:#a1a1aa; font-family: ui-monospace, monospace; }
  .sum-files .lbl { color:#71717a; }
  pre { margin:0; padding:12px; font-size:11px; background:#09090b; overflow:auto; max-height:240px; white-space:pre-wrap; word-break:break-all; }
</style></head><body>
<h1>Event Processor</h1>
<p class="meta">Latest """ + str(MAX_EVENTS) + """ events · Webhook :8090 · UI/API :8091</p>
<div class="meta" id="notify-banner" style="margin-bottom:12px;line-height:1.5;">Loading MinIO notification check…</div>
<p class="meta" id="empty-hint" style="display:none;color:#fbbf24;">No events yet. Objects must land in a bucket covered by the <strong>webhook</strong> edge (bucket/prefix/events) and the init script must have registered MinIO notifications. Upload a test object to that bucket or POST to <code style="font-size:11px">:8090/webhook</code>.</p>
<ul id="list"></ul>
<script>
(function() {
  var prevIds = {};
  var hadPoll = false;
  /** Relative to &lt;base href&gt; from DemoForge proxy — avoid fetch('/api/...') which hits the wrong origin. */
  function apiUrl(path) {
    var p = path.indexOf('/') === 0 ? path.slice(1) : path;
    return p;
  }

  function basename(p) {
    if (!p || typeof p !== 'string') return '';
    var bs = String.fromCharCode(92);
    var i = Math.max(p.lastIndexOf('/'), p.lastIndexOf(bs));
    return i >= 0 ? p.slice(i + 1) : p;
  }

  function truncateMid(s, maxLen) {
    if (!s || s.length <= maxLen) return s;
    var half = Math.floor((maxLen - 1) / 2);
    return s.slice(0, half) + '…' + s.slice(s.length - half);
  }

  /** Best-effort object key from MinIO/AWS-style webhook JSON (never throws). */
  function extractObjectKey(payload) {
    try {
      if (!payload || typeof payload !== 'object') return '';
      if (typeof payload.Key === 'string' && payload.Key) return payload.Key;
      if (typeof payload.key === 'string' && payload.key) return payload.key;
      var recs = payload.Records || payload.records;
      if (!Array.isArray(recs) || !recs.length) return '';
      var r0 = recs[0];
      if (!r0 || typeof r0 !== 'object') return '';
      var s3 = r0.s3 || r0.S3;
      if (s3 && s3.object && typeof s3.object.key === 'string') return s3.object.key;
      if (s3 && s3.Object && typeof s3.Object.Key === 'string') return s3.Object.Key;
      return '';
    } catch (e) {
      return '';
    }
  }

  function extractOutputKey(ev) {
    try {
      if (ev && typeof ev.report_key === 'string' && ev.report_key) return ev.report_key;
      return '';
    } catch (e) {
      return '';
    }
  }

  async function loadNotifyBanner() {
    try {
      var r = await fetch(apiUrl('api/notify-health'));
      var n = await r.json();
      var el = document.getElementById('notify-banner');
      if (!el) return;
      var cfg = n.configured || {};
      var bucket = cfg.webhook_bucket || '—';
      var pfx = cfg.webhook_prefix !== undefined && cfg.webhook_prefix !== '' ? cfg.webhook_prefix : '(any)';
      var sfx = cfg.webhook_suffix !== undefined && cfg.webhook_suffix !== '' ? cfg.webhook_suffix : '(any)';
      var evs = cfg.webhook_events || '—';
      var ok = n.ready === true;
      var st;
      if (n.blocking_reason === 'license_expired') {
        st = '<span style="color:#f87171">AIStor license expired or invalid — renew cluster license (S3 is disabled)</span>';
      } else if (ok) {
        st = '<span style="color:#4ade80">MinIO notifications OK</span> (' + (n.notification_rule_count || 0) + ' rule(s))';
      } else {
        st = '<span style="color:#fbbf24">MinIO notification check incomplete or issues</span>';
      }
      el.innerHTML =
        '<strong>Webhook</strong> bucket <code>' + bucket + '</code> · prefix <code>' + pfx + '</code> · suffix <code>' + sfx + '</code> · events <code>' + evs + '</code><br/>' + st;
      if (n.issues && n.issues.length) {
        el.innerHTML += '<br/><span style="color:#f87171;font-size:11px">' + n.issues.join(' ') + '</span>';
      }
      if (n.warnings && n.warnings.length) {
        el.innerHTML += '<br/><span style="color:#fbbf24;font-size:11px">' + n.warnings.join(' ') + '</span>';
      }
      if (n.s3_endpoint) {
        el.innerHTML += '<br/><span style="color:#71717a;font-size:11px">S3 ' + String(n.s3_endpoint) + '</span>';
      }
    } catch (e) {
      var el2 = document.getElementById('notify-banner');
      if (el2) el2.textContent = 'Could not load notification health (' + e + ')';
    }
  }

  async function load() {
    try {
    var r = await fetch(apiUrl('api/events'));
    var j = await r.json();
    var el = document.getElementById('list');
    var hint = document.getElementById('empty-hint');
    el.innerHTML = '';
    var events = j.events || [];
    if (hint) { hint.style.display = events.length === 0 ? 'block' : 'none'; }
    var currSet = {};
    for (var ci = 0; ci < events.length; ci++) {
      if (events[ci] && events[ci].event_id) currSet[events[ci].event_id] = true;
    }

    events.forEach(function(ev) {
      var li = document.createElement('li');
      var ts = new Date(ev.received_at_ms).toISOString();
      var ct = ev.content_type || 'no content-type';
      var inKey = extractObjectKey(ev.payload);
      var inName = basename(inKey) || (inKey ? truncateMid(inKey, 48) : '');
      var outKey = extractOutputKey(ev);
      var outName = basename(outKey);

      var isNew = hadPoll && ev.event_id && !prevIds[ev.event_id];
      if (isNew) {
        li.className = 'is-new';
        (function(node) {
          setTimeout(function() { try { node.classList.remove('is-new'); } catch (e) {} }, 12000);
        })(li);
      }

      var summary = document.createElement('summary');
      var main = document.createElement('span');
      main.className = 'sum-main';
      main.textContent = ts + ' — ' + ct;
      summary.appendChild(main);

      var files = document.createElement('span');
      files.className = 'sum-files';
      var lblIn = document.createElement('span'); lblIn.className = 'lbl'; lblIn.textContent = 'in ';
      var vIn = document.createElement('span');
      vIn.textContent = (inName || inKey ? truncateMid(inName || inKey, 56) : '—');
      files.appendChild(lblIn);
      files.appendChild(vIn);
      if (outName || outKey) {
        var sep = document.createElement('span'); sep.textContent = ' · '; files.appendChild(sep);
        var lblOut = document.createElement('span'); lblOut.className = 'lbl'; lblOut.textContent = 'out ';
        var vOut = document.createElement('span');
        vOut.textContent = truncateMid(outName || outKey, 56);
        files.appendChild(lblOut);
        files.appendChild(vOut);
      } else if (ev.report_error) {
        var sep2 = document.createElement('span'); sep2.textContent = ' · '; files.appendChild(sep2);
        var lblErr = document.createElement('span'); lblErr.style.color = '#f87171'; lblErr.textContent = 'report failed';
        files.appendChild(lblErr);
      }
      summary.appendChild(files);

      var pre = document.createElement('pre');
      try {
        pre.textContent = JSON.stringify(ev, null, 2);
      } catch (e) {
        pre.textContent = String(ev);
      }
      var details = document.createElement('details');
      details.open = false;
      details.appendChild(summary);
      details.appendChild(pre);
      li.appendChild(details);
      el.appendChild(li);
    });

    prevIds = currSet;
    hadPoll = true;
    } finally {
      await loadNotifyBanner();
    }
  }

  load();
  setInterval(load, 4000);
})();
</script>
</body></html>"""


def create_ui_app() -> FastAPI:
    app = FastAPI(title="DemoForge Event Processor (UI)")

    @app.get("/api/events")
    async def list_events() -> JSONResponse:
        return JSONResponse({"events": list(_ring)})

    @app.get("/api/notify-health")
    async def notify_health_api() -> JSONResponse:
        """Re-run S3 notification probe each call so the UI banner is not stuck on startup state."""
        await _startup_notify_probe(log_to_integration=False)
        return JSONResponse(_notify_health or {"ready": False, "message": "notification probe not run yet"})

    @app.post("/api/notify-health/refresh")
    async def notify_health_refresh() -> JSONResponse:
        await _startup_notify_probe()
        return JSONResponse(_notify_health)

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
