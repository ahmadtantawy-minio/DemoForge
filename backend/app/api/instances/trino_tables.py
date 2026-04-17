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

class TrinoQueryRequest(BaseModel):
    sql: str


@router.post("/api/demos/{demo_id}/trino-query")
async def execute_trino_query(demo_id: str, req: TrinoQueryRequest):
    """Execute a SQL query against the Trino container for this demo."""
    import time
    import json as _json

    running = state.get_demo(demo_id)
    if not running:
        raise HTTPException(404, "Demo not running")

    # Find the Trino container
    trino_container = None
    for node_id, container in running.containers.items():
        if container.component_id == "trino":
            trino_container = container.container_name
            break

    if not trino_container:
        raise HTTPException(404, "No Trino container found in this demo")

    sql = req.sql.strip()
    if not sql:
        raise HTTPException(400, "SQL query is empty")

    # Escape the SQL for shell: use shlex.quote on the full trino --execute arg
    trino_cmd = f"trino --output-format=JSON --execute {shlex.quote(sql)}"
    shell_cmd = f"sh -c {shlex.quote(trino_cmd)}"

    start_ms = time.time()
    try:
        exit_code, stdout, stderr = await exec_in_container(trino_container, shell_cmd)
    except Exception as e:
        raise HTTPException(500, f"Failed to exec in Trino container: {e}")

    duration_ms = int((time.time() - start_ms) * 1000)

    if exit_code != 0:
        error_msg = (stderr or stdout or "Query failed").strip()
        return {
            "columns": [],
            "rows": [],
            "row_count": 0,
            "duration_ms": duration_ms,
            "error": error_msg,
        }

    # Parse JSON output: each line is a JSON object (one row per line)
    # First line contains the header row with column names
    lines = [ln for ln in stdout.splitlines() if ln.strip()]
    if not lines:
        return {"columns": [], "rows": [], "row_count": 0, "duration_ms": duration_ms}

    columns: list[str] = []
    rows: list[list] = []
    for i, line in enumerate(lines[:1001]):  # cap at 1001 to detect overflow
        try:
            obj = _json.loads(line)
        except Exception:
            continue
        if i == 0:
            columns = list(obj.keys())
        rows.append([obj.get(col) for col in columns])

    truncated = len(rows) > 1000
    if truncated:
        rows = rows[:1000]

    return {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "duration_ms": duration_ms,
        "truncated": truncated,
    }


@router.post("/api/demos/{demo_id}/setup-tables")
async def setup_tables(demo_id: str):
    """Ensure all Iceberg tables exist for all dataset scenarios.

    Creates missing tables in Trino's iceberg.demo schema based on
    the scenario YAML definitions. Safe to call multiple times.
    """
    running = state.get_demo(demo_id)
    if not running:
        raise HTTPException(404, "Demo not running")

    # Find Trino container
    trino_container = None
    for node_id, container in running.containers.items():
        if container.component_id == "trino":
            trino_container = container.container_name
            break
    if not trino_container:
        raise HTTPException(404, "No Trino container found in this demo")

    # Detect primary catalog from demo definition
    import os as _os
    import yaml as _yaml
    demo_def = _load_demo(demo_id)
    primary_catalog = "iceberg"
    if demo_def:
        trino_node_id = next((n.id for n in demo_def.nodes if n.component == "trino"), None)
        if trino_node_id:
            for edge in demo_def.edges:
                if edge.target == trino_node_id:
                    cat = (edge.connection_config or {}).get("catalog_name")
                    if cat:
                        primary_catalog = cat
                        break
        if primary_catalog == "iceberg":
            # Also detect AIStor via node config
            for n in demo_def.nodes:
                if n.component == "minio" and n.config.get("MINIO_EDITION", "ce") == "aistor":
                    primary_catalog = "aistor"
                    break
            for c in demo_def.clusters:
                if getattr(c, 'aistor_tables_enabled', False):
                    primary_catalog = "aistor"
                    break

    # Load all scenario YAMLs
    datasets_dir = _os.path.join(
        _os.environ.get("DEMOFORGE_COMPONENTS_DIR", "./components"),
        "data-generator", "datasets"
    )

    results = []
    type_map = {
        "string": "VARCHAR", "int32": "INTEGER", "int64": "BIGINT",
        "float32": "REAL", "float64": "DOUBLE", "boolean": "BOOLEAN",
        "timestamp": "TIMESTAMP", "date": "DATE",
        "long": "BIGINT", "integer": "INTEGER", "double": "DOUBLE",
    }

    # Ensure schema exists
    schema_cmd = f'trino --execute "CREATE SCHEMA IF NOT EXISTS {primary_catalog}.demo"'
    await exec_in_container(trino_container, schema_cmd)
    created_schemas: set = {f"{primary_catalog}.demo"}

    if not _os.path.isdir(datasets_dir):
        return {"results": [{"table": "?", "status": "error", "detail": f"Datasets dir not found: {datasets_dir}"}]}

    for fname in sorted(_os.listdir(datasets_dir)):
        if not fname.endswith(".yaml"):
            continue
        fpath = _os.path.join(datasets_dir, fname)
        with open(fpath, "r") as f:
            scenario = _yaml.safe_load(f)

        iceberg_cfg = scenario.get("iceberg", {}) or {}
        table_name = iceberg_cfg.get("table", scenario.get("id", fname.replace(".yaml", "")).replace("-", "_"))
        table_schema = iceberg_cfg.get("namespace", "demo")
        full_table = f"{primary_catalog}.{table_schema}.{table_name}"

        # Check if table exists
        check_cmd = f'trino --execute "SELECT 1 FROM {full_table} LIMIT 1"'
        exit_code, _, _ = await exec_in_container(trino_container, check_cmd)
        if exit_code == 0:
            results.append({"table": full_table, "status": "exists"})
            continue

        # Build and create table
        schema_block = scenario.get("schema", {})
        columns = schema_block.get("columns", []) if isinstance(schema_block, dict) else schema_block
        if not columns:
            results.append({"table": full_table, "status": "skipped", "detail": "No columns in schema"})
            continue

        col_defs = ", ".join(
            f"{col['name']} {type_map.get(col.get('type', 'string'), 'VARCHAR')}"
            for col in columns
        )
        create_sql = f"CREATE TABLE IF NOT EXISTS {full_table} ({col_defs}) WITH (format = 'PARQUET')"

        create_cmd = f'trino --execute "{create_sql}"'
        exit_code, stdout, stderr = await exec_in_container(trino_container, create_cmd)
        clean_err = "\n".join(l for l in (stderr or "").splitlines() if "jline" not in l and "WARNING" not in l).strip()
        if exit_code == 0 or "already exists" in clean_err.lower():
            results.append({"table": full_table, "status": "created"})
        else:
            results.append({"table": full_table, "status": "error", "detail": clean_err[:200]})

    # Create tables for external-system scenarios (soc-firewall-events, soc-threat-intel, etc.)
    if demo_def:
        es_dir = _os.path.join(
            _os.environ.get("DEMOFORGE_COMPONENTS_DIR", "./components"),
            "external-system", "scenarios"
        )
        es_nodes = [n for n in demo_def.nodes if n.component == "external-system"]
        for es_node in es_nodes:
            es_scenario_id = es_node.config.get("ES_SCENARIO", "")
            if not es_scenario_id:
                continue
            es_path = _os.path.join(es_dir, f"{es_scenario_id}.yaml")
            if not _os.path.isfile(es_path):
                continue
            with open(es_path, "r") as f:
                es_scenario = _yaml.safe_load(f)

            for ds in es_scenario.get("datasets", []):
                ns = ds.get("namespace", "soc")
                schema_key = f"{primary_catalog}.{ns}"
                if schema_key not in created_schemas:
                    await exec_in_container(trino_container, f'trino --execute "CREATE SCHEMA IF NOT EXISTS {primary_catalog}.{ns}"')
                    created_schemas.add(schema_key)

                if ds.get("target") == "table":
                    tname = ds.get("table_name", ds.get("id", "").replace("-", "_"))
                    full = f"{primary_catalog}.{ns}.{tname}"
                    ec, _, _ = await exec_in_container(trino_container, f'trino --execute "SELECT 1 FROM {full} LIMIT 1"')
                    if ec == 0:
                        results.append({"table": full, "status": "exists"})
                        continue
                    cols = ds.get("schema", [])
                    if not cols:
                        results.append({"table": full, "status": "skipped", "detail": "No columns"})
                        continue
                    col_defs = ", ".join(
                        f"{c['name']} {type_map.get(c.get('type', 'string'), 'VARCHAR')}"
                        for c in cols if 'name' in c
                    )
                    ec, _, stderr = await exec_in_container(trino_container, f'trino --execute "CREATE TABLE IF NOT EXISTS {full} ({col_defs}) WITH (format = \'PARQUET\')"')
                    clean_err = "\n".join(l for l in (stderr or "").splitlines() if "jline" not in l and "WARNING" not in l).strip()
                    results.append({"table": full, "status": "created" if ec == 0 or "already exists" in clean_err.lower() else "error", "detail": clean_err[:200] if ec != 0 else None})

                elif ds.get("target") == "object" and ds.get("mirror_to_table"):
                    mirror = ds["mirror_to_table"]
                    m_ns = mirror.get("namespace", ns)
                    m_tname = mirror.get("table_name", "")
                    m_fields = mirror.get("fields", [])
                    if not m_tname or not m_fields:
                        continue
                    m_schema_key = f"{primary_catalog}.{m_ns}"
                    if m_schema_key not in created_schemas:
                        await exec_in_container(trino_container, f'trino --execute "CREATE SCHEMA IF NOT EXISTS {primary_catalog}.{m_ns}"')
                        created_schemas.add(m_schema_key)
                    full_m = f"{primary_catalog}.{m_ns}.{m_tname}"
                    ec, _, _ = await exec_in_container(trino_container, f'trino --execute "SELECT 1 FROM {full_m} LIMIT 1"')
                    if ec == 0:
                        results.append({"table": full_m, "status": "exists"})
                        continue
                    parent_schema = {c["name"]: c for c in ds.get("schema", []) if "name" in c}
                    col_defs = ", ".join(
                        f"{f} {type_map.get(parent_schema[f].get('type', 'string'), 'VARCHAR')}"
                        for f in m_fields if f in parent_schema
                    )
                    if not col_defs:
                        results.append({"table": full_m, "status": "skipped", "detail": "No matching mirror fields"})
                        continue
                    ec, _, stderr = await exec_in_container(trino_container, f'trino --execute "CREATE TABLE IF NOT EXISTS {full_m} ({col_defs}) WITH (format = \'PARQUET\')"')
                    clean_err = "\n".join(l for l in (stderr or "").splitlines() if "jline" not in l and "WARNING" not in l).strip()
                    results.append({"table": full_m, "status": "created" if ec == 0 or "already exists" in clean_err.lower() else "error", "detail": clean_err[:200] if ec != 0 else None})

    # Create Hive external tables for data generators in raw write mode
    try:
        raw_generators = [
            n for n in demo_def.nodes
            if n.component == "data-generator"
            and n.config.get("DG_WRITE_MODE", "iceberg").lower() == "raw"
        ]
        if raw_generators:
            await exec_in_container(
                trino_container,
                'trino --execute "CREATE SCHEMA IF NOT EXISTS hive.raw"',
            )
            for gen_node in raw_generators:
                gen_fmt = gen_node.config.get("DG_FORMAT", "parquet").upper()
                gen_scenario = gen_node.config.get("DG_SCENARIO", "ecommerce-orders")
                # Find target bucket from edges
                gen_bucket = gen_node.config.get("S3_BUCKET", "raw-data")
                for edge in demo_def.edges:
                    if edge.source == gen_node.id and edge.connection_type in ("s3", "structured-data"):
                        edge_cfg = edge.connection_config or {}
                        gen_bucket = edge_cfg.get("target_bucket") or edge_cfg.get("bucket") or gen_bucket
                        break

                # Load scenario YAML for columns
                scenario_path = _os.path.join(datasets_dir, f"{gen_scenario}.yaml")
                if not _os.path.isfile(scenario_path):
                    continue
                with open(scenario_path, "r") as f:
                    scenario_def = _yaml.safe_load(f)

                iceberg_cfg = scenario_def.get("iceberg", {}) or {}
                table_name = iceberg_cfg.get("table", gen_scenario.replace("-", "_"))
                hive_table = f"hive.raw.{table_name}"

                # Check if hive table already exists
                hive_check = f'trino --execute "SELECT 1 FROM {hive_table} LIMIT 1"'
                exit_hive, _, _ = await exec_in_container(trino_container, hive_check)
                if exit_hive == 0:
                    results.append({"table": hive_table, "status": "exists"})
                    continue

                schema_block = scenario_def.get("schema", {})
                columns = schema_block.get("columns", []) if isinstance(schema_block, dict) else schema_block
                if not columns:
                    continue

                # CSV format requires all VARCHAR columns in Hive
                if gen_fmt == "CSV":
                    col_defs = ", ".join(f"{col['name']} VARCHAR" for col in columns)
                else:
                    col_defs = ", ".join(
                        f"{col['name']} {type_map.get(col.get('type', 'string'), 'VARCHAR')}"
                        for col in columns
                    )
                hive_sql = (
                    f"CREATE TABLE IF NOT EXISTS {hive_table} ({col_defs}) "
                    f"WITH (format = '{gen_fmt}', external_location = 's3a://{gen_bucket}/'"
                    f"{', skip_header_line_count = 1' if gen_fmt == 'CSV' else ''}"
                    f")"
                )
                hive_cmd = f'trino --execute "{hive_sql}"'
                exit_h, _, stderr_h = await exec_in_container(trino_container, hive_cmd)
                clean_h = "\n".join(
                    l for l in (stderr_h or "").splitlines()
                    if "jline" not in l and "WARNING" not in l
                ).strip()
                if exit_h == 0 or "already exists" in clean_h.lower():
                    results.append({"table": hive_table, "status": "created"})
                else:
                    results.append({"table": hive_table, "status": "error", "detail": clean_h[:200]})
    except Exception as exc:
        logger.debug(f"Hive external table creation skipped: {exc}")

    return {"results": results}


