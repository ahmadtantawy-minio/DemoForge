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


def _tier_remote_bucket_and_prefix(config: dict | None) -> tuple[str, str]:
    """Resolve ``mc admin tier add --bucket`` and optional ``--prefix`` from edge config.

    Legacy: only ``tier_bucket`` was the remote bucket name (no prefix).
    Current: ``cold_bucket`` defaults to ``tiered``; ``tier_prefix`` is the key prefix under that bucket.
    """
    c = config or {}
    default_remote = "tiered"
    has_cold = "cold_bucket" in c
    has_prefix = "tier_prefix" in c
    legacy = str(c.get("tier_bucket") or "").strip()

    if not has_cold and not has_prefix and legacy:
        return legacy, ""

    cold = str(c.get("cold_bucket") or default_remote).strip() or default_remote
    prefix = str(c.get("tier_prefix") or "").strip()
    return cold, prefix


def _tier_prefix_mc_flag(prefix: str) -> str:
    """Shell fragment `` --prefix 'foo/'`` or empty when no prefix (mc examples use a trailing ``/``)."""
    p = prefix.strip()
    if not p:
        return ""
    if not p.endswith("/"):
        p = p + "/"
    return f" --prefix {_safe(p)}"


def _register_remote_tier_then_ilm_rule(
    hot_alias: str,
    source_bucket_q: str,
    tier_name_q: str,
    transition_days_q: str,
    tier_add_command: str,
) -> str:
    """Shell fragment: register remote tier (ignore duplicate), verify tier, then ``mc ilm rule add``.

    Without a registered tier, ``mc ilm rule add --transition-tier`` fails with an invalid storage
    class error. Historically we hid ``mc admin tier add`` stderr and chained with ``;``, so ILM
    ran even when tier registration failed.
    """
    err = (
        "ERROR: Remote tier is not registered on "
        f"{hot_alias}. Ensure mc admin tier add succeeds (endpoint, credentials, bucket). "
        "In Console ILM, use this tier name as the transition target—not AWS-only storage classes."
    )
    return (
        f"{tier_add_command} || "
        f'echo "mc admin tier add exit:$? (ok if tier already exists)"; '
        f"mc ilm tier check {hot_alias} {tier_name_q} >/dev/null 2>&1 || "
        f"{{ echo {shlex.quote(err)} >&2; exit 1; }} && "
        f"mc ilm rule add {hot_alias}/{source_bucket_q} "
        f"--transition-days {transition_days_q} "
        f"--transition-tier {tier_name_q}"
    )


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

    # Use the same alias names as mc-shell init (based on display_name or node id)
    import re as _re
    source_alias = _re.sub(r"[^a-zA-Z0-9_]", "_", source_node.display_name) if source_node.display_name else source_node.id
    target_alias = _re.sub(r"[^a-zA-Z0-9_]", "_", target_node.display_name) if target_node.display_name else target_node.id

    # Anchor mc admin replicate on the site that already has buckets (MinIO rejects the opposite).
    command = (
        f"for i in $(seq 1 15); do mc admin info {source_alias} >/dev/null 2>&1 && mc admin info {target_alias} >/dev/null 2>&1 && break; sleep 2; done && "
        f"NS=$(mc ls {source_alias}/ 2>/dev/null | wc -l | tr -d ' '); case $NS in ''|*[!0-9]*) NS=0;; esac && "
        f"NT=$(mc ls {target_alias}/ 2>/dev/null | wc -l | tr -d ' '); case $NT in ''|*[!0-9]*) NT=0;; esac && "
        f"if [ \"$NT\" -gt \"$NS\" ] 2>/dev/null; then PRIMARY={target_alias}; SECOND={source_alias}; "
        f"elif [ \"$NS\" -gt \"$NT\" ] 2>/dev/null; then PRIMARY={source_alias}; SECOND={target_alias}; "
        f"else PRIMARY={source_alias}; SECOND={target_alias}; fi && "
        f"STATUS=$(mc admin replicate info $PRIMARY 2>&1 | head -1) && "
        f"case \"$STATUS\" in "
        f"*enabled\\ for*) echo \"Site replication already active\"; mc admin replicate info $PRIMARY;; "
        f"*) echo \"Setting up site replication...\"; "
        f"mc ls \"$SECOND/\" 2>/dev/null | while read line; do "
        f"b=\"${{line##* }}\"; b=\"${{b%/}}\"; "
        f"[ -n \"$b\" ] && echo \"Removing $SECOND/$b\" && mc rb --force \"$SECOND/$b\" 2>/dev/null; done; "
        f"mc admin replicate add $PRIMARY $SECOND && "
        f"VERIFY=$(mc admin replicate info $PRIMARY 2>&1 | head -1) && "
        f"case \"$VERIFY\" in *enabled\\ for*) echo \"Site replication verified active\";; "
        f"*) echo \"ERROR: Site replication failed to activate\" >&2; exit 1;; esac;; "
        f"esac"
    )

    return [EdgeInitScript(
        edge_id=edge.id,
        connection_type="site-replication",
        container_name=f"{project_name}-mc-shell",
        command=command,
        order=25,
        description=f"Set up site replication: {source_node.id} <-> {target_node.id}",
        wait_for_healthy=True,
        timeout=120,
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

    cold_bucket, tier_prefix = _tier_remote_bucket_and_prefix(config)
    source_bucket = _safe(config.get("source_bucket", "data"))
    cold_q = _safe(cold_bucket)
    prefix_flag = _tier_prefix_mc_flag(tier_prefix)
    tier_name = _safe(config.get("tier_name", "COLD-TIER"))

    tier_add = (
        f"mc admin tier add minio hot {tier_name} "
        f"--endpoint http://{target_host}:9000 "
        f"--access-key {_safe(target_user)} --secret-key {_safe(target_pass)} "
        f"--bucket {cold_q}{prefix_flag}"
    )
    ilm_tail = _register_remote_tier_then_ilm_rule(
        "hot", source_bucket, tier_name, transition_days, tier_add
    )
    command = (
        f"mc alias set hot http://{source_host}:9000 {_safe(source_user)} {_safe(source_pass)} && "
        f"mc alias set cold http://{target_host}:9000 {_safe(target_user)} {_safe(target_pass)} && "
        f"mc mb hot/{source_bucket} --ignore-existing && "
        f"mc mb cold/{cold_q} --ignore-existing && "
        f"{ilm_tail}"
    )

    return [EdgeInitScript(
        edge_id=edge.id,
        connection_type="tiering",
        container_name=f"{project_name}-{source_node.id}",
        command=command,
        order=30,
        description=f"Set up ILM tiering: {source_node.id}/{config.get('source_bucket', 'data')} -> {target_node.id}/{cold_bucket}"
        + (f" (prefix {tier_prefix})" if tier_prefix else "")
        + f" (after {config.get('transition_days', '30')} days)",
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

@_register("s3")
def _gen_s3(edge: DemoEdge, demo: DemoDefinition, project_name: str) -> list[EdgeInitScript]:
    return []  # Template-driven (Trino/Spark/ClickHouse configure via Jinja2)

@_register("iceberg-catalog")
def _gen_iceberg_catalog(edge: DemoEdge, demo: DemoDefinition, project_name: str) -> list[EdgeInitScript]:
    return []  # Template-driven

@_register("sql-query")
def _gen_sql_query(edge: DemoEdge, demo: DemoDefinition, project_name: str) -> list[EdgeInitScript]:
    return []  # Template-driven

@_register("s3-queue")
def _gen_s3_queue(edge: DemoEdge, demo: DemoDefinition, project_name: str) -> list[EdgeInitScript]:
    return []  # S3Queue setup done via ClickHouse init or on-demand

@_register("spark-submit")
def _gen_spark_submit(edge: DemoEdge, demo: DemoDefinition, project_name: str) -> list[EdgeInitScript]:
    return []  # Template-driven

@_register("hdfs")
def _gen_hdfs(edge: DemoEdge, demo: DemoDefinition, project_name: str) -> list[EdgeInitScript]:
    return []  # Template-driven

@_register("failover")
def _gen_failover(edge: DemoEdge, demo: DemoDefinition, project_name: str) -> list[EdgeInitScript]:
    return []  # Template-driven (NGINX failover config)

@_register("llm-api")
def _gen_llm_api(edge: DemoEdge, demo: DemoDefinition, project_name: str) -> list[EdgeInitScript]:
    return []  # Template-driven (env vars set by compose_generator)

@_register("vector-db")
def _gen_vector_db(edge: DemoEdge, demo: DemoDefinition, project_name: str) -> list[EdgeInitScript]:
    return []  # Template-driven (env vars set by compose_generator)

@_register("mlflow-tracking")
def _gen_mlflow_tracking(edge: DemoEdge, demo: DemoDefinition, project_name: str) -> list[EdgeInitScript]:
    return []  # Template-driven (env vars set by compose_generator)

@_register("labeling-api")
def _gen_labeling_api(edge: DemoEdge, demo: DemoDefinition, project_name: str) -> list[EdgeInitScript]:
    return []  # Template-driven (env vars set by compose_generator)

@_register("vector-db-milvus")
def _gen_vector_db_milvus(edge: DemoEdge, demo: DemoDefinition, project_name: str) -> list[EdgeInitScript]:
    return []  # Template-driven (env vars set by compose_generator)

@_register("etcd")
def _gen_etcd(edge: DemoEdge, demo: DemoDefinition, project_name: str) -> list[EdgeInitScript]:
    return []  # Template-driven (env vars set by compose_generator)

@_register("workflow-api")
def _gen_workflow_api(edge: DemoEdge, demo: DemoDefinition, project_name: str) -> list[EdgeInitScript]:
    return []  # Template-driven (env vars set by compose_generator)

@_register("llm-gateway")
def _gen_llm_gateway(edge: DemoEdge, demo: DemoDefinition, project_name: str) -> list[EdgeInitScript]:
    return []  # Template-driven (env vars set by compose_generator)


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


def _cluster_first_minio_container_name(project_name: str, cluster: DemoCluster) -> str:
    """Docker service name for the first MinIO member (matches compose_generator: …-pool1-node-1)."""
    return f"{project_name}-{cluster.id}-pool1-node-1"


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
        container_name=_cluster_first_minio_container_name(project_name, source_cluster),
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
            container_name=_cluster_first_minio_container_name(project_name, target_cluster),
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

    # Use the same sanitized alias names as compose_generator's mc-shell init
    import re as _re
    source_alias = _re.sub(r"[^a-zA-Z0-9_]", "_", source_cluster.label)
    target_alias = _re.sub(r"[^a-zA-Z0-9_]", "_", target_cluster.label)

    # Collect ALL cluster aliases — mc admin replicate add requires all sites when extending
    all_aliases = [_re.sub(r"[^a-zA-Z0-9_]", "_", c.label) for c in demo.clusters]
    all_aliases_str = " ".join(all_aliases)

    # MinIO requires site-replication API calls to be anchored on the site that already holds
    # buckets ("primary"). Pick PRIMARY by max bucket count; fall back to diagram source alias.
    # `mc admin replicate add` is called with PRIMARY first, then other sites.
    # Never wipe buckets on PRIMARY; only clear joiner sites before a fresh add.
    command = (
        f"ALL_SITES=\"{all_aliases_str}\" && "
        f"for i in $(seq 1 15); do ok=1; for a in $ALL_SITES; do mc admin info \"$a\" >/dev/null 2>&1 || ok=0; done; "
        f'[ "$ok" = 1 ] && break; sleep 2; done && '
        f'PRIMARY=""; MAXB=0; for a in $ALL_SITES; do '
        f'N=$(mc ls "$a/" 2>/dev/null | wc -l); N=$(echo "$N" | tr -d " "); '
        f'case "$N" in ""|*[!0-9]*) N=0;; esac; '
        f'if [ "$N" -gt "$MAXB" ] 2>/dev/null; then MAXB=$N; PRIMARY=$a; fi; '
        f"done && "
        f'if [ -z "$PRIMARY" ] || [ "$MAXB" -eq 0 ] 2>/dev/null; then PRIMARY={source_alias}; fi && '
        f'ORDERED="$PRIMARY"; for a in $ALL_SITES; do [ "$a" = "$PRIMARY" ] && continue; ORDERED="$ORDERED $a"; done && '
        f'STATUS=$(mc admin replicate info "$PRIMARY" 2>&1 | head -1) && '
        f"case \"$STATUS\" in "
        # Already enabled — extend group; do not delete buckets on any site
        f"*enabled\\ for*) "
        f"echo \"Replication active, ensuring all sites in group...\"; "
        f"mc admin replicate add $ORDERED 2>&1 || true; "
        f'echo "Replication group updated"; mc admin replicate info "$PRIMARY";; '
        # Fresh setup — wipe buckets only on non-primary joiners, then add with primary first
        f"*) echo \"Setting up site replication...\"; "
        f'for na in $ALL_SITES; do [ "$na" = "$PRIMARY" ] && continue; '
        f"mc ls \"$na/\" 2>/dev/null | while read line; do "
        f"b=\"${{line##* }}\"; b=\"${{b%/}}\"; "
        f'[ -n "$b" ] && echo "Removing joiner bucket $na/$b" && mc rb --force "$na/$b" 2>/dev/null; done; '
        f"done; "
        f"mc admin replicate add $ORDERED && "
        f'STATUS2=$(mc admin replicate info "$PRIMARY" 2>&1 | head -1) && '
        f"case \"$STATUS2\" in *enabled\\ for*) echo \"Site replication verified active\";; "
        f"*) echo \"ERROR: Site replication failed to activate\" >&2; exit 1;; esac;; "
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

    # Hot-side bucket where ILM rule runs (objects age here before transition).
    source_bucket = _safe(config.get("source_bucket", "data"))
    cold_bucket, tier_prefix = _tier_remote_bucket_and_prefix(config)
    cold_q = _safe(cold_bucket)
    prefix_flag = _tier_prefix_mc_flag(tier_prefix)
    tier_name = _safe(config.get("tier_name", "COLD-TIER"))
    transition_days = _safe(config.get("transition_days", "30"))
    policy_name = _safe(config.get("policy_name", "auto-tier"))

    tier_add = (
        f"mc admin tier add minio hot {tier_name} "
        f"--endpoint http://{target_host}:80 "
        f"--access-key {_safe(target_user)} --secret-key {_safe(target_pass)} "
        f"--bucket {cold_q}{prefix_flag}"
    )
    ilm_tail = _register_remote_tier_then_ilm_rule(
        "hot", source_bucket, tier_name, transition_days, tier_add
    )
    command = (
        f"mc alias set hot http://{source_host}:80 {_safe(source_user)} {_safe(source_pass)} && "
        f"mc alias set cold http://{target_host}:80 {_safe(target_user)} {_safe(target_pass)} && "
        f"mc mb hot/{source_bucket} --ignore-existing && "
        f"mc mb cold/{cold_q} --ignore-existing && "
        f"{ilm_tail}"
    )

    dest_bits = cold_bucket + (f", prefix {tier_prefix}" if tier_prefix else "")
    return [EdgeInitScript(
        edge_id=edge.id,
        connection_type="cluster-tiering",
        container_name=_cluster_first_minio_container_name(project_name, source_cluster),
        command=command,
        order=30,
        description=(
            f"ILM tiering: {source_cluster.label}/{config.get('source_bucket', 'data')} "
            f"-> {target_cluster.label}/{dest_bits} (after {config.get('transition_days', '30')} days)"
        ),
        wait_for_healthy=True,
        timeout=180,
    )]


# ---------------------------------------------------------------------------
# webhook (MinIO → Event Processor): compose injects MINIO_NOTIFY_*; EP runs register-webhook.sh
# ---------------------------------------------------------------------------
@_register("webhook")
def _gen_webhook_event_processor(edge: DemoEdge, demo: DemoDefinition, project_name: str) -> list[EdgeInitScript]:
    return []
