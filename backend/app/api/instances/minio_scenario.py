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

@router.get("/api/demos/{demo_id}/minio-commands")
async def get_minio_commands(demo_id: str):
    """Return all MinIO mc commands used to set up this demo, grouped by category."""
    import re as _re

    demo = _load_demo(demo_id)
    if not demo:
        raise HTTPException(404, "Demo definition not found")

    commands = []
    project_name = f"demoforge-{demo_id}"

    # --- Alias Setup commands (from init.sh pattern in compose_generator) ---
    for cluster in demo.clusters:
        alias_name = _re.sub(r"[^a-zA-Z0-9_]", "_", cluster.label)
        lb_url = f"http://{project_name}-{cluster.id}-lb:80"
        cred_user = cluster.credentials.get("root_user", "minioadmin")
        cred_pass = cluster.credentials.get("root_password", "minioadmin")
        commands.append({
            "category": "Alias Setup",
            "description": f"Configure mc alias for cluster: {cluster.label}",
            "command": f"mc alias set '{alias_name}' '{lb_url}' '{cred_user}' '{cred_pass}'",
        })

    # Standalone MinIO nodes
    standalone_minio = [
        n for n in demo.nodes
        if n.component == "minio"
        and not any(n.id.startswith(f"{c.id}-") for c in demo.clusters)
    ]
    for node in standalone_minio:
        alias_name = _re.sub(r"[^a-zA-Z0-9_]", "_", node.display_name) if getattr(node, "display_name", None) else node.id
        node_url = f"http://{project_name}-{node.id}:9000"
        cred_user = node.config.get("MINIO_ROOT_USER", "minioadmin")
        cred_pass = node.config.get("MINIO_ROOT_PASSWORD", "minioadmin")
        commands.append({
            "category": "Alias Setup",
            "description": f"Configure mc alias for node: {node.id}",
            "command": f"mc alias set '{alias_name}' '{node_url}' '{cred_user}' '{cred_pass}'",
        })

    # --- Edge-generated commands (replication, site-replication, tiering) ---
    expanded_demo = _expand_demo_for_edges(demo)
    scripts = generate_edge_scripts(expanded_demo, project_name)

    # Map connection_type → category label
    _category_map = {
        "replication": "Bucket Replication",
        "cluster-replication": "Bucket Replication",
        "site-replication": "Site Replication",
        "cluster-site-replication": "Site Replication",
        "tiering": "ILM Tiering",
        "cluster-tiering": "ILM Tiering",
    }

    for script in scripts:
        category = _category_map.get(script.connection_type, "Other mc Commands")
        # Split compound commands (joined with &&) into individual lines for readability
        # but show the full command as-is for copy/paste accuracy
        commands.append({
            "category": category,
            "description": script.description,
            "command": script.command,
        })

    return {"demo_id": demo_id, "commands": commands}


# ---------------------------------------------------------------------------
# SQL Editor endpoints
# ---------------------------------------------------------------------------

@router.get("/api/demos/{demo_id}/scenario-queries/{scenario_id}")
async def get_scenario_queries(demo_id: str, scenario_id: str):
    """Return pre-built queries for a scenario with placeholders resolved.

    When scenario_id is 'all', returns queries for all scenarios grouped:
      { "scenarios": [{ "id": ..., "name": ..., "queries": [...] }] }

    Otherwise returns the single-scenario format (backward compat):
      { "scenario_id": ..., "queries": [...] }
    """
    import yaml as _yaml

    components_dir = os.environ.get("DEMOFORGE_COMPONENTS_DIR", "./components")
    datasets_dir = os.path.join(os.path.abspath(components_dir), "data-generator", "datasets")

    # Build a map of scenario → (catalog, namespace) from running generators
    _scenario_catalog_map = {}
    running = state.get_demo(demo_id)
    if running:
        demos_dir = os.environ.get("DEMOFORGE_DEMOS_DIR", "./demos")
        demo_path = os.path.join(demos_dir, f"{demo_id}.yaml")
        if os.path.isfile(demo_path):
            with open(demo_path) as _df:
                demo_def = _yaml.safe_load(_df)
            for node in demo_def.get("nodes", []):
                if node.get("component") == "data-generator":
                    cfg = node.get("config", {})
                    sc = cfg.get("DG_SCENARIO", "ecommerce-orders")
                    wm = cfg.get("DG_WRITE_MODE", "iceberg")
                    is_sigv4 = any(
                        e.get("source") == node.get("id")
                        and e.get("connection_config", {}).get("write_mode") == "raw"
                        for e in demo_def.get("edges", [])
                    ) or wm == "raw"
                    if is_sigv4 or wm == "raw":
                        _scenario_catalog_map[sc] = ("hive", "raw")
                    else:
                        # Check if targeting AIStor (SigV4)
                        for e in demo_def.get("edges", []):
                            if e.get("source") == node.get("id") and e.get("connection_type") in ("structured-data", "s3"):
                                target = e.get("target", "")
                                for cl in demo_def.get("clusters", []):
                                    if cl.get("id") == target and cl.get("aistor_tables_enabled"):
                                        _scenario_catalog_map[sc] = ("aistor", "demo")
                                        break
                        # Check standalone AIStor nodes
                        if sc not in _scenario_catalog_map:
                            for n in demo_def.get("nodes", []):
                                if n.get("component") == "minio" and n.get("config", {}).get("MINIO_EDITION", "ce") == "aistor":
                                    _scenario_catalog_map[sc] = ("aistor", "demo")
                                    break
                        if sc not in _scenario_catalog_map:
                            _scenario_catalog_map[sc] = ("iceberg", "demo")

    def _load_queries_from_yaml(yaml_path: str, scenario_id_hint: str = "") -> list:
        with open(yaml_path, "r", encoding="utf-8") as fh:
            raw = _yaml.safe_load(fh)
        sid = raw.get("id", scenario_id_hint)
        catalog, namespace = _scenario_catalog_map.get(sid, ("iceberg", "demo"))

        # For Hive CSV tables, all columns are VARCHAR — wrap numeric/timestamp
        # references with CAST for compatibility
        schema_cols = raw.get("schema", {})
        col_types = {}
        if isinstance(schema_cols, dict):
            for col in schema_cols.get("columns", []):
                col_types[col["name"]] = col.get("type", "string")

        iceberg_cfg = raw.get("iceberg", {}) or {}
        table = iceberg_cfg.get("table", raw.get("id", "").replace("-", "_"))

        queries = []
        for q in raw.get("queries", []):
            sql = (q.get("sql", "")
                   .replace("{catalog}", catalog)
                   .replace("{namespace}", namespace)
                   .replace("{table}", table))

            # Auto-cast for Hive CSV: replace bare column refs with CAST
            if catalog == "hive":
                import re
                cast_map = {
                    "int32": "INTEGER", "int64": "BIGINT",
                    "float32": "REAL", "float64": "DOUBLE",
                    "boolean": "BOOLEAN",
                }
                for col_name, col_type in col_types.items():
                    if col_name not in sql:
                        continue
                    if col_type == "timestamp":
                        # Use from_iso8601_timestamp for ISO format timestamps
                        sql = re.sub(
                            rf'\b{re.escape(col_name)}\b(?!\s*\.)',
                            f"from_iso8601_timestamp({col_name})",
                            sql,
                        )
                    else:
                        trino_type = cast_map.get(col_type)
                        if trino_type:
                            sql = re.sub(
                                rf'\b{re.escape(col_name)}\b(?!\s*\.)',
                                f"CAST({col_name} AS {trino_type})",
                                sql,
                            )
            queries.append({
                "id": q.get("id", ""),
                "name": q.get("name", ""),
                "sql": sql.strip(),
                "chart_type": q.get("chart_type", ""),
            })
        return raw, queries

    if scenario_id == "all":
        # Collect deployed scenario IDs from demo nodes
        deployed_scenarios: set[str] = set()
        has_running_demo = bool(running)
        if running:
            demos_dir_path = os.environ.get("DEMOFORGE_DEMOS_DIR", "./demos")
            demo_path = os.path.join(demos_dir_path, f"{demo_id}.yaml")
            if os.path.isfile(demo_path):
                with open(demo_path) as _df:
                    demo_def_all = _yaml.safe_load(_df)
                for node in demo_def_all.get("nodes", []):
                    cfg = node.get("config", {})
                    if node.get("component") == "data-generator":
                        sc = cfg.get("DG_SCENARIO", "")
                        if sc:
                            deployed_scenarios.add(sc)
                    elif node.get("component") == "external-system":
                        sc = cfg.get("ES_SCENARIO", "")
                        if sc:
                            deployed_scenarios.add(sc)

        scenarios = []
        should_skip = lambda sid: has_running_demo and deployed_scenarios and sid not in deployed_scenarios

        # Scan data-generator datasets
        if os.path.isdir(datasets_dir):
            for fname in sorted(os.listdir(datasets_dir)):
                if not fname.endswith(".yaml"):
                    continue
                sid = fname[: -len(".yaml")]
                if should_skip(sid):
                    continue
                yaml_path = os.path.join(datasets_dir, fname)
                try:
                    raw, queries = _load_queries_from_yaml(yaml_path)
                    scenarios.append({
                        "id": raw.get("id", sid),
                        "name": raw.get("name", sid),
                        "queries": queries,
                    })
                except Exception:
                    pass

        # Scan external-system scenarios
        ext_scenarios_dir = os.path.join(os.path.abspath(components_dir), "external-system", "scenarios")
        if os.path.isdir(ext_scenarios_dir):
            for fname in sorted(os.listdir(ext_scenarios_dir)):
                if not fname.endswith(".yaml") or fname.startswith("_"):
                    continue
                sid = fname[: -len(".yaml")]
                if should_skip(sid):
                    continue
                yaml_path = os.path.join(ext_scenarios_dir, fname)
                try:
                    with open(yaml_path, "r", encoding="utf-8") as fh:
                        ext_raw = _yaml.safe_load(fh)
                    scen = ext_raw.get("scenario", {})
                    scenario_name = scen.get("name", sid)
                    # Build queries from saved_queries block using first dataset's namespace
                    first_ds = next(iter(ext_raw.get("datasets", [])), {})
                    namespace = first_ds.get("namespace", "soc")
                    catalog = "iceberg"
                    ext_queries = []
                    saved_q = ext_raw.get("saved_queries", {})
                    for q in saved_q.get("queries", []):
                        sql = (q.get("query", "")
                               .replace("{catalog}", catalog)
                               .replace("{namespace}", namespace))
                        ext_queries.append({
                            "id": q.get("id", ""),
                            "name": q.get("title", q.get("name", "")),
                            "sql": sql.strip(),
                            "chart_type": q.get("visualization", ""),
                            "tab": q.get("tab", ""),
                        })
                    tabs_def = saved_q.get("tabs", [])
                    if tabs_def and ext_queries:
                        # Expand into one ScenarioTab per tab, queries filtered by tab field
                        for tab in sorted(tabs_def, key=lambda t: t.get("order", 0)):
                            tab_id = tab.get("id", "")
                            tab_queries = [q for q in ext_queries if q.get("tab") == tab_id]
                            if tab_queries:
                                scenarios.append({
                                    "id": tab_id,
                                    "name": tab.get("label", tab_id),
                                    "queries": tab_queries,
                                })
                    elif ext_queries:
                        scenarios.append({
                            "id": scen.get("id", sid),
                            "name": scenario_name,
                            "queries": ext_queries,
                        })
                except Exception:
                    pass

        return {"scenarios": scenarios}

    yaml_path = os.path.join(datasets_dir, f"{scenario_id}.yaml")
    if not os.path.exists(yaml_path):
        raise HTTPException(404, f"Scenario '{scenario_id}' not found")

    raw, queries = _load_queries_from_yaml(yaml_path)
    return {"scenario_id": scenario_id, "queries": queries}

