"""Post-steps after ``mc admin replicate add`` (sync mode via ``mc admin replicate update``)."""
from __future__ import annotations

import json
import logging
import re
import shlex
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

from ..models.demo import DemoDefinition, DemoEdge
from .edge_automation import _connection_bool, _find_cluster, _resolve_cluster_endpoint

logger = logging.getLogger(__name__)

ExecFn = Callable[[str, str], Awaitable[tuple[int, str, str]]]


def _norm_hostname(endpoint: str) -> str:
    if not endpoint:
        return ""
    ep = endpoint.strip()
    if "://" not in ep:
        ep = "http://" + ep
    try:
        return (urlparse(ep).hostname or "").lower()
    except Exception:
        return ""


def resolve_site_replication_post_kwargs(
    edge: DemoEdge, demo: DemoDefinition, project_name: str
) -> dict[str, Any] | None:
    """Return kwargs for :func:`apply_site_replication_sync` or None if not a site-replication edge."""
    ct = edge.connection_type
    cfg = edge.connection_config or {}

    if ct == "cluster-site-replication":
        source_cluster_id = cfg.get("_source_cluster_id", "")
        target_cluster_id = cfg.get("_target_cluster_id", "")
        if not source_cluster_id:
            for c in demo.clusters:
                if edge.source.startswith(f"{c.id}-node-"):
                    source_cluster_id = c.id
                    break
        if not target_cluster_id:
            for c in demo.clusters:
                if edge.target.startswith(f"{c.id}-node-"):
                    target_cluster_id = c.id
                    break
        source_cluster = _find_cluster(demo, source_cluster_id)
        target_cluster = _find_cluster(demo, target_cluster_id)
        if not source_cluster or not target_cluster:
            return None
        src_a = re.sub(r"[^a-zA-Z0-9_]", "_", source_cluster.label)
        tgt_a = re.sub(r"[^a-zA-Z0-9_]", "_", target_cluster.label)
        host_a = _resolve_cluster_endpoint(source_cluster, project_name).lower()
        host_b = _resolve_cluster_endpoint(target_cluster, project_name).lower()
        return {
            "alias_a": src_a,
            "alias_b": tgt_a,
            "host_a": host_a,
            "host_b": host_b,
            "want_sync": _connection_bool(cfg, "site_replication_sync", True),
        }

    if ct == "site-replication":
        source_node = next((n for n in demo.nodes if n.id == edge.source), None)
        target_node = next((n for n in demo.nodes if n.id == edge.target), None)
        if not source_node or not target_node:
            return None
        src_a = (
            re.sub(r"[^a-zA-Z0-9_]", "_", source_node.display_name)
            if source_node.display_name
            else source_node.id
        )
        tgt_a = (
            re.sub(r"[^a-zA-Z0-9_]", "_", target_node.display_name)
            if target_node.display_name
            else target_node.id
        )
        host_a = f"{project_name}-{source_node.id}".lower()
        host_b = f"{project_name}-{target_node.id}".lower()
        return {
            "alias_a": src_a,
            "alias_b": tgt_a,
            "host_a": host_a,
            "host_b": host_b,
            "want_sync": _connection_bool(cfg, "site_replication_sync", True),
        }

    return None


def _pick_alias_for_peer(
    peer: dict[str, Any],
    alias_a: str,
    alias_b: str,
    host_a: str,
    host_b: str,
) -> str | None:
    h = _norm_hostname(peer.get("endpoint") or "")
    if not h:
        return None
    ha = host_a.split(":")[0].lower()
    hb = host_b.split(":")[0].lower()
    if h == ha or h.startswith(ha + ".") or ha in h:
        return alias_a
    if h == hb or h.startswith(hb + ".") or hb in h:
        return alias_b
    return None


async def apply_site_replication_sync(
    exec_in_container: ExecFn,
    mc_shell: str,
    *,
    alias_a: str,
    alias_b: str,
    host_a: str,
    host_b: str,
    want_sync: bool,
) -> None:
    """Enable synchronous site replication for each peer link (two-site group)."""
    if not want_sync:
        return

    cmd = f"mc admin replicate info {alias_a} --json"
    exit_code, stdout, stderr = await exec_in_container(mc_shell, f"sh -c {shlex.quote(cmd)}")
    if exit_code != 0:
        logger.warning("site_replication_sync: info failed: %s", (stderr or stdout)[:300])
        return
    raw = stdout.strip()
    if not raw:
        return
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("site_replication_sync: invalid JSON from mc admin replicate info")
        return

    sites = data.get("sites") or []
    if len(sites) < 2:
        return

    mapped: list[tuple[str, str]] = []
    for peer in sites:
        dep = peer.get("deploymentID") or peer.get("deploymentId")
        if not dep or not isinstance(dep, str):
            continue
        al = _pick_alias_for_peer(peer, alias_a, alias_b, host_a, host_b)
        if al:
            mapped.append((al, dep))

    if len(mapped) < 2 and len(sites) >= 2:
        d0 = sites[0].get("deploymentID") or sites[0].get("deploymentId") or ""
        d1 = sites[1].get("deploymentID") or sites[1].get("deploymentId") or ""
        if isinstance(d0, str) and isinstance(d1, str) and d0 and d1:
            mapped = [(alias_a, d0), (alias_b, d1)]

    if len(mapped) != 2:
        logger.warning("site_replication_sync: could not map two sites (got %s)", mapped)
        return

    (al0, d0), (al1, d1) = mapped[0], mapped[1]
    if al0 == al1:
        logger.warning("site_replication_sync: duplicate alias mapping")
        return

    for local_alias, other_dep in ((al0, d1), (al1, d0)):
        upd = f"mc admin replicate update {local_alias} --deployment-id {other_dep} --mode sync"
        u_exit, u_out, u_err = await exec_in_container(mc_shell, f"sh -c {shlex.quote(upd)}")
        if u_exit != 0:
            logger.warning(
                "site_replication_sync: update failed for %s dep=%s: %s",
                local_alias,
                other_dep,
                (u_err or u_out)[:400],
            )
