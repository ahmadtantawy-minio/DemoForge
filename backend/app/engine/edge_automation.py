"""
Edge-driven init script generation.
Generates and executes init scripts derived from edge connections in a demo.
Each connection type has a generator that produces shell commands to configure
the relationship between source and target containers.
"""
import logging
from dataclasses import dataclass
from ..models.demo import DemoDefinition, DemoEdge
from ..models.component import ComponentManifest
from ..registry.loader import get_component

logger = logging.getLogger(__name__)


@dataclass
class EdgeInitScript:
    """An init script generated from an edge connection."""
    edge_id: str
    connection_type: str
    container_name: str   # Which container to execute in
    command: str           # Shell command to run
    order: int = 10        # Execution order (lower = first)
    description: str = ""
    wait_for_healthy: bool = True
    timeout: int = 60


_GENERATORS: dict[str, callable] = {}


def _register(conn_type: str):
    def decorator(fn):
        _GENERATORS[conn_type] = fn
        return fn
    return decorator


def _get_secret_default(manifest: ComponentManifest | None, key: str, fallback: str) -> str:
    """Get the default value of a secret from a component manifest."""
    if not manifest:
        return fallback
    for secret in manifest.secrets:
        if secret.key == key:
            return secret.default or fallback
    return fallback


def generate_edge_scripts(demo: DemoDefinition, project_name: str) -> list[EdgeInitScript]:
    """Generate init scripts for all auto-configure edges in a demo."""
    scripts = []
    for edge in demo.edges:
        if not edge.auto_configure:
            continue
        generator = _GENERATORS.get(edge.connection_type)
        if generator:
            try:
                new_scripts = generator(edge, demo, project_name)
                scripts.extend(new_scripts)
            except Exception as e:
                logger.warning(f"Failed to generate scripts for edge {edge.id} ({edge.connection_type}): {e}")
    return sorted(scripts, key=lambda s: s.order)


# ---------------------------------------------------------------------------
# Generator: load-balance
# ---------------------------------------------------------------------------
@_register("load-balance")
def _gen_load_balance(edge: DemoEdge, demo: DemoDefinition, project_name: str) -> list[EdgeInitScript]:
    """Load balancing is template-driven (nginx.conf.j2). No runtime init needed."""
    return []


# ---------------------------------------------------------------------------
# Generator: replication (bucket replication between MinIO nodes)
# ---------------------------------------------------------------------------
@_register("replication")
def _gen_bucket_replication(edge: DemoEdge, demo: DemoDefinition, project_name: str) -> list[EdgeInitScript]:
    """Generate mc commands for bucket replication between MinIO nodes."""
    source_node = next((n for n in demo.nodes if n.id == edge.source), None)
    target_node = next((n for n in demo.nodes if n.id == edge.target), None)
    if not source_node or not target_node:
        return []

    config = edge.connection_config or {}
    source_bucket = config.get("source_bucket", "demo-bucket")
    target_bucket = config.get("target_bucket", "demo-bucket")
    replication_mode = config.get("replication_mode", "async")
    bandwidth = config.get("bandwidth_limit", "0")

    # Get credentials from component secrets
    source_manifest = get_component(source_node.component)
    target_manifest = get_component(target_node.component)

    source_user = _get_secret_default(source_manifest, "MINIO_ROOT_USER", "minioadmin")
    source_pass = _get_secret_default(source_manifest, "MINIO_ROOT_PASSWORD", "minioadmin")
    target_user = _get_secret_default(target_manifest, "MINIO_ROOT_USER", "minioadmin")
    target_pass = _get_secret_default(target_manifest, "MINIO_ROOT_PASSWORD", "minioadmin")

    source_host = f"{project_name}-{source_node.id}"
    target_host = f"{project_name}-{target_node.id}"

    # Build the replication command
    bandwidth_flag = f"--bandwidth {bandwidth}" if bandwidth and bandwidth != "0" else ""
    sync_flag = "--sync" if replication_mode == "sync" else ""

    command = (
        f"mc alias set source http://{source_host}:9000 {source_user} {source_pass} && "
        f"mc alias set target http://{target_host}:9000 {target_user} {target_pass} && "
        f"mc mb source/{source_bucket} --ignore-existing && "
        f"mc mb target/{target_bucket} --ignore-existing && "
        f"mc replicate add source/{source_bucket} "
        f"--remote-target http://{target_user}:{target_pass}@{target_host}:9000/{target_bucket} "
        f'--replicate "delete,delete-marker,existing-objects" '
        f"{bandwidth_flag} {sync_flag}"
    ).strip()

    return [EdgeInitScript(
        edge_id=edge.id,
        connection_type="replication",
        container_name=f"{project_name}-{source_node.id}",
        command=command,
        order=20,
        description=f"Set up bucket replication: {source_node.id}/{source_bucket} -> {target_node.id}/{target_bucket}",
        wait_for_healthy=True,
        timeout=60,
    )]


# ---------------------------------------------------------------------------
# Generator: site-replication
# ---------------------------------------------------------------------------
@_register("site-replication")
def _gen_site_replication(edge: DemoEdge, demo: DemoDefinition, project_name: str) -> list[EdgeInitScript]:
    """Site replication requires collective processing -- handled separately."""
    source_node = next((n for n in demo.nodes if n.id == edge.source), None)
    target_node = next((n for n in demo.nodes if n.id == edge.target), None)
    if not source_node or not target_node:
        return []

    source_manifest = get_component(source_node.component)
    target_manifest = get_component(target_node.component)
    source_user = _get_secret_default(source_manifest, "MINIO_ROOT_USER", "minioadmin")
    source_pass = _get_secret_default(source_manifest, "MINIO_ROOT_PASSWORD", "minioadmin")
    target_user = _get_secret_default(target_manifest, "MINIO_ROOT_USER", "minioadmin")
    target_pass = _get_secret_default(target_manifest, "MINIO_ROOT_PASSWORD", "minioadmin")

    source_host = f"{project_name}-{source_node.id}"
    target_host = f"{project_name}-{target_node.id}"

    command = (
        f"mc alias set site1 http://{source_host}:9000 {source_user} {source_pass} && "
        f"mc alias set site2 http://{target_host}:9000 {target_user} {target_pass} && "
        f"mc admin replicate add site1 site2"
    )

    return [EdgeInitScript(
        edge_id=edge.id,
        connection_type="site-replication",
        container_name=f"{project_name}-{source_node.id}",
        command=command,
        order=25,
        description=f"Set up site replication: {source_node.id} <-> {target_node.id}",
        wait_for_healthy=True,
        timeout=60,
    )]


# ---------------------------------------------------------------------------
# Generator: tiering (ILM tiering between MinIO nodes)
# ---------------------------------------------------------------------------
@_register("tiering")
def _gen_ilm_tiering(edge: DemoEdge, demo: DemoDefinition, project_name: str) -> list[EdgeInitScript]:
    """Generate mc commands for ILM tiering between MinIO nodes."""
    source_node = next((n for n in demo.nodes if n.id == edge.source), None)
    target_node = next((n for n in demo.nodes if n.id == edge.target), None)
    if not source_node or not target_node:
        return []

    config = edge.connection_config or {}
    policy_name = config.get("policy_name", "auto-tier")
    transition_days = config.get("transition_days", "30")

    source_manifest = get_component(source_node.component)
    target_manifest = get_component(target_node.component)
    source_user = _get_secret_default(source_manifest, "MINIO_ROOT_USER", "minioadmin")
    source_pass = _get_secret_default(source_manifest, "MINIO_ROOT_PASSWORD", "minioadmin")
    target_user = _get_secret_default(target_manifest, "MINIO_ROOT_USER", "minioadmin")
    target_pass = _get_secret_default(target_manifest, "MINIO_ROOT_PASSWORD", "minioadmin")

    source_host = f"{project_name}-{source_node.id}"
    target_host = f"{project_name}-{target_node.id}"

    command = (
        f"mc alias set hot http://{source_host}:9000 {source_user} {source_pass} && "
        f"mc alias set cold http://{target_host}:9000 {target_user} {target_pass} && "
        f"mc mb hot/data --ignore-existing && "
        f"mc mb cold/tiered --ignore-existing && "
        f"mc admin tier add s3 hot COLD-TIER "
        f"--endpoint http://{target_host}:9000 "
        f"--access-key {target_user} --secret-key {target_pass} "
        f"--bucket tiered && "
        f"mc ilm rule add hot/data "
        f"--transition-days {transition_days} "
        f"--storage-class COLD-TIER "
        f"--name {policy_name}"
    )

    return [EdgeInitScript(
        edge_id=edge.id,
        connection_type="tiering",
        container_name=f"{project_name}-{source_node.id}",
        command=command,
        order=30,
        description=f"Set up ILM tiering: {source_node.id}/data -> {target_node.id}/tiered (after {transition_days} days)",
        wait_for_healthy=True,
        timeout=60,
    )]


# ---------------------------------------------------------------------------
# Generator: metrics (template-driven, no runtime init)
# ---------------------------------------------------------------------------
@_register("metrics")
def _gen_metrics(edge: DemoEdge, demo: DemoDefinition, project_name: str) -> list[EdgeInitScript]:
    """Metrics scraping is template-driven (prometheus.yml.j2). No runtime init needed."""
    return []


# ---------------------------------------------------------------------------
# Generator: metrics-query (template-driven, no runtime init)
# ---------------------------------------------------------------------------
@_register("metrics-query")
def _gen_metrics_query(edge: DemoEdge, demo: DemoDefinition, project_name: str) -> list[EdgeInitScript]:
    """Grafana datasource is template-driven. No runtime init needed."""
    return []


# ---------------------------------------------------------------------------
# Generator: file-push (template-driven, no runtime init)
# ---------------------------------------------------------------------------
@_register("file-push")
def _gen_file_push(edge: DemoEdge, demo: DemoDefinition, project_name: str) -> list[EdgeInitScript]:
    """File push is template-driven (generate.sh.j2). No runtime init needed."""
    return []
