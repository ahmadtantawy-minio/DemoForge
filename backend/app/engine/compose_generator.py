"""Generate docker-compose.yml from a demo definition."""
import os
import yaml
from ..models.demo import DemoDefinition
from ..models.component import ComponentManifest
from ..registry.loader import get_component

def generate_compose(demo: DemoDefinition, output_dir: str) -> str:
    """
    Generate a docker-compose.yml for the given demo.
    Returns the path to the generated file.
    """
    project_name = f"demoforge-{demo.id}"
    network_name = f"{project_name}-net"

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
            "networks": [network_name],
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

        # Volumes
        if manifest.volumes:
            service["volumes"] = []
            for vol in manifest.volumes:
                vol_name = f"{project_name}-{node.id}-{vol.name}"
                service["volumes"].append(f"{vol_name}:{vol.path}")

        services[service_name] = service

    # Compose file structure
    compose = {
        "version": "3.8",
        "services": services,
        "networks": {
            network_name: {
                "driver": "bridge",
                "name": network_name,
            }
        },
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

    return output_path
