"""Core docker-compose generation from a demo definition."""
import json
import os
import re
import logging
import yaml
from ...models.demo import DemoCluster, DemoDefinition, DemoNode, DemoEdge, NodePosition
from ...registry.loader import get_component
from ...config.license_store import license_store
from ..minio_iam_sim import (
    build_s3_identity_env,
    effective_iam_sim_spec,
    iam_reconcile_expected_counts,
    mc_shell_iam_lines,
    mc_shell_iam_report_shell_finalize,
    mc_shell_iam_report_shell_init,
    write_policy_files_for_spec,
)

from .helpers import (
    HOST_COMPONENTS_DIR,
    HOST_DATA_DIR,
    _mem_bytes,
    _to_host_path,
    _render_templates,
    _minio_notify_webhook_env,
    _event_processor_webhook_and_suffix,
    _event_processor_s3_from_edges,
    _event_processor_s3_fallback_from_webhook_peer,
    _iceberg_browser_env_from_edges,
    apply_default_trino_catalog_env,
    resolve_minio_peer_aistor_catalog_name,
    resolve_trino_aistor_catalog_name,
)

logger = logging.getLogger(__name__)


def _effective_standard_ec_parity(ec_parity: int, total_drives: int) -> int:
    """Parity for ``MINIO_STORAGE_CLASS_STANDARD=EC:N`` that MinIO will accept.

    STANDARD parity must be at most ``total_drives // 2`` (MinIO erasure docs). Demo defaults
    often use ``ec_parity=3`` (EC:3), which is invalid for small pools (e.g. 2 nodes × 2 drives = 4
    drives → max EC:2). That misconfiguration prevents a healthy cluster and breaks init ``mc mb``.

    ``total_drives`` must be the **actual** drive count in the server pool (MinIO erasure set size
    for this deployment), not a UI-only stripe divisor.
    """
    if total_drives < 1:
        return 1
    max_parity = total_drives // 2
    if max_parity < 1:
        return 1
    adjusted = min(ec_parity, max_parity)
    # With default RRS EC:1, STANDARD should be at least EC:2 when the drive count allows it.
    if adjusted < 2 <= max_parity:
        adjusted = 2
    return max(1, min(adjusted, max_parity))


def _minio_parity_failure_env_pair(policy: str) -> tuple[str, str]:
    """Map ``ec_parity_upgrade_policy`` to MinIO-supported env values.

    ``MINIO_ERASURE_PARITY_FAILURE`` accepts ``upgrade`` | ``ignore``.
    Legacy ``MINIO_STORAGE_CLASS_OPTIMIZE`` accepts ``availability`` | ``capacity`` (not upgrade/ignore).
    See: https://min.io/docs/minio/linux/reference/minio-server/settings/storage-class.html
    """
    p = policy if policy in ("upgrade", "ignore") else "upgrade"
    legacy_optimize = "availability" if p == "upgrade" else "capacity"
    return p, legacy_optimize


def _apply_s3_file_browser_iam_simulation(
    env: dict,
    browser_node: DemoNode,
    peer_cluster: DemoCluster | None,
    peer_node: DemoNode | None,
) -> None:
    """Inject IAM-simulation env vars when the MinIO peer defines ``MINIO_IAM_SIM_SPEC`` JSON."""
    root_user = "minioadmin"
    root_pass = "minioadmin"
    spec_raw = ""
    if peer_cluster is not None:
        root_user = peer_cluster.credentials.get("root_user", "minioadmin")
        root_pass = peer_cluster.credentials.get("root_password", "minioadmin")
        spec_raw = (peer_cluster.config or {}).get("MINIO_IAM_SIM_SPEC") or ""
    elif peer_node is not None:
        root_user = peer_node.config.get("MINIO_ROOT_USER", "minioadmin")
        root_pass = peer_node.config.get("MINIO_ROOT_PASSWORD", "minioadmin")
        spec_raw = (peer_node.config or {}).get("MINIO_IAM_SIM_SPEC") or ""

    spec = effective_iam_sim_spec(spec_raw)
    if not spec:
        return
    sim_raw = (browser_node.config or {}).get("S3_SIMULATED_IDENTITY", "")
    sim = sim_raw.strip() if isinstance(sim_raw, str) else (str(sim_raw).strip() if sim_raw is not None else "")
    imap, pub, ak, sk, active_id = build_s3_identity_env(root_user, root_pass, spec, sim)
    env["S3_ROOT_ACCESS_KEY"] = root_user
    env["S3_ROOT_SECRET_KEY"] = root_pass
    if isinstance(spec_raw, str) and str(spec_raw).strip():
        env["MINIO_IAM_SIM_SPEC"] = str(spec_raw).strip()
    else:
        env["MINIO_IAM_SIM_SPEC"] = json.dumps(spec, separators=(",", ":"))
    env["S3_IDENTITY_MAP_JSON"] = imap
    env["S3_BROWSER_IDENTITIES_JSON"] = pub
    env["S3_ACCESS_KEY"] = ak
    env["S3_SECRET_KEY"] = sk
    env["S3_ACTIVE_IDENTITY"] = active_id


def _s3_file_browser_first_minio_peer_for_iam(
    demo: DemoDefinition, browser_node: DemoNode
) -> tuple[DemoCluster | None, DemoNode | None] | None:
    """Resolve the MinIO peer for IAM simulation (same S3-edge rules as env wiring)."""
    s3_edge_types = ("s3", "structured-data", "file-push", "aistor-tables")
    for edge in demo.edges:
        if edge.connection_type not in s3_edge_types:
            continue
        if edge.target == browser_node.id:
            peer_id = edge.source
        elif edge.source == browser_node.id:
            peer_id = edge.target
        else:
            continue
        peer_component = next((n.component for n in demo.nodes if n.id == peer_id), "")
        peer_cluster = next((c for c in demo.clusters if c.id == peer_id), None)
        if peer_cluster:
            peer_component = peer_cluster.component
        is_cluster_lb = peer_id.endswith("-lb") and peer_component == "nginx"
        if is_cluster_lb:
            cluster_id_from_lb = peer_id[:-3]
            lb_cluster = next((c for c in demo.clusters if c.id == cluster_id_from_lb), None)
            if lb_cluster:
                peer_component = lb_cluster.component
        if peer_component != "minio":
            continue
        s3fb_peer = next((n for n in demo.nodes if n.id == peer_id), None) if not peer_cluster else None
        return (peer_cluster, s3fb_peer)
    return None


def _s3_file_browser_peer_has_iam_simulation(demo: DemoDefinition, browser_node: DemoNode) -> bool:
    pair = _s3_file_browser_first_minio_peer_for_iam(demo, browser_node)
    if not pair:
        return False
    peer_cluster, s3fb_peer = pair
    spec_raw = ""
    if peer_cluster is not None:
        spec_raw = (peer_cluster.config or {}).get("MINIO_IAM_SIM_SPEC") or ""
    elif s3fb_peer is not None:
        spec_raw = (s3fb_peer.config or {}).get("MINIO_IAM_SIM_SPEC") or ""
    return bool(effective_iam_sim_spec(spec_raw))


def _escape_compose_dollar_in_command(parts: list[str]) -> list[str]:
    """Compose treats $VAR and ${VAR} as file-level interpolation; use $$ so the container sees shell $vars (e.g. awk $i)."""
    return [p.replace("$", "$$") if isinstance(p, str) else p for p in parts]


_SPARK_START_SCRIPT_NAME = "demoforge-start-standalone.sh"
# Not passed into the container env — only used to set compose mem_limit from the properties panel.
_SPARK_COMPOSE_ONLY_PROPERTY_KEYS = frozenset({"DEMOFORGE_SPARK_CONTAINER_MEM"})


def _apply_spark_properties_to_env(manifest, env: dict[str, str]) -> None:
    """Fill Spark env defaults from manifest.properties when node.config omitted a key."""
    for p in manifest.properties:
        if p.key in _SPARK_COMPOSE_ONLY_PROPERTY_KEYS:
            continue
        cur = env.get(p.key)
        if cur is None or str(cur).strip() == "":
            env[p.key] = str(p.default)


def _spark_container_mem_from_properties(manifest, node_config: dict | None) -> str | None:
    """Docker mem_limit override from properties panel (string like 3g)."""
    cfg = node_config or {}
    raw = (cfg.get("DEMOFORGE_SPARK_CONTAINER_MEM") or "").strip()
    if not raw:
        for p in manifest.properties:
            if p.key == "DEMOFORGE_SPARK_CONTAINER_MEM":
                raw = str(p.default or "").strip()
                break
    return raw or None


def _spark_standalone_compose_command(component_dir: str) -> list[str]:
    """Spark master+worker command for compose.

    Prefer ``/opt/spark/demoforge-start-standalone.sh`` inside the image when present (smaller, single source in image).
    Otherwise run the same logic inline so older ``demoforge/spark-s3a`` tags without that file still start (avoids exit 127).
    """
    path = os.path.join(component_dir, _SPARK_START_SCRIPT_NAME)
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    lines = raw.strip().splitlines()
    if lines and lines[0].startswith("#!"):
        lines = lines[1:]
    body = "\n".join(lines).strip() + "\n"
    script = (
        "if [[ -f /opt/spark/"
        + _SPARK_START_SCRIPT_NAME
        + " ]]; then exec bash /opt/spark/"
        + _SPARK_START_SCRIPT_NAME
        + "; fi\n"
    ) + body
    return ["bash", "-c", script]


# Enforced on every MinIO service so demos stay offline: no MinIO SUBNET registration / call-home licensing prompts.
MINIO_SUBNET_REGISTRATION_SKIP_ENV: dict[str, str] = {
    "MINIO_CALLHOME_ENABLE": "off",
    "MINIO_SUBNET_DISABLE_ALERT": "on",
    "MINIO_SUBNET_RENEWAL": "off",
}
_MINIO_LICENSE_GUARD_ENV = MINIO_SUBNET_REGISTRATION_SKIP_ENV


def _spark_etl_job_tables_enabled_for_minio_peer(demo: DemoDefinition, peer_id: str) -> bool:
    """True when the MinIO cluster or standalone node for this peer has AIStor Tables enabled."""
    cluster_id: str | None = None
    if peer_id.endswith("-lb"):
        cluster_id = peer_id[:-3]
    else:
        cl = next((c for c in demo.clusters if c.id == peer_id), None)
        if cl:
            cluster_id = cl.id
    if cluster_id:
        cl = next((c for c in demo.clusters if c.id == cluster_id), None)
        return bool(cl and getattr(cl, "aistor_tables_enabled", False))
    peer_node = next((n for n in demo.nodes if n.id == peer_id), None)
    if peer_node and peer_node.component == "minio":
        return bool(getattr(peer_node, "aistor_tables_enabled", False))
    return False


def _spark_etl_job_resolve_minio_endpoint_creds(
    demo: DemoDefinition, peer_id: str, project_name: str
) -> tuple[str, str, str] | None:
    """HTTP S3 endpoint URL and root credentials for a MinIO cluster LB or standalone node."""
    cluster: DemoCluster | None = None
    if peer_id.endswith("-lb"):
        cid = peer_id[:-3]
        cluster = next((c for c in demo.clusters if c.id == cid), None)
    if cluster is None:
        cluster = next((c for c in demo.clusters if c.id == peer_id), None)
    if cluster:
        host = f"{project_name}-{cluster.id}-lb"
        ep = f"http://{host}:80"
        ak = cluster.credentials.get("root_user", "minioadmin")
        sk = cluster.credentials.get("root_password", "minioadmin")
        return (ep, ak, sk)
    peer_node = next((n for n in demo.nodes if n.id == peer_id), None)
    if peer_node and peer_node.component == "minio":
        host = f"{project_name}-{peer_id}"
        ep = f"http://{host}:9000"
        ak = peer_node.config.get("MINIO_ROOT_USER", "minioadmin")
        sk = peer_node.config.get("MINIO_ROOT_PASSWORD", "minioadmin")
        return (ep, ak, sk)
    return None


def _rewrite_spark_minio_lb_iceberg_rest_uri(rest_uri: str) -> str:
    """AIStor Tables REST catalog + SigV4: catalog calls must reach MinIO :9000; nginx LB :80 often returns 403 unsigned."""
    if "-lb:80" in rest_uri:
        return rest_uri.replace("-lb:80", "-pool1-node-1:9000")
    return rest_uri


def _spark_etl_job_s3_region_from_peer(demo: DemoDefinition, peer_id: str) -> str:
    """Region string for Iceberg REST SigV4 signing (AwsProperties rest.signing-region)."""
    if peer_id.endswith("-lb"):
        cid = peer_id[:-3]
        cl = next((c for c in demo.clusters if c.id == cid), None)
        if cl:
            return str((cl.config or {}).get("S3_REGION", "") or "").strip() or "us-east-1"
    cl = next((c for c in demo.clusters if c.id == peer_id), None)
    if cl:
        return str((cl.config or {}).get("S3_REGION", "") or "").strip() or "us-east-1"
    nd = next((n for n in demo.nodes if n.id == peer_id), None)
    if nd:
        return str((nd.config or {}).get("S3_REGION", "") or "").strip() or "us-east-1"
    return "us-east-1"


def _spark_etl_job_spark_catalog_name_from_peer(demo: DemoDefinition, peer_id: str) -> str:
    """Spark Iceberg catalog name from MinIO node or cluster config (ICEBERG_SPARK_CATALOG_NAME)."""
    raw = ""
    if peer_id.endswith("-lb"):
        cid = peer_id[:-3]
        cl = next((c for c in demo.clusters if c.id == cid), None)
        if cl:
            raw = str((cl.config or {}).get("ICEBERG_SPARK_CATALOG_NAME", "") or "").strip()
    if not raw:
        cl = next((c for c in demo.clusters if c.id == peer_id), None)
        if cl:
            raw = str((cl.config or {}).get("ICEBERG_SPARK_CATALOG_NAME", "") or "").strip()
    if not raw:
        nd = next((n for n in demo.nodes if n.id == peer_id), None)
        if nd:
            raw = str((nd.config or {}).get("ICEBERG_SPARK_CATALOG_NAME", "") or "").strip()
    return raw or "iceberg"


def _spark_etl_job_iceberg_wh_from_peer(demo: DemoDefinition, peer_id: str) -> str:
    """Default ICEBERG_WAREHOUSE / catalog warehouse string from cluster or node config."""
    if peer_id.endswith("-lb"):
        cid = peer_id[:-3]
        cl = next((c for c in demo.clusters if c.id == cid), None)
        if cl:
            return str((cl.config or {}).get("ICEBERG_WAREHOUSE", "warehouse"))
    cl = next((c for c in demo.clusters if c.id == peer_id), None)
    if cl:
        return str((cl.config or {}).get("ICEBERG_WAREHOUSE", "warehouse"))
    nd = next((n for n in demo.nodes if n.id == peer_id), None)
    if nd:
        return str((nd.config or {}).get("ICEBERG_WAREHOUSE", "warehouse"))
    return "warehouse"


def _inject_spark_etl_job_env(demo: DemoDefinition, node: DemoNode, env: dict, project_name: str) -> None:
    """Wire spark-etl-job container env from diagram edges (Spark master, MinIO S3/cluster LB, Iceberg REST)."""
    cfg = node.config or {}
    env.setdefault("JOB_SCHEDULE", cfg.get("JOB_SCHEDULE", "on_deploy_once"))
    env.setdefault("JOB_INTERVAL_SEC", str(cfg.get("JOB_INTERVAL_SEC", "300")))
    tpl_raw = (cfg.get("JOB_TEMPLATE") or "raw_to_iceberg").strip().lower()
    if tpl_raw == "csv_glob_to_iceberg":
        tpl_raw = "raw_to_iceberg"
    env.setdefault("JOB_TEMPLATE", tpl_raw if tpl_raw == "raw_to_iceberg" else "raw_to_iceberg")
    _ns = str(cfg.get("ICEBERG_TARGET_NAMESPACE", "") or "").strip() or "analytics"
    _tbl = str(cfg.get("ICEBERG_TARGET_TABLE", "") or "").strip() or "events_from_raw"
    env["ICEBERG_TARGET_NAMESPACE"] = _ns
    env["ICEBERG_TARGET_TABLE"] = _tbl
    fmt = (cfg.get("RAW_INPUT_FORMAT") or cfg.get("INPUT_FORMAT") or "csv").strip().lower()
    if fmt not in ("csv", "json"):
        fmt = "csv"
    env["RAW_INPUT_FORMAT"] = fmt
    jm = str(cfg.get("JSON_MULTILINE", "false")).strip().lower()
    env["JSON_MULTILINE"] = "true" if jm in ("1", "true", "yes") else "false"
    input_glob = (cfg.get("INPUT_GLOB") or "").strip()
    if not input_glob:
        input_glob = "*.json" if fmt == "json" else "*.csv"

    for e in demo.edges:
        if e.connection_type != "spark-submit":
            continue
        spark_id = None
        if e.source == node.id:
            spark_id = e.target
        elif e.target == node.id:
            spark_id = e.source
        if spark_id:
            env["SPARK_MASTER_URL"] = f"spark://{project_name}-{spark_id}:7077"
            break

    rest_from_minio: str | None = None
    rest_catalog_peer_id: str | None = None
    spark_minio_edge_types = ("s3", "aistor-tables")
    saw_minio_data_edge = False

    for e in demo.edges:
        if e.connection_type not in spark_minio_edge_types:
            continue
        peer_id = None
        if e.source == node.id:
            peer_id = e.target
        elif e.target == node.id:
            peer_id = e.source
        if not peer_id:
            continue
        resolved = _spark_etl_job_resolve_minio_endpoint_creds(demo, peer_id, project_name)
        if not resolved:
            continue
        saw_minio_data_edge = True
        if not _spark_etl_job_tables_enabled_for_minio_peer(demo, peer_id):
            raise ValueError(
                f"Apache Spark job '{node.id}' edge '{e.id}' references MinIO peer '{peer_id}' without AIStor Tables. "
                "Enable AIStor Tables on that MinIO node or cluster (Raw → Iceberg requires Tables)."
            )
        endpoint, ak, sk = resolved
        cc = e.connection_config or {}
        role_raw = (cc.get("spark_sink_role") or "").lower()
        bucket_role = (cc.get("spark_bucket_role") or "").lower()
        if bucket_role in ("raw", "landing", "input"):
            role = "input"
        elif bucket_role in ("warehouse", "output", "curated"):
            role = "output"
        else:
            role = role_raw or "input"
        if role not in ("input", "output"):
            role = "input"
        if role == "input":
            bucket = (
                str(cfg.get("RAW_LANDING_BUCKET", "") or "").strip()
                or str(cc.get("landing_bucket", "") or "").strip()
                or "raw-logs"
            )
            prefix_raw = str(cfg.get("INPUT_OBJECT_PREFIX", "") or "").strip() or str(
                cc.get("object_prefix", "") or ""
            ).strip()
            prefix = prefix_raw.lstrip("/")
            if prefix and not prefix.endswith("/"):
                prefix = prefix + "/"
            env["INPUT_S3A_URI"] = f"s3a://{bucket}/{prefix}{input_glob}"
            env["S3_ENDPOINT"] = endpoint
            env["S3_ACCESS_KEY"] = ak
            env["S3_SECRET_KEY"] = sk
        elif role == "output":
            wb = (
                str(cfg.get("WAREHOUSE_BUCKET", "") or "").strip()
                or str(cc.get("warehouse_bucket", "") or "").strip()
                or "warehouse"
            )
            env.setdefault("ICEBERG_WAREHOUSE", f"s3://{wb}/")
            env.setdefault("S3_ENDPOINT", endpoint)
            env.setdefault("S3_ACCESS_KEY", ak)
            env.setdefault("S3_SECRET_KEY", sk)
        rest_from_minio = f"{endpoint.rstrip('/')}/_iceberg"
        rest_catalog_peer_id = peer_id
        env["ICEBERG_SPARK_CATALOG_NAME"] = _spark_etl_job_spark_catalog_name_from_peer(demo, peer_id)
        env["ICEBERG_SIGV4"] = "true"
        wh_cat = _spark_etl_job_iceberg_wh_from_peer(demo, peer_id)
        if not str(env.get("ICEBERG_WAREHOUSE") or "").startswith("s3:"):
            env["ICEBERG_WAREHOUSE"] = wh_cat

    if rest_from_minio:
        env["ICEBERG_REST_URI"] = _rewrite_spark_minio_lb_iceberg_rest_uri(rest_from_minio)
        if rest_catalog_peer_id:
            env["ICEBERG_REST_SIGNING_REGION"] = _spark_etl_job_s3_region_from_peer(demo, rest_catalog_peer_id)
        env.setdefault("ICEBERG_REST_SIGNING_NAME", "s3tables")

    if not saw_minio_data_edge:
        raise ValueError(
            f"Apache Spark job '{node.id}' must connect to a MinIO node or MinIO cluster (S3 or AIStor Tables edge) "
            "with AIStor Tables enabled for Raw → Iceberg."
        )
    if not env.get("SPARK_MASTER_URL"):
        raise ValueError(f"Apache Spark job '{node.id}' requires a spark-submit edge to an Apache Spark master.")
    env["RAW_LANDING_BUCKET"] = str(cfg.get("RAW_LANDING_BUCKET", "") or "").strip() or "raw-logs"
    env["WAREHOUSE_BUCKET"] = str(cfg.get("WAREHOUSE_BUCKET", "") or "").strip() or "warehouse"
    env["INPUT_OBJECT_PREFIX"] = str(cfg.get("INPUT_OBJECT_PREFIX", "") or "").strip()

    if not env.get("INPUT_S3A_URI"):
        raise ValueError(
            f"Apache Spark job '{node.id}' needs an input MinIO edge (spark_sink_role or spark_bucket_role = input / raw). "
            "Set RAW_LANDING_BUCKET and INPUT_OBJECT_PREFIX on the job node."
        )
    if not env.get("ICEBERG_REST_URI"):
        raise ValueError(
            f"Apache Spark job '{node.id}' could not resolve ICEBERG_REST_URI from MinIO /_iceberg (check S3 or AIStor Tables edges to MinIO with Tables enabled)."
        )


def _validate_minio_license_env_or_raise(node_id: str, env: dict[str, str]) -> None:
    """Fail-fast if required MinIO license guard env is unavailable/mismatched."""
    missing_or_bad: list[str] = []
    for k, expected in _MINIO_LICENSE_GUARD_ENV.items():
        got = env.get(k)
        if got is None:
            missing_or_bad.append(f"{k}=<missing> (expected {expected})")
            continue
        got_s = str(got).strip().strip("'").strip('"').lower()
        if got_s != expected:
            missing_or_bad.append(f"{k}={got!r} (expected {expected!r})")
    if missing_or_bad:
        detail = "; ".join(missing_or_bad)
        logger.error(
            "[MINIO-LICENSE-BLOCK] Refusing deploy for node '%s': required MinIO "
            "license guard env not validated before license injection: %s",
            node_id,
            detail,
        )
        raise ValueError(
            f"[MINIO-LICENSE-BLOCK] Node '{node_id}' failed MinIO license guard "
            f"env validation: {detail}. Cluster start is blocked."
        )


def generate_compose(demo: DemoDefinition, output_dir: str, components_dir: str = "./components") -> tuple[str, DemoDefinition]:
    """
    Generate a docker-compose.yml for the given demo.
    Returns (path to the generated file, expanded demo copy).
    The original demo object is NOT mutated.
    """
    demo = demo.model_copy(deep=True)
    project_name = f"demoforge-{demo.id}"

    # Build network map from demo.networks list
    network_map = {net.name: f"{project_name}-{net.name}" for net in demo.networks}

    # Cluster coordination dicts (used by both DemoCluster and group-based clusters)
    cluster_commands: dict[str, list[str]] = {}
    cluster_health_override: dict[str, str] = {}
    cluster_credentials: dict[str, dict[str, str]] = {}
    cluster_drives: dict[str, int] = {}

    # --- DemoCluster expansion: inject synthetic nodes & edges ---
    cluster_edge_expansion: dict[str, list[str]] = {}
    for cluster in demo.clusters:
        generated_ids = []
        pools = cluster.get_pools()
        primary_pool = pools[0]
        is_multi_pool = len(pools) > 1

        cred_user = cluster.credentials.get("root_user", "minioadmin")
        cred_pass = cluster.credentials.get("root_password", "minioadmin")
        alias_prefix = f"minio-{cluster.id.replace('-', '')}"

        # Validate minimum drives per pool and collect node IDs
        pool_node_ids: list[list[str]] = []  # pool_node_ids[pool_idx] = [node_id, ...]
        for p_idx, pool in enumerate(pools, start=1):
            drives = pool.drives_per_node
            total_drives = pool.node_count * drives
            if total_drives < 4:
                drives = max(drives, 4 // pool.node_count)
                total_drives = pool.node_count * drives
                if total_drives < 4:
                    raise ValueError(
                        f"Cluster '{cluster.id}' pool {p_idx} needs at least 2 nodes for erasure coding."
                    )
                logger.info(f"Cluster '{cluster.id}' pool {p_idx}: auto-adjusted to {drives} drives/node for EC minimum")
                # Update the pool drives reference for later use
                pool = pool.model_copy(update={"drives_per_node": drives})
                pools[p_idx - 1] = pool

            ids_for_pool = []
            for i in range(1, pool.node_count + 1):
                node_id = f"{cluster.id}-pool{p_idx}-node-{i}"
                ids_for_pool.append(node_id)
                generated_ids.append(node_id)
            pool_node_ids.append(ids_for_pool)

        cluster_edge_expansion[cluster.id] = generated_ids

        p0 = pools[0]
        drives_total = p0.node_count * p0.drives_per_node
        effective_std_ec = _effective_standard_ec_parity(p0.ec_parity, drives_total)
        if effective_std_ec != p0.ec_parity:
            logger.info(
                f"Cluster '{cluster.id}': ec_parity={p0.ec_parity} is incompatible with "
                f"{drives_total} drive(s) in pool 1; "
                f"using MINIO_STORAGE_CLASS_STANDARD=EC:{effective_std_ec} (max EC:{drives_total // 2} for this pool)"
            )

        parity_failure, legacy_storage_class_optimize = _minio_parity_failure_env_pair(
            p0.ec_parity_upgrade_policy
        )
        # Build expansion URLs per pool
        expansion_urls = []
        for p_idx, pool in enumerate(pools, start=1):
            n = pool.node_count
            drives = pool.drives_per_node
            pool_alias = f"{alias_prefix}pool{p_idx}"
            if drives > 1:
                url = f"http://{pool_alias}{{1...{n}}}:9000/data{{1...{drives}}}"
            else:
                url = f"http://{pool_alias}{{1...{n}}}:9000/data"
            expansion_urls.append(url)

        server_cmd = ["server"] + expansion_urls + ["--console-address", ":9001"]

        # Create synthetic DemoNode entries
        for p_idx, (pool, ids_for_pool) in enumerate(zip(pools, pool_node_ids), start=1):
            for i, node_id in enumerate(ids_for_pool):
                node_alias = f"{alias_prefix}pool{p_idx}{i + 1}"
                synthetic_node = DemoNode(
                    id=node_id,
                    component=cluster.component,
                    variant="cluster",
                    position=NodePosition(x=cluster.position.x + (i % 2) * 200,
                                          y=cluster.position.y + (i // 2) * 150),
                    config={
                        "MINIO_ROOT_USER": cred_user,
                        "MINIO_ROOT_PASSWORD": cred_pass,
                        **cluster.config,
                    },
                    display_name=f"Node {i + 1}" if not is_multi_pool else f"P{p_idx} Node {i + 1}",
                )
                synthetic_node.labels = {"_cluster_alias": node_alias}
                demo.nodes.append(synthetic_node)

        # --- Embedded NGINX load balancer for the cluster ---
        lb_node_id = f"{cluster.id}-lb"
        lb_node = DemoNode(
            id=lb_node_id,
            component="nginx",
            variant="",
            position=NodePosition(x=cluster.position.x - 200,
                                  y=cluster.position.y + 50),
            config={"mode": "round-robin"},
            display_name=f"{cluster.label} LB",
        )
        demo.nodes.append(lb_node)

        # Auto-generate load-balance edges from LB to each MinIO node
        for j, gen_id in enumerate(generated_ids):
            demo.edges.append(DemoEdge(
                id=f"{cluster.id}-lb-edge-{j+1}",
                source=lb_node_id,
                target=gen_id,
                connection_type="load-balance",
                network="default",
                connection_config={"algorithm": "least-conn", "backend_port": "9000"},
                auto_configure=True,
                label="",
            ))

        # Expand edges: any edge referencing the cluster ID now routes through the LB
        # - cluster-level types (replication, site-replication, tiering) → LB node
        # - data-flow types (load-balance, metrics, s3, etc.) → LB node (no fan-out)
        original_edges = list(demo.edges)
        new_edges = []
        edges_to_remove = []
        for edge in original_edges:
            is_cluster_level = edge.connection_type.startswith("cluster-")
            # Preserve TRUE original edge ID across multiple cluster expansions
            true_original = edge.connection_config.get("_original_edge_id", edge.id)
            if edge.source == cluster.id:
                edges_to_remove.append(edge.id)
                if is_cluster_level:
                    # Cluster-level operation → route to LB
                    new_edges.append(DemoEdge(
                        id=f"{edge.id}-cluster",
                        source=lb_node_id,
                        target=edge.target,
                        connection_type=edge.connection_type,
                        network=edge.network,
                        connection_config={
                            **edge.connection_config,
                            "_source_cluster_id": cluster.id,
                            "_original_edge_id": true_original,
                        },
                        auto_configure=edge.auto_configure,
                        label=edge.label,
                    ))
                else:
                    # Data-flow outbound: route from LB (e.g. metrics from cluster)
                    # For metrics, use node-1 since LB doesn't expose metrics
                    if edge.connection_type == "metrics":
                        new_edges.append(DemoEdge(
                            id=f"{edge.id}-metrics",
                            source=generated_ids[0],
                            target=edge.target,
                            connection_type=edge.connection_type,
                            network=edge.network,
                            connection_config={
                                **edge.connection_config,
                                "_original_edge_id": true_original,
                            },
                            auto_configure=edge.auto_configure,
                            label=edge.label,
                        ))
                    else:
                        new_edges.append(DemoEdge(
                            id=f"{edge.id}-lb",
                            source=lb_node_id,
                            target=edge.target,
                            connection_type=edge.connection_type,
                            network=edge.network,
                            connection_config={
                                **edge.connection_config,
                                "_original_edge_id": true_original,
                            },
                            auto_configure=edge.auto_configure,
                            label=edge.label,
                        ))
            elif edge.target == cluster.id:
                edges_to_remove.append(edge.id)
                if is_cluster_level:
                    # Cluster-level operation → route to LB
                    new_edges.append(DemoEdge(
                        id=f"{edge.id}-cluster",
                        source=edge.source,
                        target=lb_node_id,
                        connection_type=edge.connection_type,
                        network=edge.network,
                        connection_config={
                            **edge.connection_config,
                            "_target_cluster_id": cluster.id,
                            "_original_edge_id": true_original,
                        },
                        auto_configure=edge.auto_configure,
                        label=edge.label,
                    ))
                else:
                    # Data-flow inbound: route to LB (LB fans out to nodes internally)
                    new_edges.append(DemoEdge(
                        id=f"{edge.id}-lb",
                        source=edge.source,
                        target=lb_node_id,
                        connection_type=edge.connection_type,
                        network=edge.network,
                        connection_config={
                            **edge.connection_config,
                            "_original_edge_id": true_original,
                        },
                        auto_configure=edge.auto_configure,
                        label=edge.label,
                    ))
        demo.edges = [e for e in demo.edges if e.id not in edges_to_remove] + new_edges

        # Register cluster commands
        for p_idx, (pool, ids_for_pool) in enumerate(zip(pools, pool_node_ids), start=1):
            for node_id in ids_for_pool:
                cluster_commands[node_id] = server_cmd
                cluster_health_override[node_id] = "/minio/health/cluster"
                cluster_credentials[node_id] = {
                    "MINIO_ROOT_USER": cred_user,
                    "MINIO_ROOT_PASSWORD": cred_pass,
                    "MINIO_STORAGE_CLASS_STANDARD": f"EC:{effective_std_ec}",
                    "MINIO_STORAGE_CLASS_RRS": "EC:1",
                    "MINIO_ERASURE_PARITY_FAILURE": parity_failure,
                    "MINIO_STORAGE_CLASS_OPTIMIZE": legacy_storage_class_optimize,
                }
                cluster_drives[node_id] = pool.drives_per_node

    # Cluster coordination: build coordinated commands for cluster group members
    for group in demo.groups:
        if group.mode != "cluster":
            continue
        member_nodes = [n for n in demo.nodes if n.group_id == group.id]
        if len(member_nodes) < 2:
            continue

        # Build MinIO distributed server command with explicit URLs
        drives = int(group.cluster_config.get("drives_per_node", 1))
        peer_urls = []
        for n in member_nodes:
            svc_name = f"{project_name}-{n.id}"
            if drives > 1:
                peer_urls.append(f"http://{svc_name}:9000/data{{1...{drives}}}")
            else:
                peer_urls.append(f"http://{svc_name}:9000/data")

        server_cmd = ["server"] + peer_urls + ["--console-address", ":9001"]

        # Get cluster credentials from group config or first node
        cluster_user = group.cluster_config.get("root_user", "minioadmin")
        cluster_pass = group.cluster_config.get("root_password", "minioadmin")

        for n in member_nodes:
            cluster_commands[n.id] = server_cmd
            cluster_health_override[n.id] = "/minio/health/cluster"
            cluster_credentials[n.id] = {
                "MINIO_ROOT_USER": cluster_user,
                "MINIO_ROOT_PASSWORD": cluster_pass,
            }
            cluster_drives[n.id] = drives

    services = {}
    compose_volumes = {}
    for node in demo.nodes:
        manifest = get_component(node.component)
        if manifest is None:
            raise ValueError(f"Unknown component: {node.component}")

        # Virtual components are reference-only nodes — no Docker service generated
        if manifest.virtual:
            continue

        component_dir = os.path.join(components_dir, node.component)
        service_name = node.id
        container_name = f"{project_name}-{node.id}"

        # Check cluster coordination first
        if node.id in cluster_commands:
            command = cluster_commands[node.id]
        else:
            variant = manifest.variants.get(node.variant)
            command = variant.command if variant and variant.command else manifest.command

        # Spark: always inject resilient startup (manifest `command` ignored). Uses image script when present,
        # else inlines components/spark/demoforge-start-standalone.sh so stale image tags do not exit 127.
        if node.component == "spark":
            command = _spark_standalone_compose_command(component_dir)

        # Merge environment: manifest defaults → node overrides
        env = {}
        for key, val in manifest.environment.items():
            # Resolve ${VAR:-default} patterns using secrets defaults
            resolved = val
            for secret in manifest.secrets:
                placeholder = f"${{{secret.key}:-{secret.default}}}"
                if placeholder in val and secret.default:
                    resolved = secret.default
                placeholder2 = f"${{{secret.key}}}"
                if placeholder2 in val and secret.default:
                    resolved = secret.default
            env[key] = resolved

        node_edition = node.config.get("MINIO_EDITION", "ce")
        is_cluster_node = node.variant == "cluster"
        if node.id in cluster_credentials:
            env.update(cluster_credentials[node.id])

        env.update(node.config)

        # Synthetic cluster nodes merge ``DemoCluster.config`` into ``node.config``. Any
        # ``MINIO_STORAGE_CLASS_*`` / parity keys there would otherwise override the values
        # computed above (including fixes for MinIO-valid ``MINIO_STORAGE_CLASS_OPTIMIZE``).
        if node.id in cluster_credentials:
            env.update(cluster_credentials[node.id])

        if node.component == "spark":
            _apply_spark_properties_to_env(manifest, env)
            env.pop("DEMOFORGE_SPARK_CONTAINER_MEM", None)

        # Force MinIO license guard env on every MinIO node so cluster-wide behavior
        # stays consistent across standalone and distributed topologies.
        if node.component == "minio":
            env.update(_MINIO_LICENSE_GUARD_ENV)

        if node.component == "spark-etl-job":
            _inject_spark_etl_job_env(demo, node, env, project_name)

        # Inject license keys only after validating guard env.
        for lic_req in manifest.license_requirements:
            # Skip edition-gated licenses that don't match
            if lic_req.edition and lic_req.edition != node_edition:
                continue
            # For MinIO: use aistor-free for single nodes, enterprise for clusters
            if node.component == "minio" and node_edition == "aistor":
                if is_cluster_node and lic_req.license_id == "minio-aistor-free":
                    continue  # Clusters use enterprise license
                if not is_cluster_node and lic_req.license_id == "minio-enterprise":
                    continue  # Single nodes use aistor-free license
            entry = license_store.get(lic_req.license_id)
            if entry and lic_req.injection_type == "env_var" and lic_req.env_var:
                if node.component == "minio":
                    _validate_minio_license_env_or_raise(node.id, env)
                env[lic_req.env_var] = entry.value
            elif entry and lic_req.injection_type == "file_mount" and lic_req.mount_path:
                if node.component == "minio":
                    _validate_minio_license_env_or_raise(node.id, env)
                lic_file = os.path.join(output_dir, project_name, node.id, "license.key")
                os.makedirs(os.path.dirname(lic_file), exist_ok=True)
                with open(lic_file, "w") as f:
                    f.write(entry.value)
                # Volume added later after service_volumes is built

        # Auto-resolve S3 endpoint from s3/structured-data/file-push edges
        s3_edge_types = ("s3", "structured-data", "file-push", "aistor-tables")
        for edge in demo.edges:
            # event-processor: S3/Iceberg/credentials come from the dedicated block (external-system parity)
            if node.component == "event-processor":
                break
            if edge.connection_type not in s3_edge_types:
                continue
            # Determine the MinIO peer: if this node is target, peer is source; if source, peer is target
            if edge.target == node.id:
                peer_id = edge.source
            elif edge.source == node.id:
                peer_id = edge.target
            elif (
                node.component == "inference-sim"
                and getattr(node, "group_id", None)
                and (edge.source == node.group_id or edge.target == node.group_id)
            ):
                # Diagram edge from visual group (e.g. GPU server) → MinIO; apply to inference-sim in that group
                peer_id = edge.target if edge.source == node.group_id else edge.source
            else:
                continue
            # Check nodes first, then clusters, then cluster LBs
            peer_component = next((n.component for n in demo.nodes if n.id == peer_id), "")
            peer_cluster = next((c for c in demo.clusters if c.id == peer_id), None)
            if peer_cluster:
                peer_component = peer_cluster.component
            # Also detect cluster LB nodes (e.g. minio-cluster-3-lb → nginx, but backed by MinIO cluster)
            is_cluster_lb = peer_id.endswith("-lb") and peer_component == "nginx"
            if is_cluster_lb:
                cluster_id_from_lb = peer_id[:-3]  # strip "-lb"
                lb_cluster = next((c for c in demo.clusters if c.id == cluster_id_from_lb), None)
                if lb_cluster:
                    peer_component = lb_cluster.component
            if peer_component != "minio":
                continue
            # Use the full container name (project_name-peer_id) for Docker DNS
            if peer_cluster:
                s3_service_name = f"{project_name}-{peer_id}-lb"
                s3_port = 80
            elif is_cluster_lb:
                s3_service_name = f"{project_name}-{peer_id}"
                s3_port = 80
            else:
                s3_service_name = f"{project_name}-{peer_id}"
                s3_port = 9000
            s3_endpoint_host = f"{s3_service_name}:{s3_port}"
            s3_endpoint_url = f"http://{s3_service_name}:{s3_port}"
            # Inject S3 endpoint for known env var patterns (some need http:// prefix)
            if "CATALOG_S3_ENDPOINT" in env:
                env["CATALOG_S3_ENDPOINT"] = s3_endpoint_url
            if "S3_ENDPOINT" in env:
                env["S3_ENDPOINT"] = s3_endpoint_url

            # S3 File Browser: plain S3 only — always use MinIO root creds from the peer (no AIStor Tables / Iceberg).
            if node.component == "s3-file-browser":
                s3fb_peer = next((n for n in demo.nodes if n.id == peer_id), None) if not peer_cluster else None
                if peer_cluster:
                    env["S3_ACCESS_KEY"] = peer_cluster.credentials.get("root_user", "minioadmin")
                    env["S3_SECRET_KEY"] = peer_cluster.credentials.get("root_password", "minioadmin")
                elif s3fb_peer and s3fb_peer.component == "minio":
                    env["S3_ACCESS_KEY"] = s3fb_peer.config.get("MINIO_ROOT_USER", "minioadmin")
                    env["S3_SECRET_KEY"] = s3fb_peer.config.get("MINIO_ROOT_PASSWORD", "minioadmin")
                _apply_s3_file_browser_iam_simulation(env, node, peer_cluster, s3fb_peer)

            # Forward MinIO endpoint + credentials for inference-sim (tier_role based)
            if node.component == "inference-sim":
                edge_cfg = edge.connection_config or {}
                tier_role = edge_cfg.get("tier_role", "g35-cmx")
                if tier_role == "g35-cmx":
                    env["MINIO_ENDPOINT_G35"] = s3_endpoint_url
                elif tier_role == "g4-archive":
                    env["MINIO_ENDPOINT_G4"] = s3_endpoint_url
                # Resolve credentials from node or cluster
                if peer_cluster:
                    env["MINIO_ACCESS_KEY"] = peer_cluster.credentials.get("root_user", "minioadmin")
                    env["MINIO_SECRET_KEY"] = peer_cluster.credentials.get("root_password", "minioadmin")
                else:
                    peer_node_obj = next((n for n in demo.nodes if n.id == peer_id), None)
                    if peer_node_obj:
                        env["MINIO_ACCESS_KEY"] = peer_node_obj.config.get("MINIO_ROOT_USER", "minioadmin")
                        env["MINIO_SECRET_KEY"] = peer_node_obj.config.get("MINIO_ROOT_PASSWORD", "minioadmin")

            # Forward MinIO credentials for rag-app
            if node.component == "rag-app":
                peer_node_obj = next((n for n in demo.nodes if n.id == peer_id), None)
                if peer_node_obj:
                    env["MINIO_ACCESS_KEY"] = peer_node_obj.config.get("MINIO_ROOT_USER", "minioadmin")
                    env["MINIO_SECRET_KEY"] = peer_node_obj.config.get("MINIO_ROOT_PASSWORD", "minioadmin")
                env["MINIO_ENDPOINT"] = s3_endpoint_url

            # Forward MinIO credentials for MLflow and ML Trainer
            if node.component in ("mlflow", "ml-trainer"):
                peer_node_obj = next((n for n in demo.nodes if n.id == peer_id), None)
                if peer_node_obj:
                    env["AWS_ACCESS_KEY_ID"] = peer_node_obj.config.get("MINIO_ROOT_USER", "minioadmin")
                    env["AWS_SECRET_ACCESS_KEY"] = peer_node_obj.config.get("MINIO_ROOT_PASSWORD", "minioadmin")
                env["MLFLOW_S3_ENDPOINT_URL"] = s3_endpoint_url

            # Apply edge config to environment (e.g. target_bucket, format, rate)
            edge_cfg = edge.connection_config or {}
            if edge_cfg:
                _edge_env_map = {
                    "target_bucket": "S3_BUCKET",
                    "bucket": "S3_BUCKET",
                    "format": "DG_FORMAT",
                    "rows_per_file": "DG_FILE_SIZE_ROWS",
                    "rate": "DG_RATE",
                    "scenario": "DG_SCENARIO",
                    "rate_profile": "DG_RATE_PROFILE",
                    "documents_bucket": "DOCUMENTS_BUCKET",
                    "audit_bucket": "AUDIT_BUCKET",
                    "snapshot_bucket": "QDRANT_SNAPSHOT_BUCKET",
                    "embedding_model": "EMBEDDING_MODEL",
                    "chat_model": "CHAT_MODEL",
                    "artifact_bucket": "MLFLOW_ARTIFACTS_BUCKET",
                    "training_bucket": "TRAINING_BUCKET",
                    "source_bucket": "LABELING_SOURCE_BUCKET",
                    "output_bucket": "LABELING_OUTPUT_BUCKET",
                    "milvus_bucket": "MINIO_BUCKET_NAME",
                    "dag_bucket": "AIRFLOW_DAG_BUCKET",
                    "log_bucket": "AIRFLOW_LOG_BUCKET",
                    "sink_bucket": "S3_BUCKET",
                    "sink_format": "S3_SINK_FORMAT",
                    "flush_size": "S3_FLUSH_SIZE",
                    "source_name": "DREMIO_SOURCE_NAME",
                    "topic": "KAFKA_TOPIC",
                    "catalog_name": "TRINO_CATALOG",
                    "namespace": "TRINO_SCHEMA",
                }
                for cfg_key, env_key in _edge_env_map.items():
                    if cfg_key in edge_cfg and edge_cfg[cfg_key]:
                        env[env_key] = str(edge_cfg[cfg_key])

            # inference-sim needs multiple S3 edges (G3.5 + G4 tiers)
            if node.component != "inference-sim":
                break  # Use first s3 edge for other components

        # Auto-inject ICEBERG_CATALOG_URI for data generators
        # Strategy: follow the generator's edge to its target MinIO cluster, then:
        #   - If the cluster has aistor_tables_enabled → use cluster LB's /_iceberg endpoint
        #   - Otherwise → find iceberg-rest node connected to that cluster
        if node.component in ("data-generator", "external-system") and "ICEBERG_CATALOG_URI" not in env:
            # Find this generator's target cluster/node via edges
            target_cluster_id = None
            target_lb_id = None
            target_standalone_id = None
            for edge in demo.edges:
                if edge.source == node.id and edge.connection_type in s3_edge_types:
                    target_id = edge.target
                    # Could be a cluster LB (after expansion) or cluster ID
                    if target_id.endswith("-lb"):
                        target_lb_id = target_id
                        target_cluster_id = target_id[:-3]
                    else:
                        # Check if it's a cluster
                        tc = next((c for c in demo.clusters if c.id == target_id), None)
                        if tc:
                            target_cluster_id = tc.id
                            target_lb_id = f"{tc.id}-lb"
                        else:
                            target_standalone_id = target_id
                    break

            # Handle standalone AIStor node (single minio node with MINIO_EDITION=aistor)
            if not target_cluster_id and target_standalone_id:
                standalone = next((n for n in demo.nodes if n.id == target_standalone_id), None)
                if standalone and standalone.component == "minio":
                    node_cfg = standalone.config or {}
                    if node_cfg.get("MINIO_EDITION", "ce") == "aistor":
                        env["ICEBERG_CATALOG_URI"] = f"http://{project_name}-{standalone.id}:9000/_iceberg"
                        env["ICEBERG_WAREHOUSE"] = node_cfg.get("ICEBERG_WAREHOUSE", "analytics")
                        env["ICEBERG_SIGV4"] = "true"
                        env["ICEBERG_CATALOG_NAME"] = resolve_minio_peer_aistor_catalog_name(
                            demo, standalone.id
                        )

            if target_cluster_id:
                target_cluster = next((c for c in demo.clusters if c.id == target_cluster_id), None)
                if target_cluster and getattr(target_cluster, 'aistor_tables_enabled', False):
                    # AIStor Tables: use the cluster's /_iceberg endpoint
                    env["ICEBERG_CATALOG_URI"] = f"http://{project_name}-{target_lb_id or target_cluster_id + '-lb'}:80/_iceberg"
                    env["ICEBERG_WAREHOUSE"] = target_cluster.config.get("ICEBERG_WAREHOUSE", "analytics")
                    env["ICEBERG_SIGV4"] = "true"
                    env["ICEBERG_CATALOG_NAME"] = resolve_minio_peer_aistor_catalog_name(
                        demo, target_cluster_id
                    )
                else:
                    # External Iceberg REST: find iceberg-rest connected to this cluster
                    for edge in demo.edges:
                        if edge.connection_type == "s3":
                            # iceberg-rest → cluster or cluster → iceberg-rest
                            peer = None
                            if edge.source == target_cluster_id or (target_lb_id and edge.source == target_lb_id):
                                peer = edge.target
                            elif edge.target == target_cluster_id or (target_lb_id and edge.target == target_lb_id):
                                peer = edge.source
                            if peer:
                                peer_node = next((n for n in demo.nodes if n.id == peer and n.component == "iceberg-rest"), None)
                                if peer_node:
                                    env["ICEBERG_CATALOG_URI"] = f"http://{project_name}-{peer_node.id}:8181"
                                    break
                    else:
                        # Fallback: find any iceberg-rest in the demo
                        iceberg_node = next((n for n in demo.nodes if n.component == "iceberg-rest"), None)
                        if iceberg_node:
                            env["ICEBERG_CATALOG_URI"] = f"http://{project_name}-{iceberg_node.id}:8181"

        # Auto-inject TRINO_HOST for data generators / external-system (DG scenario mode uses Trino writer too)
        if node.component in ("data-generator", "external-system"):
            trino_node = next((n for n in demo.nodes if n.component == "trino"), None)
            if trino_node:
                if "TRINO_HOST" not in env:
                    env["TRINO_HOST"] = f"{project_name}-{trino_node.id}:8080"
                apply_default_trino_catalog_env(env, demo, trino_node.id)

        # external-system: inject env vars from connected edges
        if node.component == "external-system":
            # Inject ES_SCENARIO and ES_STARTUP_DELAY from node config
            if "ES_SCENARIO" not in env and node.config.get("ES_SCENARIO"):
                env["ES_SCENARIO"] = node.config["ES_SCENARIO"]
            if "ES_STARTUP_DELAY" not in env and node.config.get("ES_STARTUP_DELAY"):
                env["ES_STARTUP_DELAY"] = node.config["ES_STARTUP_DELAY"]
            env["ES_SINK_MODE"] = (node.config or {}).get("ES_SINK_MODE") or "files_and_iceberg"

            # Inject S3/AIStor env vars from s3 or aistor-tables edges to a MinIO node
            es_s3_edge_types = ("s3", "aistor-tables")
            for edge in demo.edges:
                if edge.connection_type not in es_s3_edge_types:
                    continue
                if edge.source == node.id:
                    peer_id = edge.target
                elif edge.target == node.id:
                    peer_id = edge.source
                else:
                    continue
                # Resolve peer as cluster or standalone node
                peer_cluster = next((c for c in demo.clusters if c.id == peer_id), None)
                peer_node_obj = next((n for n in demo.nodes if n.id == peer_id), None)
                is_cluster_lb = peer_id.endswith("-lb")
                if is_cluster_lb:
                    cluster_id_from_lb = peer_id[:-3]
                    peer_cluster = next((c for c in demo.clusters if c.id == cluster_id_from_lb), None)

                if peer_cluster:
                    svc = f"{project_name}-{peer_cluster.id}-lb"
                    port = 80
                elif is_cluster_lb:
                    svc = f"{project_name}-{peer_id}"
                    port = 80
                elif peer_node_obj and peer_node_obj.component == "minio":
                    svc = f"{project_name}-{peer_id}"
                    port = 9000
                else:
                    continue

                env["S3_ENDPOINT"] = f"http://{svc}:{port}"
                if peer_cluster:
                    env["S3_ACCESS_KEY"] = peer_cluster.credentials.get("root_user", "minioadmin")
                    env["S3_SECRET_KEY"] = peer_cluster.credentials.get("root_password", "minioadmin")
                elif peer_node_obj:
                    env["S3_ACCESS_KEY"] = peer_node_obj.config.get("MINIO_ROOT_USER", "minioadmin")
                    env["S3_SECRET_KEY"] = peer_node_obj.config.get("MINIO_ROOT_PASSWORD", "minioadmin")

                # aistor-tables edge: inject Iceberg catalog URI + warehouse
                if edge.connection_type == "aistor-tables":
                    env["ICEBERG_CATALOG_URI"] = f"http://{svc}:{port}/_iceberg"
                    env["ICEBERG_SIGV4"] = "true"
                    if peer_cluster:
                        env["ICEBERG_WAREHOUSE"] = peer_cluster.config.get("ICEBERG_WAREHOUSE", "analytics")
                    elif peer_node_obj:
                        env["ICEBERG_WAREHOUSE"] = (peer_node_obj.config or {}).get("ICEBERG_WAREHOUSE", "analytics")
                elif "ICEBERG_CATALOG_URI" not in env or not env["ICEBERG_CATALOG_URI"]:
                    # s3 edge to AIStor standalone node: check edition
                    if peer_node_obj:
                        node_cfg = peer_node_obj.config or {}
                        if node_cfg.get("MINIO_EDITION", "ce") == "aistor":
                            env["ICEBERG_CATALOG_URI"] = f"http://{svc}:{port}/_iceberg"
                            env["ICEBERG_SIGV4"] = "true"
                            env["ICEBERG_WAREHOUSE"] = node_cfg.get("ICEBERG_WAREHOUSE", "analytics")
                    elif peer_cluster and getattr(peer_cluster, "aistor_tables_enabled", False):
                        env["ICEBERG_CATALOG_URI"] = f"http://{svc}:{port}/_iceberg"
                        env["ICEBERG_SIGV4"] = "true"
                        env["ICEBERG_WAREHOUSE"] = peer_cluster.config.get("ICEBERG_WAREHOUSE", "analytics")
                if env.get("ICEBERG_SIGV4") == "true":
                    env["ICEBERG_CATALOG_NAME"] = resolve_minio_peer_aistor_catalog_name(demo, peer_id)
                break

            # Inject TRINO_HOST and TRINO_CATALOG if a Trino node exists
            trino_node = next((n for n in demo.nodes if n.component == "trino"), None)
            if trino_node:
                if "TRINO_HOST" not in env or not env["TRINO_HOST"]:
                    env["TRINO_HOST"] = f"{project_name}-{trino_node.id}:8080"
                apply_default_trino_catalog_env(env, demo, trino_node.id)

            # Inject METABASE_URL from dashboard-provision edges
            for edge in demo.edges:
                if edge.connection_type != "dashboard-provision":
                    continue
                if edge.source == node.id:
                    peer_id = edge.target
                elif edge.target == node.id:
                    peer_id = edge.source
                else:
                    continue
                peer_node_obj = next((n for n in demo.nodes if n.id == peer_id), None)
                if peer_node_obj and peer_node_obj.component == "metabase":
                    env["METABASE_URL"] = f"http://{project_name}-{peer_id}:3000"
                break

            # Raw / Data Generator output format: prefer node (ES_DG_FORMAT / DG_FORMAT) over legacy edge format.
            nc = node.config or {}
            fmt_override = (nc.get("ES_DG_FORMAT") or nc.get("DG_FORMAT") or "").strip().lower()
            if fmt_override in ("csv", "json", "parquet"):
                env["DG_FORMAT"] = fmt_override
                env["ES_DG_FORMAT"] = fmt_override

        # event-processor: webhook edge config + S3/Iceberg from outgoing edges (external-system parity)
        if node.component == "event-processor":
            _event_processor_webhook_and_suffix(demo, node, env, container_name)
            _event_processor_s3_from_edges(demo, node, env, project_name)
            _event_processor_s3_fallback_from_webhook_peer(demo, node, env, project_name)
            # Trino INSERT for configurable processing pipelines (e.g. malware_metadata)
            trino_node = next((n for n in demo.nodes if n.component == "trino"), None)
            if trino_node:
                if "TRINO_HOST" not in env or not env["TRINO_HOST"]:
                    env["TRINO_HOST"] = f"{project_name}-{trino_node.id}:8080"
                apply_default_trino_catalog_env(env, demo, trino_node.id)

        if node.component == "iceberg-browser":
            _iceberg_browser_env_from_edges(demo, node, env, project_name)

        # Auto-resolve LLM API endpoint from llm-api edges
        for edge in demo.edges:
            if edge.connection_type != "llm-api":
                continue
            if edge.target == node.id:
                peer_id = edge.source
            elif edge.source == node.id:
                peer_id = edge.target
            else:
                continue
            peer_node = next((n for n in demo.nodes if n.id == peer_id), None)
            if not peer_node:
                continue
            peer_manifest = get_component(peer_node.component)
            if peer_manifest:
                llm_port = next((p.container for p in peer_manifest.ports if p.name == "api"), 11434)
                env["OLLAMA_ENDPOINT"] = f"http://{project_name}-{peer_id}:{llm_port}"
            edge_cfg = edge.connection_config or {}
            if edge_cfg.get("embedding_model"):
                env["EMBEDDING_MODEL"] = edge_cfg["embedding_model"]
            if edge_cfg.get("chat_model"):
                env["CHAT_MODEL"] = edge_cfg["chat_model"]
            break

        # Auto-resolve inference API endpoint from inference-api edges
        for edge in demo.edges:
            if edge.connection_type != "inference-api":
                continue
            if edge.source == node.id:
                peer_id = edge.target
            elif edge.target == node.id:
                peer_id = edge.source
            else:
                continue
            peer_node = next((n for n in demo.nodes if n.id == peer_id), None)
            if not peer_node:
                continue
            peer_manifest = get_component(peer_node.component)
            if peer_manifest:
                api_port = next((p.container for p in peer_manifest.ports if p.name == "web"), 8095)
                env["INFERENCE_ENDPOINT"] = f"{project_name}-{peer_id}:{api_port}"
            break

        # Auto-resolve vector DB endpoint from vector-db edges
        for edge in demo.edges:
            if edge.connection_type != "vector-db":
                continue
            if edge.target == node.id:
                peer_id = edge.source
            elif edge.source == node.id:
                peer_id = edge.target
            else:
                continue
            peer_node = next((n for n in demo.nodes if n.id == peer_id), None)
            if not peer_node:
                continue
            peer_manifest = get_component(peer_node.component)
            if peer_manifest:
                vdb_port = next((p.container for p in peer_manifest.ports if p.name == "http"), 6333)
                env["QDRANT_ENDPOINT"] = f"http://{project_name}-{peer_id}:{vdb_port}"
            break

        # Auto-resolve MLflow tracking URI from mlflow-tracking edges
        for edge in demo.edges:
            if edge.connection_type != "mlflow-tracking":
                continue
            if edge.target == node.id:
                peer_id = edge.source
            elif edge.source == node.id:
                peer_id = edge.target
            else:
                continue
            peer_node = next((n for n in demo.nodes if n.id == peer_id), None)
            if not peer_node:
                continue
            peer_manifest = get_component(peer_node.component)
            if peer_manifest:
                mlflow_port = next((p.container for p in peer_manifest.ports if p.name == "web"), 5000)
                env["MLFLOW_TRACKING_URI"] = f"http://{project_name}-{peer_id}:{mlflow_port}"
                # MLflow client needs S3 endpoint for artifact access
                env["MLFLOW_S3_ENDPOINT_URL"] = env.get("MINIO_ENDPOINT", env.get("S3_ENDPOINT", ""))
            break

        # Auto-resolve Milvus S3 storage from s3 edges (special handling)
        if node.component == "milvus":
            for edge in demo.edges:
                if edge.connection_type != "s3":
                    continue
                if edge.source == node.id:
                    peer_id = edge.target
                elif edge.target == node.id:
                    peer_id = edge.source
                else:
                    continue
                peer_node = next((n for n in demo.nodes if n.id == peer_id), None)
                if peer_node and peer_node.component == "minio":
                    env["MINIO_ADDRESS"] = f"{project_name}-{peer_id}"
                    env["MINIO_PORT"] = "9000"
                    edge_cfg = edge.connection_config or {}
                    env["MINIO_BUCKET_NAME"] = edge_cfg.get("milvus_bucket", "milvus-data")
                    break

        # Auto-resolve etcd endpoint from etcd edges
        for edge in demo.edges:
            if edge.connection_type != "etcd":
                continue
            if edge.target == node.id:
                peer_id = edge.source
            elif edge.source == node.id:
                peer_id = edge.target
            else:
                continue
            peer_node = next((n for n in demo.nodes if n.id == peer_id), None)
            if not peer_node:
                continue
            env["ETCD_ENDPOINTS"] = f"{project_name}-{peer_id}:2379"
            break

        # Auto-resolve Label Studio URL from labeling-api edges
        for edge in demo.edges:
            if edge.connection_type != "labeling-api":
                continue
            if edge.target == node.id:
                peer_id = edge.source
            elif edge.source == node.id:
                peer_id = edge.target
            else:
                continue
            peer_node = next((n for n in demo.nodes if n.id == peer_id), None)
            if not peer_node:
                continue
            peer_manifest = get_component(peer_node.component)
            if peer_manifest:
                ls_port = next((p.container for p in peer_manifest.ports if p.name == "web"), 8080)
                env["LABEL_STUDIO_URL"] = f"http://{project_name}-{peer_id}:{ls_port}"
            break

        # Auto-resolve Airflow URL from workflow-api edges
        for edge in demo.edges:
            if edge.connection_type != "workflow-api":
                continue
            if edge.target == node.id:
                peer_id = edge.source
            elif edge.source == node.id:
                peer_id = edge.target
            else:
                continue
            peer_node = next((n for n in demo.nodes if n.id == peer_id), None)
            if not peer_node:
                continue
            peer_manifest = get_component(peer_node.component)
            if peer_manifest:
                airflow_port = next((p.container for p in peer_manifest.ports if p.name == "web"), 8080)
                env["AIRFLOW_API_URL"] = f"http://{project_name}-{peer_id}:{airflow_port}"
            break

        # Auto-resolve LLM gateway from llm-gateway edges
        for edge in demo.edges:
            if edge.connection_type != "llm-gateway":
                continue
            if edge.target == node.id:
                peer_id = edge.source
            elif edge.source == node.id:
                peer_id = edge.target
            else:
                continue
            peer_node = next((n for n in demo.nodes if n.id == peer_id), None)
            if not peer_node:
                continue
            peer_manifest = get_component(peer_node.component)
            if peer_manifest:
                gw_port = next((p.container for p in peer_manifest.ports if p.name == "api"), 4000)
                env["LLM_GATEWAY_URL"] = f"http://{project_name}-{peer_id}:{gw_port}"
                env["OPENAI_API_BASE"] = f"http://{project_name}-{peer_id}:{gw_port}/v1"
            break

        # Auto-resolve Milvus vector-db-milvus endpoint
        for edge in demo.edges:
            if edge.connection_type != "vector-db-milvus":
                continue
            if edge.target == node.id:
                peer_id = edge.source
            elif edge.source == node.id:
                peer_id = edge.target
            else:
                continue
            peer_node = next((n for n in demo.nodes if n.id == peer_id), None)
            if not peer_node:
                continue
            peer_manifest = get_component(peer_node.component)
            if peer_manifest:
                milvus_port = next((p.container for p in peer_manifest.ports if p.name == "grpc"), 19530)
                env["MILVUS_ENDPOINT"] = f"http://{project_name}-{peer_id}:{milvus_port}"
            break

        # Auto-resolve Kafka broker endpoint from kafka edges
        for edge in demo.edges:
            if edge.connection_type != "kafka":
                continue
            if edge.target == node.id:
                peer_id = edge.source
            elif edge.source == node.id:
                peer_id = edge.target
            else:
                continue
            peer_node = next((n for n in demo.nodes if n.id == peer_id), None)
            if not peer_node:
                continue
            peer_manifest = get_component(peer_node.component)
            if peer_manifest:
                kafka_port = next((p.container for p in peer_manifest.ports if p.name == "kafka"), 9092)
                kafka_addr = f"{project_name}-{peer_id}:{kafka_port}"
                if "CONNECT_BOOTSTRAP_SERVERS" in env:
                    env["CONNECT_BOOTSTRAP_SERVERS"] = kafka_addr
                elif "KAFKA_BROKERS" in env:
                    env["KAFKA_BROKERS"] = kafka_addr
                else:
                    env["KAFKA_BOOTSTRAP_SERVERS"] = kafka_addr
            edge_cfg = edge.connection_config or {}
            if edge_cfg.get("topic"):
                env["KAFKA_TOPIC"] = edge_cfg["topic"]
            break

        # Auto-resolve schema registry endpoint from schema-registry edges
        for edge in demo.edges:
            if edge.connection_type != "schema-registry":
                continue
            if edge.target == node.id:
                peer_id = edge.source
            elif edge.source == node.id:
                peer_id = edge.target
            else:
                continue
            peer_node = next((n for n in demo.nodes if n.id == peer_id), None)
            if not peer_node:
                continue
            peer_manifest = get_component(peer_node.component)
            if peer_manifest:
                sr_port = next((p.container for p in peer_manifest.ports if p.name == "schema-registry"), 8081)
                env["KAFKA_SCHEMAREGISTRY_URLS"] = f"http://{project_name}-{peer_id}:{sr_port}"
            break

        # Auto-resolve Dremio SQL endpoint from dremio-sql edges
        for edge in demo.edges:
            if edge.connection_type != "dremio-sql":
                continue
            if edge.target == node.id:
                peer_id = edge.source
            elif edge.source == node.id:
                peer_id = edge.target
            else:
                continue
            peer_node = next((n for n in demo.nodes if n.id == peer_id), None)
            if not peer_node:
                continue
            peer_manifest = get_component(peer_node.component)
            if peer_manifest:
                dremio_port = next((p.container for p in peer_manifest.ports if p.name == "client"), 31010)
                env["DREMIO_HOST"] = f"{project_name}-{peer_id}"
                env["DREMIO_PORT"] = str(dremio_port)
            break

        # Auto-resolve Kafka Connect endpoint from kafka-connect edges
        for edge in demo.edges:
            if edge.connection_type != "kafka-connect":
                continue
            if edge.target == node.id:
                peer_id = edge.source
            elif edge.source == node.id:
                peer_id = edge.target
            else:
                continue
            peer_node = next((n for n in demo.nodes if n.id == peer_id), None)
            if not peer_node:
                continue
            peer_manifest = get_component(peer_node.component)
            if peer_manifest:
                kc_port = next((p.container for p in peer_manifest.ports if p.name == "api"), 8083)
                env["KAFKA_CONNECT_URL"] = f"http://{project_name}-{peer_id}:{kc_port}"
            break

        # Generic env_map resolution: inject peer node config values declared in manifest
        # Works for any connection type — additive alongside the hardcoded blocks above
        for edge in demo.edges:
            if edge.source == node.id:
                peer_id = edge.target
            elif edge.target == node.id:
                peer_id = edge.source
            else:
                continue
            peer_node = next((n for n in demo.nodes if n.id == peer_id), None)
            if not peer_node:
                continue
            peer_manifest = get_component(peer_node.component)
            if not peer_manifest:
                continue
            property_defaults = {p.key: p.default for p in peer_manifest.properties}
            for provides in peer_manifest.connections.provides:
                if provides.type == edge.connection_type and provides.env_map:
                    for mapping in provides.env_map:
                        val = peer_node.config.get(mapping.config_key) or property_defaults.get(mapping.config_key)
                        if val:
                            env[mapping.env_var] = val

        # MinIO: MinIO notify webhook env for event-processor targets (per pool node / standalone)
        _minio_notify_webhook_env(demo, node, env, project_name)

        # Determine which networks this node joins
        # If node.networks is empty, join all demo networks
        if node.networks:
            node_network_names = list(node.networks.keys())
        else:
            node_network_names = list(network_map.keys())

        # Build per-service network config
        service_networks = {}
        for net_key in node_network_names:
            docker_net_name = network_map.get(net_key)
            if docker_net_name is None:
                continue
            net_cfg = node.networks.get(net_key)
            net_entry: dict = {}
            if net_cfg:
                if net_cfg.ip:
                    net_entry["ipv4_address"] = net_cfg.ip
                if net_cfg.aliases:
                    net_entry["aliases"] = net_cfg.aliases
            service_networks[docker_net_name] = net_entry if net_entry else None

        # Inject cluster network alias for erasure-coded pool discovery
        cluster_alias = node.labels.get("_cluster_alias", "")
        if cluster_alias:
            # Add alias to all networks this node joins
            for net_name in list(service_networks.keys()):
                existing = service_networks[net_name]
                if existing is None:
                    service_networks[net_name] = {"aliases": [cluster_alias]}
                elif isinstance(existing, dict):
                    aliases = existing.get("aliases", [])
                    aliases.append(cluster_alias)
                    existing["aliases"] = aliases

        # Dev Logs → Integrations JSONL: stable node id for tails from this container
        if node.component in ("external-system", "event-processor"):
            env.setdefault("INTEGRATION_NODE_ID", node.id)

        # Resolve resource limits: use the larger of demo default or manifest value
        res = demo.resources
        manifest_mem = manifest.resources.memory
        manifest_cpu = manifest.resources.cpu
        mem = max(res.default_memory or "256m", manifest_mem, key=_mem_bytes)
        cpu = max(res.default_cpu or 0.5, manifest_cpu)
        if res.max_memory:
            # Parse and cap memory (simple: just use max if set)
            mem = res.max_memory if _mem_bytes(mem) > _mem_bytes(res.max_memory) else mem
        if res.max_cpu and cpu > res.max_cpu:
            cpu = res.max_cpu

        if node.component == "spark":
            extra_mem = _spark_container_mem_from_properties(manifest, node.config)
            if extra_mem:
                mem = max(mem, extra_mem, key=_mem_bytes)

        # Resolve image — allow edition override for MinIO nodes
        image = manifest.image
        if node.component == "minio":
            edition = node.config.get("MINIO_EDITION", "ce")
            if edition == "aistor":
                image = "quay.io/minio/aistor/minio:latest"
            elif edition == "aistor-edge":
                image = "quay.io/minio/aistor/minio:edge"

        # Build service definition
        service = {
            "image": image,
            "container_name": container_name,
            "expose": [str(p.container) for p in manifest.ports],
            "environment": env,
            "mem_limit": mem,
            "cpus": cpu,
            "labels": {
                "demoforge.demo": demo.id,
                "demoforge.node": node.id,
                "demoforge.component": manifest.id,
            },
            "networks": service_networks,
            "restart": "unless-stopped",
        }

        if command:
            if node.component == "spark":
                command = _escape_compose_dollar_in_command(list(command))
            service["command"] = command

        if manifest.entrypoint:
            service["entrypoint"] = manifest.entrypoint

        if manifest.shm_size:
            service["shm_size"] = manifest.shm_size

        # Host port mappings for ports with explicit host overrides
        host_ports = [f"{p.host}:{p.container}" for p in manifest.ports if p.host]
        if host_ports:
            service["ports"] = host_ports

        # Healthcheck
        if manifest.health_check and not getattr(manifest.health_check, 'disabled', False) and manifest.health_check.port:
            hc = manifest.health_check
            if node.id in cluster_health_override:
                endpoint = cluster_health_override[node.id]
            else:
                endpoint = hc.endpoint
            health_url = f"http://localhost:{hc.port}{endpoint}"
            # For cluster nodes using /minio/health/cluster, omit the TCP fallback so that
            # a failed HTTP check correctly marks the container unhealthy.
            if node.id in cluster_health_override:
                hc_test = f"curl -sf {health_url} || wget -qO- {health_url}"
            else:
                hc_test = f"curl -sf {health_url} || wget -qO- {health_url} || bash -c 'echo > /dev/tcp/localhost/{hc.port}'"
            # Cluster nodes need a longer start period — forming quorum across N nodes
            # takes more time than a single node starting. 15s is not enough on dev machines.
            is_cluster_node = node.id in cluster_health_override
            start_period = "90s" if is_cluster_node else (hc.start_period if hasattr(hc, 'start_period') else "15s")
            service["healthcheck"] = {
                "test": ["CMD-SHELL", hc_test],
                "interval": hc.interval,
                "timeout": hc.timeout,
                "retries": 5,
                "start_period": start_period,
            }

        # Named volumes
        service_volumes = []
        if manifest.volumes:
            for vol in manifest.volumes:
                # Skip the default /data mount for cluster nodes with multiple drives:
                # MINIO_VOLUMES uses /data1.../dataN — the bare /data would be an orphan.
                if node.id in cluster_drives and cluster_drives[node.id] > 1 and vol.path == "/data":
                    continue
                vol_name = f"{project_name}-{node.id}-{vol.name}"
                service_volumes.append(f"{vol_name}:{vol.path}")

        # Extra volumes for cluster nodes with multiple drives
        if node.id in cluster_drives and cluster_drives[node.id] > 1:
            for d in range(1, cluster_drives[node.id] + 1):
                vol_name = f"{project_name}-{node.id}-data{d}"
                service_volumes.append(f"{vol_name}:/data{d}")
                compose_volumes[vol_name] = None

        # Template mounts: render Jinja2 templates and add as bind-mounts
        template_dir = os.path.join(component_dir, "templates")
        if manifest.template_mounts and os.path.isdir(template_dir):
            rendered = _render_templates(template_dir, node, demo, output_dir, project_name, manifest)
            for host_path, mount_path in rendered:
                bind_path = _to_host_path(host_path, "data")
                service_volumes.append(f"{bind_path}:{mount_path}:ro")

        # Static mounts: bind-mount files from component dir
        for sm in manifest.static_mounts:
            host_path = os.path.abspath(os.path.join(component_dir, sm.host_path))
            bind_path = _to_host_path(host_path, "components")
            service_volumes.append(f"{bind_path}:{sm.mount_path}:ro")

        # License file mounts
        for lic_req in manifest.license_requirements:
            entry = license_store.get(lic_req.license_id)
            if entry and lic_req.injection_type == "file_mount" and lic_req.mount_path:
                lic_file = os.path.join(output_dir, project_name, node.id, "license.key")
                bind_path = _to_host_path(os.path.abspath(lic_file), "data")
                service_volumes.append(f"{bind_path}:{lic_req.mount_path}:ro")

        if service_volumes:
            service["volumes"] = service_volumes

        services[service_name] = service

    # spark-etl-job: depend on the specific Spark master connected via spark-submit edge
    for sj_node in demo.nodes:
        if sj_node.component != "spark-etl-job" or sj_node.id not in services:
            continue
        spark_peer = None
        for e in demo.edges:
            if e.connection_type != "spark-submit":
                continue
            if e.source == sj_node.id:
                spark_peer = e.target
                break
            if e.target == sj_node.id:
                spark_peer = e.source
                break
        if spark_peer and spark_peer in services:
            services[sj_node.id]["depends_on"] = {spark_peer: {"condition": "service_healthy"}}

    # Resolve depends_on_components: map component names to actual node IDs
    for node in demo.nodes:
        manifest = get_component(node.component)
        if manifest and manifest.depends_on_components:
            resolved = {}
            for dep_component in manifest.depends_on_components:
                for other_node in demo.nodes:
                    if other_node.component == dep_component:
                        resolved[other_node.id] = {"condition": "service_healthy"}
                        break
            if resolved and node.id in services:
                services[node.id]["depends_on"] = resolved

    # Enforce total demo budget — scale down per-container if total exceeds budget
    res = demo.resources
    if res.total_memory and _mem_bytes(res.total_memory) > 0:
        total_budget = _mem_bytes(res.total_memory)
        total_used = sum(_mem_bytes(s.get("mem_limit", "256m")) for s in services.values())
        if total_used > total_budget:
            scale = total_budget / total_used
            for svc in services.values():
                current = _mem_bytes(svc.get("mem_limit", "256m"))
                scaled = int(current * scale)
                svc["mem_limit"] = f"{max(scaled // (1024*1024), 64)}m"
            logger.info(f"Total memory budget {res.total_memory}: scaled {len(services)} services by {scale:.2f}")

    if res.total_cpu and res.total_cpu > 0:
        total_used = sum(s.get("cpus", 0.5) for s in services.values())
        if total_used > res.total_cpu:
            scale = res.total_cpu / total_used
            for svc in services.values():
                svc["cpus"] = round(max(svc.get("cpus", 0.5) * scale, 0.1), 2)
            logger.info(f"Total CPU budget {res.total_cpu}: scaled {len(services)} services by {scale:.2f}")

    # --- mc-shell: lightweight MinIO Client container for every demo ---
    metabase_node = next((n for n in demo.nodes if n.component == "metabase"), None)
    has_minio_nodes = any(n.component == "minio" for n in demo.nodes)
    needs_mc_shell = bool(demo.clusters) or bool(metabase_node) or has_minio_nodes
    if needs_mc_shell:
        mc_shell_name = f"{project_name}-mc-shell"
        mc_env = {}
        for i, cluster in enumerate(demo.clusters):
            sanitized_label = cluster.label.replace(" ", "_").replace("-", "_")
            cred_user = cluster.credentials.get("root_user", "minioadmin")
            cred_pass = cluster.credentials.get("root_password", "minioadmin")
            mc_env[f"MC_ALIAS_{i}_NAME"] = sanitized_label
            mc_env[f"MC_ALIAS_{i}_URL"] = f"http://{project_name}-{cluster.id}-lb:80"
            mc_env[f"MC_ALIAS_{i}_ACCESS_KEY"] = cred_user
            mc_env[f"MC_ALIAS_{i}_SECRET_KEY"] = cred_pass
        mc_env["MC_ALIAS_COUNT"] = str(len(demo.clusters))

        # Expected IAM reconcile counts (mc-shell init.sh) — used with runtime counters for DEMOFORGE_IAM_REPORT
        _iam_exp_pol = _iam_exp_usr = _iam_exp_att = 0
        for _c in demo.clusters:
            _sp = effective_iam_sim_spec((_c.config or {}).get("MINIO_IAM_SIM_SPEC"))
            if _sp:
                _p, _u, _a = iam_reconcile_expected_counts(_sp)
                _iam_exp_pol += _p
                _iam_exp_usr += _u
                _iam_exp_att += _a
        _standalone_for_iam_counts = [n for n in demo.nodes if n.component == "minio" and not any(
            n.id.startswith(f"{c.id}-") for c in demo.clusters
        )]
        for _n in _standalone_for_iam_counts:
            _sp = effective_iam_sim_spec((_n.config or {}).get("MINIO_IAM_SIM_SPEC"))
            if _sp:
                _p, _u, _a = iam_reconcile_expected_counts(_sp)
                _iam_exp_pol += _p
                _iam_exp_usr += _u
                _iam_exp_att += _a
        if _iam_exp_pol + _iam_exp_usr + _iam_exp_att > 0:
            mc_env["DEMOFORGE_IAM_EXP_POLICIES"] = str(_iam_exp_pol)
            mc_env["DEMOFORGE_IAM_EXP_USERS"] = str(_iam_exp_usr)
            mc_env["DEMOFORGE_IAM_EXP_ATTACHES"] = str(_iam_exp_att)

        # Join ALL demo networks
        mc_networks = {}
        for net_key, docker_net_name in network_map.items():
            mc_networks[docker_net_name] = None

        # Generate init script with explicit mc alias set commands per cluster
        init_script_dir = os.path.join(output_dir, project_name, "mc-shell")
        os.makedirs(init_script_dir, exist_ok=True)
        init_script_path = os.path.join(init_script_dir, "init.sh")
        lines = ["#!/bin/sh", "# Wait for clusters then configure mc aliases", "sleep 15"]
        for cluster in demo.clusters:
            alias_name = re.sub(r"[^a-zA-Z0-9_]", "_", cluster.label)
            lb_url = f"http://{project_name}-{cluster.id}-lb:80"
            cred_user = cluster.credentials.get("root_user", "minioadmin")
            cred_pass = cluster.credentials.get("root_password", "minioadmin")
            lines.append(f"# Retry alias setup for {alias_name}")
            lines.append(f"for attempt in 1 2 3 4 5 6 7 8 9 10; do")
            lines.append(f"  mc alias set '{alias_name}' '{lb_url}' '{cred_user}' '{cred_pass}' 2>/dev/null && break")
            lines.append(f"  echo 'Waiting for {alias_name}... attempt $attempt'")
            lines.append(f"  sleep 10")
            lines.append(f"done")
        # Also add aliases for standalone MinIO nodes (not in clusters)
        standalone_minio = [n for n in demo.nodes if n.component == "minio" and not any(
            n.id.startswith(f"{c.id}-") for c in demo.clusters
        )]
        for node in standalone_minio:
            alias_name = re.sub(r"[^a-zA-Z0-9_]", "_", node.display_name) if node.display_name else node.id
            node_url = f"http://{project_name}-{node.id}:9000"
            cred_user = node.config.get("MINIO_ROOT_USER", "minioadmin")
            cred_pass = node.config.get("MINIO_ROOT_PASSWORD", "minioadmin")
            lines.append(f"# Retry alias setup for standalone {alias_name}")
            lines.append(f"for attempt in 1 2 3 4 5 6 7 8 9 10; do")
            lines.append(f"  mc alias set '{alias_name}' '{node_url}' '{cred_user}' '{cred_pass}' 2>/dev/null && break")
            lines.append(f"  echo 'Waiting for {alias_name}... attempt $attempt'")
            lines.append(f"  sleep 10")
            lines.append(f"done")

        # MinIO IAM simulation — custom policies + users (mc admin policy / user / attach)
        iam_host_root = os.path.join(init_script_dir, "iam")
        _iam_shell_counters_started = False
        for cluster in demo.clusters:
            spec = effective_iam_sim_spec((cluster.config or {}).get("MINIO_IAM_SIM_SPEC"))
            if not spec:
                continue
            if not _iam_shell_counters_started:
                lines.extend(mc_shell_iam_report_shell_init())
                _iam_shell_counters_started = True
            alias_name = re.sub(r"[^a-zA-Z0-9_]", "_", cluster.label)
            pairs = write_policy_files_for_spec(spec, iam_host_root, cluster.id)
            lines.append("")
            lines.extend(mc_shell_iam_lines(alias_name, cluster.id, spec, pairs))
        for node in standalone_minio:
            spec = effective_iam_sim_spec((node.config or {}).get("MINIO_IAM_SIM_SPEC"))
            if not spec:
                continue
            if not _iam_shell_counters_started:
                lines.extend(mc_shell_iam_report_shell_init())
                _iam_shell_counters_started = True
            alias_name = re.sub(r"[^a-zA-Z0-9_]", "_", node.display_name) if node.display_name else node.id
            pairs = write_policy_files_for_spec(spec, iam_host_root, node.id)
            lines.append("")
            lines.extend(mc_shell_iam_lines(alias_name, node.id, spec, pairs))
        if _iam_shell_counters_started:
            lines.extend(mc_shell_iam_report_shell_finalize())

        # Create warehouse bucket on MinIO nodes connected to Iceberg REST catalog
        iceberg_nodes = [n for n in demo.nodes if n.component == "iceberg-rest"]
        if iceberg_nodes:
            for edge in demo.edges:
                if edge.connection_type == "s3":
                    source_node = next((n for n in demo.nodes if n.id == edge.source), None)
                    target_node = next((n for n in demo.nodes if n.id == edge.target), None)
                    # Find the MinIO node in this s3 edge
                    minio_node = None
                    if source_node and source_node.component == "minio":
                        minio_node = source_node
                    elif target_node and target_node.component == "minio":
                        minio_node = target_node
                    if minio_node:
                        alias = re.sub(r"[^a-zA-Z0-9_]", "_", minio_node.display_name) if minio_node.display_name else minio_node.id
                        lines.append(f"# Create warehouse bucket for Iceberg on {alias}")
                        lines.append(f"mc mb '{alias}/warehouse' --ignore-existing 2>/dev/null || true")

        # Auto-create AIStor Tables warehouse for clusters with aistor_tables_enabled
        for cluster in demo.clusters:
            if getattr(cluster, 'aistor_tables_enabled', False):
                alias_name = re.sub(r"[^a-zA-Z0-9_]", "_", cluster.label)
                # Use direct node access (not LB) for mc table commands since LB may not proxy SigV4
                node_id = f"{cluster.id}-pool1-node-1"
                node_url = f"http://{project_name}-{node_id}:9000"
                cred_user = cluster.credentials.get("root_user", "minioadmin")
                cred_pass = cluster.credentials.get("root_password", "minioadmin")
                warehouse = cluster.config.get("ICEBERG_WAREHOUSE", "analytics")
                lines.append(f"# Setup AIStor Tables warehouse for {alias_name}")
                lines.append(f"mc alias set '{alias_name}_direct' '{node_url}' '{cred_user}' '{cred_pass}' 2>/dev/null || true")
                lines.append(f"mc table warehouse create '{alias_name}_direct' {warehouse} --ignore-existing 2>/dev/null || echo 'Warehouse setup skipped (mc table not available)'")

        # Auto-create AIStor Tables warehouse for standalone AIStor nodes
        for snode in standalone_minio:
            if snode.config.get("MINIO_EDITION", "ce") == "aistor":
                alias_name = re.sub(r"[^a-zA-Z0-9_]", "_", snode.display_name) if snode.display_name else snode.id
                warehouse = snode.config.get("ICEBERG_WAREHOUSE", "analytics")
                lines.append(f"# Setup AIStor Tables warehouse for standalone {alias_name}")
                lines.append(f"mc table warehouse create '{alias_name}' {warehouse} --ignore-existing 2>/dev/null || echo 'Warehouse setup skipped (mc table not available)'")

        # Comprehensive bucket auto-creation for all S3-connected edges
        _s3_edge_types = {"s3", "structured-data", "file-push", "aistor-tables"}
        _bucket_cfg_keys = [
            "target_bucket", "bucket", "sink_bucket", "documents_bucket", "audit_bucket",
            "snapshot_bucket", "artifact_bucket", "training_bucket", "source_bucket",
            "output_bucket", "milvus_bucket", "dag_bucket", "log_bucket",
        ]

        def _cluster_alias_for_node(node_id: str) -> str | None:
            """Return the mc alias name for a cluster LB or standalone MinIO node, or None."""
            if node_id.endswith("-lb"):
                cid = node_id[:-3]
                c = next((x for x in demo.clusters if x.id == cid), None)
                if c:
                    return re.sub(r"[^a-zA-Z0-9_]", "_", c.label)
            n = next((x for x in standalone_minio if x.id == node_id), None)
            if n:
                return re.sub(r"[^a-zA-Z0-9_]", "_", n.display_name) if n.display_name else n.id
            return None

        seen_mc_buckets: set[tuple[str, str]] = set()
        for edge in demo.edges:
            if edge.connection_type not in _s3_edge_types:
                continue
            cfg = edge.connection_config or {}

            # Resolve MinIO alias(es) for this edge
            minio_aliases: list[str] = []
            for node_id in (edge.target, edge.source):
                a = _cluster_alias_for_node(node_id)
                if a:
                    minio_aliases.append(a)
            # For user-placed nginx intermediaries: follow their load-balance edges
            target_node = next((n for n in demo.nodes if n.id == edge.target), None)
            if target_node and target_node.component == "nginx":
                for e2 in demo.edges:
                    if e2.source == edge.target and e2.connection_type in ("load-balance", "nginx-backend"):
                        a = _cluster_alias_for_node(e2.target)
                        if a:
                            minio_aliases.append(a)

            # Collect bucket names from edge config
            edge_buckets: list[str] = [cfg[k] for k in _bucket_cfg_keys if cfg.get(k)]
            # Default bucket for file-push with no explicit config
            if edge.connection_type == "file-push" and not edge_buckets:
                edge_buckets.append("demo-bucket")

            for alias in minio_aliases:
                for bucket in edge_buckets:
                    key = (alias, bucket)
                    if key not in seen_mc_buckets:
                        seen_mc_buckets.add(key)
                        lines.append(f"mc mb '{alias}/{bucket}' --ignore-existing 2>/dev/null || true")

        lines.append("echo 'mc aliases configured.'")

        # Metabase setup is handled by a separate sidecar (see below)

        # Signal readiness for compose healthchecks (IAM reconcile + bucket bootstrap finished).
        lines.append("touch /tmp/demoforge-mc-shell-ready 2>/dev/null || true")

        lines.append("sleep infinity")

        init_host_path = _to_host_path(os.path.abspath(init_script_dir), "data")

        with open(init_script_path, "w") as f:
            f.write("\n".join(lines) + "\n")
        os.chmod(init_script_path, 0o755)

        # Use AIStor mc image if any cluster has AIStor features (mc table commands)
        has_aistor = any(getattr(c, 'aistor_tables_enabled', False) for c in demo.clusters) or any(
            n.config.get("MINIO_EDITION", "ce") in ("aistor", "aistor-edge") for n in demo.nodes if n.component == "minio"
        )
        mc_image = "quay.io/minio/aistor/mc:latest" if has_aistor else "quay.io/minio/mc:latest"

        services["mc-shell"] = {
            "image": mc_image,
            "container_name": mc_shell_name,
            "entrypoint": ["/bin/sh", "-c"],
            "command": [f"sh /etc/mc-shell/init.sh"],
            "environment": mc_env,
            "mem_limit": "256m",
            "cpus": 0.25,
            "labels": {
                "demoforge.demo": demo.id,
                "demoforge.node": "mc-shell",
                "demoforge.component": "mc-shell",
            },
            "networks": mc_networks,
            "volumes": [f"{init_host_path}:/etc/mc-shell:ro"],
            "restart": "unless-stopped",
            "healthcheck": {
                "test": ["CMD-SHELL", "test -f /tmp/demoforge-mc-shell-ready"],
                "interval": "5s",
                "timeout": "4s",
                "retries": 5,
                "start_period": "240s",
            },
        }

        logger.info(f"Added mc-shell service for demo {demo.id} with {len(demo.clusters)} cluster alias(es)")

        # S3 File Browser + IAM simulation: wait until mc-shell has applied policies/users on MinIO.
        for bn in demo.nodes:
            if bn.component != "s3-file-browser" or bn.id not in services:
                continue
            if not _s3_file_browser_peer_has_iam_simulation(demo, bn):
                continue
            dep = services[bn.id].get("depends_on")
            if not isinstance(dep, dict):
                dep = {}
            dep = {**dep, "mc-shell": {"condition": "service_healthy"}}
            services[bn.id]["depends_on"] = dep
            logger.info(
                "Demo %s: s3-file-browser %s depends_on mc-shell (IAM simulation peer)",
                demo.id,
                bn.id,
            )

    # --- metabase-init: setup sidecar when Metabase is in the demo ---
    if metabase_node:
        trino_edge = next((e for e in demo.edges if e.target == metabase_node.id and e.connection_type == "sql-query"), None)
        trino_node = next((n for n in demo.nodes if trino_edge and n.id == trino_edge.source), None)
        # Fallback: any Trino node in the demo (Metabase must still reach Trino on the Docker network)
        if not trino_node:
            trino_node = next((n for n in demo.nodes if n.component == "trino"), None)
        metabase_host = f"{project_name}-{metabase_node.id}"
        trino_host = f"{project_name}-{trino_node.id}" if trino_node else ""
        catalog_override = trino_edge.connection_config.get("catalog_name", "") if trino_edge else ""
        if trino_node and any(
            e.target == trino_node.id and e.connection_type == "aistor-tables"
            for e in demo.edges
        ):
            catalog = resolve_trino_aistor_catalog_name(demo, trino_node.id)
        elif catalog_override:
            catalog = catalog_override
        else:
            catalog = "iceberg"
        schema = trino_edge.connection_config.get("schema", "analytics") if trino_edge else "analytics"
        if not trino_edge and trino_node:
            logger.warning(
                f"Demo {demo.id}: Metabase has no sql-query edge from Trino — using first Trino node "
                f"{trino_node.id} for TRINO_HOST (add Trino→Metabase sql-query edge for explicit catalog/schema)."
            )

        components_dir = os.environ.get("DEMOFORGE_COMPONENTS_DIR", "./components")
        setup_script = os.path.join(os.path.abspath(components_dir), "metabase", "init", "setup-metabase.sh")
        provision_script = os.path.join(os.path.abspath(components_dir), "metabase", "init", "provision.py")
        integration_log_script = os.path.join(os.path.abspath(components_dir), "metabase", "init", "integration_log.py")

        if os.path.exists(setup_script):
            setup_host_path = _to_host_path(setup_script, "components")
            init_networks = {docker_net_name: None for docker_net_name in network_map.values()}

            has_provision = os.path.exists(provision_script)
            sidecar_image = "python:3.11-alpine" if has_provision else "alpine:3.19"
            if has_provision:
                provision_host_path = _to_host_path(provision_script, "components")
                # provision.py uses stdlib urllib only — no pip/network at container start (offline-safe)
                entrypoint_cmd = "/bin/sh /setup/setup-metabase.sh && python3 /setup/provision.py"
                sidecar_entrypoint = ["/bin/sh", "-c", entrypoint_cmd]
            else:
                sidecar_entrypoint = ["/bin/sh", "/setup/setup-metabase.sh"]

            sidecar_env = {
                "METABASE_HOST": metabase_host,
                "TRINO_HOST": trino_host,
                "TRINO_CATALOG": catalog,
                "TRINO_SCHEMA": schema,
                "INTEGRATION_NODE_ID": "metabase-init",
                "INTEGRATION_LOG_SOURCE": "metabase-init",
                "METABASE_INTEGRATION_LOG": "/tmp/demoforge_integration.jsonl",
            }

            mb_intents_vol = f"{project_name}-mb-intents"
            sidecar_volumes = [f"{setup_host_path}:/setup/setup-metabase.sh:ro"]
            if has_provision:
                sidecar_volumes.append(f"{provision_host_path}:/setup/provision.py:ro")
                if os.path.exists(integration_log_script):
                    il_host_path = _to_host_path(integration_log_script, "components")
                    sidecar_volumes.append(f"{il_host_path}:/setup/integration_log.py:ro")
                sidecar_volumes.append(f"{mb_intents_vol}:/provision-intents")

            services["metabase-init"] = {
                "image": sidecar_image,
                "container_name": f"{project_name}-metabase-init",
                "entrypoint": sidecar_entrypoint,
                "environment": sidecar_env,
                "mem_limit": "128m" if has_provision else "64m",
                "cpus": 0.1,
                "labels": {
                    "demoforge.demo": demo.id,
                    "demoforge.node": "metabase-init",
                    "demoforge.component": "metabase-init",
                    "demoforge.sidecar": "true",
                },
                "networks": init_networks,
                "volumes": sidecar_volumes,
                "restart": "no",
                # Start after Metabase JVM and Trino HTTP — avoids empty TRINO_HOST and connection refused to :8080
                "depends_on": [metabase_node.id] + ([trino_node.id] if trino_node else []),
            }
            logger.info(f"Added metabase-init sidecar for demo {demo.id} (provision={'yes' if has_provision else 'no'})")

            if has_provision:
                # Mount the shared intents volume into every external-system container
                for es_node in [n for n in demo.nodes if n.component == "external-system"]:
                    if es_node.id in services:
                        svc_vols = services[es_node.id].setdefault("volumes", [])
                        svc_vols.append(f"{mb_intents_vol}:/provision-intents")
                compose_volumes[mb_intents_vol] = None

    # --- mcp-server: one MCP sidecar per MinIO cluster for AI tool access ---
    if demo.clusters:
        for cluster in [c for c in demo.clusters if c.mcp_enabled and c.config.get("MINIO_EDITION", "ce") == "aistor"]:
            mcp_svc_name = f"{cluster.id}-mcp"
            mcp_container_name = f"{project_name}-{cluster.id}-mcp"
            cred_user = cluster.credentials.get("root_user", "minioadmin")
            cred_pass = cluster.credentials.get("root_password", "minioadmin")

            mcp_env = {
                "MINIO_ENDPOINT": f"{project_name}-{cluster.id}-lb:80",
                "MINIO_ACCESS_KEY": cred_user,
                "MINIO_SECRET_KEY": cred_pass,
                "MINIO_USE_SSL": "false",
            }

            mcp_networks = {docker_net_name: None for docker_net_name in network_map.values()}

            services[mcp_svc_name] = {
                "image": "quay.io/minio/aistor/mcp-server-aistor:latest",
                "container_name": mcp_container_name,
                "command": ["--allow-write", "--allow-delete", "--allow-admin",
                            "--http", "--http-port", "8090"],
                "environment": mcp_env,
                "expose": ["8090"],
                "mem_limit": "128m",
                "cpus": 0.25,
                "labels": {
                    "demoforge.demo": demo.id,
                    "demoforge.node": mcp_svc_name,
                    "demoforge.component": "mcp-server-minio",
                },
                "networks": mcp_networks,
                "restart": "unless-stopped",
            }
        mcp_clusters = [c for c in demo.clusters if c.mcp_enabled]
        if mcp_clusters:
            logger.info(f"Added {len(mcp_clusters)} MCP server sidecar(s) for demo {demo.id}")

    # Also inject MCP sidecar for standalone MinIO nodes (not in clusters)
    minio_nodes = [n for n in demo.nodes if n.component == "minio" and not any(
        n.id.startswith(f"{c.id}-") for c in demo.clusters
    ) and n.labels.get("mcp_enabled", "false").lower() == "true"]
    for node in minio_nodes:
        mcp_svc_name = f"{node.id}-mcp"
        mcp_container_name = f"{project_name}-{node.id}-mcp"
        cred_user = node.config.get("MINIO_ROOT_USER", "minioadmin")
        cred_pass = node.config.get("MINIO_ROOT_PASSWORD", "minioadmin")

        mcp_env = {
            "MINIO_ENDPOINT": f"{project_name}-{node.id}:9000",
            "MINIO_ACCESS_KEY": cred_user,
            "MINIO_SECRET_KEY": cred_pass,
            "MINIO_USE_SSL": "false",
        }

        mcp_networks = {docker_net_name: None for docker_net_name in network_map.values()}

        services[mcp_svc_name] = {
            "image": "quay.io/minio/aistor/mcp-server-aistor:latest",
            "container_name": mcp_container_name,
            "command": ["--allow-write", "--allow-delete", "--allow-admin",
                        "--http", "--http-port", "8090"],
            "environment": mcp_env,
            "expose": ["8090"],
            "mem_limit": "128m",
            "cpus": 0.25,
            "labels": {
                "demoforge.demo": demo.id,
                "demoforge.node": mcp_svc_name,
                "demoforge.component": "mcp-server-minio",
            },
            "networks": mcp_networks,
            "restart": "unless-stopped",
        }
    if minio_nodes:
        logger.info(f"Added {len(minio_nodes)} MCP server sidecar(s) for standalone MinIO nodes")

    # Top-level networks block — let Docker auto-assign subnets to avoid conflicts
    compose_networks = {}
    for net in demo.networks:
        docker_net_name = network_map[net.name]
        compose_networks[docker_net_name] = {
            "driver": net.driver,
            "name": docker_net_name,
        }

    # Compose file structure (omit obsolete top-level version — Compose V2 warns if present)
    compose = {
        "services": services,
        "networks": compose_networks,
    }

    # Add named volumes
    volumes = {}
    for node in demo.nodes:
        manifest = get_component(node.component)
        if manifest:
            for vol in manifest.volumes:
                if node.id in cluster_drives and cluster_drives[node.id] > 1 and vol.path == "/data":
                    continue
                vol_name = f"{project_name}-{node.id}-{vol.name}"
                volumes[vol_name] = {"driver": "local"}
    # Add cluster-specific extra volumes
    for vol_name, vol_val in compose_volumes.items():
        volumes[vol_name] = {"driver": "local"} if vol_val is None else vol_val
    if volumes:
        compose["volumes"] = volumes

    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{project_name}.yml")

    # Use a custom dumper that quotes strings which could be misinterpreted as numbers
    class QuotedDumper(yaml.Dumper):
        pass

    def _str_representer(dumper, data):
        # Force quoting for strings that YAML might interpret as numbers/booleans
        if data and (data[0].isdigit() or data.lower() in ("true", "false", "yes", "no", "null", "on", "off")):
            return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="'")
        return dumper.represent_scalar("tag:yaml.org,2002:str", data)

    QuotedDumper.add_representer(str, _str_representer)

    with open(output_path, "w") as f:
        yaml.dump(compose, f, Dumper=QuotedDumper, default_flow_style=False, sort_keys=False)

    logger.info(f"Generated compose file: {output_path}")
    return output_path, demo
