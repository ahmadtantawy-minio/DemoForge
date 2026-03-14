"""Generate docker-compose.yml from a demo definition."""
import os
import logging
import yaml
from jinja2 import Environment, FileSystemLoader
from ..models.demo import DemoDefinition
from ..registry.loader import get_component

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

    services = {}
    for node in demo.nodes:
        manifest = get_component(node.component)
        if manifest is None:
            raise ValueError(f"Unknown component: {node.component}")

        service_name = node.id
        container_name = f"{project_name}-{node.id}"

        # Determine command from variant
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

        # Healthcheck
        if manifest.health_check:
            hc = manifest.health_check
            service["healthcheck"] = {
                "test": ["CMD", "curl", "-sf", f"http://localhost:{hc.port}{hc.endpoint}"],
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

        if service_volumes:
            service["volumes"] = service_volumes

        services[service_name] = service

    # Top-level networks block with IPAM config
    # Auto-assign unique subnets when multiple networks share the same default
    compose_networks = {}
    used_subnets: set[str] = set()
    subnet_counter = 20  # Start at 172.20.x.0/24
    for net in demo.networks:
        docker_net_name = network_map[net.name]
        subnet = net.subnet
        # If this subnet is already used by another network, auto-increment
        while subnet in used_subnets:
            subnet_counter += 1
            subnet = f"172.{subnet_counter}.0.0/16"
        used_subnets.add(subnet)
        net_def: dict = {
            "driver": net.driver,
            "name": docker_net_name,
        }
        if subnet:
            net_def["ipam"] = {
                "config": [{"subnet": subnet}]
            }
        compose_networks[docker_net_name] = net_def

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
    if volumes:
        compose["volumes"] = volumes

    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{project_name}.yml")
    with open(output_path, "w") as f:
        yaml.dump(compose, f, default_flow_style=False, sort_keys=False)

    logger.info(f"Generated compose file: {output_path}")
    return output_path
