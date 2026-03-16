"""Generate docker-compose.yml from a demo definition."""
import os
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
HOST_COMPONENTS_DIR = os.environ.get("DEMOFORGE_HOST_COMPONENTS_DIR", "")
HOST_DATA_DIR = os.environ.get("DEMOFORGE_HOST_DATA_DIR", "")


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
        for lic_req in manifest.license_requirements:
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

        # Auto-resolve S3 endpoint from s3 edges for components that accept s3
        for edge in demo.edges:
            if edge.target == node.id and edge.connection_type == "s3":
                s3_service_name = edge.source  # service name in compose
                s3_port = 9000
                # Find the source node's manifest to get the correct port
                source_manifest = get_component(
                    next((n.component for n in demo.nodes if n.id == edge.source), "")
                )
                if source_manifest:
                    for p in source_manifest.ports:
                        if p.name in ("api", "s3", "http") and p.container == 9000:
                            s3_port = p.container
                            break
                s3_endpoint = f"http://{s3_service_name}:{s3_port}"
                # Inject S3 endpoint for known env var patterns
                s3_env_keys = {
                    "CATALOG_S3_ENDPOINT": s3_endpoint,
                }
                for env_key, env_val in s3_env_keys.items():
                    if env_key in env:
                        env[env_key] = env_val
                break  # Use first s3 edge

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

        # Build service definition
        service = {
            "image": manifest.image,
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

        # Healthcheck
        if manifest.health_check:
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
    if demo.clusters:
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
            alias_name = cluster.label.replace(" ", "_").replace("-", "_")
            lb_url = f"http://{project_name}-{cluster.id}-lb:80"
            cred_user = cluster.credentials.get("root_user", "minioadmin")
            cred_pass = cluster.credentials.get("root_password", "minioadmin")
            lines.append(f"# Retry alias setup for {alias_name}")
            lines.append(f"for attempt in 1 2 3 4 5 6 7 8 9 10; do")
            lines.append(f"  mc alias set '{alias_name}' '{lb_url}' '{cred_user}' '{cred_pass}' 2>/dev/null && break")
            lines.append(f"  echo 'Waiting for {alias_name}... attempt $attempt'")
            lines.append(f"  sleep 10")
            lines.append(f"done")
        lines.append("echo 'mc aliases configured.'")
        lines.append("sleep infinity")
        with open(init_script_path, "w") as f:
            f.write("\n".join(lines) + "\n")
        os.chmod(init_script_path, 0o755)

        init_host_path = _to_host_path(os.path.abspath(init_script_path), "data")

        services["mc-shell"] = {
            "image": "minio/mc:latest",
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
    with open(output_path, "w") as f:
        yaml.dump(compose, f, default_flow_style=False, sort_keys=False)

    logger.info(f"Generated compose file: {output_path}")
    return output_path, demo
