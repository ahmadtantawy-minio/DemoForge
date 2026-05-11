"""Config script export endpoint.

Generates a complete shell script with mc commands that would recreate
the current demo setup from scratch. Educational / documentation tool.
"""
import logging
import shlex
from dataclasses import dataclass, field
from fastapi import APIRouter, HTTPException
from ..models.demo import DemoDefinition, DemoEdge, DemoNode, DemoCluster
from ..registry.loader import get_component
from ..engine.edge_automation import _tier_prefix_mc_flag, _tier_remote_bucket_and_prefix
from ..models.component import ComponentManifest
from .demos import _load_demo

logger = logging.getLogger(__name__)
router = APIRouter()


@dataclass
class ScriptSection:
    name: str
    commands: list[str] = field(default_factory=list)
    comments: list[str] = field(default_factory=list)


def _safe(value: str) -> str:
    return shlex.quote(str(value))


def _get_credential(node: DemoNode, manifest: ComponentManifest | None, key: str, fallback: str) -> str:
    val = node.config.get(key)
    if val:
        return val
    if manifest:
        for secret in manifest.secrets:
            if secret.key == key:
                return secret.default or fallback
    return fallback


def _cluster_alias(cluster: DemoCluster) -> str:
    return cluster.label.replace(" ", "_").replace("-", "_")


def _get_cluster_credentials(cluster: DemoCluster) -> tuple[str, str]:
    return (
        cluster.credentials.get("root_user", "minioadmin"),
        cluster.credentials.get("root_password", "minioadmin"),
    )


def _resolve_cluster_endpoint(cluster: DemoCluster, project_name: str) -> str:
    return f"{project_name}-{cluster.id}-lb"


def _find_cluster(demo: DemoDefinition, cluster_id: str) -> DemoCluster | None:
    return next((c for c in demo.clusters if c.id == cluster_id), None)


def _resolve_cluster_id_from_node(demo: DemoDefinition, node_id: str) -> str:
    for c in demo.clusters:
        if node_id.startswith(f"{c.id}-node-"):
            return c.id
    return ""


# ---------------------------------------------------------------------------
# Section generators
# ---------------------------------------------------------------------------

def _gen_cluster_setup(demo: DemoDefinition, project_name: str) -> ScriptSection:
    """Generate mc alias set commands for every cluster."""
    section = ScriptSection(name="Cluster Setup")
    section.comments.append("# Configure mc aliases so subsequent commands can target each cluster")

    for cluster in demo.clusters:
        user, password = _get_cluster_credentials(cluster)
        host = _resolve_cluster_endpoint(cluster, project_name)
        alias = _cluster_alias(cluster)
        section.comments.append(f"# Alias for cluster '{cluster.label}'")
        section.commands.append(
            f"mc alias set {alias} http://{host}:80 {_safe(user)} {_safe(password)}"
        )

    # Standalone MinIO nodes (not part of a cluster)
    for node in demo.nodes:
        manifest = get_component(node.component)
        if not manifest or manifest.id != "minio":
            continue
        user = _get_credential(node, manifest, "MINIO_ROOT_USER", "minioadmin")
        password = _get_credential(node, manifest, "MINIO_ROOT_PASSWORD", "minioadmin")
        host = f"{project_name}-{node.id}"
        alias = node.display_name.replace(" ", "_").replace("-", "_") if node.display_name else node.id
        section.comments.append(f"# Alias for standalone node '{node.id}'")
        section.commands.append(
            f"mc alias set {alias} http://{host}:9000 {_safe(user)} {_safe(password)}"
        )

    return section


def _gen_bucket_creation(demo: DemoDefinition, project_name: str) -> ScriptSection:
    """Generate mc mb commands for buckets referenced in edge configs."""
    section = ScriptSection(name="Bucket Creation")
    section.comments.append("# Create buckets referenced by replication, tiering, and other edges")

    seen: set[str] = set()

    for edge in demo.edges:
        if not edge.auto_configure:
            continue
        config = edge.connection_config or {}

        if edge.connection_type in ("replication", "cluster-replication"):
            for bucket_key, node_key in [("source_bucket", edge.source), ("target_bucket", edge.target)]:
                bucket = config.get(bucket_key, "demo-bucket")
                # Determine alias
                alias = _resolve_alias_for_node(demo, node_key, project_name)
                key = f"{alias}/{bucket}"
                if key not in seen:
                    seen.add(key)
                    section.commands.append(f"mc mb {alias}/{_safe(bucket)} --ignore-existing")

        elif edge.connection_type in ("tiering", "cluster-tiering"):
            source_bucket = config.get("source_bucket", "data")
            cold_bucket, _ = _tier_remote_bucket_and_prefix(config)
            source_alias = _resolve_alias_for_node(demo, edge.source, project_name)
            target_alias = _resolve_alias_for_node(demo, edge.target, project_name)
            for alias, bucket in [(source_alias, source_bucket), (target_alias, cold_bucket)]:
                key = f"{alias}/{bucket}"
                if key not in seen:
                    seen.add(key)
                    section.commands.append(f"mc mb {alias}/{_safe(bucket)} --ignore-existing")

    return section


def _gen_versioning(demo: DemoDefinition, project_name: str) -> ScriptSection:
    """Generate mc version enable for buckets that need versioning (replication requires it)."""
    section = ScriptSection(name="Versioning")
    section.comments.append("# Enable versioning on buckets used by replication (required for replication to work)")

    seen: set[str] = set()
    for edge in demo.edges:
        if not edge.auto_configure:
            continue
        if edge.connection_type not in ("replication", "cluster-replication"):
            continue
        config = edge.connection_config or {}
        for bucket_key, node_key in [("source_bucket", edge.source), ("target_bucket", edge.target)]:
            bucket = config.get(bucket_key, "demo-bucket")
            alias = _resolve_alias_for_node(demo, node_key, project_name)
            key = f"{alias}/{bucket}"
            if key not in seen:
                seen.add(key)
                section.commands.append(f"mc version enable {alias}/{_safe(bucket)}")

    return section


def _gen_replication(demo: DemoDefinition, project_name: str) -> ScriptSection:
    """Generate mc replicate add commands."""
    section = ScriptSection(name="Replication Setup")
    section.comments.append("# Set up bucket-level replication between MinIO instances")

    for edge in demo.edges:
        if not edge.auto_configure:
            continue
        if edge.connection_type not in ("replication", "cluster-replication"):
            continue

        config = edge.connection_config or {}
        source_bucket = _safe(config.get("source_bucket", "demo-bucket"))
        target_bucket = _safe(config.get("target_bucket", "demo-bucket"))
        replication_mode = config.get("replication_mode", "async")
        bandwidth = config.get("bandwidth_limit", "0")
        direction = config.get("direction", "one-way")

        source_alias = _resolve_alias_for_node(demo, edge.source, project_name)
        target_alias = _resolve_alias_for_node(demo, edge.target, project_name)
        target_endpoint, target_user, target_pass = _resolve_endpoint_creds(demo, edge.target, project_name)

        bandwidth_flag = f"--bandwidth {_safe(bandwidth)}" if bandwidth != "0" else ""
        sync_flag = "--sync" if replication_mode == "sync" else ""

        section.comments.append(f"# Replicate {source_alias}/{source_bucket} -> {target_alias}/{target_bucket}")
        cmd = (
            f"mc replicate add {source_alias}/{source_bucket} "
            f"--remote-bucket http://{_safe(target_user)}:{_safe(target_pass)}@{target_endpoint}/{target_bucket} "
            f'--replicate "delete,delete-marker,existing-objects" '
            f"--priority 1 {bandwidth_flag} {sync_flag}"
        ).strip()
        section.commands.append(cmd)

        # Bidirectional reverse
        if direction == "bidirectional":
            source_endpoint, source_user, source_pass = _resolve_endpoint_creds(demo, edge.source, project_name)
            section.comments.append(f"# Reverse replication: {target_alias}/{target_bucket} -> {source_alias}/{source_bucket}")
            rev_cmd = (
                f"mc replicate add {target_alias}/{target_bucket} "
                f"--remote-bucket http://{_safe(source_user)}:{_safe(source_pass)}@{source_endpoint}/{source_bucket} "
                f'--replicate "delete,delete-marker,existing-objects" '
                f"--priority 1 {bandwidth_flag} {sync_flag}"
            ).strip()
            section.commands.append(rev_cmd)

    return section


def _gen_site_replication(demo: DemoDefinition, project_name: str) -> ScriptSection:
    """Generate mc admin replicate add commands."""
    section = ScriptSection(name="Site Replication")
    section.comments.append("# Site replication synchronizes IAM, policies, and buckets across clusters")

    for edge in demo.edges:
        if not edge.auto_configure:
            continue
        if edge.connection_type not in ("site-replication", "cluster-site-replication"):
            continue

        source_alias = _resolve_alias_for_node(demo, edge.source, project_name)
        target_alias = _resolve_alias_for_node(demo, edge.target, project_name)

        section.comments.append(f"# Bidirectional site replication: {source_alias} <-> {target_alias}")
        section.commands.append(f"mc admin replicate add {source_alias} {target_alias}")

    return section


def _gen_ilm_tiering(demo: DemoDefinition, project_name: str) -> ScriptSection:
    """Generate mc admin tier add + mc ilm rule add commands."""
    section = ScriptSection(name="ILM Tiering")
    section.comments.append("# ILM tiering moves objects to a remote tier after a transition period")

    for edge in demo.edges:
        if not edge.auto_configure:
            continue
        if edge.connection_type not in ("tiering", "cluster-tiering"):
            continue

        config = edge.connection_config or {}
        source_bucket = _safe(config.get("source_bucket", "data"))
        cold_bucket, tier_prefix = _tier_remote_bucket_and_prefix(config)
        cold_bucket_q = _safe(cold_bucket)
        prefix_flag = _tier_prefix_mc_flag(tier_prefix)
        tier_name = _safe(config.get("tier_name", "COLD-TIER"))
        transition_days = _safe(config.get("transition_days", "30"))

        source_alias = _resolve_alias_for_node(demo, edge.source, project_name)
        target_endpoint, target_user, target_pass = _resolve_endpoint_creds(demo, edge.target, project_name)

        section.comments.append(
            f"# Add remote tier '{tier_name}' on the hot cluster; ILM rule uses {source_alias}/{source_bucket}. "
            f"--bucket is the cold bucket (default tiered); optional --prefix scopes keys under that bucket."
        )
        section.commands.append(
            f"mc admin tier add minio {source_alias} {tier_name} "
            f"--endpoint http://{target_endpoint} "
            f"--access-key {_safe(target_user)} --secret-key {_safe(target_pass)} "
            f"--bucket {cold_bucket_q}{prefix_flag}"
        )

        section.comments.append(f"# Transition objects in {source_alias}/{source_bucket} after {transition_days} days")
        section.commands.append(
            f"mc ilm rule add {source_alias}/{source_bucket} "
            f"--transition-days {transition_days} "
            f"--transition-tier {tier_name}"
        )

    return section


# ---------------------------------------------------------------------------
# Alias / endpoint resolution helpers
# ---------------------------------------------------------------------------

def _resolve_alias_for_node(demo: DemoDefinition, node_id: str, project_name: str) -> str:
    """Return the mc alias name for a node (cluster member or standalone)."""
    # Check if this node belongs to a cluster
    for cluster in demo.clusters:
        if node_id.startswith(f"{cluster.id}-node-"):
            return _cluster_alias(cluster)
    # Standalone node
    node = next((n for n in demo.nodes if n.id == node_id), None)
    if node:
        return node.display_name.replace(" ", "_").replace("-", "_") if node.display_name else node.id
    return node_id


def _resolve_endpoint_creds(demo: DemoDefinition, node_id: str, project_name: str) -> tuple[str, str, str]:
    """Return (host:port, user, password) for a node."""
    for cluster in demo.clusters:
        if node_id.startswith(f"{cluster.id}-node-"):
            user, password = _get_cluster_credentials(cluster)
            host = _resolve_cluster_endpoint(cluster, project_name)
            return f"{host}:80", user, password
    node = next((n for n in demo.nodes if n.id == node_id), None)
    if node:
        manifest = get_component(node.component)
        user = _get_credential(node, manifest, "MINIO_ROOT_USER", "minioadmin")
        password = _get_credential(node, manifest, "MINIO_ROOT_PASSWORD", "minioadmin")
        host = f"{project_name}-{node.id}"
        return f"{host}:9000", user, password
    return f"{project_name}-{node_id}:9000", "minioadmin", "minioadmin"


# ---------------------------------------------------------------------------
# Script assembly
# ---------------------------------------------------------------------------

def build_config_script(demo: DemoDefinition, project_name: str) -> tuple[str, list[dict]]:
    """Build a full shell script and structured sections list."""
    generators = [
        _gen_cluster_setup,
        _gen_bucket_creation,
        _gen_versioning,
        _gen_replication,
        _gen_site_replication,
        _gen_ilm_tiering,
    ]

    sections: list[dict] = []
    script_lines = [
        "#!/bin/sh",
        f"# DemoForge config script for demo: {demo.name} ({demo.id})",
        f"# Project name: {project_name}",
        "#",
        "# This script contains all mc commands needed to recreate this",
        "# demo's MinIO configuration from scratch.",
        "#",
        "# Prerequisites:",
        "#   - MinIO Client (mc) installed: https://min.io/docs/minio/linux/reference/minio-mc.html",
        "#   - All MinIO servers running and reachable",
        "",
    ]

    for gen in generators:
        section = gen(demo, project_name)
        if not section.commands:
            continue
        sections.append({"name": section.name, "commands": section.commands})

        script_lines.append(f"# ===== {section.name.upper()} =====")
        # Interleave comments and commands
        for comment in section.comments:
            script_lines.append(comment)
        script_lines.append("")
        for cmd in section.commands:
            script_lines.append(cmd)
        script_lines.append("")

    return "\n".join(script_lines), sections


# ---------------------------------------------------------------------------
# API endpoint
# ---------------------------------------------------------------------------

@router.get("/api/demos/{demo_id}/config-script")
async def get_config_script(demo_id: str):
    """Generate a complete shell script with mc commands for the demo setup."""
    demo = _load_demo(demo_id)
    if not demo:
        raise HTTPException(404, "Demo not found")

    project_name = f"demoforge-{demo_id}"
    script, sections = build_config_script(demo, project_name)

    return {
        "demo_id": demo_id,
        "script": script,
        "sections": sections,
    }
