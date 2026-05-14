"""Shared helpers for docker-compose generation (env mapping, paths, templates)."""

from __future__ import annotations

import os
import re
import logging
import yaml
from jinja2 import Environment, FileSystemLoader
from ...models.demo import DemoCluster, DemoDefinition, DemoNode, DemoEdge, NodePosition
from ...registry.loader import get_component
from ...config.license_store import license_store

logger = logging.getLogger(__name__)


def _mem_bytes(mem_str: str) -> int:
    """Parse Docker memory string (e.g. '256m', '1g') to bytes for comparison."""
    mem_str = mem_str.strip().lower()
    if mem_str.endswith("g"):
        return int(float(mem_str[:-1]) * 1024 * 1024 * 1024)
    elif mem_str.endswith("m"):
        return int(float(mem_str[:-1]) * 1024 * 1024)
    elif mem_str.endswith("k"):
        return int(float(mem_str[:-1]) * 1024)
    return int(mem_str) if mem_str.isdigit() else 0

# Host-side paths for bind mounts (needed when backend runs in Docker)
# Auto-detect from Docker if env vars point to wrong directory (e.g. run from subdirectory)
HOST_COMPONENTS_DIR = os.environ.get("DEMOFORGE_HOST_COMPONENTS_DIR", "")
HOST_DATA_DIR = os.environ.get("DEMOFORGE_HOST_DATA_DIR", "")


def _validate_host_paths():
    """Validate and auto-correct HOST_*_DIR paths.

    If docker compose was run from a subdirectory, ${PWD} resolves wrong.
    Detect this by checking if HOST_DATA_DIR ends with a known project subdirectory
    (e.g. frontend/data instead of data), and fix it by inspecting our own mounts.
    """
    global HOST_COMPONENTS_DIR, HOST_DATA_DIR

    # Quick sanity check: HOST_DATA_DIR should end with /data, not /frontend/data etc.
    if HOST_DATA_DIR and not HOST_DATA_DIR.rstrip("/").endswith("/data"):
        logger.warning(f"HOST_DATA_DIR looks suspicious: {HOST_DATA_DIR}")

    try:
        from ...network_manager import find_self_backend_container

        backend = find_self_backend_container()
        if not backend:
            return
        for mount in backend.attrs.get("Mounts", []):
            dest = mount.get("Destination", "")
            src = mount.get("Source", "")
            if dest == "/app/data" and src:
                if HOST_DATA_DIR != src:
                    logger.warning(
                        f"AUTO-FIX: HOST_DATA_DIR was '{HOST_DATA_DIR}', "
                        f"corrected to '{src}' (from Docker mount)"
                    )
                    HOST_DATA_DIR = src
            elif dest == "/app/components" and src:
                if HOST_COMPONENTS_DIR != src:
                    logger.warning(
                        f"AUTO-FIX: HOST_COMPONENTS_DIR was '{HOST_COMPONENTS_DIR}', "
                        f"corrected to '{src}' (from Docker mount)"
                    )
                    HOST_COMPONENTS_DIR = src
    except Exception as exc:
        logger.debug(f"Could not auto-detect host paths: {exc}")


_validate_host_paths()


def _to_host_path(container_path: str, path_type: str) -> str:
    """Translate a container-internal path to the host-equivalent path.
    path_type is 'data' or 'components'."""
    if path_type == "data" and HOST_DATA_DIR:
        data_dir = os.environ.get("DEMOFORGE_DATA_DIR", "./data")
        abs_data = os.path.abspath(data_dir)
        if container_path.startswith(abs_data):
            return HOST_DATA_DIR + container_path[len(abs_data):]
    elif path_type == "components" and HOST_COMPONENTS_DIR:
        comp_dir = os.environ.get("DEMOFORGE_COMPONENTS_DIR", "./components")
        abs_comp = os.path.abspath(comp_dir)
        if container_path.startswith(abs_comp):
            return HOST_COMPONENTS_DIR + container_path[len(abs_comp):]
    return container_path


def _sanitize_trino_catalog_file_stem(name: str, *, fallback: str = "aistor") -> str:
    """Trino catalog id = basename of catalog/*.properties (limited charset)."""
    raw = (name or "").strip()
    if not raw:
        return fallback
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", raw).strip("_") or fallback
    reserved = {"iceberg", "hive", "memory", "system"}
    if safe.lower() in reserved:
        logger.warning(
            "Trino AIStor catalog name %r resolves to reserved id %r — using %r instead "
            "(rename MinIO \"Default Trino catalog\" or remove conflicting catalog/*.properties).",
            raw,
            safe,
            fallback,
        )
        return fallback
    return safe


def resolve_minio_peer_aistor_catalog_name(demo: DemoDefinition, peer_id: str) -> str:
    """Trino catalog id for AIStor on a MinIO cluster LB, cluster id, or standalone MinIO node.

    Source of truth: MinIO cluster / standalone ``AISTOR_TABLES_CATALOG_NAME``, then ``aistor``.
    MinIO→Trino ``aistor-tables`` edges must not override this (compose + UI stay aligned).
    Must stay consistent with :func:`resolve_trino_aistor_catalog_name` (same *.properties stem).
    """
    default = "aistor"

    if peer_id.endswith("-lb"):
        cid = peer_id[:-3]
        cl = next((c for c in demo.clusters if c.id == cid), None)
        if cl:
            cfg = cl.config or {}
            node_cat = str(cfg.get("AISTOR_TABLES_CATALOG_NAME") or "").strip()
            chosen = node_cat or default
            return _sanitize_trino_catalog_file_stem(chosen)

    cl = next((c for c in demo.clusters if c.id == peer_id), None)
    if cl:
        cfg = cl.config or {}
        node_cat = str(cfg.get("AISTOR_TABLES_CATALOG_NAME") or "").strip()
        chosen = node_cat or default
        return _sanitize_trino_catalog_file_stem(chosen)

    nd = next((n for n in demo.nodes if n.id == peer_id), None)
    if nd and nd.component == "minio":
        cfg = nd.config or {}
        node_cat = str(cfg.get("AISTOR_TABLES_CATALOG_NAME") or "").strip()
        chosen = node_cat or default
        return _sanitize_trino_catalog_file_stem(chosen)

    return _sanitize_trino_catalog_file_stem(default)


def resolve_trino_aistor_catalog_name(demo: DemoDefinition, trino_node_id: str) -> str:
    """
    SQL catalog name for the AIStor Iceberg REST connector on Trino.

    Must match the catalog *.properties filename DemoForge mounts. Resolved from the MinIO peer
    on each incoming ``aistor-tables`` edge (cluster or standalone config only).
    """
    for e in demo.edges:
        if e.target != trino_node_id or e.connection_type != "aistor-tables":
            continue
        return resolve_minio_peer_aistor_catalog_name(demo, e.source)
    return "aistor"


def apply_default_trino_catalog_env(env: dict, demo: DemoDefinition, trino_node_id: str) -> None:
    """Set ``TRINO_CATALOG`` when unset: AIStor catalog from MinIO config, else other edges' ``catalog_name``."""
    if env.get("TRINO_CATALOG"):
        return
    if any(e.target == trino_node_id and e.connection_type == "aistor-tables" for e in demo.edges):
        env["TRINO_CATALOG"] = resolve_trino_aistor_catalog_name(demo, trino_node_id)
        return
    for e in demo.edges:
        if e.target == trino_node_id and e.connection_type in ("sql-query", "aistor-tables", "iceberg"):
            cat = (e.connection_config or {}).get("catalog_name")
            if cat:
                env["TRINO_CATALOG"] = str(cat)
                return
    for e in demo.edges:
        if e.source == trino_node_id or e.target == trino_node_id:
            if e.connection_type in ("sql-query", "aistor-tables", "iceberg"):
                cat = (e.connection_config or {}).get("catalog_name")
                if cat:
                    env["TRINO_CATALOG"] = str(cat)
                    return


def _render_templates(template_dir, node, demo, output_dir, project_name, manifest):
    env = Environment(loader=FileSystemLoader(template_dir))
    results = []
    for tm in manifest.template_mounts:
        template = env.get_template(tm.template)
        rendered = template.render(
            node=node, demo=demo, nodes=demo.nodes,
            edges=demo.edges, project_name=project_name,
        )
        mount_path = tm.mount_path
        base_slug = tm.template.removesuffix(".j2")
        host_path = os.path.join(output_dir, project_name, node.id, base_slug)
        # Trino: AIStor REST catalog file must be named {catalog}.properties so SQL uses MinIO catalog setting.
        if getattr(node, "component", None) == "trino" and tm.template == "aistor-iceberg.properties.j2":
            cat = resolve_trino_aistor_catalog_name(demo, node.id)
            mount_path = f"/etc/trino/catalog/{cat}.properties"
            host_path = os.path.join(output_dir, project_name, node.id, f"aistor-iceberg-{cat}.properties")
        os.makedirs(os.path.dirname(host_path), exist_ok=True)
        with open(host_path, "w") as f:
            f.write(rendered)
        results.append((os.path.abspath(host_path), mount_path))
    return results


def _minio_node_matches_webhook_peer(minio_node_id: str, edge_mid: str, demo: DemoDefinition) -> bool:
    """MinIO container receives notify env when edge_mid is its LB, cluster id, or standalone node id."""
    if edge_mid.endswith("-lb"):
        cluster_id = edge_mid[:-3]
        return minio_node_id.startswith(f"{cluster_id}-pool") and "-node-" in minio_node_id
    cl = next((c for c in demo.clusters if c.id == edge_mid), None)
    if cl:
        return minio_node_id.startswith(f"{cl.id}-pool") and "-node-" in minio_node_id
    return minio_node_id == edge_mid


def _minio_notify_webhook_env(demo: DemoDefinition, node: DemoNode, env: dict, project_name: str) -> None:
    if node.component != "minio":
        return
    for edge in demo.edges:
        if edge.connection_type != "webhook":
            continue
        ep_node = next(
            (n for n in demo.nodes if n.id in (edge.source, edge.target) and n.component == "event-processor"),
            None,
        )
        if not ep_node:
            continue
        mid = edge.source if ep_node.id == edge.target else edge.target
        if not _minio_node_matches_webhook_peer(node.id, mid, demo):
            continue
        suffix = re.sub(r"[^a-zA-Z0-9_]", "_", ep_node.id)
        endpoint = f"http://{project_name}-{ep_node.id}:8090/webhook"
        env[f"MINIO_NOTIFY_WEBHOOK_ENABLE_{suffix}"] = "on"
        env[f"MINIO_NOTIFY_WEBHOOK_ENDPOINT_{suffix}"] = endpoint
        env[f"MINIO_NOTIFY_WEBHOOK_QUEUE_DIR_{suffix}"] = f"/tmp/.minio/events/{suffix}"
        env[f"MINIO_NOTIFY_WEBHOOK_QUEUE_LIMIT_{suffix}"] = "10000"


def _event_processor_webhook_and_suffix(demo: DemoDefinition, node: DemoNode, env: dict, container_name: str) -> None:
    env["EP_WEBHOOK_ENDPOINT"] = f"http://{container_name}:8090/webhook"
    env["EP_MINIO_NOTIFY_SUFFIX"] = re.sub(r"[^a-zA-Z0-9_]", "_", node.id)
    # EP_ACTION_SCENARIO / EP_MODE come from manifest + node.config (merged earlier)
    for edge in demo.edges:
        if edge.connection_type != "webhook":
            continue
        ep_node = next(
            (n for n in demo.nodes if n.id in (edge.source, edge.target) and n.component == "event-processor"),
            None,
        )
        if not ep_node or ep_node.id != node.id:
            continue
        cfg = edge.connection_config or {}
        env["EP_WEBHOOK_BUCKET"] = str(cfg.get("webhook_bucket", "") or "")
        env["EP_WEBHOOK_PREFIX"] = str(cfg.get("webhook_prefix", "") or "")
        env["EP_WEBHOOK_SUFFIX"] = str(cfg.get("webhook_suffix", "") or "")
        env["EP_WEBHOOK_EVENTS"] = str(cfg.get("webhook_events", "put") or "put")
        break


def _event_processor_s3_from_edges(demo: DemoDefinition, node: DemoNode, env: dict, project_name: str) -> None:
    """Inject S3 / Iceberg for event-processor (same rules as external-system)."""
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

        edge_cfg = edge.connection_config or {}
        for cfg_key in ("target_bucket", "bucket", "sink_bucket"):
            val = edge_cfg.get(cfg_key)
            if val:
                env["S3_BUCKET"] = str(val)
                break

        if edge.connection_type == "aistor-tables":
            env["ICEBERG_CATALOG_URI"] = f"http://{svc}:{port}/_iceberg"
            env["ICEBERG_SIGV4"] = "true"
            wh = (edge.connection_config or {}).get("warehouse")
            if peer_cluster:
                env["ICEBERG_WAREHOUSE"] = wh or peer_cluster.config.get("ICEBERG_WAREHOUSE", "analytics")
            elif peer_node_obj:
                env["ICEBERG_WAREHOUSE"] = wh or (peer_node_obj.config or {}).get("ICEBERG_WAREHOUSE", "analytics")
        elif "ICEBERG_CATALOG_URI" not in env or not env["ICEBERG_CATALOG_URI"]:
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


def _event_processor_s3_fallback_from_webhook_peer(demo: DemoDefinition, node: DemoNode, env: dict, project_name: str) -> None:
    """If no outgoing s3/aistor edge, use the MinIO peer from the webhook edge (mc init script)."""
    if env.get("S3_ENDPOINT"):
        return
    for edge in demo.edges:
        if edge.connection_type != "webhook":
            continue
        ep_node = next(
            (n for n in demo.nodes if n.id in (edge.source, edge.target) and n.component == "event-processor"),
            None,
        )
        if not ep_node or ep_node.id != node.id:
            continue
        mid = edge.target if edge.source == node.id else edge.source
        peer_cluster = next((c for c in demo.clusters if c.id == mid), None)
        peer_node_obj = next((n for n in demo.nodes if n.id == mid), None)
        is_cluster_lb = mid.endswith("-lb")
        if is_cluster_lb:
            cluster_id_from_lb = mid[:-3]
            peer_cluster = next((c for c in demo.clusters if c.id == cluster_id_from_lb), None)

        if peer_cluster:
            svc = f"{project_name}-{peer_cluster.id}-lb"
            port = 80
        elif is_cluster_lb:
            svc = f"{project_name}-{mid}"
            port = 80
        elif peer_node_obj and peer_node_obj.component == "minio":
            svc = f"{project_name}-{mid}"
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
        break


def _iceberg_browser_peer_services(
    demo: DemoDefinition, peer_id: str, project_name: str
) -> tuple[str | None, int | None, DemoCluster | None, DemoNode | None]:
    """Resolve (svc, port, peer_cluster, peer_minio_node) for a MinIO peer or cluster LB."""
    peer_cluster = next((c for c in demo.clusters if c.id == peer_id), None)
    peer_node_obj = next((n for n in demo.nodes if n.id == peer_id), None)
    is_cluster_lb = peer_id.endswith("-lb")
    if is_cluster_lb:
        cluster_id_from_lb = peer_id[:-3]
        peer_cluster = next((c for c in demo.clusters if c.id == cluster_id_from_lb), None)
    if peer_cluster:
        return f"{project_name}-{peer_cluster.id}-lb", 80, peer_cluster, None
    if is_cluster_lb:
        return f"{project_name}-{peer_id}", 80, None, None
    if peer_node_obj and peer_node_obj.component == "minio":
        return f"{project_name}-{peer_id}", 9000, None, peer_node_obj
    return None, None, None, None


def _iceberg_browser_env_from_edges(demo: DemoDefinition, node: DemoNode, env: dict, project_name: str) -> None:
    """Inject Iceberg REST + S3 env for iceberg-browser from diagram edges."""
    for edge in demo.edges:
        if edge.connection_type not in ("aistor-tables", "iceberg-catalog", "s3"):
            continue
        if edge.target != node.id and edge.source != node.id:
            continue
        peer_id = edge.source if edge.target == node.id else edge.target
        peer_node_obj = next((n for n in demo.nodes if n.id == peer_id), None)

        if edge.connection_type == "iceberg-catalog" and peer_node_obj and peer_node_obj.component == "iceberg-rest":
            env["ICEBERG_REST_URI"] = f"http://{project_name}-{peer_id}:8181"
            env["ICEBERG_SIGV4"] = "false"
            if not str(env.get("ICEBERG_WAREHOUSE", "") or "").strip():
                env["ICEBERG_WAREHOUSE"] = "s3://warehouse/"
            continue

        svc, port, peer_cluster, peer_minio = _iceberg_browser_peer_services(demo, peer_id, project_name)
        if not svc or port is None:
            continue
        s3_url = f"http://{svc}:{port}"

        if edge.connection_type == "aistor-tables":
            rest_uri = f"{s3_url}/_iceberg"
            if "-lb:80" in rest_uri:
                rest_uri = rest_uri.replace("-lb:80", "-pool1-node-1:9000")
            env["ICEBERG_REST_URI"] = rest_uri
            env["ICEBERG_SIGV4"] = "true"
            if peer_cluster:
                env["ICEBERG_WAREHOUSE"] = str(
                    (peer_cluster.config or {}).get("ICEBERG_WAREHOUSE", "analytics")
                )
            elif peer_minio:
                env["ICEBERG_WAREHOUSE"] = str((peer_minio.config or {}).get("ICEBERG_WAREHOUSE", "analytics"))

        if edge.connection_type in ("s3", "aistor-tables"):
            env["S3_ENDPOINT"] = s3_url
            if peer_cluster:
                env["S3_ACCESS_KEY"] = peer_cluster.credentials.get("root_user", "minioadmin")
                env["S3_SECRET_KEY"] = peer_cluster.credentials.get("root_password", "minioadmin")
            elif peer_minio:
                env["S3_ACCESS_KEY"] = peer_minio.config.get("MINIO_ROOT_USER", "minioadmin")
                env["S3_SECRET_KEY"] = peer_minio.config.get("MINIO_ROOT_PASSWORD", "minioadmin")
            if not str(env.get("TRINO_CATALOG", "") or "").strip():
                env["TRINO_CATALOG"] = resolve_minio_peer_aistor_catalog_name(demo, peer_id)

    trino_node = next((n for n in demo.nodes if n.component == "trino"), None)
    if trino_node and not str(env.get("TRINO_WEB_URL", "") or "").strip():
        nc = node.config or {}
        if not str(nc.get("TRINO_WEB_URL", "") or "").strip():
            env["TRINO_WEB_URL"] = f"http://{project_name}-{trino_node.id}:8080"


