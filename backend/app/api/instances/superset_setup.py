from __future__ import annotations

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

@router.post("/api/demos/{demo_id}/setup-superset")
async def setup_superset_dashboards(demo_id: str):
    """Auto-create Superset dashboards for all active data generator scenarios.

    Authenticates to Superset via JWT, creates a Trino database connection,
    registers datasets, and provisions dashboards for each active scenario.
    """
    import yaml as _yaml
    import json as _json

    running = state.get_demo(demo_id)
    if not running:
        raise HTTPException(404, "Demo not running")

    # Find Superset container
    superset_container = None
    for node_id, container in running.containers.items():
        if container.component_id == "superset":
            superset_container = container.container_name
            break
    if not superset_container:
        raise HTTPException(404, "No Superset container in this demo")

    # Load demo definition for catalog routing
    demos_dir = os.environ.get("DEMOFORGE_DEMOS_DIR", "./demos")
    demo_path = os.path.join(demos_dir, f"{demo_id}.yaml")
    if not os.path.isfile(demo_path):
        raise HTTPException(404, "Demo definition not found")
    with open(demo_path) as f:
        demo_def = _yaml.safe_load(f)

    # Build scenario → (catalog, namespace) map (same logic as Metabase)
    scenario_catalog: dict = {}
    for node in demo_def.get("nodes", []):
        if node.get("component") != "data-generator":
            continue
        cfg = node.get("config", {})
        sc = cfg.get("DG_SCENARIO", "ecommerce-orders")
        wm = cfg.get("DG_WRITE_MODE", "iceberg")
        if wm == "raw":
            scenario_catalog[sc] = ("hive", "raw")
        else:
            is_aistor = False
            for e in demo_def.get("edges", []):
                if e.get("source") == node.get("id") and e.get("connection_type") in ("structured-data", "s3"):
                    target = e.get("target", "")
                    for cl in demo_def.get("clusters", []):
                        if cl.get("id") == target and cl.get("aistor_tables_enabled"):
                            is_aistor = True
                            break
            # Also detect AIStor via minio node MINIO_EDITION config
            if not is_aistor:
                for n in demo_def.get("nodes", []):
                    if n.get("component") == "minio" and n.get("config", {}).get("MINIO_EDITION", "ce") == "aistor":
                        is_aistor = True
                        break
            scenario_catalog[sc] = ("aistor", "demo") if is_aistor else ("iceberg", "demo")

    # Wait for Superset to be ready (up to 60s) via health endpoint
    import httpx
    superset_url = f"http://{superset_container}:8088"
    async with httpx.AsyncClient(timeout=10) as client:
        for attempt in range(12):
            try:
                r = await client.get(f"{superset_url}/health")
                if r.status_code == 200:
                    break
            except Exception:
                pass
            await asyncio.sleep(5)
        else:
            return {"results": [{"status": "error", "detail": "Superset not ready after 60s"}]}

    # Find Trino container for URI
    trino_container = None
    for node_id, container in running.containers.items():
        if container.component_id == "trino":
            trino_container = container.container_name
            break

    primary_catalog = next(
        (cat for cat, _ in scenario_catalog.values()), "iceberg"
    )
    trino_uri = f"trino://demoforge@{trino_container or 'trino'}:8080/{primary_catalog}"

    dashboard_specs = _build_superset_dashboard_specs()
    results = []

    # Process each active scenario via docker exec (avoids Flask-Login/JWT auth issues)
    for scenario_id, (catalog, namespace) in scenario_catalog.items():
        spec = dashboard_specs.get(scenario_id)
        if not spec:
            results.append({"scenario": scenario_id, "status": "skipped", "detail": "No Superset dashboard spec"})
            continue

        try:
            charts_json = _json.dumps(spec["charts"])
            layout_json = _json.dumps(spec["layout"])
            script = (
                "import os, json, sys\n"
                "os.environ['SUPERSET_CONFIG_PATH'] = '/app/superset_config.py'\n"
                "from superset.app import create_app\n"
                "app = create_app()\n"
                "with app.app_context():\n"
                "    from superset import db, security_manager\n"
                "    from superset.models.core import Database\n"
                "    from superset.connectors.sqla.models import SqlaTable\n"
                "    from superset.models.slice import Slice\n"
                "    from superset.models.dashboard import Dashboard\n"
                "    from flask_login import login_user\n"
                "    admin = security_manager.find_user('admin')\n"
                "    with app.test_request_context():\n"
                "        login_user(admin)\n"
                f"        trino_uri = {_json.dumps(trino_uri)}\n"
                f"        schema = {_json.dumps(spec['schema'])}\n"
                f"        table_name = {_json.dumps(spec['table'])}\n"
                f"        dash_title = {_json.dumps(spec['title'])}\n"
                f"        dash_slug = {_json.dumps(spec['slug'])}\n"
                f"        charts_spec = json.loads({_json.dumps(charts_json)})\n"
                f"        layout_spec = json.loads({_json.dumps(layout_json)})\n"
                "        database = db.session.query(Database).filter_by(database_name='DemoForge Trino').first()\n"
                "        if not database:\n"
                "            database = Database(database_name='DemoForge Trino', sqlalchemy_uri=trino_uri, expose_in_sqllab=True, allow_run_async=False)\n"
                "            db.session.add(database)\n"
                "            db.session.commit()\n"
                "        table = db.session.query(SqlaTable).filter_by(database_id=database.id, schema=schema, table_name=table_name).first()\n"
                "        if not table:\n"
                "            table = SqlaTable(table_name=table_name, schema=schema, database_id=database.id)\n"
                "            db.session.add(table)\n"
                "            db.session.commit()\n"
                "        chart_ids = []\n"
                "        for cs in charts_spec:\n"
                "            ch = db.session.query(Slice).filter_by(slice_name=cs['name']).first()\n"
                "            if not ch:\n"
                "                ch = Slice(slice_name=cs['name'], viz_type=cs['viz_type'], datasource_id=table.id, datasource_type='table', params=json.dumps(cs['params']))\n"
                "                db.session.add(ch)\n"
                "            else:\n"
                "                ch.params = json.dumps(cs['params'])\n"
                "            db.session.commit()\n"
                "            chart_ids.append(ch.id)\n"
                "        dash = db.session.query(Dashboard).filter_by(slug=dash_slug).first()\n"
                "        if not dash:\n"
                "            slices = [db.session.get(Slice, cid) for cid in chart_ids]\n"
                "            dash = Dashboard(dashboard_title=dash_title, slug=dash_slug, published=True, slices=slices)\n"
                "            db.session.add(dash)\n"
                "            db.session.commit()\n"
                "        meta = json.loads(dash.json_metadata or '{}')\n"
                "        meta['refresh_frequency'] = 60\n"
                "        meta['stagger_refresh'] = False\n"
                "        meta['timed_refresh_immune_slices'] = []\n"
                "        dash.json_metadata = json.dumps(meta)\n"
                "        db.session.commit()\n"
                "        # Grant Public role Admin-level permissions so unauthenticated users see dashboards\n"
                "        admin_role = security_manager.find_role('Admin')\n"
                "        public_role = security_manager.find_role('Public')\n"
                "        if admin_role and public_role:\n"
                "            public_role.permissions = list(admin_role.permissions)\n"
                "            db.session.commit()\n"
                "        print(json.dumps({'status': 'created', 'dashboard_id': dash.id, 'charts': len(chart_ids)}))\n"
            )
            proc = await asyncio.create_subprocess_exec(
                "docker", "exec", superset_container, "python3", "-c", script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=90)
            if proc.returncode == 0:
                output = stdout.decode().strip().splitlines()
                # Last line should be the JSON result
                for line in reversed(output):
                    try:
                        result = _json.loads(line)
                        results.append({"scenario": scenario_id, **result})
                        break
                    except Exception:
                        continue
                else:
                    results.append({"scenario": scenario_id, "status": "error", "detail": stdout.decode()[-200:]})
            else:
                results.append({"scenario": scenario_id, "status": "error", "detail": stderr.decode()[-300:]})
        except Exception as exc:
            results.append({"scenario": scenario_id, "status": "error", "detail": str(exc)[:200]})

    return {"results": results}

