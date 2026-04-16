#!/usr/bin/env python3
"""
Metabase dashboard provisioner — reconcile loop.

Polls a shared Docker volume for JSON intent files written by external-system
containers. For each intent, provisions missing collections, questions, and
dashboards into Metabase, then moves the file to done/.

Runs fully offline — no S3, no external network access required.
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
from urllib import error as urllib_error
from urllib import request as urllib_request

_SETUP_DIR = os.path.dirname(os.path.abspath(__file__))
if _SETUP_DIR not in sys.path:
    sys.path.insert(0, _SETUP_DIR)

from integration_log import append as log_integration

MB_HOST = os.environ.get("METABASE_HOST", "metabase")
MB_URL = f"http://{MB_HOST}:3000"
MB_USER = os.environ.get("MB_USER", "admin@demoforge.local")
MB_PASS = os.environ.get("MB_PASSWORD", "DemoForge123!")
TRINO_HOST = os.environ.get("TRINO_HOST", "")
TRINO_CATALOG = os.environ.get("TRINO_CATALOG", "iceberg")
# Set on metabase-init by compose from sql-query edge (namespace / default schema hint for demos)
TRINO_SCHEMA = os.environ.get("TRINO_SCHEMA", "")

_LOGGED_TRINO_SEED_ENV = False
_LOGGED_NO_TRINO_AND_NO_TRINO_HOST = False
_LAST_REUSED_TRINO_DB_ID: int | None = None
_LAST_INTENT_SKIP_LOG_MONO = 0.0


class _MbHttpError(Exception):
    """Metabase API returned non-2xx (stdlib urllib has no requests-style wrapper)."""

    __slots__ = ("status_code", "body")

    def __init__(self, status_code: int, body: str):
        self.status_code = status_code
        self.body = body
        super().__init__(f"HTTP {status_code}")


def _urlopen_json(
    method: str,
    path: str,
    *,
    token: str | None = None,
    body: dict | None = None,
    timeout: float = 60,
) -> dict | list:
    url = f"{MB_URL}{path}"
    hdrs = {"Content-Type": "application/json"}
    if token:
        hdrs["X-Metabase-Session"] = token
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib_request.Request(url, data=data, method=method, headers=hdrs)
    try:
        with urllib_request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else {}
    except urllib_error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise _MbHttpError(e.code, err_body) from e


INTENTS_DIR = os.environ.get("MB_INTENTS_DIR", "/provision-intents")
DONE_DIR = os.path.join(INTENTS_DIR, "done")
FAILED_DIR = os.path.join(INTENTS_DIR, "failed")
POLL_INTERVAL_BASE = int(os.environ.get("MB_PROVISION_POLL_SEC", "20"))
MAX_PROVISION_ATTEMPTS = int(os.environ.get("MB_PROVISION_MAX_ATTEMPTS", "8"))
METABASE_HEALTH_MAX_ATTEMPTS = int(os.environ.get("MB_METABASE_HEALTH_MAX_ATTEMPTS", "10"))

VIS_MAP = {
    "table": "table", "bar": "bar", "line": "line",
    "number": "scalar", "scalar": "scalar", "pie": "pie",
    "time_series": "line",
}


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, urllib_error.URLError):
        return True
    if isinstance(exc, _MbHttpError):
        return exc.status_code in (502, 503, 504, 429)
    return False


def wait_ready(timeout: int = 900) -> None:
    """Wait for Metabase /api/health with exponential backoff (at most METABASE_HEALTH_MAX_ATTEMPTS tries)."""
    max_attempts = METABASE_HEALTH_MAX_ATTEMPTS
    deadline = time.time() + timeout
    delay = 2.0
    detail = ""
    for attempt in range(1, max_attempts + 1):
        if time.time() >= deadline:
            raise RuntimeError(f"Metabase not ready after {timeout}s")
        try:
            data = _urlopen_json("GET", "/api/health", timeout=8)
            if isinstance(data, dict) and data.get("status") == "ok":
                log_integration("info", "metabase_provision", "Metabase API healthy", f"attempt={attempt}/{max_attempts}")
                return
            if isinstance(data, dict):
                detail = f"status={data.get('status')!r}"
            else:
                detail = f"unexpected_response={type(data).__name__}"
        except Exception as exc:
            detail = f"{type(exc).__name__}: {str(exc)[:200]}"
        log_integration(
            "warn" if attempt > 3 else "info",
            "metabase_provision",
            "Metabase /api/health not ready yet",
            f"attempt={attempt}/{max_attempts} {detail}",
        )
        if attempt >= max_attempts:
            raise RuntimeError(f"Metabase /api/health not ok after {max_attempts} attempts (last: {detail})")
        remaining = deadline - time.time()
        if remaining <= 0:
            raise RuntimeError(f"Metabase not ready after {timeout}s")
        sleep_for = min(delay, float(remaining))
        next_at = time.time() + sleep_for
        next_local = time.strftime("%H:%M:%S", time.localtime(next_at))
        log_integration(
            "warn" if attempt > 3 else "info",
            "metabase_provision",
            "Metabase health backoff — next check",
            f"completed_attempt={attempt}/{max_attempts} next_retry_in_s={sleep_for:.2f} next_retry_at_local={next_local}",
        )
        time.sleep(sleep_for)
        delay = min(60.0, delay * 1.5 + random.uniform(0, 0.5))


def get_token() -> str:
    data = _urlopen_json(
        "POST",
        "/api/session",
        body={"username": MB_USER, "password": MB_PASS},
        timeout=20,
    )
    if not isinstance(data, dict) or "id" not in data:
        raise _MbHttpError(0, "session response missing id")
    return str(data["id"])


def get(token: str, path: str):
    return _urlopen_json("GET", path, token=token, timeout=30)


def post(token: str, path: str, body: dict):
    return _urlopen_json("POST", path, token=token, body=body, timeout=60)


def put(token: str, path: str, body: dict):
    return _urlopen_json("PUT", path, token=token, body=body, timeout=60)


def _find_existing_trino_db_id(token: str) -> int | None:
    """Reuse Trino/Presto connection already registered by setup-metabase.sh or the user."""
    data = get(token, "/api/database")
    dbs = data if isinstance(data, list) else data.get("data", [])
    for db in dbs:
        name = (db.get("name") or "").lower()
        eng = (db.get("engine") or "").lower()
        if "trino" in name or "presto" in name or eng in ("presto", "presto-jdbc", "starburst"):
            return db["id"]
    return None


def ensure_trino_db(token: str) -> int | None:
    global _LOGGED_TRINO_SEED_ENV, _LOGGED_NO_TRINO_AND_NO_TRINO_HOST, _LAST_REUSED_TRINO_DB_ID
    existing = _find_existing_trino_db_id(token)
    if existing is not None:
        if _LAST_REUSED_TRINO_DB_ID != existing:
            _LAST_REUSED_TRINO_DB_ID = existing
            log_integration("info", "metabase_provision", f"Using existing Trino/Presto DB id={existing}", "discovered via /api/database")
        return existing
    if not TRINO_HOST:
        if not _LOGGED_NO_TRINO_AND_NO_TRINO_HOST:
            _LOGGED_NO_TRINO_AND_NO_TRINO_HOST = True
            log_integration(
                "warn",
                "metabase_provision",
                "No Trino DB in Metabase and TRINO_HOST unset — cannot auto-create connection",
                "Add Trino + sql-query edge to Metabase, or run setup-metabase.sh with TRINO_HOST.",
            )
        return None
    host, port = (TRINO_HOST.split(":", 1) + ["8080"])[:2]
    if not _LOGGED_TRINO_SEED_ENV:
        _LOGGED_TRINO_SEED_ENV = True
        log_integration(
            "info",
            "trino_metabase_seed",
            "Provisioner: Trino↔Metabase env (same TRINO_* as setup-metabase.sh; from compose / diagram edges)",
            f"host={host} port={port} catalog={TRINO_CATALOG} TRINO_SCHEMA={TRINO_SCHEMA or '(unset)'}",
        )
    log_integration("info", "trino_metabase_seed", "Creating Trino DB via Metabase API (presto-jdbc)", f"host={host} catalog={TRINO_CATALOG}")
    body = {
        "name": "Trino (DemoForge)",
        "engine": "presto-jdbc",
        "details": {"host": host, "port": int(port), "catalog": TRINO_CATALOG,
                      "schema": "default", "user": "demoforge", "ssl": False},
        "is_full_sync": True,
    }
    try:
        return post(token, "/api/database", body)["id"]
    except Exception:
        body["engine"] = "presto"
        return post(token, "/api/database", body)["id"]


def ensure_collection(token: str, name: str, description: str = "", parent_id=None) -> int:
    data = get(token, "/api/collection")
    cols = data if isinstance(data, list) else data.get("data", [])
    for c in cols:
        if c.get("name") == name and c.get("parent_id") == parent_id:
            return c["id"]
    result = post(token, "/api/collection",
                  {"name": name, "description": description, "color": "#509EE3", "parent_id": parent_id})
    log_integration("info", "metabase_provision", f"Created collection '{name}'", f"id={result['id']}")
    return result["id"]


def create_question(token: str, col_id: int | None, title: str, sql: str, vis: str, db_id: int) -> int:
    body: dict = {
        "name": title,
        "display": VIS_MAP.get(vis, "table"),
        "visualization_settings": {},
        "dataset_query": {"type": "native", "native": {"query": sql.strip()}, "database": db_id},
    }
    if col_id is not None:
        body["collection_id"] = col_id
    result = post(token, "/api/card", body)
    log_integration("info", "metabase_provision", f"Saved question: {title}", f"card_id={result['id']}")
    return result["id"]


def create_dashboard(token: str, title: str, description: str = "") -> int:
    result = post(token, "/api/dashboard", {"name": title, "description": description})
    log_integration("info", "metabase_provision", f"Created dashboard '{title}'", f"id={result['id']}")
    return result["id"]


def add_cards(token: str, dash_id: int, dashcards: list) -> None:
    payload = [
        {
            "id": -(i + 1), "card_id": dc["card_id"],
            "row": dc.get("row", 0), "col": dc.get("col", 0),
            "size_x": dc.get("width", 6), "size_y": dc.get("height", 4),
            "parameter_mappings": [], "visualization_settings": {},
        }
        for i, dc in enumerate(dashcards)
    ]
    put(token, f"/api/dashboard/{dash_id}", {"dashcards": payload})


def provision_spec_once(token: str, db_id: int, spec: dict) -> None:
    """Single attempt to apply intent; raises on failure."""
    dashboards = spec.get("dashboards", [])
    saved_queries = spec.get("saved_queries", {})
    qlist = saved_queries.get("queries") or []
    sid = spec.get("scenario_id") or spec.get("scenario_name") or "unknown"
    titles = [d.get("title", "?") for d in dashboards]
    log_integration(
        "info",
        "metabase_provision",
        f"Applying Metabase dashboard seed for scenario {sid}",
        f"dashboards={len(dashboards)} titles={titles!r} saved_queries={len(qlist)}",
    )

    col_name = saved_queries.get("collection", "")
    col_id: int | None = ensure_collection(token, col_name) if col_name else None

    if (dashboards or saved_queries.get("queries")) and col_id is None:
        col_id = ensure_collection(token, "DemoForge", "DemoForge auto-created for dashboard cards")

    subcol_id_map: dict = {}
    for sc in saved_queries.get("subcollections", []):
        sc_id = ensure_collection(token, sc["name"], sc.get("description", ""), parent_id=col_id)
        subcol_id_map[sc["id"]] = sc_id
        log_integration("info", "metabase_provision", f"Sub-collection '{sc['name']}'", f"id={sc_id}")

    for q in sorted(saved_queries.get("queries", []), key=lambda q: q.get("order", 0)):
        try:
            q_col_id = subcol_id_map.get(q.get("subcollection"), col_id)
            create_question(token, q_col_id, q["title"], q["query"],
                            q.get("visualization", "table"), db_id)
        except Exception as exc:
            log_integration("warn", "metabase_provision", f"Saved query failed: {q.get('id')}", str(exc)[:400])

    for dash in dashboards:
        dash_id = create_dashboard(token, dash["title"], dash.get("description", ""))
        dashcards = []
        for chart in dash.get("charts", []):
            card_id = create_question(
                token, col_id, chart["title"], chart["query"],
                chart.get("type", "table"), db_id,
            )
            pos = chart.get("position", {})
            dashcards.append({
                "card_id": card_id, "row": pos.get("row", 0),
                "col": pos.get("col", 0), "width": pos.get("width", 6),
                "height": pos.get("height", 4),
            })
        if dashcards:
            add_cards(token, dash_id, dashcards)
            log_integration("info", "metabase_provision", f"Dashboard ready: {dash['title']}", f"{len(dashcards)} cards")


def provision_spec_with_retries(token: str, db_id: int, spec: dict, scenario_id: str) -> None:
    last_exc: BaseException | None = None
    for attempt in range(1, MAX_PROVISION_ATTEMPTS + 1):
        try:
            provision_spec_once(token, db_id, spec)
            nd = len(spec.get("dashboards", []))
            nq = len((spec.get("saved_queries") or {}).get("queries") or [])
            log_integration(
                "info",
                "dashboard_seed_result",
                f"SUCCESS: Metabase dashboard seed finished for scenario {scenario_id}",
                f"dashboards={nd} saved_queries={nq} attempt={attempt}/{MAX_PROVISION_ATTEMPTS}",
            )
            log_integration("info", "metabase_provision", f"Intent applied: {scenario_id}", f"attempt={attempt}")
            return
        except Exception as exc:
            last_exc = exc
            log_integration(
                "warn" if attempt < MAX_PROVISION_ATTEMPTS else "error",
                "metabase_provision",
                f"Intent {scenario_id} attempt {attempt}/{MAX_PROVISION_ATTEMPTS} failed",
                str(exc)[:500],
            )
            if attempt < MAX_PROVISION_ATTEMPTS and _is_transient(exc):
                time.sleep(min(30.0, 2.0 ** attempt))
                continue
            if attempt < MAX_PROVISION_ATTEMPTS:
                time.sleep(min(20.0, 3.0 * attempt))
                continue
            break
    assert last_exc is not None
    log_integration(
        "error",
        "dashboard_seed_result",
        f"FAILED: Metabase dashboard seed for scenario {scenario_id} after {MAX_PROVISION_ATTEMPTS} attempt(s)",
        f"{type(last_exc).__name__}: {str(last_exc)[:700]}",
    )
    raise last_exc


def list_pending() -> list[str]:
    try:
        return [
            os.path.join(INTENTS_DIR, f)
            for f in os.listdir(INTENTS_DIR)
            if f.endswith(".json") and os.path.isfile(os.path.join(INTENTS_DIR, f))
        ]
    except FileNotFoundError:
        return []


def mark_done(path: str) -> None:
    os.makedirs(DONE_DIR, exist_ok=True)
    dest = os.path.join(DONE_DIR, os.path.basename(path))
    os.replace(path, dest)


def mark_failed(path: str, reason: str) -> None:
    os.makedirs(FAILED_DIR, exist_ok=True)
    dest = os.path.join(FAILED_DIR, os.path.basename(path))
    try:
        os.replace(path, dest)
        with open(dest + ".txt", "w", encoding="utf-8") as f:
            f.write(reason[:4000])
    except OSError as exc:
        log_integration("error", "metabase_provision", "Could not move intent to failed/", str(exc))


def main() -> None:
    global _LAST_INTENT_SKIP_LOG_MONO
    log_integration("info", "metabase_provision", "Provisioner started", f"intents={INTENTS_DIR} poll≈{POLL_INTERVAL_BASE}s")
    os.makedirs(INTENTS_DIR, exist_ok=True)
    os.makedirs(DONE_DIR, exist_ok=True)

    wait_ready()

    poll_delay = float(POLL_INTERVAL_BASE)
    while True:
        try:
            token = get_token()
            db_id = ensure_trino_db(token)
        except Exception as exc:
            log_integration("warn", "metabase_provision", "Auth/DB setup failed — retrying", str(exc)[:400])
            time.sleep(min(60.0, poll_delay))
            poll_delay = min(120.0, poll_delay * 1.2)
            continue

        poll_delay = float(POLL_INTERVAL_BASE)

        pending = list_pending()
        if not db_id:
            now_m = time.monotonic()
            if pending and (now_m - _LAST_INTENT_SKIP_LOG_MONO >= 90.0 or _LAST_INTENT_SKIP_LOG_MONO == 0.0):
                _LAST_INTENT_SKIP_LOG_MONO = now_m
                names = ", ".join(os.path.basename(p) for p in pending[:8])
                more = f" (+{len(pending) - 8} more)" if len(pending) > 8 else ""
                log_integration(
                    "warn",
                    "dashboard_seed_result",
                    f"Intent files waiting but no Trino database id — cannot run Metabase provisioning ({len(pending)} file(s))",
                    f"pending={names}{more} fix=TRINO_HOST+edge or ensure setup-metabase registered Trino in Metabase",
                )
                log_integration(
                    "warn",
                    "metabase_provision",
                    "Skipping intent processing until a Trino/Presto data source exists in Metabase",
                    f"pending_intents={len(pending)}",
                )
            time.sleep(int(poll_delay))
            continue

        if not pending:
            time.sleep(int(poll_delay))
            continue

        for path in pending:
            scenario_id = os.path.basename(path).removesuffix(".json")
            try:
                with open(path, encoding="utf-8") as f:
                    spec = json.load(f)
                log_integration("info", "metabase_provision", f"Processing intent: {scenario_id}", path)
                provision_spec_with_retries(token, db_id, spec, scenario_id)
                mark_done(path)
            except json.JSONDecodeError as exc:
                log_integration("error", "metabase_provision", f"Intent JSON invalid: {scenario_id}", str(exc)[:400])
                log_integration(
                    "error",
                    "dashboard_seed_result",
                    f"FAILED: could not parse intent file for scenario {scenario_id}",
                    str(exc)[:700],
                )
                try:
                    mark_failed(path, str(exc))
                except Exception:
                    pass
            except Exception as exc:
                log_integration("error", "metabase_provision", f"Intent failed permanently: {scenario_id}", str(exc)[:500])
                try:
                    mark_failed(path, str(exc))
                except Exception:
                    pass

        time.sleep(int(poll_delay))


if __name__ == "__main__":
    main()
