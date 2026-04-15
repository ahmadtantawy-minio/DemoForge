"""
metabase_client.py — Minimal Metabase REST client for provisioning collections,
questions, and dashboards from scenario YAML definitions.
"""

import time
import requests


DEFAULT_USER = "admin@demoforge.local"
DEFAULT_PASSWORD = "DemoForge123!"


class MetabaseError(RuntimeError):
    pass


def wait_for_metabase(url: str, timeout: int = 300) -> bool:
    """Poll /api/health until Metabase reports 'ok'."""
    url = url.rstrip("/")
    deadline = time.time() + timeout
    last_exc = None
    while time.time() < deadline:
        try:
            resp = requests.get(f"{url}/api/health", timeout=5)
            if resp.status_code == 200 and resp.json().get("status") == "ok":
                return True
        except Exception as exc:
            last_exc = exc
        time.sleep(3)
    raise MetabaseError(f"Metabase not ready at {url} after {timeout}s ({last_exc})")


def get_session_token(url: str, user: str, password: str) -> str:
    url = url.rstrip("/")
    resp = requests.post(
        f"{url}/api/session",
        json={"username": user, "password": password},
        timeout=15,
    )
    if resp.status_code != 200:
        raise MetabaseError(f"Metabase login failed {resp.status_code}: {resp.text}")
    return resp.json()["id"]


def _headers(token: str) -> dict:
    return {"X-Metabase-Session": token, "Content-Type": "application/json"}


def _get(url: str, token: str, path: str) -> dict:
    resp = requests.get(f"{url.rstrip('/')}{path}", headers=_headers(token), timeout=15)
    resp.raise_for_status()
    return resp.json()


def _post(url: str, token: str, path: str, body: dict) -> dict:
    resp = requests.post(
        f"{url.rstrip('/')}{path}", json=body, headers=_headers(token), timeout=30
    )
    resp.raise_for_status()
    return resp.json()


def _put(url: str, token: str, path: str, body: dict) -> dict:
    resp = requests.put(
        f"{url.rstrip('/')}{path}", json=body, headers=_headers(token), timeout=30
    )
    resp.raise_for_status()
    return resp.json()


def find_collection(url: str, token: str, name: str):
    data = _get(url, token, "/api/collection")
    cols = data if isinstance(data, list) else data.get("data", [])
    for c in cols:
        if c.get("name") == name:
            return c.get("id")
    return None


def create_collection(url: str, token: str, name: str, description: str = "") -> int:
    existing = find_collection(url, token, name)
    if existing is not None:
        return existing
    result = _post(
        url,
        token,
        "/api/collection",
        {"name": name, "description": description, "color": "#509EE3", "parent_id": None},
    )
    return result["id"]


def ensure_trino_database(
    url: str,
    token: str,
    trino_host: str,
    name: str = "Trino (DemoForge)",
    catalog: str = "iceberg",
    schema: str = None,
) -> int:
    """Find or create a Metabase database entry for Trino."""
    data = _get(url, token, "/api/database")
    dbs = data if isinstance(data, list) else data.get("data", [])
    for db in dbs:
        db_name = db.get("name", "").lower()
        if "trino" in db_name or "presto" in db_name or db.get("name") == name:
            return db["id"]

    host = trino_host
    port = 8080
    if ":" in trino_host:
        host, port_s = trino_host.split(":", 1)
        port = int(port_s)

    body = {
        "name": name,
        "engine": "presto-jdbc",
        "details": {
            "host": host,
            "port": port,
            "catalog": catalog,
            "schema": schema or "default",
            "user": "demoforge",
            "ssl": False,
        },
        "is_full_sync": True,
    }
    try:
        result = _post(url, token, "/api/database", body)
        return result["id"]
    except Exception:
        # fallback engine name
        body["engine"] = "presto"
        result = _post(url, token, "/api/database", body)
        return result["id"]


_VIS_MAP = {
    "table": "table",
    "bar": "bar",
    "line": "line",
    "number": "scalar",
    "scalar": "scalar",
    "pie": "pie",
    "time_series": "line",
}


def create_question(
    url: str,
    token: str,
    collection_id: int,
    title: str,
    sql: str,
    visualization: str = "table",
    description: str = "",
    db_id: int = None,
) -> int:
    display = _VIS_MAP.get(visualization, "table")
    body = {
        "name": title,
        "description": description,
        "display": display,
        "visualization_settings": {},
        "collection_id": collection_id,
        "dataset_query": {
            "type": "native",
            "native": {"query": sql.strip()},
            "database": db_id,
        },
    }
    result = _post(url, token, "/api/card", body)
    return result["id"]


def create_dashboard(url: str, token: str, title: str, description: str = "") -> int:
    result = _post(
        url, token, "/api/dashboard", {"name": title, "description": description}
    )
    return result["id"]


def add_cards_to_dashboard(url: str, token: str, dashboard_id: int, dashcards: list):
    """Submit layout in a single PUT."""
    payload = []
    for i, dc in enumerate(dashcards):
        payload.append(
            {
                "id": -(i + 1),
                "card_id": dc["card_id"],
                "row": dc.get("row", 0),
                "col": dc.get("col", 0),
                "size_x": dc.get("width", 6),
                "size_y": dc.get("height", 4),
                "parameter_mappings": [],
                "visualization_settings": dc.get("visualization_settings", {}),
            }
        )
    return _put(url, token, f"/api/dashboard/{dashboard_id}", {"dashcards": payload})
