"""Generate docker-compose.yml from a demo definition."""
import os
import logging
import yaml
from jinja2 import Environment, FileSystemLoader
from ..models.demo import DemoDefinition
from ..registry.loader import get_component
from ..config.license_store import license_store

logger = logging.getLogger(__name__)

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


def generate_compose(demo: DemoDefinition, output_dir: str, components_dir: str = "./components") -> str:
    """
    Generate a docker-compose.yml for the given demo.
    Returns the path to the generated file.
    """
    project_name = f"demoforge-{demo.id}"

    # Build network map from demo.networks list
    network_map = {net.name: f"{project_name}-{net.name}" for net in demo.networks}

    # Cluster coordination: build coordinated commands for cluster group members
    cluster_commands: dict[str, list[str]] = {}
    cluster_health_override: dict[str, str] = {}
    cluster_credentials: dict[str, dict[str, str]] = {}
    cluster_drives: dict[str, int] = {}

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

        # Build service definition
        service = {
            "image": manifest.image,
            "container_name": container_name,
            "expose": [str(p.container) for p in manifest.ports],
            "environment": env,
            "mem_limit": manifest.resources.memory,
            "cpus": manifest.resources.cpu,
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
            service["healthcheck"] = {
                "test": ["CMD", "curl", "-sf", f"http://localhost:{hc.port}{endpoint}"],
                "interval": hc.interval,
                "timeout": hc.timeout,
                "retries": 3,
                "start_period": "10s",
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
        component_dir = os.path.join(components_dir, node.component)
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
    return output_path
