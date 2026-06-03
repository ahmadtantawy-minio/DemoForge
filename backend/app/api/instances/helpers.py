"""Shared helpers for the instances API (audit, replication, edge expansion, Superset specs)."""

from __future__ import annotations

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
from ...engine.integration_audit_log import (
    append_integration_audit_line,
    read_integration_audit_tail,
    integration_audit_path,
)

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
    """Path to per-demo integration audit JSONL (LogViewer Integrations tab)."""
    return integration_audit_path(demo_id)


def append_demo_integration_audit(
    demo_id: str,
    level: str,
    kind: str,
    message: str,
    details: str = "",
    *,
    node_id: str | None = None,
    command: str | None = None,
    exit_code: int | None = None,
) -> None:
    """Append one audit line (Metabase, edge/mc actions, etc.)."""
    append_integration_audit_line(
        demo_id,
        level,
        kind,
        message,
        details,
        node_id=node_id,
        command=command,
        exit_code=exit_code,
    )


def _load_demo_integration_audit(demo_id: str, limit: int = 400) -> list[dict]:
    return read_integration_audit_tail(demo_id, limit=limit)


def _metabase_dashboard_rows(body: object) -> list:
    """Normalize GET /api/dashboard response (array or {data: [...]})."""
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        return body.get("data") or []
    return []


# Cache per-edge site replication status (avoid hammering mc on every poll)
_repl_edge_cache: dict[str, tuple[float, str, str]] = {}


def _find_demo_edge_for_ec(demo, ec_edge_id: str):
    """Resolve diagram or expanded edge id to a DemoEdge."""
    for e in demo.edges:
        if e.id == ec_edge_id or ec_edge_id.startswith(f"{e.id}-"):
            return e
    try:
        expanded = _expand_demo_for_edges(demo)
    except Exception:
        expanded = demo
    for e in expanded.edges:
        if e.id == ec_edge_id:
            return e
        orig = (e.connection_config or {}).get("_original_edge_id")
        if orig and (ec_edge_id == orig or ec_edge_id.startswith(f"{orig}-")):
            return e
        if ec_edge_id.startswith(f"{e.id}-"):
            return e
    return None


def _cluster_lb_node_id(cluster_id: str) -> str:
    return f"{cluster_id}-lb"


def _cluster_is_deployed(running, cluster_id: str) -> bool:
    lb = _cluster_lb_node_id(cluster_id)
    if lb in running.containers:
        return True
    prefix = f"{cluster_id}-pool"
    return any(nid.startswith(prefix) for nid in running.containers)


def _cluster_ids_for_site_edge(edge, demo) -> tuple[str, str]:
    """Return (source_cluster_id, target_cluster_id) for cluster-site-replication."""
    cfg = edge.connection_config or {}
    source_id = cfg.get("_source_cluster_id", "")
    target_id = cfg.get("_target_cluster_id", "")
    if not source_id:
        for c in demo.clusters:
            if edge.source.startswith(f"{c.id}-") or edge.source == c.id:
                source_id = c.id
                break
    if not target_id:
        for c in demo.clusters:
            if edge.target.startswith(f"{c.id}-") or edge.target == c.id:
                target_id = c.id
                break
    return source_id, target_id


async def _lb_health_ok(http_client: httpx.AsyncClient, project_name: str, cluster_id: str) -> bool:
    host = f"{project_name}-{cluster_id}-lb"
    try:
        resp = await http_client.get(
            f"http://{host}:80/minio/health/live",
            timeout=httpx.Timeout(2.0),
        )
        return resp.status_code == 200
    except Exception:
        return False


async def _resolve_site_replication_edge_status(
    running,
    demo_id: str,
    demo,
    ec: EdgeConfigResult,
    http_client: httpx.AsyncClient | None,
) -> tuple[str, str]:
    """Per-edge site replication status for the canvas (not demo-global)."""
    import time

    now = time.time()
    cached = _repl_edge_cache.get(ec.edge_id)
    if cached and now - cached[0] < 10:
        return cached[1], cached[2]

    base_status = ec.status
    base_error = ec.error or ""

    edge = _find_demo_edge_for_ec(demo, ec.edge_id)
    if not edge:
        out = (
            ("failed", "Replication edge removed from diagram — pause or redeploy to clear")
            if base_status == "applied"
            else (base_status, base_error)
        )
        _repl_edge_cache[ec.edge_id] = (now, out[0], out[1])
        return out

    project_name = f"demoforge-{demo_id}"
    from ...engine.site_replication_post import resolve_site_replication_post_kwargs

    post = resolve_site_replication_post_kwargs(edge, demo, project_name)
    if not post:
        out = (base_status, base_error)
        _repl_edge_cache[ec.edge_id] = (now, out[0], out[1])
        return out

    src_c, tgt_c = _cluster_ids_for_site_edge(edge, demo)
    if edge.connection_type == "cluster-site-replication":
        missing = [cid for cid in (src_c, tgt_c) if cid and not _cluster_is_deployed(running, cid)]
        if missing:
            out = (
                "failed",
                f"Peer cluster not running ({', '.join(missing)}) — remove site replication or start peer",
            )
            _repl_edge_cache[ec.edge_id] = (now, out[0], out[1])
            return out
        if http_client:
            for cid in (src_c, tgt_c):
                if cid and not await _lb_health_ok(http_client, project_name, cid):
                    out = (
                        "failed",
                        f"Peer cluster unreachable ({cid}) — replication link is down",
                    )
                    _repl_edge_cache[ec.edge_id] = (now, out[0], out[1])
                    return out

    mc_shell = f"{project_name}-mc-shell"
    if mc_shell not in [c.container_name for c in running.containers.values()]:
        out = (base_status, base_error)
        _repl_edge_cache[ec.edge_id] = (now, out[0], out[1])
        return out

    alias_a = post["alias_a"]
    host_a = post["host_a"].split(":")[0].lower()
    host_b = post["host_b"].split(":")[0].lower()
    try:
        exit_code, stdout, _stderr = await exec_in_container(
            mc_shell,
            f"sh -c {shlex.quote(f'mc admin replicate info {alias_a} 2>&1')}",
        )
    except Exception as exc:
        out = (base_status, base_error or str(exc)[:200])
        _repl_edge_cache[ec.edge_id] = (now, out[0], out[1])
        return out

    if exit_code != 0 or "enabled for" not in stdout.lower():
        out = (
            ("failed", "Site replication not active on cluster")
            if base_status == "applied"
            else (base_status, base_error or "Site replication not active")
        )
        _repl_edge_cache[ec.edge_id] = (now, out[0], out[1])
        return out

    # Stale link: SR still lists a peer host that is not a deployed cluster LB in this demo.
    if edge.connection_type == "cluster-site-replication" and http_client:
        live_hosts = {
            f"{project_name}-{c.id}-lb".lower()
            for c in demo.clusters
            if _cluster_is_deployed(running, c.id)
        }
        expected = {host_a, host_b}
        if not expected.issubset(live_hosts):
            out = (
                "failed",
                "Site replication references a peer that is not running in this demo",
            )
            _repl_edge_cache[ec.edge_id] = (now, out[0], out[1])
            return out
        for line in stdout.splitlines():
            if "http://" not in line.lower():
                continue
            for token in line.split():
                if not token.lower().startswith("http://"):
                    continue
                peer_host = token.lower().replace("http://", "").split("/")[0].split(":")[0]
                if peer_host and peer_host not in live_hosts:
                    out = (
                        "failed",
                        f"Stale replication peer ({peer_host}) — not deployed; use Remove Site Replication",
                    )
                    _repl_edge_cache[ec.edge_id] = (now, out[0], out[1])
                    return out

    out = ("applied", "")
    _repl_edge_cache[ec.edge_id] = (now, out[0], out[1])
    return out


async def _check_live_replication_status(running, demo_id: str) -> bool | None:
    """Legacy demo-wide check. True only if every site-replication edge reports applied."""
    demo = _load_demo(demo_id)
    if not demo or not running:
        return None
    saw = False
    for ec in running.edge_configs.values():
        if ec.connection_type not in ("site-replication", "cluster-site-replication"):
            continue
        saw = True
        status, _ = await _resolve_site_replication_edge_status(
            running, demo_id, demo, ec, None
        )
        if status != "applied":
            return False
    return True if saw else None


def clear_replication_edge_cache(demo_id: str | None = None, edge_id: str | None = None) -> None:
    """Invalidate cached per-edge replication status after pause/activate."""
    if edge_id:
        _repl_edge_cache.pop(edge_id, None)
        return
    if demo_id:
        prefix = demo_id
        for key in list(_repl_edge_cache):
            if prefix in key:
                _repl_edge_cache.pop(key, None)
        return
    _repl_edge_cache.clear()


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
        pools = cluster.get_pools()
        pool = pools[0] if pools else None
        if pool:
            generated_ids = [
                f"{cluster.id}-pool1-node-{i}" for i in range(1, pool.node_count + 1)
            ]
        else:
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
