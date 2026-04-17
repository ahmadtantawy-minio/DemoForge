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

@router.post("/api/demos/{demo_id}/instances/{node_id}/exec", response_model=ExecResponse)
async def exec_command(demo_id: str, node_id: str, req: ExecRequest):
    running = state.get_demo(demo_id)
    if not running or node_id not in running.containers:
        raise HTTPException(404, "Instance not found")
    exit_code, stdout, stderr = await exec_in_container(
        running.containers[node_id].container_name, req.command
    )
    return ExecResponse(exit_code=exit_code, stdout=stdout, stderr=stderr)


@router.get("/api/demos/{demo_id}/instances/{node_id}/logs", response_model=LogResponse)
async def get_container_logs(demo_id: str, node_id: str, tail: int = 200, since: str = ""):
    """Fetch recent stdout/stderr from a container."""
    running = state.get_demo(demo_id)
    if not running or node_id not in running.containers:
        raise HTTPException(404, "Instance not found")
    container_name = running.containers[node_id].container_name
    try:
        def _fetch():
            c = docker_client.containers.get(container_name)
            kwargs: dict = {"tail": tail, "timestamps": True, "stream": False}
            if since:
                # Accept "60s", "5m", or raw int seconds
                if since.endswith("s"):
                    kwargs["since"] = int(since[:-1])
                elif since.endswith("m"):
                    kwargs["since"] = int(since[:-1]) * 60
                else:
                    kwargs["since"] = int(since)
            raw = c.logs(**kwargs)
            return raw

        raw = await asyncio.to_thread(_fetch)
        text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        lines = [l for l in text.split("\n") if l] if text.strip() else []
        return LogResponse(lines=lines, container=node_id, truncated=len(lines) >= tail)
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/api/demos/{demo_id}/instances/{node_id}/exec-log", response_model=LogResponse)
async def exec_container_log(demo_id: str, node_id: str, req: ExecLogRequest):
    """Run a read-only command inside a container and return its output as log lines."""
    running = state.get_demo(demo_id)
    if not running or node_id not in running.containers:
        raise HTTPException(404, "Instance not found")
    container_name = running.containers[node_id].container_name
    try:
        exit_code, stdout, stderr = await exec_in_container(container_name, f"sh -c {shlex.quote(req.command)}")
        combined = (stdout or "") + (stderr or "")
        lines = [l for l in combined.split("\n") if l]
        return LogResponse(lines=lines, container=node_id, truncated=False)
    except Exception as e:
        raise HTTPException(500, str(e))


