"""Generate docker-compose.yml from a demo definition."""
import os
import re
import logging
import yaml
from jinja2 import Environment, FileSystemLoader
from ..models.demo import DemoDefinition, DemoNode, DemoEdge, NodePosition
from ..registry.loader import get_component
from ..config.license_store import license_store

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
    import docker as _docker

    # Quick sanity check: HOST_DATA_DIR should end with /data, not /frontend/data etc.
    if HOST_DATA_DIR and not HOST_DATA_DIR.rstrip("/").endswith("/data"):
        logger.warning(f"HOST_DATA_DIR looks suspicious: {HOST_DATA_DIR}")

    try:
        client = _docker.from_env()
        # Find our own container by the demoforge.role=backend label
        containers = client.containers.list(filters={"label": "demoforge.role=backend"})
        if not containers:
            return
        backend = containers[0]
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


def _render_templates(template_dir, node, demo, output_dir, project_name, manifest):
    env = Environment(loader=FileSystemLoader(template_dir))
    results = []
    for tm in manifest.template_mounts:
        template = env.get_template(tm.template)
        rendered = template.render(
            node=node, demo=demo, nodes=demo.nodes,
            edges=demo.edges, project_name=project_name,
        )
        host_path = os.path.join(output_dir, project_name, node.id, tm.template.removesuffix(".j2"))
        os.makedirs(os.path.dirname(host_path), exist_ok=True)
        with open(host_path, "w") as f:
            f.write(rendered)
        results.append((os.path.abspath(host_path), tm.mount_path))
    return results


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
        drives = cluster.drives_per_node
        total_drives = cluster.node_count * drives
        if total_drives < 4:
            # Auto-adjust drives_per_node to meet minimum 4-drive EC requirement
            drives = max(drives, 4 // cluster.node_count)
            total_drives = cluster.node_count * drives
            if total_drives < 4:
                raise ValueError(
                    f"Cluster '{cluster.id}' needs at least 2 nodes for erasure coding."
                )
            logger.info(f"Cluster '{cluster.id}': auto-adjusted to {drives} drive(s) per node for EC minimum")
        cred_user = cluster.credentials.get("root_user", "minioadmin")
        cred_pass = cluster.credentials.get("root_password", "minioadmin")

        # Build node IDs and network alias prefix for expansion notation
        alias_prefix = f"minio-{cluster.id.replace('-', '')}"
        for i in range(1, cluster.node_count + 1):
            node_id = f"{cluster.id}-node-{i}"
            generated_ids.append(node_id)

        cluster_edge_expansion[cluster.id] = generated_ids

        # Single expansion URL for one erasure-coded pool
        n = cluster.node_count
        if drives > 1:
            expansion_url = f"http://{alias_prefix}{{1...{n}}}:9000/data{{1...{drives}}}"
        else:
            expansion_url = f"http://{alias_prefix}{{1...{n}}}:9000/data"

        # Create synthetic DemoNode entries with network aliases
        for i, node_id in enumerate(generated_ids):
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
                display_name=f"Node {i + 1}",
            )
            # Store network alias for compose generation
            synthetic_node.labels = {"_cluster_alias": f"{alias_prefix}{i + 1}"}
            demo.nodes.append(synthetic_node)

        # --- Embedded NGINX load balancer for the cluster ---
        lb_node_id = f"{cluster.id}-lb"
        lb_node = DemoNode(
            id=lb_node_id,
            component="nginx",
            variant="load-balancer",
            position=NodePosition(x=cluster.position.x - 200,
                                  y=cluster.position.y + 50),
            config={},
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

        # Register cluster commands — single expansion URL = single erasure-coded pool
        server_cmd = ["server", expansion_url, "--console-address", ":9001"]
        for node_id in generated_ids:
            cluster_commands[node_id] = server_cmd
            cluster_health_override[node_id] = "/minio/health/cluster"
            cluster_credentials[node_id] = {
                "MINIO_ROOT_USER": cred_user,
                "MINIO_ROOT_PASSWORD": cred_pass,
            }
            cluster_drives[node_id] = drives

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

        component_dir = os.path.join(components_dir, node.component)
        service_name = node.id
        container_name = f"{project_name}-{node.id}"

        # Check cluster coordination first
        if node.id in cluster_commands:
            command = cluster_commands[node.id]
        else:
            variant = manifest.variants.get(node.variant)
            command = variant.command if variant and variant.command else manifest.command

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

        # Inject license keys (before node.config overrides)
        node_edition = node.config.get("MINIO_EDITION", "ce")
        is_cluster_node = node.variant == "cluster"
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
                env[lic_req.env_var] = entry.value
            elif entry and lic_req.injection_type == "file_mount" and lic_req.mount_path:
                lic_file = os.path.join(output_dir, project_name, node.id, "license.key")
                os.makedirs(os.path.dirname(lic_file), exist_ok=True)
                with open(lic_file, "w") as f:
                    f.write(entry.value)
                # Volume added later after service_volumes is built

        if node.id in cluster_credentials:
            env.update(cluster_credentials[node.id])

        env.update(node.config)

        # Auto-resolve S3 endpoint from s3/structured-data/file-push edges
        s3_edge_types = ("s3", "structured-data", "file-push", "aistor-tables")
        for edge in demo.edges:
            if edge.connection_type not in s3_edge_types:
                continue
            # Determine the MinIO peer: if this node is target, peer is source; if source, peer is target
            if edge.target == node.id:
                peer_id = edge.source
            elif edge.source == node.id:
                peer_id = edge.target
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
        if node.component == "data-generator" and "ICEBERG_CATALOG_URI" not in env:
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

            if target_cluster_id:
                target_cluster = next((c for c in demo.clusters if c.id == target_cluster_id), None)
                if target_cluster and getattr(target_cluster, 'aistor_tables_enabled', False):
                    # AIStor Tables: use the cluster's /_iceberg endpoint
                    env["ICEBERG_CATALOG_URI"] = f"http://{project_name}-{target_lb_id or target_cluster_id + '-lb'}:80/_iceberg"
                    env["ICEBERG_WAREHOUSE"] = target_cluster.config.get("ICEBERG_WAREHOUSE", "analytics")
                    env["ICEBERG_SIGV4"] = "true"
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

        # Auto-inject TRINO_HOST for data generators if a Trino node exists in the demo
        if node.component == "data-generator" and "TRINO_HOST" not in env:
            trino_node = next((n for n in demo.nodes if n.component == "trino"), None)
            if trino_node:
                env["TRINO_HOST"] = f"{project_name}-{trino_node.id}"

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

        # Resolve image — allow edition override for MinIO nodes
        image = manifest.image
        if node.component == "minio":
            edition = node.config.get("MINIO_EDITION", "ce")
            if edition == "aistor":
                image = "quay.io/minio/aistor/minio:latest"

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
            service["healthcheck"] = {
                "test": ["CMD-SHELL", f"curl -sf {health_url} || wget -qO- {health_url} || bash -c 'echo > /dev/tcp/localhost/{hc.port}'"],
                "interval": hc.interval,
                "timeout": hc.timeout,
                "retries": 3,
                "start_period": hc.start_period if hasattr(hc, 'start_period') else "15s",
            }

        # Named volumes
        service_volumes = []
        if manifest.volumes:
            for vol in manifest.volumes:
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
                node_id = f"{cluster.id}-node-1"
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

        lines.append("echo 'mc aliases configured.'")

        # Metabase setup is handled by a separate sidecar (see below)

        lines.append("sleep infinity")
        with open(init_script_path, "w") as f:
            f.write("\n".join(lines) + "\n")
        os.chmod(init_script_path, 0o755)

        init_host_path = _to_host_path(os.path.abspath(init_script_path), "data")

        # Use AIStor mc image if any cluster has AIStor features (mc table commands)
        has_aistor = any(getattr(c, 'aistor_tables_enabled', False) for c in demo.clusters) or any(
            n.config.get("MINIO_EDITION", "ce") == "aistor" for n in demo.nodes if n.component == "minio"
        )
        mc_image = "quay.io/minio/aistor/mc:latest" if has_aistor else "minio/mc:latest"

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
            "volumes": [f"{init_host_path}:/etc/mc-shell/init.sh:ro"],
            "restart": "unless-stopped",
        }

        logger.info(f"Added mc-shell service for demo {demo.id} with {len(demo.clusters)} cluster alias(es)")

    # --- metabase-init: setup sidecar when Metabase is in the demo ---
    if metabase_node:
        trino_edge = next((e for e in demo.edges if e.target == metabase_node.id and e.connection_type == "sql-query"), None)
        trino_node = next((n for n in demo.nodes if trino_edge and n.id == trino_edge.source), None)
        metabase_host = f"{project_name}-{metabase_node.id}"
        trino_host = f"{project_name}-{trino_node.id}" if trino_node else ""
        catalog = trino_edge.connection_config.get("catalog", "iceberg") if trino_edge else "iceberg"
        schema = trino_edge.connection_config.get("schema", "analytics") if trino_edge else "analytics"

        components_dir = os.environ.get("DEMOFORGE_COMPONENTS_DIR", "./components")
        setup_script = os.path.join(os.path.abspath(components_dir), "metabase", "init", "setup-metabase.sh")
        if os.path.exists(setup_script):
            setup_host_path = _to_host_path(setup_script, "components")
            init_networks = {docker_net_name: None for docker_net_name in network_map.values()}

            services["metabase-init"] = {
                "image": "alpine:3.19",
                "container_name": f"{project_name}-metabase-init",
                "entrypoint": ["/bin/sh", "/setup/setup-metabase.sh"],
                "environment": {
                    "METABASE_HOST": metabase_host,
                    "TRINO_HOST": trino_host,
                    "TRINO_CATALOG": catalog,
                    "TRINO_SCHEMA": schema,
                },
                "mem_limit": "64m",
                "cpus": 0.1,
                "labels": {
                    "demoforge.demo": demo.id,
                    "demoforge.node": "metabase-init",
                    "demoforge.component": "metabase-init",
                },
                "networks": init_networks,
                "volumes": [f"{setup_host_path}:/setup/setup-metabase.sh:ro"],
                "restart": "no",
                "depends_on": [metabase_node.id],
            }
            logger.info(f"Added metabase-init sidecar for demo {demo.id}")

    # --- mcp-server: one MCP sidecar per MinIO cluster for AI tool access ---
    if demo.clusters:
        for cluster in [c for c in demo.clusters if c.mcp_enabled]:
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

    # Compose file structure
    compose = {
        "version": "3.8",
        "services": services,
        "networks": compose_networks,
    }

    # Add named volumes
    volumes = {}
    for node in demo.nodes:
        manifest = get_component(node.component)
        if manifest:
            for vol in manifest.volumes:
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
