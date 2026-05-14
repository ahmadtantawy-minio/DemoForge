"""Create/remove Docker networks, join/disconnect backend container."""

from __future__ import annotations

import logging
import socket

import docker
from docker.errors import NotFound, APIError

docker_client = docker.from_env()
logger = logging.getLogger(__name__)


def find_self_backend_container():
    """Return **this** backend container when multiple stacks run (FA + dev, FA + fa-local).

    All stacks use ``demoforge.role=backend``; ``containers[0]`` is arbitrary and can attach
    the wrong container to demo networks — breaking ``/proxy`` (502/500 from unreachable UIs).
    Docker sets each container's ``Config.Hostname`` to a unique value; it matches
    ``socket.gethostname()`` inside this process.
    """
    try:
        my_hostname = socket.gethostname()
    except Exception:
        my_hostname = None
    try:
        containers = docker_client.containers.list(
            filters={"label": "demoforge.role=backend"}
        )
    except Exception as e:
        logger.debug("list backend containers: %s", e)
        return None
    if not containers:
        return None
    if my_hostname:
        for c in containers:
            ch = (c.attrs.get("Config") or {}).get("Hostname")
            if ch == my_hostname:
                return c
    if len(containers) == 1:
        return containers[0]
    logger.warning(
        "Multiple backend containers with demoforge.role=backend (%s) but hostname %r matched none",
        [c.name for c in containers],
        my_hostname,
    )
    return None


def _find_self_container_id() -> str | None:
    c = find_self_backend_container()
    return c.id if c else None


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
