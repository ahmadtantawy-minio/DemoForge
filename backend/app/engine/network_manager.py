"""Create/remove Docker networks, join/disconnect backend container."""
import docker
from docker.errors import NotFound, APIError

docker_client = docker.from_env()


def _find_self_container_id() -> str | None:
    """Find the DemoForge backend container by its label."""
    containers = docker_client.containers.list(
        filters={"label": "demoforge.role=backend"}
    )
    if containers:
        return containers[0].id
    return None


def join_network(network_name: str):
    """Connect the backend container to a demo network."""
    self_id = _find_self_container_id()
    if not self_id:
        return
    try:
        network = docker_client.networks.get(network_name)
        network.connect(self_id)
    except APIError:
        pass  # May already be connected


def leave_network(network_name: str):
    """Disconnect the backend container from a demo network."""
    self_id = _find_self_container_id()
    if not self_id:
        return
    try:
        network = docker_client.networks.get(network_name)
        network.disconnect(self_id)
    except (NotFound, APIError):
        pass


def leave_all_networks(network_names: list[str]):
    """Disconnect the backend from multiple demo networks."""
    for net_name in network_names:
        leave_network(net_name)


def remove_network(network_name: str):
    """Remove a Docker network by name."""
    try:
        network = docker_client.networks.get(network_name)
        network.remove()
    except (NotFound, APIError):
        pass
