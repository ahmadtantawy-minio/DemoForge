"""
Edge-driven init script generation.
Generates and executes init scripts derived from edge connections in a demo.
Each connection type has a generator that produces shell commands to configure
the relationship between source and target containers.
"""
import logging
import shlex
from dataclasses import dataclass
from ..models.demo import DemoDefinition, DemoEdge, DemoNode, DemoCluster
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


def _get_credential(node: DemoNode, manifest: ComponentManifest | None, key: str, fallback: str) -> str:
    """Get credential: check node config overrides first, then manifest defaults."""
    # Node-level config takes precedence (user customization)
    val = node.config.get(key)
    if val:
        return val
    # Fall back to manifest secret defaults
    if manifest:
        for secret in manifest.secrets:
            if secret.key == key:
                return secret.default or fallback
    return fallback


def _safe(value: str) -> str:
    """Sanitize a value for safe shell interpolation."""
    return shlex.quote(str(value))


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
    source_bucket = _safe(config.get("source_bucket", "demo-bucket"))
    target_bucket = _safe(config.get("target_bucket", "demo-bucket"))
    replication_mode = config.get("replication_mode", "async")
    bandwidth = _safe(config.get("bandwidth_limit", "0"))

    source_manifest = get_component(source_node.component)
    target_manifest = get_component(target_node.component)

    source_user = _get_credential(source_node, source_manifest, "MINIO_ROOT_USER", "minioadmin")
    source_pass = _get_credential(source_node, source_manifest, "MINIO_ROOT_PASSWORD", "minioadmin")
    target_user = _get_credential(target_node, target_manifest, "MINIO_ROOT_USER", "minioadmin")
    target_pass = _get_credential(target_node, target_manifest, "MINIO_ROOT_PASSWORD", "minioadmin")

    source_host = f"{project_name}-{source_node.id}"
    target_host = f"{project_name}-{target_node.id}"

    bandwidth_flag = f"--bandwidth {bandwidth}" if config.get("bandwidth_limit", "0") != "0" else ""
    sync_flag = "--sync" if replication_mode == "sync" else ""

    command = (
        f"mc alias set source http://{source_host}:9000 {_safe(source_user)} {_safe(source_pass)} && "
        f"mc alias set target http://{target_host}:9000 {_safe(target_user)} {_safe(target_pass)} && "
        f"mc mb source/{source_bucket} --ignore-existing && "
        f"mc mb target/{target_bucket} --ignore-existing && "
        f"mc version enable source/{source_bucket} && "
        f"mc version enable target/{target_bucket} && "
        f"mc replicate add source/{source_bucket} "
        f"--remote-bucket http://{_safe(target_user)}:{_safe(target_pass)}@{target_host}:9000/{target_bucket} "
        f'--replicate "delete,delete-marker,existing-objects" '
        f"--priority 1 {bandwidth_flag} {sync_flag}"
    ).strip()

    return [EdgeInitScript(
        edge_id=edge.id,
        connection_type="replication",
        container_name=f"{project_name}-{source_node.id}",
        command=command,
        order=20,
        description=f"Set up bucket replication: {source_node.id}/{config.get('source_bucket', 'demo-bucket')} -> {target_node.id}/{config.get('target_bucket', 'demo-bucket')}",
        wait_for_healthy=True,
        timeout=60,
    )]


# ---------------------------------------------------------------------------
# Generator: site-replication
# ---------------------------------------------------------------------------
@_register("site-replication")
def _gen_site_replication(edge: DemoEdge, demo: DemoDefinition, project_name: str) -> list[EdgeInitScript]:
    """Generate mc admin replicate add for bidirectional site replication."""
    source_node = next((n for n in demo.nodes if n.id == edge.source), None)
    target_node = next((n for n in demo.nodes if n.id == edge.target), None)
    if not source_node or not target_node:
        return []

    source_manifest = get_component(source_node.component)
    target_manifest = get_component(target_node.component)
    source_user = _get_credential(source_node, source_manifest, "MINIO_ROOT_USER", "minioadmin")
    source_pass = _get_credential(source_node, source_manifest, "MINIO_ROOT_PASSWORD", "minioadmin")
    target_user = _get_credential(target_node, target_manifest, "MINIO_ROOT_USER", "minioadmin")
    target_pass = _get_credential(target_node, target_manifest, "MINIO_ROOT_PASSWORD", "minioadmin")

    if source_user != target_user or source_pass != target_pass:
        logger.warning(f"site-replication edge {edge.id}: credentials differ between {source_node.id} and {target_node.id}. Site replication requires matching root credentials.")

    source_host = f"{project_name}-{source_node.id}"
    target_host = f"{project_name}-{target_node.id}"

    command = (
        f"mc alias set site1 http://{source_host}:9000 {_safe(source_user)} {_safe(source_pass)} && "
        f"mc alias set site2 http://{target_host}:9000 {_safe(target_user)} {_safe(target_pass)} && "
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
    policy_name = _safe(config.get("policy_name", "auto-tier"))
    transition_days = _safe(config.get("transition_days", "30"))

    source_manifest = get_component(source_node.component)
    target_manifest = get_component(target_node.component)
    source_user = _get_credential(source_node, source_manifest, "MINIO_ROOT_USER", "minioadmin")
    source_pass = _get_credential(source_node, source_manifest, "MINIO_ROOT_PASSWORD", "minioadmin")
    target_user = _get_credential(target_node, target_manifest, "MINIO_ROOT_USER", "minioadmin")
    target_pass = _get_credential(target_node, target_manifest, "MINIO_ROOT_PASSWORD", "minioadmin")

    source_host = f"{project_name}-{source_node.id}"
    target_host = f"{project_name}-{target_node.id}"

    command = (
        f"mc alias set hot http://{source_host}:9000 {_safe(source_user)} {_safe(source_pass)} && "
        f"mc alias set cold http://{target_host}:9000 {_safe(target_user)} {_safe(target_pass)} && "
        f"mc mb hot/data --ignore-existing && "
        f"mc mb cold/tiered --ignore-existing && "
        f"mc admin tier add minio hot COLD-TIER "
        f"--endpoint http://{target_host}:9000 "
        f"--access-key {_safe(target_user)} --secret-key {_safe(target_pass)} "
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
        description=f"Set up ILM tiering: {source_node.id}/data -> {target_node.id}/tiered (after {config.get('transition_days', '30')} days)",
        wait_for_healthy=True,
        timeout=60,
    )]


# ---------------------------------------------------------------------------
# Template-driven generators (no runtime init needed)
# ---------------------------------------------------------------------------
@_register("metrics")
def _gen_metrics(edge: DemoEdge, demo: DemoDefinition, project_name: str) -> list[EdgeInitScript]:
    return []

@_register("metrics-query")
def _gen_metrics_query(edge: DemoEdge, demo: DemoDefinition, project_name: str) -> list[EdgeInitScript]:
    return []

@_register("file-push")
def _gen_file_push(edge: DemoEdge, demo: DemoDefinition, project_name: str) -> list[EdgeInitScript]:
    return []


# ---------------------------------------------------------------------------
# Helpers for cluster-level operations
# ---------------------------------------------------------------------------

def _find_cluster(demo: DemoDefinition, cluster_id: str) -> DemoCluster | None:
    """Find a DemoCluster by ID."""
    return next((c for c in demo.clusters if c.id == cluster_id), None)


def _get_cluster_credentials(cluster: DemoCluster) -> tuple[str, str]:
    """Get root user/password from cluster definition."""
    return (
        cluster.credentials.get("root_user", "minioadmin"),
        cluster.credentials.get("root_password", "minioadmin"),
    )


def _resolve_cluster_endpoint(cluster: DemoCluster, project_name: str) -> str:
    """Resolve cluster endpoint to its embedded NGINX LB hostname."""
    return f"{project_name}-{cluster.id}-lb"


# ---------------------------------------------------------------------------
# Generator: cluster-replication (bucket replication between clusters)
# ---------------------------------------------------------------------------
@_register("cluster-replication")
def _gen_cluster_replication(edge: DemoEdge, demo: DemoDefinition, project_name: str) -> list[EdgeInitScript]:
    """Generate mc commands for bucket replication between MinIO clusters."""
    config = edge.connection_config or {}
    source_cluster_id = config.get("_source_cluster_id", "")
    target_cluster_id = config.get("_target_cluster_id", "")

    # Resolve clusters from edge source/target nodes
    if not source_cluster_id:
        # Source node is a synthetic node — derive cluster ID
        source_node = next((n for n in demo.nodes if n.id == edge.source), None)
        if source_node:
            for c in demo.clusters:
                if edge.source.startswith(f"{c.id}-node-"):
                    source_cluster_id = c.id
                    break
    if not target_cluster_id:
        target_node = next((n for n in demo.nodes if n.id == edge.target), None)
        if target_node:
            for c in demo.clusters:
                if edge.target.startswith(f"{c.id}-node-"):
                    target_cluster_id = c.id
                    break

    source_cluster = _find_cluster(demo, source_cluster_id)
    target_cluster = _find_cluster(demo, target_cluster_id)
    if not source_cluster or not target_cluster:
        logger.warning(f"cluster-replication edge {edge.id}: cannot resolve source/target clusters")
        return []

    source_user, source_pass = _get_cluster_credentials(source_cluster)
    target_user, target_pass = _get_cluster_credentials(target_cluster)
    source_host = _resolve_cluster_endpoint(source_cluster, project_name)
    target_host = _resolve_cluster_endpoint(target_cluster, project_name)

    source_bucket = _safe(config.get("source_bucket", "demo-bucket"))
    target_bucket = _safe(config.get("target_bucket", "demo-bucket"))
    replication_mode = config.get("replication_mode", "async")
    direction = config.get("direction", "one-way")
    bandwidth = _safe(config.get("bandwidth_limit", "0"))

    bandwidth_flag = f"--bandwidth {bandwidth}" if config.get("bandwidth_limit", "0") != "0" else ""
    sync_flag = "--sync" if replication_mode == "sync" else ""

    # Forward replication: source -> target via embedded NGINX LB (port 80)
    # Versioning must be enabled on both buckets for replication to work
    # mc commands execute on a MinIO node but target the LB endpoint
    command = (
        f"mc alias set source http://{source_host}:80 {_safe(source_user)} {_safe(source_pass)} && "
        f"mc alias set target http://{target_host}:80 {_safe(target_user)} {_safe(target_pass)} && "
        f"mc mb source/{source_bucket} --ignore-existing && "
        f"mc mb target/{target_bucket} --ignore-existing && "
        f"mc version enable source/{source_bucket} && "
        f"mc version enable target/{target_bucket} && "
        f"mc replicate add source/{source_bucket} "
        f"--remote-bucket http://{_safe(target_user)}:{_safe(target_pass)}@{target_host}:80/{target_bucket} "
        f'--replicate "delete,delete-marker,existing-objects" '
        f"--priority 1 {bandwidth_flag} {sync_flag}"
    ).strip()

    scripts = [EdgeInitScript(
        edge_id=edge.id,
        connection_type="cluster-replication",
        container_name=f"{project_name}-{source_cluster.id}-node-1",
        command=command,
        order=20,
        description=f"Cluster replication: {source_cluster.label}/{config.get('source_bucket', 'demo-bucket')} -> {target_cluster.label}/{config.get('target_bucket', 'demo-bucket')}",
        wait_for_healthy=True,
        timeout=180,
    )]

    # Bidirectional: add reverse replication
    if direction == "bidirectional":
        reverse_cmd = (
            f"mc alias set source http://{target_host}:80 {_safe(target_user)} {_safe(target_pass)} && "
            f"mc alias set target http://{source_host}:80 {_safe(source_user)} {_safe(source_pass)} && "
            f"mc replicate add source/{target_bucket} "
            f"--remote-bucket http://{_safe(source_user)}:{_safe(source_pass)}@{source_host}:80/{source_bucket} "
            f'--replicate "delete,delete-marker,existing-objects" '
            f"--priority 1 {bandwidth_flag} {sync_flag}"
        ).strip()
        scripts.append(EdgeInitScript(
            edge_id=f"{edge.id}-reverse",
            connection_type="cluster-replication",
            container_name=f"{project_name}-{target_cluster.id}-node-1",
            command=reverse_cmd,
            order=21,
            description=f"Cluster replication (reverse): {target_cluster.label}/{config.get('target_bucket', 'demo-bucket')} -> {source_cluster.label}/{config.get('source_bucket', 'demo-bucket')}",
            wait_for_healthy=True,
            timeout=180,
        ))

    return scripts


# ---------------------------------------------------------------------------
# Generator: cluster-site-replication (full cluster sync)
# ---------------------------------------------------------------------------
@_register("cluster-site-replication")
def _gen_cluster_site_replication(edge: DemoEdge, demo: DemoDefinition, project_name: str) -> list[EdgeInitScript]:
    """Generate mc admin replicate add for site replication between clusters."""
    config = edge.connection_config or {}
    source_cluster_id = config.get("_source_cluster_id", "")
    target_cluster_id = config.get("_target_cluster_id", "")

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
        logger.warning(f"cluster-site-replication edge {edge.id}: cannot resolve clusters")
        return []

    source_user, source_pass = _get_cluster_credentials(source_cluster)
    target_user, target_pass = _get_cluster_credentials(target_cluster)

    if source_user != target_user or source_pass != target_pass:
        logger.warning(f"cluster-site-replication edge {edge.id}: credentials differ between {source_cluster.label} and {target_cluster.label}. Site replication requires matching root credentials.")

    source_host = _resolve_cluster_endpoint(source_cluster, project_name)
    target_host = _resolve_cluster_endpoint(target_cluster, project_name)

    # Smart site-replication activation:
    # 1. Check if already configured via mc admin replicate info
    # 2. If "enabled" found → already active, report success
    # 3. If not → clean target buckets, then add
    command = (
        f"mc alias set site1 http://{source_host}:80 {_safe(source_user)} {_safe(source_pass)} && "
        f"mc alias set site2 http://{target_host}:80 {_safe(target_user)} {_safe(target_pass)} && "
        f"STATUS=$(mc admin replicate info site1 2>&1 | head -1) && "
        f"case \"$STATUS\" in "
        f"*enabled*) echo \"Site replication already active\"; mc admin replicate info site1;; "
        f"*) echo \"Setting up site replication...\"; "
        f"for b in $(mc ls site2 2>/dev/null | tr -s ' ' | cut -d' ' -f5 | tr -d '/'); do "
        f"[ -n \"$b\" ] && mc rb site2/$b --force 2>/dev/null; done; "
        f"mc admin replicate add site1 site2;; "
        f"esac"
    )

    return [EdgeInitScript(
        edge_id=edge.id,
        connection_type="cluster-site-replication",
        container_name=f"{project_name}-mc-shell",
        command=command,
        order=25,
        description=f"Site replication: {source_cluster.label} <-> {target_cluster.label}",
        wait_for_healthy=True,
        timeout=180,
    )]


# ---------------------------------------------------------------------------
# Generator: cluster-tiering (ILM lifecycle between clusters)
# ---------------------------------------------------------------------------
@_register("cluster-tiering")
def _gen_cluster_tiering(edge: DemoEdge, demo: DemoDefinition, project_name: str) -> list[EdgeInitScript]:
    """Generate mc commands for ILM tiering from hot cluster to cold cluster."""
    config = edge.connection_config or {}
    source_cluster_id = config.get("_source_cluster_id", "")
    target_cluster_id = config.get("_target_cluster_id", "")

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
        logger.warning(f"cluster-tiering edge {edge.id}: cannot resolve clusters")
        return []

    source_user, source_pass = _get_cluster_credentials(source_cluster)
    target_user, target_pass = _get_cluster_credentials(target_cluster)
    source_host = _resolve_cluster_endpoint(source_cluster, project_name)
    target_host = _resolve_cluster_endpoint(target_cluster, project_name)

    source_bucket = _safe(config.get("source_bucket", "data"))
    tier_bucket = _safe(config.get("tier_bucket", "tiered"))
    tier_name = _safe(config.get("tier_name", "COLD-TIER"))
    transition_days = _safe(config.get("transition_days", "30"))
    policy_name = _safe(config.get("policy_name", "auto-tier"))

    command = (
        f"mc alias set hot http://{source_host}:80 {_safe(source_user)} {_safe(source_pass)} && "
        f"mc alias set cold http://{target_host}:80 {_safe(target_user)} {_safe(target_pass)} && "
        f"mc mb hot/{source_bucket} --ignore-existing && "
        f"mc mb cold/{tier_bucket} --ignore-existing && "
        f"mc admin tier add minio hot {tier_name} "
        f"--endpoint http://{target_host}:80 "
        f"--access-key {_safe(target_user)} --secret-key {_safe(target_pass)} "
        f"--bucket {tier_bucket} 2>/dev/null; "
        f"mc ilm rule add hot/{source_bucket} "
        f"--transition-days {transition_days} "
        f"--transition-tier {tier_name}"
    )

    return [EdgeInitScript(
        edge_id=edge.id,
        connection_type="cluster-tiering",
        container_name=f"{project_name}-{source_cluster.id}-node-1",
        command=command,
        order=30,
        description=f"ILM tiering: {source_cluster.label}/{config.get('source_bucket', 'data')} -> {target_cluster.label}/{config.get('tier_bucket', 'tiered')} (after {config.get('transition_days', '30')} days)",
        wait_for_healthy=True,
        timeout=180,
    )]
