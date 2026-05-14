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


def _audit_edge_exec(
    demo_id: str,
    kind: str,
    message: str,
    command: str,
    exit_code: int,
    stdout: str,
    stderr: str,
    *,
    node_id: str = "mc-shell",
) -> None:
    tail = "\n".join(x for x in [stdout or "", stderr or ""] if x).strip()
    details = tail[:12000] if tail else ""
    level = "error" if exit_code != 0 else "info"
    append_demo_integration_audit(
        demo_id,
        level,
        kind,
        message,
        details,
        node_id=node_id,
        command=command,
        exit_code=exit_code,
    )


@router.post("/api/demos/{demo_id}/edges/{edge_id}/activate")
async def activate_edge_config(demo_id: str, edge_id: str):
    """Activate a paused edge config (run the mc commands)."""
    running = state.get_demo(demo_id)
    if not running:
        raise HTTPException(404, "Demo not running")

    demo = _load_demo(demo_id)
    if not demo:
        raise HTTPException(404, "Demo definition not found")

    project_name = f"demoforge-{demo_id}"
    expanded_demo = _expand_demo_for_edges(demo)
    scripts = generate_edge_scripts(expanded_demo, project_name)

    # Build reverse mapping: original_edge_id → expanded_edge_id
    edge_id_map: dict[str, str] = {}
    for edge in expanded_demo.edges:
        orig = (edge.connection_config or {}).get("_original_edge_id")
        if orig:
            edge_id_map[orig] = edge.id

    # Find matching script — try exact match, then mapped ID from original
    script = next((s for s in scripts if s.edge_id == edge_id), None)
    if not script:
        mapped_id = edge_id_map.get(edge_id)
        if mapped_id:
            script = next((s for s in scripts if s.edge_id == mapped_id), None)
            if script:
                edge_id = mapped_id
    if not script:
        raise HTTPException(404, f"No automation script for edge '{edge_id}'")

    # Ensure edge config entry exists
    ec = running.edge_configs.get(edge_id)
    if not ec:
        ec = EdgeConfigResult(
            edge_id=edge_id,
            connection_type=script.connection_type,
            status="paused",
            description=script.description,
        )
        running.edge_configs[edge_id] = ec

    if ec.status == "applied":
        return {"status": "already_applied", "edge_id": edge_id}
    if not script:
        raise HTTPException(404, f"No automation script for edge '{edge_id}'")

    ec.status = "pending"
    ec.error = ""
    state.set_demo(running)

    try:
        exit_code, stdout, stderr = await exec_in_container(
            script.container_name, f"sh -c {shlex.quote(script.command)}"
        )
        short_node = script.container_name
        if short_node.startswith(f"demoforge-{demo_id}-"):
            short_node = short_node[len(f"demoforge-{demo_id}-") :]
        _audit_edge_exec(
            demo_id,
            "edge_activate",
            f"{script.connection_type} edge {edge_id}: {script.description}",
            script.command,
            exit_code,
            stdout,
            stderr,
            node_id=short_node[:64] or "mc-shell",
        )
        if exit_code != 0:
            ec.status = "failed"
            ec.error = stderr[:500]
            state.set_demo(running)
            return {"status": "failed", "edge_id": edge_id, "error": stderr[:500]}
        else:
            ec.status = "applied"
            ec.previously_applied = True
            ec.error = ""
            state.set_demo(running)
            edge_obj = next((e for e in expanded_demo.edges if e.id == edge_id), None)
            if edge_obj and script.connection_type in ("site-replication", "cluster-site-replication"):
                from ...engine.site_replication_post import apply_site_replication_sync, resolve_site_replication_post_kwargs

                post = resolve_site_replication_post_kwargs(edge_obj, expanded_demo, project_name)
                if post:
                    try:
                        await apply_site_replication_sync(
                            exec_in_container,
                            script.container_name,
                            **post,
                        )
                    except Exception as sync_err:
                        logger.warning(
                            "Site replication sync follow-up failed for edge %s: %s",
                            edge_id,
                            sync_err,
                        )
            return {"status": "applied", "edge_id": edge_id}
    except Exception as e:
        short_node = script.container_name
        if short_node.startswith(f"demoforge-{demo_id}-"):
            short_node = short_node[len(f"demoforge-{demo_id}-") :]
        _audit_edge_exec(
            demo_id,
            "edge_activate",
            f"{script.connection_type} edge {edge_id}: exec exception — {script.description}",
            script.command,
            -1,
            "",
            str(e),
            node_id=short_node[:64] or "mc-shell",
        )
        ec.status = "failed"
        ec.error = str(e)[:500]
        state.set_demo(running)
        return {"status": "failed", "edge_id": edge_id, "error": str(e)[:500]}

@router.post("/api/demos/{demo_id}/edges/{edge_id}/pause")
async def pause_edge_config(demo_id: str, edge_id: str):
    """Pause an edge config.

    For bucket replication (replication, cluster-replication): executes
    ``mc replicate update ALIAS/BUCKET --state disable`` to actually stop
    replication on the server side.

    Site-replication cannot be paused — it is all-or-nothing.
    Tiering (ILM rules) cannot be paused without removing the rule entirely.
    """
    running = state.get_demo(demo_id)
    if not running:
        raise HTTPException(404, "Demo not running")

    # Look up edge config: try exact match, then search by original edge ID prefix
    ec = running.edge_configs.get(edge_id)
    if not ec:
        # The config may be stored under an expanded ID (with -cluster suffixes)
        # Search for any config whose ID starts with the frontend edge ID
        for key, val in running.edge_configs.items():
            if key.startswith(edge_id):
                ec = val
                edge_id = key
                break
    if not ec:
        raise HTTPException(404, f"Edge config '{edge_id}' not found")

    # For site-replication: remove via mc admin replicate remove
    if ec.connection_type in ("site-replication", "cluster-site-replication") and ec.status == "applied":
        _demo = _load_demo(demo_id)
        if _demo:
            expanded = _expand_demo_for_edges(_demo)
            project_name = f"demoforge-{demo_id}"
            edge = next((e for e in expanded.edges if e.id == edge_id), None)
            if edge:
                alias = _get_first_cluster_alias(expanded)
                if alias:
                    cmd = f"mc admin replicate remove {alias} --all --force"
                    try:
                        exit_code, stdout, stderr = await exec_in_container(
                            f"{project_name}-mc-shell", f"sh -c {shlex.quote(cmd)}"
                        )
                        _audit_edge_exec(
                            demo_id,
                            "edge_pause_site_replication",
                            f"Site replication remove (edge {edge_id})",
                            cmd,
                            exit_code,
                            stdout,
                            stderr,
                        )
                        if exit_code != 0:
                            logger.warning(f"Failed to remove site-replication: {stderr[:200]}")
                    except Exception as e:
                        logger.warning(f"Error removing site-replication: {e}")
                        _audit_edge_exec(
                            demo_id,
                            "edge_pause_site_replication",
                            f"Site replication remove (edge {edge_id})",
                            cmd,
                            -1,
                            "",
                            str(e),
                        )

    # For tiering: state-only pause (no single mc remove without rule id)
    if ec.connection_type in ("tiering", "cluster-tiering") and ec.status == "applied":
        append_demo_integration_audit(
            demo_id,
            "info",
            "edge_pause_tiering",
            f"Tiering edge {edge_id} marked paused (no automatic mc rule removal)",
            "",
            node_id="mc-shell",
        )

    # For bucket replication, disable the rule on the server
    if ec.connection_type in ("replication", "cluster-replication") and ec.status == "applied":
        _demo = _load_demo(demo_id)
        if _demo:
            expanded = _expand_demo_for_edges(_demo)
            project_name = f"demoforge-{demo_id}"
            try:
                pause_cmd = _build_replication_state_cmd(
                    expanded, edge_id, project_name, "disable",
                )
                if pause_cmd:
                    exit_code, stdout, stderr = await exec_in_container(
                        pause_cmd["container"],
                        f"sh -c {shlex.quote(pause_cmd['command'])}",
                    )
                    cshort = pause_cmd["container"]
                    if cshort.startswith(f"demoforge-{demo_id}-"):
                        cshort = cshort[len(f"demoforge-{demo_id}-") :]
                    _audit_edge_exec(
                        demo_id,
                        "edge_pause_replication",
                        f"Disable bucket replication (edge {edge_id})",
                        pause_cmd["command"],
                        exit_code,
                        stdout,
                        stderr,
                        node_id=cshort[:64] or "mc-shell",
                    )
                    if exit_code != 0:
                        logger.warning(
                            f"Failed to disable replication for edge {edge_id}: {stderr[:200]}"
                        )
                        # Still mark as paused in state — the user asked to pause
            except Exception as e:
                logger.warning(f"Error disabling replication for edge {edge_id}: {e}")

    ec.status = "paused"
    state.set_demo(running)
    # Clear replication cache
    _repl_cache.pop(demo_id, None)
    return {"status": "paused", "edge_id": edge_id}


def _get_first_cluster_alias(demo) -> str | None:
    """Get the sanitized alias name of the first cluster (used for mc admin commands)."""
    import re as _re
    if demo.clusters:
        return _re.sub(r"[^a-zA-Z0-9_]", "_", demo.clusters[0].label)
    return None


@router.post("/api/demos/{demo_id}/edges/{edge_id}/resync")
async def resync_edge(demo_id: str, edge_id: str):
    """Trigger mc admin replicate resync on a site-replication edge."""
    running = state.get_demo(demo_id)
    if not running:
        raise HTTPException(404, "Demo not running")

    demo = _load_demo(demo_id)
    if not demo:
        raise HTTPException(404, "Demo definition not found")

    import re as _re
    expanded = _expand_demo_for_edges(demo)
    if len(expanded.clusters) < 2:
        raise HTTPException(400, "Need at least 2 clusters for resync")

    # mc admin replicate resync start requires exactly 2 aliases
    # Find the edge's source and target clusters
    edge = next((e for e in expanded.edges if e.id == edge_id or e.id.startswith(edge_id)), None)
    if edge:
        src_cid = (edge.connection_config or {}).get("_source_cluster_id", "")
        tgt_cid = (edge.connection_config or {}).get("_target_cluster_id", "")
        src_cluster = next((c for c in expanded.clusters if c.id == src_cid), None)
        tgt_cluster = next((c for c in expanded.clusters if c.id == tgt_cid), None)
        if src_cluster and tgt_cluster:
            alias1 = _re.sub(r"[^a-zA-Z0-9_]", "_", src_cluster.label)
            alias2 = _re.sub(r"[^a-zA-Z0-9_]", "_", tgt_cluster.label)
        else:
            # Fallback: use first two clusters
            alias1 = _re.sub(r"[^a-zA-Z0-9_]", "_", expanded.clusters[0].label)
            alias2 = _re.sub(r"[^a-zA-Z0-9_]", "_", expanded.clusters[1].label)
    else:
        alias1 = _re.sub(r"[^a-zA-Z0-9_]", "_", expanded.clusters[0].label)
        alias2 = _re.sub(r"[^a-zA-Z0-9_]", "_", expanded.clusters[1].label)

    project_name = f"demoforge-{demo_id}"
    mc_shell = f"{project_name}-mc-shell"

    cmd = f"mc admin replicate resync start {alias1} {alias2}"
    try:
        exit_code, stdout, stderr = await exec_in_container(
            mc_shell, f"sh -c {shlex.quote(cmd)}"
        )
        _audit_edge_exec(
            demo_id,
            "edge_resync",
            f"Site replication resync (edge {edge_id})",
            cmd,
            exit_code,
            stdout,
            stderr,
        )
        if exit_code != 0:
            return {"status": "failed", "edge_id": edge_id, "error": (stderr or stdout)[:500]}
        # Clear replication cache to force refresh
        _repl_cache.pop(demo_id, None)
        return {"status": "resync_started", "edge_id": edge_id, "output": stdout[:500]}
    except Exception as e:
        _audit_edge_exec(
            demo_id,
            "edge_resync",
            f"Site replication resync (edge {edge_id})",
            cmd,
            -1,
            "",
            str(e),
        )
        return {"status": "failed", "edge_id": edge_id, "error": str(e)[:500]}


@router.post("/api/demos/{demo_id}/clusters/{cluster_id}/reset")
async def reset_cluster(demo_id: str, cluster_id: str):
    """Remove all buckets from a MinIO cluster via mc-shell."""
    import re as _re
    running = state.get_demo(demo_id)
    if not running:
        raise HTTPException(404, "Demo not running")

    demo = _load_demo(demo_id)
    if not demo:
        raise HTTPException(404, "Demo definition not found")

    cluster = next((c for c in demo.clusters if c.id == cluster_id), None)
    if not cluster:
        raise HTTPException(404, f"Cluster '{cluster_id}' not found")

    alias = re.sub(r"[^a-zA-Z0-9_]", "_", cluster.label)
    project_name = f"demoforge-{demo_id}"
    mc_shell = f"{project_name}-mc-shell"

    # First pass: remove buckets
    remove_cmd = (
        f"mc ls {alias}/ 2>/dev/null | while read line; do "
        f'b="${{line##* }}"; b="${{b%/}}"; '
        f'[ -n "$b" ] && mc rb --force {alias}/$b 2>/dev/null && echo "REMOVED:$b"; '
        f"done"
    )

    try:
        exit_code, stdout, stderr = await exec_in_container(
            mc_shell, f"sh -c {shlex.quote(remove_cmd)}"
        )
        _audit_edge_exec(
            demo_id,
            "cluster_reset_buckets",
            f"Remove all buckets on cluster {cluster_id} ({cluster.label})",
            remove_cmd,
            exit_code,
            stdout,
            stderr,
        )
        if exit_code != 0:
            return {"status": "failed", "cluster_id": cluster_id, "error": (stderr or stdout)[:500]}

        removed = [line[len("REMOVED:"):] for line in stdout.splitlines() if line.startswith("REMOVED:")]
        return {"status": "reset", "cluster_id": cluster_id, "buckets_removed": len(removed)}
    except Exception as e:
        _audit_edge_exec(
            demo_id,
            "cluster_reset_buckets",
            f"Remove all buckets on cluster {cluster_id}",
            remove_cmd,
            -1,
            "",
            str(e),
        )
        raise HTTPException(500, str(e))

