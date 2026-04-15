#!/usr/bin/env python3
"""
Metabase dashboard provisioning from MB_PROVISION_SPEC env var.
Runs as a sidecar after setup-metabase.sh completes.
Reads a JSON spec injected by DemoForge compose generator and provisions
dashboards/saved-queries into the already-setup Metabase instance.
"""

import json
import os
import sys
import time

import requests

MB_HOST = os.environ.get("METABASE_HOST", "metabase")
MB_URL = f"http://{MB_HOST}:3000"
MB_USER = os.environ.get("MB_USER", "admin@demoforge.local")
MB_PASS = os.environ.get("MB_PASSWORD", "DemoForge123!")
TRINO_HOST = os.environ.get("TRINO_HOST", "")
TRINO_CATALOG = os.environ.get("TRINO_CATALOG", "iceberg")
SPEC_JSON = os.environ.get("MB_PROVISION_SPEC", "")

VIS_MAP = {
    "table": "table", "bar": "bar", "line": "line",
    "number": "scalar", "scalar": "scalar", "pie": "pie",
    "time_series": "line",
}


def wait_ready(timeout=300):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(f"{MB_URL}/api/health", timeout=5)
            if r.ok and r.json().get("status") == "ok":
                print("[provision] Metabase ready.", flush=True)
                return
        except Exception:
            pass
        remaining = int(deadline - time.time())
        print(f"[provision] Waiting for Metabase… ({remaining}s left)", flush=True)
        time.sleep(5)
    raise RuntimeError(f"Metabase not ready after {timeout}s")


def get_token():
    r = requests.post(f"{MB_URL}/api/session",
                      json={"username": MB_USER, "password": MB_PASS}, timeout=15)
    r.raise_for_status()
    return r.json()["id"]


def headers(token):
    return {"X-Metabase-Session": token, "Content-Type": "application/json"}


def get(token, path):
    r = requests.get(f"{MB_URL}{path}", headers=headers(token), timeout=15)
    r.raise_for_status()
    return r.json()


def post(token, path, body):
    r = requests.post(f"{MB_URL}{path}", json=body, headers=headers(token), timeout=30)
    r.raise_for_status()
    return r.json()


def put(token, path, body):
    r = requests.put(f"{MB_URL}{path}", json=body, headers=headers(token), timeout=30)
    r.raise_for_status()
    return r.json()


def ensure_trino_db(token):
    host, port = (TRINO_HOST.split(":", 1) + ["8080"])[:2]
    data = get(token, "/api/database")
    dbs = data if isinstance(data, list) else data.get("data", [])
    for db in dbs:
        if "trino" in db.get("name", "").lower() or "presto" in db.get("name", "").lower():
            print(f"[provision] Using existing Trino DB id={db['id']}", flush=True)
            return db["id"]
    print(f"[provision] Creating Trino DB (host={host}, catalog={TRINO_CATALOG})", flush=True)
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


def ensure_collection(token, name, description="", parent_id=None):
    data = get(token, "/api/collection")
    cols = data if isinstance(data, list) else data.get("data", [])
    for c in cols:
        if c.get("name") == name and c.get("parent_id") == parent_id:
            return c["id"]
    result = post(token, "/api/collection",
                  {"name": name, "description": description, "color": "#509EE3", "parent_id": parent_id})
    print(f"[provision] Created collection '{name}' id={result['id']}", flush=True)
    return result["id"]


def create_question(token, col_id, title, sql, vis, db_id):
    body = {
        "name": title,
        "display": VIS_MAP.get(vis, "table"),
        "visualization_settings": {},
        "collection_id": col_id,
        "dataset_query": {"type": "native", "native": {"query": sql.strip()}, "database": db_id},
    }
    result = post(token, "/api/card", body)
    print(f"[provision]   + question: {title} (card={result['id']})", flush=True)
    return result["id"]


def create_dashboard(token, title, description=""):
    result = post(token, "/api/dashboard", {"name": title, "description": description})
    print(f"[provision] Created dashboard '{title}' id={result['id']}", flush=True)
    return result["id"]


def add_cards(token, dash_id, dashcards):
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


def main():
    if not SPEC_JSON:
        print("[provision] MB_PROVISION_SPEC not set — nothing to provision.", flush=True)
        return

    spec = json.loads(SPEC_JSON)
    dashboards = spec.get("dashboards", [])
    saved_queries = spec.get("saved_queries", {})

    if not dashboards and not saved_queries.get("queries"):
        print("[provision] No dashboards or saved queries in spec.", flush=True)
        return

    print(f"[provision] Starting Metabase provisioning (catalog={TRINO_CATALOG})", flush=True)
    wait_ready()
    token = get_token()
    print("[provision] Authenticated.", flush=True)

    db_id = ensure_trino_db(token) if TRINO_HOST else None
    if not db_id:
        print("[provision] No Trino host — skipping.", flush=True)
        return

    # Saved queries / collection
    col_name = saved_queries.get("collection", "")
    col_id = ensure_collection(token, col_name) if col_name else None

    # Create sub-collections as children of root collection
    subcol_id_map: dict = {}
    for sc in saved_queries.get("subcollections", []):
        sc_id = ensure_collection(token, sc["name"], sc.get("description", ""), parent_id=col_id)
        subcol_id_map[sc["id"]] = sc_id
        print(f"[provision] Sub-collection '{sc['name']}' id={sc_id}", flush=True)

    queries = sorted(saved_queries.get("queries", []), key=lambda q: q.get("order", 0))
    for q in queries:
        try:
            # Resolve to sub-collection if specified, otherwise root collection
            q_col_id = subcol_id_map.get(q.get("subcollection"), col_id)
            create_question(token, q_col_id, q["title"], q["query"],
                            q.get("visualization", "table"), db_id)
        except Exception as exc:
            print(f"[provision]   ! question failed {q.get('id')}: {exc}", flush=True)

    # Dashboards
    for dash in dashboards:
        try:
            dash_id = create_dashboard(token, dash["title"], dash.get("description", ""))
            dashcards = []
            for chart in dash.get("charts", []):
                try:
                    card_id = create_question(token, col_id, chart["title"], chart["query"],
                                              chart.get("type", "table"), db_id)
                    pos = chart.get("position", {})
                    dashcards.append({"card_id": card_id, "row": pos.get("row", 0),
                                      "col": pos.get("col", 0), "width": pos.get("width", 6),
                                      "height": pos.get("height", 4)})
                except Exception as exc:
                    print(f"[provision]   ! chart '{chart.get('title')}' failed: {exc}", flush=True)
            if dashcards:
                add_cards(token, dash_id, dashcards)
                print(f"[provision] Dashboard '{dash['title']}' ready ({len(dashcards)} cards)", flush=True)
        except Exception as exc:
            print(f"[provision] Dashboard '{dash.get('title')}' failed: {exc}", flush=True)

    print("[provision] Provisioning complete.", flush=True)


if __name__ == "__main__":
    main()
