"""Shared helpers for the instances API (audit, replication, edge expansion, Superset specs)."""
import asyncio
import base64
import json
import logging
import os
import re
from pathlib import Path
import shlex
import time as time_module
import uuid
import httpx
from fastapi import HTTPException
from pydantic import BaseModel
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
    _cluster_first_minio_container_name,
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

logger = logging.getLogger(__name__)


def _resolve_components_dir() -> str:
    """Resolve components/ for scenario YAML. When uvicorn cwd is backend/, ./components is wrong."""
    env = (os.environ.get("DEMOFORGE_COMPONENTS_DIR") or "").strip()
    if env:
        return os.path.abspath(env)
    try:
        here = Path(__file__).resolve()
        root_components = here.parents[4] / "components"
        if root_components.is_dir():
            return str(root_components)
    except (OSError, IndexError):
        pass
    return os.path.abspath("./components")


def _demo_integration_audit_path(demo_id: str) -> str:
    demos_dir = os.environ.get("DEMOFORGE_DEMOS_DIR", "./demos")
    return os.path.join(demos_dir, demo_id, "integration_audit.jsonl")


def append_demo_integration_audit(
    demo_id: str, level: str, kind: str, message: str, details: str = ""
) -> None:
    """Append-only local JSONL for data-generator Metabase setup (offline, no cloud)."""
    path = _demo_integration_audit_path(demo_id)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        rec = {
            "id": str(uuid.uuid4()),
            "ts_ms": int(time_module.time() * 1000),
            "level": level,
            "kind": kind,
            "message": message,
            "details": details or "",
            "source": "backend",
            "node_id": "setup-metabase",
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _load_demo_integration_audit(demo_id: str, limit: int = 400) -> list[dict]:
    path = _demo_integration_audit_path(demo_id)
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        out: list[dict] = []
        for line in lines[-limit:]:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if isinstance(rec, dict):
                    out.append(rec)
            except json.JSONDecodeError:
                continue
        return out
    except OSError:
        return []


def _metabase_dashboard_rows(body: object) -> list:
    """Normalize GET /api/dashboard response (array or {data: [...]})."""
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        return body.get("data") or []
    return []


# Cache for live replication checks (avoid hammering mc on every poll)
_repl_cache: dict[str, tuple[float, bool]] = {}


async def _check_live_replication_status(running, demo_id: str) -> bool | None:
    """Check if site replication is actually enabled by querying mc-shell.

    Returns True if enabled, False if not, None if we can't determine.
    Caches result for 10 seconds to avoid excessive Docker exec calls.
    """
    import time
    now = time.time()
    cached = _repl_cache.get(demo_id)
    if cached and now - cached[0] < 10:
        return cached[1]

    mc_shell_name = f"demoforge-{demo_id}-mc-shell"
    if mc_shell_name not in [c.container_name for c in running.containers.values()]:
        return None

    try:
        # Compute the alias name from demo definition (same as compose_generator)
        import re as _re
        demo_def = None
        try:
            from ..demos import _load_demo
            demo_def = _load_demo(demo_id)
        except Exception:
            pass
        if demo_def and demo_def.clusters:
            alias = _re.sub(r"[^a-zA-Z0-9_]", "_", demo_def.clusters[0].label)
        elif demo_def:
            # Standalone MinIO nodes — site-replication uses "site1" alias
            minio_nodes = [n for n in demo_def.nodes if n.component == "minio"]
            if minio_nodes:
                alias = _re.sub(r"[^a-zA-Z0-9_]", "_", minio_nodes[0].display_name) if minio_nodes[0].display_name else minio_nodes[0].id
            else:
                return None
        else:
            return None
        exit_code, stdout, stderr = await exec_in_container(
            mc_shell_name,
            f"sh -c 'mc admin replicate info {alias} 2>&1 | head -1'",
        )
        # "SiteReplication enabled for:" vs "SiteReplication is not enabled"
        enabled = "enabled for" in stdout.lower() if exit_code == 0 else False
        _repl_cache[demo_id] = (now, enabled)
        return enabled
    except Exception:
        return None


def _build_replication_state_cmd(
    demo, edge_id: str, project_name: str, desired_state: str,
) -> dict | None:
    """Build an mc command to enable/disable bucket replication for an edge.

    Returns {"container": ..., "command": ...} or None if the edge type
    does not support pause/resume.

    Only 'replication' and 'cluster-replication' edges support this.
    Site-replication and tiering cannot be paused.
    """
    edge = next((e for e in demo.edges if e.id == edge_id), None)
    if not edge:
        return None

    config = edge.connection_config or {}

    if edge.connection_type == "replication":
        source_node = next((n for n in demo.nodes if n.id == edge.source), None)
        if not source_node:
            return None
        source_manifest = get_component(source_node.component)
        source_user = _get_credential(source_node, source_manifest, "MINIO_ROOT_USER", "minioadmin")
        source_pass = _get_credential(source_node, source_manifest, "MINIO_ROOT_PASSWORD", "minioadmin")
        source_host = f"{project_name}-{source_node.id}"
        source_bucket = _safe(config.get("source_bucket", "demo-bucket"))
        command = (
            f"mc alias set source http://{source_host}:9000 {_safe(source_user)} {_safe(source_pass)} && "
            f"mc replicate update source/{source_bucket} --state {desired_state}"
        )
        return {"container": f"{project_name}-{source_node.id}", "command": command}

    elif edge.connection_type == "cluster-replication":
        source_cluster_id = config.get("_source_cluster_id", "")
        if not source_cluster_id:
            for c in demo.clusters:
                if edge.source.startswith(f"{c.id}-node-") or edge.source == f"{c.id}-lb":
                    source_cluster_id = c.id
                    break
        source_cluster = _find_cluster(demo, source_cluster_id)
        if not source_cluster:
            return None
        source_user, source_pass = _get_cluster_credentials(source_cluster)
        source_host = _resolve_cluster_endpoint(source_cluster, project_name)
        source_bucket = _safe(config.get("source_bucket", "demo-bucket"))
        command = (
            f"mc alias set source http://{source_host}:80 {_safe(source_user)} {_safe(source_pass)} && "
            f"mc replicate update source/{source_bucket} --state {desired_state}"
        )
        return {"container": _cluster_first_minio_container_name(project_name, source_cluster), "command": command}

    return None

def _expand_demo_for_edges(demo):
    """Lightweight cluster edge expansion — same logic as compose_generator but
    only expands edges and injects synthetic nodes. Does NOT render templates or
    build compose files. Works even without component manifests loaded."""
    from ...models.demo import DemoNode, DemoEdge, NodePosition
    demo = demo.model_copy(deep=True)
    for cluster in demo.clusters:
        generated_ids = [f"{cluster.id}-node-{i}" for i in range(1, cluster.node_count + 1)]
        lb_node_id = f"{cluster.id}-lb"
        # Add synthetic nodes
        for i, node_id in enumerate(generated_ids):
            demo.nodes.append(DemoNode(
                id=node_id, component=cluster.component, variant="cluster",
                position=NodePosition(x=0, y=0),
                config={"MINIO_ROOT_USER": cluster.credentials.get("root_user", "minioadmin"),
                        "MINIO_ROOT_PASSWORD": cluster.credentials.get("root_password", "minioadmin")},
            ))
        demo.nodes.append(DemoNode(id=lb_node_id, component="nginx", variant="",
                                    config={"mode": "round-robin"},
                                    position=NodePosition(x=0, y=0)))
        # Expand edges referencing cluster ID
        original_edges = list(demo.edges)
        new_edges, edges_to_remove = [], []
        for edge in original_edges:
            is_cluster_level = edge.connection_type.startswith("cluster-")
            # Preserve the TRUE original edge ID across multiple cluster expansions
            true_original = edge.connection_config.get("_original_edge_id", edge.id)
            if edge.source == cluster.id:
                edges_to_remove.append(edge.id)
                new_edges.append(DemoEdge(
                    id=f"{edge.id}-cluster" if is_cluster_level else f"{edge.id}-lb",
                    source=lb_node_id, target=edge.target,
                    connection_type=edge.connection_type, network=edge.network,
                    connection_config={**edge.connection_config, "_source_cluster_id": cluster.id, "_original_edge_id": true_original},
                    auto_configure=edge.auto_configure, label=edge.label,
                ))
            elif edge.target == cluster.id:
                edges_to_remove.append(edge.id)
                new_edges.append(DemoEdge(
                    id=f"{edge.id}-cluster" if is_cluster_level else f"{edge.id}-lb",
                    source=edge.source, target=lb_node_id,
                    connection_type=edge.connection_type, network=edge.network,
                    connection_config={**edge.connection_config, "_target_cluster_id": cluster.id, "_original_edge_id": true_original},
                    auto_configure=edge.auto_configure, label=edge.label,
                ))
        demo.edges = [e for e in demo.edges if e.id not in edges_to_remove] + new_edges
        # Add LB → node edges
        for j, gen_id in enumerate(generated_ids):
            demo.edges.append(DemoEdge(
                id=f"{cluster.id}-lb-edge-{j+1}", source=lb_node_id, target=gen_id,
                connection_type="load-balance", network="default",
                connection_config={"algorithm": "least-conn", "backend_port": "9000"},
                auto_configure=True,
            ))
    return demo


def _get_first_cluster_alias(demo) -> str | None:
    """Get the sanitized alias name of the first cluster (used for mc admin commands)."""
    import re as _re
    if demo.clusters:
        return _re.sub(r"[^a-zA-Z0-9_]", "_", demo.clusters[0].label)
    return None

def _external_system_on_demand_meta_dict(demo_id: str, node_id: str) -> dict:
    """Load scenario YAML and list datasets with generation.on_demand.enabled."""
    import yaml as _yaml

    demo = _load_demo(demo_id)
    if not demo:
        raise HTTPException(404, "Demo not found")
    node = next((n for n in demo.nodes if n.id == node_id), None)
    if not node or node.component != "external-system":
        raise HTTPException(400, "Not an external-system node")
    scenario_id = (node.config or {}).get("ES_SCENARIO", "").strip()
    if not scenario_id:
        return {"enabled": False, "scenario_id": "", "datasets": []}
    components_dir = _resolve_components_dir()
    yaml_path = os.path.join(components_dir, "external-system", "scenarios", f"{scenario_id}.yaml")
    if not os.path.isfile(yaml_path):
        return {"enabled": False, "scenario_id": scenario_id, "datasets": []}
    with open(yaml_path, "r", encoding="utf-8") as fh:
        raw = _yaml.safe_load(fh)
    scen = raw.get("scenario", {}) if isinstance(raw, dict) else {}
    sid = scen.get("id", scenario_id)
    datasets_out: list[dict] = []
    for ds in raw.get("datasets", []) if isinstance(raw, dict) else []:
        if not isinstance(ds, dict):
            continue
        gen = ds.get("generation") or {}
        od = gen.get("on_demand")
        if isinstance(od, dict) and od.get("enabled"):
            datasets_out.append({
                "id": ds.get("id", ""),
                "target": ds.get("target", ""),
                "default_count": int(od.get("default_count", 1)),
            })
    return {
        "enabled": len(datasets_out) > 0,
        "scenario_id": sid,
        "datasets": datasets_out,
    }

# Chart type mapping for Metabase (matches metabase_setup.py)
_METABASE_CHART_MAP = {
    "bar": ("bar", {}),
    "line": ("line", {}),
    "pie": ("pie", {}),
    "donut": ("pie", {"pie.show_legend": True, "pie.percent_visibility": "inside"}),
    "horizontal_bar": ("bar", {"graph.x_axis.axis_enabled": True, "bar.horizontal": True}),
    "scalar": ("scalar", {}),
    "stacked_area": ("area", {"stackable.stack_type": "stacked"}),
    "pivot_table": ("pivot", {}),
    "table": ("table", {}),
}


def _build_superset_position_json(chart_layout: list) -> dict:
    """Build Superset dashboard position JSON from a simplified layout spec."""
    import json as _json
    position = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
        "GRID_ID": {
            "type": "GRID",
            "id": "GRID_ID",
            "children": [],
            "parents": ["ROOT_ID"],
        },
        "HEADER_ID": {
            "type": "HEADER",
            "id": "HEADER_ID",
            "meta": {"text": ""},
        },
    }
    rows: dict = {}
    for item in chart_layout:
        r = item["row"]
        rows.setdefault(r, []).append(item)
    for row_idx in sorted(rows.keys()):
        row_id = f"ROW-row{row_idx}"
        position["GRID_ID"]["children"].append(row_id)
        position[row_id] = {
            "type": "ROW",
            "id": row_id,
            "children": [],
            "parents": ["ROOT_ID", "GRID_ID"],
            "meta": {"background": "BACKGROUND_TRANSPARENT"},
        }
        for item in sorted(rows[row_idx], key=lambda x: x["col"]):
            chart_key = f"CHART-{item['chart_id']}"
            position[row_id]["children"].append(chart_key)
            position[chart_key] = {
                "type": "CHART",
                "id": chart_key,
                "children": [],
                "parents": ["ROOT_ID", "GRID_ID", row_id],
                "meta": {
                    "width": item["width"],
                    "height": item["height"],
                    "chartId": item["chart_id"],
                    "sliceName": item.get("name", ""),
                },
            }
    return position


def _build_superset_dashboard_specs() -> dict:
    """Return dashboard specs for all 5 DemoForge scenarios."""
    return {
        "ecommerce-orders": {
            "title": "Live Orders Analytics",
            "slug": "live-orders",
            "schema": "demo",
            "table": "orders",
            "charts": [
                {"name": "Orders: Total Count", "viz_type": "big_number_total", "params": {"metric": {"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "Total Orders"}, "header_font_size": 0.4, "y_axis_format": "SMART_NUMBER"}},
                {"name": "Orders: Total Revenue", "viz_type": "big_number_total", "params": {"metric": {"expressionType": "SQL", "sqlExpression": "SUM(total_amount)", "label": "Revenue"}, "header_font_size": 0.4, "y_axis_format": "$,.2f"}},
                {"name": "Orders: Avg Order Value", "viz_type": "big_number_total", "params": {"metric": {"expressionType": "SQL", "sqlExpression": "AVG(total_amount)", "label": "Avg Order"}, "header_font_size": 0.4, "y_axis_format": "$,.2f"}},
                {"name": "Orders: Orders/min", "viz_type": "echarts_timeseries_line", "params": {"x_axis": "order_ts", "time_grain_sqla": "PT1M", "metrics": [{"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "orders/min"}], "row_limit": 1000, "show_legend": False, "x_axis_time_format": "%H:%M"}},
                {"name": "Orders: Revenue by Region", "viz_type": "dist_bar", "params": {"groupby": ["region"], "metrics": [{"expressionType": "SQL", "sqlExpression": "SUM(total_amount)", "label": "Revenue"}], "row_limit": 50, "y_axis_format": "$,.0f", "color_scheme": "supersetColors", "show_bar_value": True}},
                {"name": "Orders: Top Products", "viz_type": "dist_bar", "params": {"groupby": ["product_name"], "metrics": [{"expressionType": "SQL", "sqlExpression": "SUM(total_amount)", "label": "Revenue"}], "row_limit": 10, "order_bars": True, "y_axis_format": "$,.0f", "show_bar_value": True}},
                {"name": "Orders: Categories", "viz_type": "pie", "params": {"groupby": ["category"], "metric": {"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "Orders"}, "donut": True, "show_labels": True, "label_type": "key_percent", "color_scheme": "supersetColors"}},
                {"name": "Orders: Payment Methods", "viz_type": "pie", "params": {"groupby": ["payment_method"], "metric": {"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "Orders"}, "donut": True, "show_labels": True, "label_type": "key_percent", "color_scheme": "supersetColors"}},
            ],
            "layout": [
                {"row": 0, "col": 0, "width": 4, "height": 8, "name": "Total Orders"},
                {"row": 0, "col": 4, "width": 4, "height": 8, "name": "Total Revenue"},
                {"row": 0, "col": 8, "width": 4, "height": 8, "name": "Avg Order Value"},
                {"row": 1, "col": 0, "width": 12, "height": 12, "name": "Orders/min"},
                {"row": 2, "col": 0, "width": 6, "height": 12, "name": "Revenue by Region"},
                {"row": 2, "col": 6, "width": 6, "height": 12, "name": "Top Products"},
                {"row": 3, "col": 0, "width": 6, "height": 12, "name": "Categories"},
                {"row": 3, "col": 6, "width": 6, "height": 12, "name": "Payment Methods"},
            ],
        },
        "iot-telemetry": {
            "title": "IoT Sensor Monitoring",
            "slug": "iot-sensors",
            "schema": "demo",
            "table": "sensor_readings",
            "charts": [
                {"name": "IoT: Total Readings", "viz_type": "big_number_total", "params": {"metric": {"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "Readings"}, "header_font_size": 0.4, "y_axis_format": "SMART_NUMBER"}},
                {"name": "IoT: Active Sensors", "viz_type": "big_number_total", "params": {"metric": {"expressionType": "SQL", "sqlExpression": "COUNT(DISTINCT device_id)", "label": "Sensors"}, "header_font_size": 0.4, "y_axis_format": "SMART_NUMBER"}},
                {"name": "IoT: Critical Alerts", "viz_type": "big_number_total", "params": {"metric": {"expressionType": "SQL", "sqlExpression": "COUNT(*) FILTER (WHERE alert_level = 'critical')", "label": "Critical"}, "header_font_size": 0.4, "y_axis_format": "SMART_NUMBER"}},
                {"name": "IoT: Readings/min", "viz_type": "echarts_timeseries_line", "params": {"x_axis": "reading_ts", "time_grain_sqla": "PT1M", "metrics": [{"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "readings/min"}], "row_limit": 1000, "show_legend": False, "x_axis_time_format": "%H:%M"}},
                {"name": "IoT: Alert Levels", "viz_type": "pie", "params": {"groupby": ["alert_level"], "metric": {"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "Count"}, "donut": True, "show_labels": True, "label_type": "key_percent", "color_scheme": "supersetColors"}},
                {"name": "IoT: Temp by Facility", "viz_type": "dist_bar", "params": {"groupby": ["facility"], "metrics": [{"expressionType": "SQL", "sqlExpression": "ROUND(AVG(temperature_c), 1)", "label": "Avg Temp (°C)"}], "y_axis_format": ",.1f", "show_bar_value": True}},
                {"name": "IoT: Battery Levels", "viz_type": "dist_bar", "params": {"groupby": ["battery_pct"], "metrics": [{"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "Sensors"}], "row_limit": 100}},
            ],
            "layout": [
                {"row": 0, "col": 0, "width": 4, "height": 8, "name": "Total Readings"},
                {"row": 0, "col": 4, "width": 4, "height": 8, "name": "Active Sensors"},
                {"row": 0, "col": 8, "width": 4, "height": 8, "name": "Critical Alerts"},
                {"row": 1, "col": 0, "width": 12, "height": 12, "name": "Readings/min"},
                {"row": 2, "col": 0, "width": 4, "height": 12, "name": "Alert Levels"},
                {"row": 2, "col": 4, "width": 4, "height": 12, "name": "Temp by Facility"},
                {"row": 2, "col": 8, "width": 4, "height": 12, "name": "Battery Levels"},
            ],
        },
        "financial-txn": {
            "title": "Financial Transactions Monitor",
            "slug": "financial-txns",
            "schema": "demo",
            "table": "transactions",
            "charts": [
                {"name": "Fin: Total Transactions", "viz_type": "big_number_total", "params": {"metric": {"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "Transactions"}, "header_font_size": 0.4, "y_axis_format": "SMART_NUMBER"}},
                {"name": "Fin: Total Volume", "viz_type": "big_number_total", "params": {"metric": {"expressionType": "SQL", "sqlExpression": "SUM(amount)", "label": "Volume"}, "header_font_size": 0.4, "y_axis_format": "$,.0f"}},
                {"name": "Fin: Flagged %", "viz_type": "big_number_total", "params": {"metric": {"expressionType": "SQL", "sqlExpression": "ROUND(100.0 * COUNT(*) FILTER (WHERE flagged = true) / NULLIF(COUNT(*), 0), 2)", "label": "Flagged %"}, "header_font_size": 0.4, "y_axis_format": ",.2f"}},
                {"name": "Fin: Txns/min", "viz_type": "echarts_timeseries_line", "params": {"x_axis": "txn_ts", "time_grain_sqla": "PT1M", "metrics": [{"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "txns/min"}], "row_limit": 1000, "show_legend": False, "x_axis_time_format": "%H:%M"}},
                {"name": "Fin: Volume by Currency", "viz_type": "dist_bar", "params": {"groupby": ["currency"], "metrics": [{"expressionType": "SQL", "sqlExpression": "SUM(amount)", "label": "Volume"}], "order_bars": True, "y_axis_format": "$,.0f", "show_bar_value": True}},
                {"name": "Fin: Channels", "viz_type": "pie", "params": {"groupby": ["channel"], "metric": {"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "Txns"}, "donut": True, "show_labels": True, "label_type": "key_percent"}},
                {"name": "Fin: High-Risk Accounts", "viz_type": "table", "params": {"query_mode": "raw", "all_columns": ["account_from", "country", "risk_score", "compliance_status", "amount", "txn_type"], "adhoc_filters": [{"expressionType": "SQL", "sqlExpression": "risk_score > 0.65", "clause": "WHERE"}], "row_limit": 50, "page_length": 15}},
            ],
            "layout": [
                {"row": 0, "col": 0, "width": 4, "height": 8, "name": "Total Txns"},
                {"row": 0, "col": 4, "width": 4, "height": 8, "name": "Total Volume"},
                {"row": 0, "col": 8, "width": 4, "height": 8, "name": "Flagged %"},
                {"row": 1, "col": 0, "width": 12, "height": 12, "name": "Txns/min"},
                {"row": 2, "col": 0, "width": 6, "height": 12, "name": "Volume by Currency"},
                {"row": 2, "col": 6, "width": 6, "height": 12, "name": "Channels"},
                {"row": 3, "col": 0, "width": 12, "height": 14, "name": "High-Risk Accounts"},
            ],
        },
        "clickstream": {
            "title": "Real-time Clickstream",
            "slug": "clickstream",
            "schema": "demo",
            "table": "clickstream",
            "charts": [
                {"name": "Click: Total Events", "viz_type": "big_number_total", "params": {"metric": {"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "Events"}, "header_font_size": 0.4, "y_axis_format": "SMART_NUMBER"}},
                {"name": "Click: Unique Sessions", "viz_type": "big_number_total", "params": {"metric": {"expressionType": "SQL", "sqlExpression": "COUNT(DISTINCT session_id)", "label": "Sessions"}, "header_font_size": 0.4, "y_axis_format": "SMART_NUMBER"}},
                {"name": "Click: Events/min", "viz_type": "echarts_timeseries_line", "params": {"x_axis": "event_ts", "time_grain_sqla": "PT1M", "metrics": [{"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "events/min"}], "row_limit": 1000, "show_legend": False, "x_axis_time_format": "%H:%M"}},
                {"name": "Click: Device Types", "viz_type": "pie", "params": {"groupby": ["device_type"], "metric": {"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "Events"}, "donut": True, "show_labels": True, "label_type": "key_percent"}},
                {"name": "Click: Top Pages", "viz_type": "dist_bar", "params": {"groupby": ["page_url"], "metrics": [{"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "Hits"}], "row_limit": 10, "order_bars": True, "show_bar_value": True}},
            ],
            "layout": [
                {"row": 0, "col": 0, "width": 6, "height": 8, "name": "Total Events"},
                {"row": 0, "col": 6, "width": 6, "height": 8, "name": "Unique Sessions"},
                {"row": 1, "col": 0, "width": 12, "height": 12, "name": "Events/min"},
                {"row": 2, "col": 0, "width": 4, "height": 12, "name": "Device Types"},
                {"row": 2, "col": 4, "width": 8, "height": 12, "name": "Top Pages"},
            ],
        },
        "customer-360": {
            "title": "Customer 360 Overview",
            "slug": "customer-360",
            "schema": "default",
            "table": "customer_360",
            "charts": [
                {"name": "C360: Total Customers", "viz_type": "big_number_total", "params": {"metric": {"expressionType": "SQL", "sqlExpression": "COUNT(DISTINCT customer_id)", "label": "Customers"}, "header_font_size": 0.4, "y_axis_format": "SMART_NUMBER"}},
                {"name": "C360: Total Volume", "viz_type": "big_number_total", "params": {"metric": {"expressionType": "SQL", "sqlExpression": "SUM(amount)", "label": "Volume"}, "header_font_size": 0.4, "y_axis_format": "$,.0f"}},
                {"name": "C360: Avg Transaction", "viz_type": "big_number_total", "params": {"metric": {"expressionType": "SQL", "sqlExpression": "ROUND(AVG(amount), 2)", "label": "Avg Txn"}, "header_font_size": 0.4, "y_axis_format": "$,.2f"}},
                {"name": "C360: Spend by Segment", "viz_type": "dist_bar", "params": {"groupby": ["segment"], "metrics": [{"expressionType": "SQL", "sqlExpression": "SUM(amount)", "label": "Total Spend"}], "y_axis_format": "$,.0f", "show_bar_value": True}},
                {"name": "C360: Countries", "viz_type": "pie", "params": {"groupby": ["country"], "metric": {"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "Transactions"}, "donut": True, "show_labels": True, "label_type": "key_percent"}},
                {"name": "C360: Top Merchants", "viz_type": "dist_bar", "params": {"groupby": ["merchant"], "metrics": [{"expressionType": "SQL", "sqlExpression": "SUM(amount)", "label": "Revenue"}], "row_limit": 10, "order_bars": True, "y_axis_format": "$,.0f", "show_bar_value": True}},
            ],
            "layout": [
                {"row": 0, "col": 0, "width": 4, "height": 8, "name": "Total Customers"},
                {"row": 0, "col": 4, "width": 4, "height": 8, "name": "Total Volume"},
                {"row": 0, "col": 8, "width": 4, "height": 8, "name": "Avg Transaction"},
                {"row": 1, "col": 0, "width": 6, "height": 12, "name": "Spend by Segment"},
                {"row": 1, "col": 6, "width": 6, "height": 12, "name": "Countries"},
                {"row": 2, "col": 0, "width": 12, "height": 12, "name": "Top Merchants"},
            ],
        },
    }
