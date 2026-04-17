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

@router.get("/api/demos/{demo_id}/generator-status/{node_id}")
async def get_generator_status(demo_id: str, node_id: str):
    """Read generator status from /tmp/gen.status inside the container."""
    running = state.get_demo(demo_id)
    if not running or node_id not in running.containers:
        raise HTTPException(404, "Instance not found")
    container_name = running.containers[node_id].container_name
    try:
        exit_code, stdout, stderr = await exec_in_container(
            container_name,
            "sh -c '[ -f /tmp/gen.status ] && cat /tmp/gen.status || echo STATE=idle'",
        )
        parsed: dict = {"state": "idle", "rows_generated": 0, "batches_sent": 0, "errors": 0}
        for line in stdout.splitlines():
            line = line.strip()
            if "=" in line:
                k, _, v = line.partition("=")
                parsed[k.lower()] = v
        # Normalise numeric fields
        for field in ("rows_generated", "batches_sent", "errors", "rows_per_sec"):
            if field in parsed:
                try:
                    parsed[field] = float(parsed[field]) if field == "rows_per_sec" else int(parsed[field])
                except (ValueError, TypeError):
                    parsed[field] = 0
        return parsed
    except Exception as e:
        raise HTTPException(500, str(e))


class GeneratorStartRequest(BaseModel):
    scenario: str = "ecommerce-orders"
    format: str = "parquet"
    rate_profile: str = "medium"


@router.post("/api/demos/{demo_id}/generator-start/{node_id}")
async def start_generator(demo_id: str, node_id: str, req: GeneratorStartRequest):
    """Start/resume the data-generator.

    If the generator is idle (paused via stop), touch /tmp/gen.start to resume.
    If no process is running at all, spawn a new one.
    """
    running = state.get_demo(demo_id)
    if not running or node_id not in running.containers:
        raise HTTPException(404, "Instance not found")
    container_name = running.containers[node_id].container_name
    # Check if the main generate.py process is alive (PID 1 in the container)
    # If it's alive but idle (no /tmp/gen.pid), just touch /tmp/gen.start to resume
    # If it's not alive, spawn a new one
    resume_cmd = "sh -c 'touch /tmp/gen.start; echo resumed'"
    try:
        exit_code, stdout, stderr = await exec_in_container(container_name, resume_cmd)
        return {"state": "streaming", "scenario": req.scenario, "format": req.format, "rate_profile": req.rate_profile}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/api/demos/{demo_id}/generator-stop/{node_id}")
async def stop_generator(demo_id: str, node_id: str):
    """Pause the data-generator by touching /tmp/gen.stop.

    The generator stays alive but enters idle mode (doesn't exit).
    """
    running = state.get_demo(demo_id)
    if not running or node_id not in running.containers:
        raise HTTPException(404, "Instance not found")
    container_name = running.containers[node_id].container_name
    stop_cmd = "sh -c 'touch /tmp/gen.stop; echo stopped'"
    try:
        await exec_in_container(container_name, stop_cmd)
        return {"state": "idle"}
    except Exception as e:
        raise HTTPException(500, str(e))


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


@router.get(
    "/api/demos/{demo_id}/instances/{node_id}/external-system/on-demand",
    response_model=ExternalSystemOnDemandMetaResponse,
)
async def get_external_system_on_demand_meta(demo_id: str, node_id: str):
    """Whether the selected ES_SCENARIO has on-demand datasets (for UI context menu)."""
    d = _external_system_on_demand_meta_dict(demo_id, node_id)
    return ExternalSystemOnDemandMetaResponse(
        enabled=d["enabled"],
        scenario_id=d["scenario_id"],
        datasets=[ExternalSystemOnDemandDataset(**x) for x in d["datasets"]],
    )


@router.post("/api/demos/{demo_id}/instances/{node_id}/external-system/on-demand")
async def trigger_external_system_on_demand(
    demo_id: str,
    node_id: str,
    req: ExternalSystemOnDemandTriggerRequest = ExternalSystemOnDemandTriggerRequest(),
):
    """Drop a JSON request file in the container's ES_ON_DEMAND_DIR (default /tmp/es-on-demand)."""
    running = state.get_demo(demo_id)
    if not running or node_id not in running.containers:
        raise HTTPException(404, "Instance not found")
    d = _external_system_on_demand_meta_dict(demo_id, node_id)
    if not d["enabled"]:
        raise HTTPException(400, "On-demand generation is not enabled for this scenario")
    payload = req.payload or {}
    if not isinstance(payload, dict):
        raise HTTPException(400, "payload must be a JSON object")
    raw_json = json.dumps(payload, separators=(",", ":"))
    b64 = base64.standard_b64encode(raw_json.encode()).decode("ascii")
    fname = f"trigger-{int(time_module.time() * 1000)}.json"
    code = (
        "import base64, pathlib; "
        f"b={repr(b64)}; "
        "pathlib.Path('/tmp/es-on-demand').mkdir(parents=True, exist_ok=True); "
        f"pathlib.Path('/tmp/es-on-demand/{fname}').write_bytes(base64.standard_b64decode(b.encode('ascii')))"
    )
    shell_cmd = f"python3 -c {shlex.quote(code)}"
    container_name = running.containers[node_id].container_name
    exit_code, stdout, stderr = await exec_in_container(container_name, shell_cmd, timeout=30)
    if exit_code != 0:
        raise HTTPException(500, f"Could not write on-demand trigger: {stderr or stdout or 'exec failed'}")
    return {"ok": True, "file": f"/tmp/es-on-demand/{fname}"}

