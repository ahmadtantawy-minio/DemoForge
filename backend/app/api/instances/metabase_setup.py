from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import asyncio
import base64
import json
import logging
import os
import re
import shlex
import time as time_module
import uuid
import httpx
from ...state.store import state, EdgeConfigResult
from ...registry.loader import get_component
from ...engine.docker_manager import (
    get_container_health,
    restart_container,
    exec_in_container,
    docker_client,
    apply_saved_demo_topology,
)
from ...engine.proxy_gateway import get_http_client
from ...engine.edge_automation import (
    generate_edge_scripts, _get_credential, _safe, _find_cluster,
    _get_cluster_credentials, _resolve_cluster_endpoint,
)
from ...engine.compose_generator import generate_compose
from ...models.api_models import (
    InstancesResponse, ContainerInstance, WebUILink,
    ExecRequest, ExecResponse, NetworkMembership, CredentialInfo,
    EdgeConfigStatus, ExecLogRequest, LogResponse,
    ExternalSystemOnDemandMetaResponse, ExternalSystemOnDemandDataset,
    ExternalSystemOnDemandTriggerRequest,
)
from ..demos import _load_demo, _save_demo
from ...engine import task_manager
from .helpers import (
    _repl_cache,
    _resolve_components_dir,
    append_demo_integration_audit,
    _load_demo_integration_audit,
    _metabase_dashboard_rows,
    _check_live_replication_status,
    _build_replication_state_cmd,
    _expand_demo_for_edges,
    _get_first_cluster_alias,
    _external_system_on_demand_meta_dict,
    _METABASE_CHART_MAP,
    _build_superset_position_json,
    _build_superset_dashboard_specs,
)

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/api/demos/{demo_id}/setup-metabase")
async def setup_metabase_dashboards(demo_id: str):
    """Auto-create Metabase dashboards for all active data generator scenarios.

    Resolves the correct Trino catalog (iceberg/aistor/hive) for each scenario
    based on the generator's write mode and target cluster.
    """
    import yaml as _yaml

    running = state.get_demo(demo_id)
    if not running:
        raise HTTPException(404, "Demo not running")

    # Find Metabase container
    metabase_container = None
    for node_id, container in running.containers.items():
        if container.component_id == "metabase":
            metabase_container = container.container_name
            break
    if not metabase_container:
        raise HTTPException(404, "No Metabase container in this demo")

    # Load demo definition for catalog routing
    demos_dir = os.environ.get("DEMOFORGE_DEMOS_DIR", "./demos")
    demo_path = os.path.join(demos_dir, f"{demo_id}.yaml")
    if not os.path.isfile(demo_path):
        raise HTTPException(404, "Demo definition not found")
    with open(demo_path) as f:
        demo_def = _yaml.safe_load(f)

    # Build scenario → (catalog, namespace) map
    components_dir = os.environ.get("DEMOFORGE_COMPONENTS_DIR", "./components")
    datasets_dir = os.path.join(os.path.abspath(components_dir), "data-generator", "datasets")

    scenario_catalog = {}
    for node in demo_def.get("nodes", []):
        if node.get("component") != "data-generator":
            continue
        cfg = node.get("config", {})
        sc = cfg.get("DG_SCENARIO", "ecommerce-orders")
        wm = cfg.get("DG_WRITE_MODE", "iceberg")
        if wm == "raw":
            scenario_catalog[sc] = ("hive", "raw")
        else:
            # Check if targeting AIStor cluster
            is_aistor = False
            for e in demo_def.get("edges", []):
                if e.get("source") == node.get("id") and e.get("connection_type") in ("structured-data", "s3"):
                    target = e.get("target", "")
                    for cl in demo_def.get("clusters", []):
                        if cl.get("id") == target and cl.get("aistor_tables_enabled"):
                            is_aistor = True
                            break
            scenario_catalog[sc] = ("aistor", "demo") if is_aistor else ("iceberg", "demo")

    # Create dashboards via exec in Metabase container (it has requests + python)
    # Actually, call Metabase API from the backend directly since we're on the same network
    results = []

    # Find Metabase URL — resolve from container (same Docker network as backend; offline)
    metabase_url = f"http://{metabase_container}:3000"
    append_demo_integration_audit(
        demo_id, "info", "data_generator_dash", "setup-metabase started", metabase_url,
    )

    import asyncio
    import httpx

    # Wait for Metabase with exponential backoff (handles slow JVM / Trino ordering)
    delay = 2.0
    healthy = False
    for attempt in range(24):
        try:
            async with httpx.AsyncClient(timeout=12) as client:
                r = await client.get(f"{metabase_url}/api/health")
                if r.status_code == 200:
                    body = r.json()
                    st = body.get("status") if isinstance(body, dict) else None
                    if st in (None, "ok"):
                        healthy = True
                        break
        except Exception as exc:
            append_demo_integration_audit(
                demo_id,
                "warn" if attempt > 4 else "info",
                "data_generator_dash",
                f"Metabase health check attempt {attempt + 1}",
                str(exc)[:200],
            )
        await asyncio.sleep(min(45.0, delay))
        delay = min(45.0, delay * 1.35)
    if not healthy:
        append_demo_integration_audit(demo_id, "error", "data_generator_dash", "Metabase not ready", "")
        return {"results": [{"status": "error", "detail": "Metabase not ready"}]}

    append_demo_integration_audit(demo_id, "info", "data_generator_dash", "Metabase healthy", "")

    # Authenticate
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            auth_resp = await client.post(
                f"{metabase_url}/api/session",
                json={"username": "admin@demoforge.local", "password": "DemoForge123!"},
            )
            auth_resp.raise_for_status()
            mb_token = auth_resp.json()["id"]
    except Exception as exc:
        append_demo_integration_audit(demo_id, "error", "data_generator_dash", "Metabase auth failed", str(exc)[:300])
        return {"results": [{"status": "error", "detail": f"Metabase auth failed: {exc}"}]}

    headers = {"X-Metabase-Session": mb_token, "Content-Type": "application/json"}

    # Find Trino database ID (retry: metabase-init may still be adding DB)
    trino_db_id = None
    databases: list = []
    for db_attempt in range(8):
        async with httpx.AsyncClient(timeout=20) as client:
            db_resp = await client.get(f"{metabase_url}/api/database", headers=headers)
            raw = db_resp.json()
            databases = raw.get("data", []) if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])
            for db in databases:
                if "trino" in db.get("name", "").lower():
                    trino_db_id = db["id"]
                    break
        if trino_db_id:
            break
        append_demo_integration_audit(
            demo_id, "warn", "data_generator_dash",
            f"No Trino DB in Metabase yet (attempt {db_attempt + 1}/8)",
            str([d.get("name") for d in databases]),
        )
        await asyncio.sleep(min(20.0, 3.0 * (db_attempt + 1)))

    if not trino_db_id:
        append_demo_integration_audit(
            demo_id, "error", "data_generator_dash", "No Trino database in Metabase",
            str([d.get("name") for d in databases]),
        )
        return {
            "results": [{
                "status": "error",
                "detail": f"No Trino database in Metabase. Available: {[d.get('name') for d in databases]}",
            }],
        }

    # Process each active scenario
    for scenario_id, (catalog, namespace) in scenario_catalog.items():
        yaml_path = os.path.join(datasets_dir, f"{scenario_id}.yaml")
        if not os.path.isfile(yaml_path):
            results.append({"scenario": scenario_id, "status": "skipped", "detail": "YAML not found"})
            continue

        with open(yaml_path) as f:
            scenario = _yaml.safe_load(f)

        dashboard_cfg = scenario.get("metabase_dashboard", {})
        if not dashboard_cfg:
            results.append({"scenario": scenario_id, "status": "skipped", "detail": "No dashboard config"})
            continue

        # Resolve queries with correct catalog
        queries = []
        for q in scenario.get("queries", []):
            sql = q.get("sql", "").replace("{catalog}", catalog).replace("{namespace}", namespace)

            # Auto-cast for Hive CSV
            if catalog == "hive":
                import re
                schema_block = scenario.get("schema", {})
                col_types = {}
                if isinstance(schema_block, dict):
                    for col in schema_block.get("columns", []):
                        col_types[col["name"]] = col.get("type", "string")
                cast_map = {"int32": "INTEGER", "int64": "BIGINT", "float32": "REAL", "float64": "DOUBLE", "boolean": "BOOLEAN"}
                for col_name, col_type in col_types.items():
                    if col_name not in sql:
                        continue
                    if col_type == "timestamp":
                        sql = re.sub(rf'\b{re.escape(col_name)}\b(?!\s*\.)', f"from_iso8601_timestamp({col_name})", sql)
                    elif col_type in cast_map:
                        sql = re.sub(rf'\b{re.escape(col_name)}\b(?!\s*\.)', f"CAST({col_name} AS {cast_map[col_type]})", sql)

            queries.append({**q, "sql": sql.strip()})

        # Check if dashboard already exists (API returns {data: [...]} or a bare list)
        async with httpx.AsyncClient(timeout=20) as client:
            dash_list_resp = await client.get(f"{metabase_url}/api/dashboard", headers=headers)
            dash_rows = _metabase_dashboard_rows(dash_list_resp.json())
            target_name = dashboard_cfg.get("name")
            existing = [d for d in dash_rows if d.get("name") == target_name]
            if existing:
                append_demo_integration_audit(
                    demo_id, "info", "data_generator_dash",
                    f"Dashboard exists: {target_name}", f"id={existing[0].get('id')}",
                )
                results.append({"scenario": scenario_id, "status": "exists", "dashboard_id": existing[0]["id"]})
                continue

        # Create cards and dashboard
        try:
            card_ids = {}
            async with httpx.AsyncClient(timeout=45) as client:
                for q in queries:
                    chart_type = q.get("chart_type", "table")
                    display, viz = _METABASE_CHART_MAP.get(chart_type, ("table", {}))
                    card_body = {
                        "name": q.get("name", q.get("id", "Untitled")),
                        "display": display,
                        "visualization_settings": viz,
                        "dataset_query": {
                            "type": "native",
                            "native": {"query": q["sql"]},
                            "database": trino_db_id,
                        },
                    }
                    cid = None
                    card_resp = None
                    for card_try in range(5):
                        card_resp = await client.post(
                            f"{metabase_url}/api/card", json=card_body, headers=headers,
                        )
                        if card_resp.status_code in (200, 202):
                            cid = card_resp.json()["id"]
                            break
                        if card_resp.status_code in (502, 503, 504):
                            await asyncio.sleep(min(8.0, 1.5 * (card_try + 1)))
                            continue
                        break
                    if cid:
                        card_ids[q["id"]] = cid
                    else:
                        _detail = ""
                        try:
                            _detail = (card_resp.text[:300] if card_resp else "") or ""
                        except Exception:
                            _detail = ""
                        append_demo_integration_audit(
                            demo_id, "warn", "data_generator_dash",
                            f"Card create failed for query {q.get('id')}",
                            _detail,
                        )

                # Create dashboard
                dash_name = dashboard_cfg.get("name", f"{scenario.get('name')} Dashboard")
                dash_resp = await client.post(
                    f"{metabase_url}/api/dashboard",
                    json={"name": dash_name, "description": dashboard_cfg.get("description", "")},
                    headers=headers,
                )
                dash_resp.raise_for_status()
                dash_id = dash_resp.json()["id"]

                # Add cards with layout
                layout = dashboard_cfg.get("layout", [])
                dashcards = []
                for item in layout:
                    card_id = card_ids.get(item.get("query"))
                    if card_id:
                        dashcards.append({
                            "id": -(len(dashcards) + 1),
                            "card_id": card_id,
                            "row": item.get("row", 0),
                            "col": item.get("col", 0),
                            "size_x": item.get("width", 4),
                            "size_y": item.get("height", 4),
                        })
                await client.put(
                    f"{metabase_url}/api/dashboard/{dash_id}",
                    json={"dashcards": dashcards},
                    headers=headers,
                )

            append_demo_integration_audit(
                demo_id, "info", "data_generator_dash",
                f"Created dashboard {dash_name}", f"scenario={scenario_id} cards={len(card_ids)}",
            )
            results.append({
                "scenario": scenario_id,
                "status": "created",
                "dashboard_id": dash_id,
                "cards": len(card_ids),
            })
        except Exception as exc:
            append_demo_integration_audit(
                demo_id, "error", "data_generator_dash", f"Scenario failed: {scenario_id}", str(exc)[:400],
            )
            results.append({"scenario": scenario_id, "status": "error", "detail": str(exc)[:200]})

    return {"results": results}

