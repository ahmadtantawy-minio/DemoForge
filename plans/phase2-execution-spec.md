# DemoForge — Phase 2 Execution Spec

This is the build spec for Phase 2. Follow the steps in exact order within each stream.
Streams 1, 2, and 3 can execute in parallel, but steps within a stream are sequential.

---

## 0. Constraints

- **Runtime**: Docker Compose v2, laptop target (16GB RAM, 8 cores).
- **No host port exposure from demo containers** — all component UIs accessed through DemoForge reverse proxy.
- **Backend joins ALL of a demo's Docker networks** at deploy time for multi-site proxy support.
- **Phase 2 scope**: Multi-instance demos with typed connections, replication, monitoring stack (Prometheus + Grafana), multi-network support, animated edges, and Control Plane v2.
- **Deliverable**: Deploy a 3-site replication demo with monitoring, and manage all instances from Control Plane.

---

## 0.1 Dependency Map

```
Stream 1 (Backend):     Step 1 -> Step 2 -> Step 3 -> Step 4
Stream 2 (Components):  Step 5 -> Step 6 -> Step 7 -> Step 8
Stream 3 (Frontend):    Step 9 -> Step 10 -> Step 11 -> Step 12 -> Step 13
Cross-stream:           Step 14 (Integration test) depends on ALL other steps
```

---

# STREAM 1: BACKEND

---

## Step 1: Update Backend Models for Multi-Network and Typed Connections

**Depends on**: Nothing (start immediately)

### Step 1.1 — Update `backend/app/models/demo.py` (REPLACE entire file)

```python
"""Pydantic models for demo definitions (saved/loaded as YAML)."""
from pydantic import BaseModel

class NodePosition(BaseModel):
    x: float
    y: float

class NodeNetworkConfig(BaseModel):
    ip: str | None = None
    aliases: list[str] = []

class DemoNode(BaseModel):
    id: str                       # Unique within demo, e.g. "minio-1"
    component: str                # Component manifest ID, e.g. "minio"
    variant: str = "single"       # Which variant from the manifest
    position: NodePosition
    config: dict[str, str] = {}   # Override environment variables
    network: NodeNetworkConfig = NodeNetworkConfig()
    site: str = "default"         # Which site/network this node belongs to

class DemoEdge(BaseModel):
    id: str
    source: str                   # Node ID
    target: str                   # Node ID
    connection_type: str = "default"  # "s3", "jdbc", "metrics", "http"
    label: str = ""
    animated: bool = True         # Whether to show flow animation

class DemoNetwork(BaseModel):
    name: str
    subnet: str = "172.20.0.0/16"
    dns_suffix: str = "demo.local"

class DemoSite(BaseModel):
    """A site is a logical grouping with its own Docker network."""
    name: str                     # "site-a", "site-b", "site-c"
    network: DemoNetwork
    label: str = ""               # Human-readable, e.g. "US-East"

class DemoDefinition(BaseModel):
    """Complete demo definition — serializable to/from YAML."""
    id: str
    name: str
    description: str = ""
    network: DemoNetwork = DemoNetwork(name="default")
    sites: list[DemoSite] = []
    nodes: list[DemoNode] = []
    edges: list[DemoEdge] = []

    def get_all_networks(self) -> list[DemoNetwork]:
        if self.sites:
            return [s.network for s in self.sites]
        return [self.network]

    def get_all_network_names(self) -> list[str]:
        return [n.name for n in self.get_all_networks()]

    def get_node_network(self, node: "DemoNode") -> DemoNetwork:
        if self.sites:
            for site in self.sites:
                if site.name == node.site:
                    return site.network
            return self.sites[0].network if self.sites else self.network
        return self.network
```

### Step 1.2 — Update `backend/app/models/component.py` (REPLACE entire file)

```python
"""Pydantic models for component manifests (parsed from YAML)."""
from pydantic import BaseModel

class PortDef(BaseModel):
    name: str
    container: int
    protocol: str = "tcp"

class ResourceDef(BaseModel):
    memory: str = "256m"
    cpu: float = 0.5

class VolumeDef(BaseModel):
    name: str
    path: str
    size: str = "1g"

class HealthCheckDef(BaseModel):
    endpoint: str
    port: int
    interval: str = "10s"
    timeout: str = "5s"

class SecretDef(BaseModel):
    key: str
    label: str
    default: str | None = None
    required: bool = True

class WebUIDef(BaseModel):
    name: str
    port: int
    path: str = "/"
    description: str = ""

class QuickActionDef(BaseModel):
    label: str
    command: str

class TerminalDef(BaseModel):
    shell: str = "/bin/sh"
    welcome_message: str = ""
    quick_actions: list[QuickActionDef] = []

class ConnectionProvides(BaseModel):
    type: str                     # "s3", "metrics", "jdbc", "http"
    port: int
    description: str = ""
    path: str = ""

class ConnectionAccepts(BaseModel):
    type: str
    description: str = ""

class ConnectionsDef(BaseModel):
    provides: list[ConnectionProvides] = []
    accepts: list[ConnectionAccepts] = []

class VariantDef(BaseModel):
    description: str = ""
    command: list[str] | None = None
    replicas: int = 1

class InitScriptDef(BaseModel):
    """Post-deploy init script run via docker exec."""
    name: str
    description: str = ""
    command: list[str]
    wait_for_healthy: bool = True
    delay_seconds: int = 5
    run_on: str = "self"
    requires_nodes: list[str] = []

class ConfigTemplateDef(BaseModel):
    """Jinja2 config template rendered with topology context."""
    source: str                   # Relative path to .j2 template
    destination: str              # Path inside container
    description: str = ""

class ComponentManifest(BaseModel):
    id: str
    name: str
    category: str
    icon: str = ""
    version: str = ""
    image: str
    description: str = ""
    resources: ResourceDef = ResourceDef()
    ports: list[PortDef] = []
    environment: dict[str, str] = {}
    volumes: list[VolumeDef] = []
    command: list[str] = []
    health_check: HealthCheckDef | None = None
    secrets: list[SecretDef] = []
    web_ui: list[WebUIDef] = []
    terminal: TerminalDef = TerminalDef()
    connections: ConnectionsDef = ConnectionsDef()
    variants: dict[str, VariantDef] = {}
    init_scripts: list[InitScriptDef] = []
    config_templates: list[ConfigTemplateDef] = []
```

### Step 1.3 — Update `backend/app/models/api_models.py` (REPLACE entire file)

```python
"""Request/response models for all API endpoints."""
from pydantic import BaseModel
from enum import Enum

class ConnectionTypeInfo(BaseModel):
    type: str
    port: int
    description: str

class ComponentSummary(BaseModel):
    id: str
    name: str
    category: str
    icon: str
    description: str
    variants: list[str]
    provides: list[ConnectionTypeInfo] = []
    accepts: list[str] = []

class RegistryResponse(BaseModel):
    components: list[ComponentSummary]

class DemoSummary(BaseModel):
    id: str
    name: str
    description: str
    node_count: int
    status: str

class DemoListResponse(BaseModel):
    demos: list[DemoSummary]

class CreateDemoRequest(BaseModel):
    name: str
    description: str = ""
    sites: list[dict] = []

class SaveDiagramRequest(BaseModel):
    nodes: list[dict]
    edges: list[dict]

class DeployResponse(BaseModel):
    demo_id: str
    status: str
    message: str = ""

class ContainerHealthStatus(str, Enum):
    HEALTHY = "healthy"
    STARTING = "starting"
    DEGRADED = "degraded"
    ERROR = "error"
    STOPPED = "stopped"

class WebUILink(BaseModel):
    name: str
    proxy_url: str
    description: str

class ContainerInstance(BaseModel):
    node_id: str
    component_id: str
    container_name: str
    health: ContainerHealthStatus
    web_uis: list[WebUILink]
    has_terminal: bool
    quick_actions: list[dict]
    resource_usage: dict = {}
    site: str = "default"

class InstancesResponse(BaseModel):
    demo_id: str
    status: str
    instances: list[ContainerInstance]

class ExecRequest(BaseModel):
    command: str

class ExecResponse(BaseModel):
    exit_code: int
    stdout: str
    stderr: str

class ConnectionValidationRequest(BaseModel):
    source_component: str
    target_component: str
    connection_type: str

class ConnectionValidationResponse(BaseModel):
    valid: bool
    reason: str = ""
    connection_type: str
    source_port: int | None = None

class InitScriptStatus(BaseModel):
    name: str
    node_id: str
    status: str
    output: str = ""

class InitStatusResponse(BaseModel):
    demo_id: str
    scripts: list[InitScriptStatus]
```

---

## Step 2: Multi-Network Compose Generation and Init Script Runner

**Depends on**: Step 1

### Step 2.1 — Update `backend/app/engine/compose_generator.py` (REPLACE entire file)

```python
"""Generate docker-compose.yml from a demo definition."""
import os
import yaml
import jinja2
from ..models.demo import DemoDefinition, DemoNode
from ..registry.loader import get_component

def _build_template_context(demo: DemoDefinition) -> dict:
    """Build Jinja2 context with full topology info for config templates."""
    project_name = f"demoforge-{demo.id}"
    nodes_by_component: dict[str, list[dict]] = {}
    for node in demo.nodes:
        comp = node.component
        if comp not in nodes_by_component:
            nodes_by_component[comp] = []
        container_name = f"{project_name}-{node.id}"
        manifest = get_component(node.component)
        nodes_by_component[comp].append({
            "node_id": node.id,
            "container_name": container_name,
            "hostname": node.id,
            "site": node.site,
            "config": node.config,
            "ports": {p.name: p.container for p in manifest.ports} if manifest else {},
        })

    edges_ctx = []
    for edge in demo.edges:
        edges_ctx.append({
            "source": edge.source,
            "target": edge.target,
            "type": edge.connection_type,
        })

    return {
        "demo_id": demo.id,
        "demo_name": demo.name,
        "project_name": project_name,
        "nodes": {n.id: {
            "component": n.component,
            "site": n.site,
            "container_name": f"{project_name}-{n.id}",
            "hostname": n.id,
            "config": n.config,
        } for n in demo.nodes},
        "nodes_by_component": nodes_by_component,
        "edges": edges_ctx,
        "sites": [{"name": s.name, "label": s.label} for s in demo.sites] if demo.sites else [{"name": "default", "label": "Default"}],
    }


def _render_config_templates(
    manifest_id: str,
    templates: list,
    context: dict,
    components_dir: str,
    output_dir: str,
    node_id: str,
) -> list[tuple[str, str]]:
    """Render Jinja2 config templates. Returns [(host_path, container_path)]."""
    binds = []
    for tmpl in templates:
        source_path = os.path.join(components_dir, manifest_id, tmpl.source)
        if not os.path.exists(source_path):
            continue
        with open(source_path) as f:
            template_str = f.read()
        env = jinja2.Environment(undefined=jinja2.StrictUndefined)
        rendered = env.from_string(template_str).render(**context, node_id=node_id)
        out_name = f"{node_id}-{os.path.basename(tmpl.source).replace('.j2', '')}"
        out_path = os.path.join(output_dir, out_name)
        with open(out_path, "w") as f:
            f.write(rendered)
        binds.append((out_path, tmpl.destination))
    return binds


def generate_compose(demo: DemoDefinition, output_dir: str) -> str:
    """Generate docker-compose.yml. Supports multi-network (multi-site) demos."""
    project_name = f"demoforge-{demo.id}"
    components_dir = os.environ.get("DEMOFORGE_COMPONENTS_DIR", "./components")

    # Determine networks
    networks_config = {}
    if demo.sites:
        for site in demo.sites:
            net_name = site.network.name
            networks_config[net_name] = {
                "driver": "bridge",
                "name": net_name,
                "ipam": {"config": [{"subnet": site.network.subnet}]},
            }
    else:
        net_name = f"{project_name}-net"
        networks_config[net_name] = {"driver": "bridge", "name": net_name}

    tmpl_context = _build_template_context(demo)

    services = {}
    for node in demo.nodes:
        manifest = get_component(node.component)
        if manifest is None:
            raise ValueError(f"Unknown component: {node.component}")

        service_name = node.id
        container_name = f"{project_name}-{node.id}"

        variant = manifest.variants.get(node.variant)
        command = variant.command if variant and variant.command else manifest.command

        # Merge environment
        env = {}
        for key, val in manifest.environment.items():
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

        # Determine node's network(s)
        if demo.sites:
            node_network = demo.get_node_network(node)
            node_networks = [node_network.name]
        else:
            node_networks = [f"{project_name}-net"]

        service: dict = {
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
                "demoforge.site": node.site,
            },
            "networks": node_networks,
            "restart": "unless-stopped",
        }

        if command:
            service["command"] = command

        if manifest.health_check:
            hc = manifest.health_check
            service["healthcheck"] = {
                "test": ["CMD", "curl", "-sf", f"http://localhost:{hc.port}{hc.endpoint}"],
                "interval": hc.interval,
                "timeout": hc.timeout,
                "retries": 3,
                "start_period": "10s",
            }

        if manifest.volumes:
            service["volumes"] = []
            for vol in manifest.volumes:
                vol_name = f"{project_name}-{node.id}-{vol.name}"
                service["volumes"].append(f"{vol_name}:{vol.path}")

        # Render and mount config templates
        if manifest.config_templates:
            config_dir = os.path.join(output_dir, f"{project_name}-configs")
            os.makedirs(config_dir, exist_ok=True)
            binds = _render_config_templates(
                manifest.id, manifest.config_templates, tmpl_context,
                components_dir, config_dir, node.id,
            )
            if "volumes" not in service:
                service["volumes"] = []
            for host_path, container_path in binds:
                abs_host = os.path.abspath(host_path)
                service["volumes"].append(f"{abs_host}:{container_path}:ro")

        services[service_name] = service

    compose: dict = {"services": services, "networks": networks_config}

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
```

### Step 2.2 — Create `backend/app/engine/init_runner.py` (NEW file)

```python
"""
Post-deploy initialization script runner.
Executes init_scripts from component manifests after containers are healthy.
Used for: replication setup, bucket creation, config pushes, etc.
"""
import asyncio
import logging
from ..state.store import state, InitScriptState
from ..registry.loader import get_component
from .docker_manager import get_container_health, exec_in_container
from ..models.api_models import ContainerHealthStatus

logger = logging.getLogger(__name__)


async def _wait_for_healthy(container_name: str, timeout: int = 120) -> bool:
    elapsed = 0
    while elapsed < timeout:
        health = get_container_health(container_name)
        if health == ContainerHealthStatus.HEALTHY:
            return True
        if health in (ContainerHealthStatus.ERROR, ContainerHealthStatus.STOPPED):
            return False
        await asyncio.sleep(2)
        elapsed += 2
    return False


async def _wait_for_nodes_healthy(demo_id: str, node_ids: list[str], timeout: int = 120) -> bool:
    running = state.get_demo(demo_id)
    if not running:
        return False
    for node_id in node_ids:
        container = running.containers.get(node_id)
        if not container:
            return False
        if not await _wait_for_healthy(container.container_name, timeout):
            return False
    return True


async def run_init_scripts(demo_id: str):
    """Run all init scripts for a deployed demo, respecting dependencies."""
    running = state.get_demo(demo_id)
    if not running:
        return

    scripts_to_run: list[tuple[str, str, object]] = []
    for node_id, container in running.containers.items():
        manifest = get_component(container.component_id)
        if not manifest or not manifest.init_scripts:
            continue
        for script in manifest.init_scripts:
            scripts_to_run.append((node_id, container.container_name, script))

    if not scripts_to_run:
        return

    running.init_scripts = {}
    for node_id, _, script in scripts_to_run:
        key = f"{node_id}:{script.name}"
        running.init_scripts[key] = InitScriptState(name=script.name, node_id=node_id, status="pending")
    state.set_demo(running)

    for node_id, container_name, script in scripts_to_run:
        key = f"{node_id}:{script.name}"
        running.init_scripts[key].status = "running"
        state.set_demo(running)

        try:
            if script.requires_nodes:
                if not await _wait_for_nodes_healthy(demo_id, script.requires_nodes):
                    running.init_scripts[key].status = "failed"
                    running.init_scripts[key].output = "Required nodes not healthy"
                    state.set_demo(running)
                    continue

            if script.wait_for_healthy:
                if not await _wait_for_healthy(container_name):
                    running.init_scripts[key].status = "failed"
                    running.init_scripts[key].output = "Container not healthy"
                    state.set_demo(running)
                    continue

            if script.delay_seconds > 0:
                await asyncio.sleep(script.delay_seconds)

            target = container_name
            if script.run_on != "self":
                target_node = running.containers.get(script.run_on)
                if target_node:
                    target = target_node.container_name

            cmd_str = " ".join(script.command)
            logger.info(f"[{key}] Running: {cmd_str}")
            exit_code, stdout, stderr = await exec_in_container(target, cmd_str)

            if exit_code == 0:
                running.init_scripts[key].status = "success"
                running.init_scripts[key].output = stdout + stderr
            else:
                running.init_scripts[key].status = "failed"
                running.init_scripts[key].output = f"Exit {exit_code}: {stdout}{stderr}"
        except Exception as e:
            running.init_scripts[key].status = "failed"
            running.init_scripts[key].output = str(e)

        state.set_demo(running)
```

### Step 2.3 — Update `backend/app/state/store.py` (REPLACE entire file)

```python
"""In-memory state for running demos."""
from dataclasses import dataclass, field
from ..models.api_models import ContainerHealthStatus

@dataclass
class InitScriptState:
    name: str
    node_id: str
    status: str = "pending"       # "pending", "running", "success", "failed"
    output: str = ""

@dataclass
class RunningContainer:
    node_id: str
    component_id: str
    container_name: str
    networks: list[str]
    site: str = "default"
    health: ContainerHealthStatus = ContainerHealthStatus.STARTING

@dataclass
class RunningDemo:
    demo_id: str
    status: str = "stopped"
    compose_project: str = ""
    networks: list[str] = field(default_factory=list)
    containers: dict[str, RunningContainer] = field(default_factory=dict)
    compose_file_path: str = ""
    init_scripts: dict[str, InitScriptState] = field(default_factory=dict)

class StateStore:
    def __init__(self):
        self.running_demos: dict[str, RunningDemo] = {}

    def get_demo(self, demo_id: str) -> RunningDemo | None:
        return self.running_demos.get(demo_id)

    def set_demo(self, demo: RunningDemo):
        self.running_demos[demo.demo_id] = demo

    def remove_demo(self, demo_id: str):
        self.running_demos.pop(demo_id, None)

    def list_demos(self) -> list[RunningDemo]:
        return list(self.running_demos.values())

state = StateStore()
```

### Step 2.4 — Update `backend/app/engine/docker_manager.py` (REPLACE entire file)

```python
"""Docker operations: compose up/down, container inspection, multi-network."""
import asyncio
import docker
from docker.errors import NotFound, APIError
from ..models.demo import DemoDefinition
from ..state.store import state, RunningDemo, RunningContainer
from ..models.api_models import ContainerHealthStatus
from .compose_generator import generate_compose
from .network_manager import join_network, leave_all_networks
from .init_runner import run_init_scripts

docker_client = docker.from_env()

async def deploy_demo(demo: DemoDefinition, data_dir: str) -> RunningDemo:
    """Generate compose, bring up containers, join all networks, run init scripts."""
    project_name = f"demoforge-{demo.id}"
    all_network_names = demo.get_all_network_names()
    if not all_network_names:
        all_network_names = [f"{project_name}-net"]

    compose_path = generate_compose(demo, data_dir)

    running = RunningDemo(
        demo_id=demo.id, status="deploying",
        compose_project=project_name, networks=all_network_names,
        compose_file_path=compose_path,
    )
    state.set_demo(running)

    proc = await asyncio.create_subprocess_exec(
        "docker", "compose", "-f", compose_path, "-p", project_name, "up", "-d",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        running.status = "error"
        state.set_demo(running)
        raise RuntimeError(f"docker compose up failed: {stderr.decode()}")

    # Join backend to ALL demo networks
    for net_name in all_network_names:
        join_network(net_name)

    containers = docker_client.containers.list(
        filters={"label": f"demoforge.demo={demo.id}"}
    )
    for c in containers:
        node_id = c.labels.get("demoforge.node", "")
        component_id = c.labels.get("demoforge.component", "")
        site = c.labels.get("demoforge.site", "default")
        container_nets = [n for n in all_network_names
                          if n in (c.attrs.get("NetworkSettings", {}).get("Networks", {}))]
        if not container_nets:
            container_nets = all_network_names[:1]
        running.containers[node_id] = RunningContainer(
            node_id=node_id, component_id=component_id,
            container_name=c.name, networks=container_nets, site=site,
        )

    running.status = "running"
    state.set_demo(running)
    asyncio.create_task(run_init_scripts(demo.id))
    return running

async def stop_demo(demo_id: str):
    running = state.get_demo(demo_id)
    if not running:
        return
    leave_all_networks(running.networks)
    if running.compose_file_path:
        proc = await asyncio.create_subprocess_exec(
            "docker", "compose", "-f", running.compose_file_path,
            "-p", running.compose_project, "down", "-v",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
    state.remove_demo(demo_id)

def get_container_health(container_name: str) -> ContainerHealthStatus:
    try:
        c = docker_client.containers.get(container_name)
        if c.status != "running":
            return ContainerHealthStatus.STOPPED
        health = c.attrs.get("State", {}).get("Health", {})
        hs = health.get("Status", "none")
        if hs == "healthy":
            return ContainerHealthStatus.HEALTHY
        elif hs == "starting":
            return ContainerHealthStatus.STARTING
        elif hs == "unhealthy":
            return ContainerHealthStatus.ERROR
        else:
            return ContainerHealthStatus.HEALTHY if c.status == "running" else ContainerHealthStatus.STOPPED
    except NotFound:
        return ContainerHealthStatus.STOPPED

async def restart_container(container_name: str):
    try:
        c = docker_client.containers.get(container_name)
        c.restart(timeout=10)
    except NotFound:
        raise ValueError(f"Container {container_name} not found")

async def exec_in_container(container_name: str, command: str) -> tuple[int, str, str]:
    try:
        c = docker_client.containers.get(container_name)
        result = c.exec_run(["sh", "-c", command], demux=True)
        stdout = result.output[0].decode() if result.output[0] else ""
        stderr = result.output[1].decode() if result.output[1] else ""
        return result.exit_code, stdout, stderr
    except NotFound:
        raise ValueError(f"Container {container_name} not found")
```

---

## Step 3: Update API Routes

**Depends on**: Step 2

### Step 3.1 — Create `backend/app/api/connections.py` (NEW file)

```python
"""Connection validation API — checks if source can connect to target."""
from fastapi import APIRouter
from ..registry.loader import get_component, get_registry
from ..models.api_models import ConnectionValidationRequest, ConnectionValidationResponse

router = APIRouter()

@router.post("/api/connections/validate", response_model=ConnectionValidationResponse)
async def validate_connection(req: ConnectionValidationRequest):
    source = get_component(req.source_component)
    target = get_component(req.target_component)

    if not source:
        return ConnectionValidationResponse(
            valid=False, reason=f"Unknown source: {req.source_component}",
            connection_type=req.connection_type,
        )
    if not target:
        return ConnectionValidationResponse(
            valid=False, reason=f"Unknown target: {req.target_component}",
            connection_type=req.connection_type,
        )

    # Check source provides this type
    source_port = None
    for p in source.connections.provides:
        if p.type == req.connection_type:
            source_port = p.port
            break

    if source_port is None:
        return ConnectionValidationResponse(
            valid=False,
            reason=f"{source.name} does not provide {req.connection_type}",
            connection_type=req.connection_type,
        )

    # Check target accepts this type
    accepted = [a.type for a in target.connections.accepts]
    if req.connection_type not in accepted:
        return ConnectionValidationResponse(
            valid=False,
            reason=f"{target.name} does not accept {req.connection_type}",
            connection_type=req.connection_type,
        )

    return ConnectionValidationResponse(
        valid=True, connection_type=req.connection_type, source_port=source_port,
    )

@router.get("/api/connections/types")
async def list_connection_types():
    """Return all connection types available across all components."""
    types = set()
    for m in get_registry().values():
        for p in m.connections.provides:
            types.add(p.type)
        for a in m.connections.accepts:
            types.add(a.type)
    return {"types": sorted(types)}
```

### Step 3.2 — Update `backend/app/api/demos.py` (REPLACE entire file)

```python
import os
import uuid
import yaml
from fastapi import APIRouter, HTTPException
from ..models.demo import DemoDefinition, DemoNetwork, DemoSite, DemoNode, DemoEdge, NodePosition
from ..models.api_models import (
    DemoListResponse, DemoSummary, CreateDemoRequest, SaveDiagramRequest,
    InitStatusResponse, InitScriptStatus,
)
from ..state.store import state

router = APIRouter()
DEMOS_DIR = os.environ.get("DEMOFORGE_DEMOS_DIR", "./demos")

def _load_demo(demo_id: str) -> DemoDefinition | None:
    path = os.path.join(DEMOS_DIR, f"{demo_id}.yaml")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return DemoDefinition(**yaml.safe_load(f))

def _save_demo(demo: DemoDefinition):
    os.makedirs(DEMOS_DIR, exist_ok=True)
    path = os.path.join(DEMOS_DIR, f"{demo.id}.yaml")
    with open(path, "w") as f:
        yaml.dump(demo.model_dump(), f, default_flow_style=False, sort_keys=False)

@router.get("/api/demos", response_model=DemoListResponse)
async def list_demos():
    demos = []
    if os.path.isdir(DEMOS_DIR):
        for fname in os.listdir(DEMOS_DIR):
            if fname.endswith(".yaml"):
                d = _load_demo(fname.replace(".yaml", ""))
                if d:
                    running = state.get_demo(d.id)
                    demos.append(DemoSummary(
                        id=d.id, name=d.name, description=d.description,
                        node_count=len(d.nodes),
                        status=running.status if running else "stopped",
                    ))
    return DemoListResponse(demos=demos)

@router.post("/api/demos", response_model=DemoSummary)
async def create_demo(req: CreateDemoRequest):
    demo_id = str(uuid.uuid4())[:8]

    sites = []
    if req.sites:
        for i, s in enumerate(req.sites):
            site_name = s.get("name", f"site-{chr(97+i)}")
            subnet = f"172.{20+i}.0.0/16"
            sites.append(DemoSite(
                name=site_name,
                network=DemoNetwork(
                    name=f"demoforge-{demo_id}-{site_name}",
                    subnet=subnet,
                ),
                label=s.get("label", site_name),
            ))

    demo = DemoDefinition(
        id=demo_id, name=req.name, description=req.description,
        network=DemoNetwork(name=f"demoforge-{demo_id}-net"),
        sites=sites,
    )
    _save_demo(demo)
    return DemoSummary(
        id=demo.id, name=demo.name, description=demo.description,
        node_count=0, status="stopped",
    )

@router.get("/api/demos/{demo_id}")
async def get_demo(demo_id: str):
    demo = _load_demo(demo_id)
    if not demo:
        raise HTTPException(404, "Demo not found")
    return demo.model_dump()

@router.put("/api/demos/{demo_id}/diagram")
async def save_diagram(demo_id: str, req: SaveDiagramRequest):
    demo = _load_demo(demo_id)
    if not demo:
        raise HTTPException(404, "Demo not found")

    demo.nodes = []
    for rf_node in req.nodes:
        data = rf_node.get("data", {})
        demo.nodes.append(DemoNode(
            id=rf_node["id"],
            component=data.get("componentId", ""),
            variant=data.get("variant", "single"),
            position=NodePosition(
                x=rf_node.get("position", {}).get("x", 0),
                y=rf_node.get("position", {}).get("y", 0),
            ),
            config=data.get("config", {}),
            site=data.get("site", "default"),
        ))

    demo.edges = []
    for rf_edge in req.edges:
        demo.edges.append(DemoEdge(
            id=rf_edge["id"],
            source=rf_edge["source"],
            target=rf_edge["target"],
            connection_type=rf_edge.get("data", {}).get("connectionType", rf_edge.get("type", "default")),
            label=rf_edge.get("label", ""),
            animated=rf_edge.get("data", {}).get("animated", True),
        ))

    _save_demo(demo)
    return {"status": "saved"}

@router.get("/api/demos/{demo_id}/init-status", response_model=InitStatusResponse)
async def get_init_status(demo_id: str):
    running = state.get_demo(demo_id)
    if not running:
        raise HTTPException(404, "Demo not running")
    scripts = [
        InitScriptStatus(name=s.name, node_id=s.node_id, status=s.status, output=s.output)
        for s in running.init_scripts.values()
    ]
    return InitStatusResponse(demo_id=demo_id, scripts=scripts)

@router.delete("/api/demos/{demo_id}")
async def delete_demo(demo_id: str):
    path = os.path.join(DEMOS_DIR, f"{demo_id}.yaml")
    if os.path.exists(path):
        os.remove(path)
    return {"status": "deleted"}
```

### Step 3.3 — Update `backend/app/api/registry.py` (REPLACE entire file)

```python
from fastapi import APIRouter
from ..registry.loader import get_registry
from ..models.api_models import RegistryResponse, ComponentSummary, ConnectionTypeInfo

router = APIRouter()

@router.get("/api/registry/components", response_model=RegistryResponse)
async def list_components():
    registry = get_registry()
    return RegistryResponse(
        components=[
            ComponentSummary(
                id=m.id, name=m.name, category=m.category,
                icon=m.icon, description=m.description,
                variants=list(m.variants.keys()),
                provides=[
                    ConnectionTypeInfo(type=p.type, port=p.port, description=p.description)
                    for p in m.connections.provides
                ],
                accepts=[a.type for a in m.connections.accepts],
            )
            for m in registry.values()
        ]
    )
```

### Step 3.4 — Update `backend/app/api/instances.py` (REPLACE entire file)

```python
from fastapi import APIRouter, HTTPException
from ..state.store import state
from ..registry.loader import get_component
from ..engine.docker_manager import get_container_health, restart_container, exec_in_container
from ..models.api_models import (
    InstancesResponse, ContainerInstance, WebUILink, ExecRequest, ExecResponse,
)

router = APIRouter()

@router.get("/api/demos/{demo_id}/instances", response_model=InstancesResponse)
async def list_instances(demo_id: str):
    running = state.get_demo(demo_id)
    if not running:
        raise HTTPException(404, "Demo not running")

    instances = []
    for node_id, container in running.containers.items():
        manifest = get_component(container.component_id)
        health = get_container_health(container.container_name)
        container.health = health

        web_uis = []
        if manifest:
            for ui in manifest.web_ui:
                web_uis.append(WebUILink(
                    name=ui.name,
                    proxy_url=f"/proxy/{demo_id}/{node_id}/{ui.name}/",
                    description=ui.description,
                ))

        quick_actions = []
        if manifest:
            quick_actions = [qa.model_dump() for qa in manifest.terminal.quick_actions]

        instances.append(ContainerInstance(
            node_id=node_id, component_id=container.component_id,
            container_name=container.container_name, health=health,
            web_uis=web_uis, has_terminal=True,
            quick_actions=quick_actions, site=container.site,
        ))

    return InstancesResponse(demo_id=demo_id, status=running.status, instances=instances)

@router.post("/api/demos/{demo_id}/instances/{node_id}/restart")
async def restart_instance(demo_id: str, node_id: str):
    running = state.get_demo(demo_id)
    if not running or node_id not in running.containers:
        raise HTTPException(404, "Instance not found")
    await restart_container(running.containers[node_id].container_name)
    return {"status": "restarted"}

@router.post("/api/demos/{demo_id}/instances/{node_id}/exec", response_model=ExecResponse)
async def exec_command(demo_id: str, node_id: str, req: ExecRequest):
    running = state.get_demo(demo_id)
    if not running or node_id not in running.containers:
        raise HTTPException(404, "Instance not found")
    exit_code, stdout, stderr = await exec_in_container(
        running.containers[node_id].container_name, req.command
    )
    return ExecResponse(exit_code=exit_code, stdout=stdout, stderr=stderr)
```

### Step 3.5 — Update `backend/app/main.py` (REPLACE entire file)

```python
import os
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .registry.loader import load_registry
from .engine.health_monitor import health_monitor_loop
from .api import registry, demos, deploy, instances, proxy, terminal, health, connections

@asynccontextmanager
async def lifespan(app: FastAPI):
    components_dir = os.environ.get("DEMOFORGE_COMPONENTS_DIR", "./components")
    load_registry(components_dir)
    monitor_task = asyncio.create_task(health_monitor_loop())
    yield
    monitor_task.cancel()

app = FastAPI(title="DemoForge API", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(registry.router)
app.include_router(demos.router)
app.include_router(deploy.router)
app.include_router(instances.router)
app.include_router(health.router)
app.include_router(terminal.router)
app.include_router(connections.router)
app.include_router(proxy.router)  # Must be last — catch-all pattern
```

---

## Step 4: Backend Replication Script Support

**Depends on**: Step 3

The init_runner (Step 2.2) handles execution generically. Replication scripts are embedded in the MinIO manifest `init_scripts` field (see Step 8). No additional backend code needed for this step -- the architecture is already in place.

The `mc admin replicate` and bucket replication commands will be added as additional init_scripts in the MinIO manifest when the user configures replication edges between MinIO nodes. For Phase 2, the init scripts in Step 8.1 cover alias setup and demo bucket creation. Site replication setup is triggered manually via quick-action chips or terminal.

---

# STREAM 2: COMPONENTS

---

## Step 5: NGINX Load Balancer Component Manifest

**Depends on**: Nothing (start immediately)

### Step 5.1 — Create `components/nginx/manifest.yaml` (NEW file)

```yaml
id: nginx
name: NGINX
category: infra
icon: nginx
version: "1.25"
image: nginx:1.25-alpine
description: "NGINX — load balancer and reverse proxy"

resources:
  memory: "128m"
  cpu: 0.25

ports:
  - name: http
    container: 80
    protocol: tcp
  - name: https
    container: 443
    protocol: tcp

environment:
  NGINX_ENTRYPOINT_QUIET_LOGS: "1"

volumes:
  - name: config
    path: /etc/nginx/conf.d
    size: 100m

health_check:
  endpoint: /health
  port: 80
  interval: 10s
  timeout: 5s

web_ui:
  - name: status
    port: 80
    path: "/"
    description: "NGINX status page"

terminal:
  shell: /bin/sh
  welcome_message: "NGINX container."
  quick_actions:
    - label: "Test config"
      command: "nginx -t"
    - label: "Reload"
      command: "nginx -s reload"

connections:
  provides:
    - type: http
      port: 80
      description: "HTTP load balancer endpoint"
  accepts:
    - type: s3
      description: "Backend S3 endpoints to load-balance"
    - type: http
      description: "Backend HTTP endpoints to proxy"

config_templates:
  - source: templates/default.conf.j2
    destination: /etc/nginx/conf.d/default.conf
    description: "Auto-generated upstream and server config"

variants:
  load-balancer:
    description: "Round-robin load balancer across S3 backends"
  reverse-proxy:
    description: "Path-based reverse proxy to multiple backends"
```

### Step 5.2 — Create `components/nginx/templates/default.conf.j2` (NEW file)

```nginx
# Auto-generated by DemoForge from demo topology

{% set my_edges = edges | selectattr('target', 'equalto', node_id) | list %}
{% set s3_sources = [] %}
{% for edge in my_edges %}
{% if edge.type == 's3' or edge.type == 'http' %}
{% set src_node = nodes[edge.source] %}
{% if src_node %}
{% set _ = s3_sources.append(src_node) %}
{% endif %}
{% endif %}
{% endfor %}

upstream backends {
{% if s3_sources %}
{% for src in s3_sources %}
    server {{ src.hostname }}:9000;
{% endfor %}
{% else %}
    server 127.0.0.1:9000;
{% endif %}
}

server {
    listen 80;
    server_name _;

    location /health {
        access_log off;
        return 200 'OK';
        add_header Content-Type text/plain;
    }

    location / {
        proxy_pass http://backends;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_buffering off;
        client_max_body_size 0;
    }
}
```

---

## Step 6: Prometheus Component Manifest

**Depends on**: Nothing (start immediately)

### Step 6.1 — Create `components/prometheus/manifest.yaml` (NEW file)

```yaml
id: prometheus
name: Prometheus
category: monitoring
icon: prometheus
version: "2.51"
image: prom/prometheus:v2.51.0
description: "Prometheus metrics collection with auto-discovery from demo topology"

resources:
  memory: "512m"
  cpu: 0.5

ports:
  - name: web
    container: 9090
    protocol: tcp

environment: {}

volumes:
  - name: data
    path: /prometheus
    size: 2g

command: ["--config.file=/etc/prometheus/prometheus.yml", "--storage.tsdb.path=/prometheus", "--web.enable-lifecycle"]

health_check:
  endpoint: /-/healthy
  port: 9090
  interval: 10s
  timeout: 5s

web_ui:
  - name: prometheus
    port: 9090
    path: "/"
    description: "Prometheus query UI"

terminal:
  shell: /bin/sh
  welcome_message: "Prometheus container."
  quick_actions:
    - label: "Check targets"
      command: "wget -qO- http://localhost:9090/api/v1/targets | head -100"
    - label: "Reload config"
      command: "wget -qO- --post-data='' http://localhost:9090/-/reload"

connections:
  provides:
    - type: metrics
      port: 9090
      description: "Prometheus query API"
  accepts:
    - type: metrics
      description: "Scrape metrics from targets"

config_templates:
  - source: templates/prometheus.yml.j2
    destination: /etc/prometheus/prometheus.yml
    description: "Auto-generated scrape config from demo topology"

variants:
  default:
    description: "Standard Prometheus instance"
```

### Step 6.2 — Create `components/prometheus/templates/prometheus.yml.j2` (NEW file)

```yaml
# Auto-generated by DemoForge from demo topology
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']

{% set my_edges = edges | selectattr('target', 'equalto', node_id) | list %}
{% set metrics_sources = [] %}
{% for edge in my_edges %}
{% if edge.type == 'metrics' %}
{% set src = nodes[edge.source] %}
{% if src %}
{% set _ = metrics_sources.append(src) %}
{% endif %}
{% endif %}
{% endfor %}

{% if metrics_sources %}
  - job_name: 'minio'
    metrics_path: /minio/v2/metrics/cluster
    scheme: http
    static_configs:
      - targets:
{% for src in metrics_sources %}
        - '{{ src.hostname }}:9000'
{% endfor %}

  - job_name: 'minio-node'
    metrics_path: /minio/v2/metrics/node
    scheme: http
    static_configs:
      - targets:
{% for src in metrics_sources %}
        - '{{ src.hostname }}:9000'
{% endfor %}
{% endif %}
```

---

## Step 7: Grafana Component Manifest with MinIO Dashboard

**Depends on**: Step 6

### Step 7.1 — Create `components/grafana/manifest.yaml` (NEW file)

```yaml
id: grafana
name: Grafana
category: monitoring
icon: grafana
version: "10.4"
image: grafana/grafana:10.4.0
description: "Grafana dashboards with pre-provisioned MinIO overview"

resources:
  memory: "256m"
  cpu: 0.5

ports:
  - name: web
    container: 3001
    protocol: tcp

environment:
  GF_SECURITY_ADMIN_USER: admin
  GF_SECURITY_ADMIN_PASSWORD: admin
  GF_SERVER_HTTP_PORT: "3001"
  GF_AUTH_ANONYMOUS_ENABLED: "true"
  GF_AUTH_ANONYMOUS_ORG_ROLE: Admin
  GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH: /var/lib/grafana/dashboards/minio-overview.json

volumes:
  - name: data
    path: /var/lib/grafana
    size: 1g

health_check:
  endpoint: /api/health
  port: 3001
  interval: 10s
  timeout: 5s

secrets:
  - key: GF_SECURITY_ADMIN_USER
    label: "Admin User"
    default: "admin"
  - key: GF_SECURITY_ADMIN_PASSWORD
    label: "Admin Password"
    default: "admin"

web_ui:
  - name: grafana
    port: 3001
    path: "/"
    description: "Grafana dashboards"

terminal:
  shell: /bin/sh
  welcome_message: "Grafana container."
  quick_actions:
    - label: "List dashboards"
      command: "wget -qO- http://localhost:3001/api/search | head -50"

connections:
  accepts:
    - type: metrics
      description: "Prometheus data source for dashboards"

config_templates:
  - source: templates/datasources.yml.j2
    destination: /etc/grafana/provisioning/datasources/datasources.yml
    description: "Auto-configured Prometheus datasource"
  - source: templates/dashboards.yml.j2
    destination: /etc/grafana/provisioning/dashboards/dashboards.yml
    description: "Dashboard provisioning config"

init_scripts:
  - name: copy-dashboards
    description: "Copy pre-built dashboards into Grafana"
    command: ["sh", "-c", "mkdir -p /var/lib/grafana/dashboards && cp /etc/grafana/dashboards/*.json /var/lib/grafana/dashboards/ 2>/dev/null || true"]
    wait_for_healthy: false
    delay_seconds: 0

variants:
  default:
    description: "Grafana with MinIO dashboards"
```

### Step 7.2 — Create `components/grafana/templates/datasources.yml.j2` (NEW file)

```yaml
# Auto-generated by DemoForge
apiVersion: 1
datasources:
{% set my_edges = edges | selectattr('target', 'equalto', node_id) | list %}
{% set prom_sources = [] %}
{% for edge in my_edges %}
{% if edge.type == 'metrics' %}
{% set src = nodes[edge.source] %}
{% if src %}
{% set _ = prom_sources.append(src) %}
{% endif %}
{% endif %}
{% endfor %}
{% if prom_sources %}
{% for src in prom_sources %}
  - name: {{ src.hostname }}
    type: prometheus
    access: proxy
    url: http://{{ src.hostname }}:9090
    isDefault: {{ loop.first | lower }}
    editable: true
{% endfor %}
{% else %}
  - name: prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
    editable: true
{% endif %}
```

### Step 7.3 — Create `components/grafana/templates/dashboards.yml.j2` (NEW file)

```yaml
apiVersion: 1
providers:
  - name: default
    orgId: 1
    folder: ''
    type: file
    disableDeletion: false
    updateIntervalSeconds: 30
    options:
      path: /var/lib/grafana/dashboards
      foldersFromFilesStructure: false
```

### Step 7.4 — Create `components/grafana/dashboards/minio-overview.json` (NEW file)

```json
{
  "annotations": { "list": [] },
  "editable": true,
  "fiscalYearStartMonth": 0,
  "graphTooltip": 1,
  "id": null,
  "links": [],
  "panels": [
    {
      "datasource": { "type": "prometheus", "uid": "${DS_PROMETHEUS}" },
      "fieldConfig": {
        "defaults": { "color": { "mode": "palette-classic" }, "thresholds": { "mode": "absolute", "steps": [{"color": "green", "value": null}] } },
        "overrides": []
      },
      "gridPos": { "h": 4, "w": 6, "x": 0, "y": 0 },
      "id": 1,
      "options": { "colorMode": "value", "graphMode": "area", "justifyMode": "auto", "textMode": "auto", "reduceOptions": { "calcs": ["lastNotNull"], "fields": "", "values": false } },
      "title": "Total Buckets",
      "type": "stat",
      "targets": [{ "expr": "count(minio_bucket_usage_total_bytes)", "legendFormat": "Buckets", "refId": "A" }]
    },
    {
      "datasource": { "type": "prometheus", "uid": "${DS_PROMETHEUS}" },
      "fieldConfig": { "defaults": { "color": { "mode": "palette-classic" }, "unit": "bytes" }, "overrides": [] },
      "gridPos": { "h": 4, "w": 6, "x": 6, "y": 0 },
      "id": 2,
      "options": { "colorMode": "value", "graphMode": "area", "justifyMode": "auto", "textMode": "auto", "reduceOptions": { "calcs": ["lastNotNull"], "fields": "", "values": false } },
      "title": "Total Storage Used",
      "type": "stat",
      "targets": [{ "expr": "sum(minio_bucket_usage_total_bytes)", "legendFormat": "Total", "refId": "A" }]
    },
    {
      "datasource": { "type": "prometheus", "uid": "${DS_PROMETHEUS}" },
      "fieldConfig": { "defaults": { "color": { "mode": "palette-classic" }, "unit": "short" }, "overrides": [] },
      "gridPos": { "h": 4, "w": 6, "x": 12, "y": 0 },
      "id": 3,
      "options": { "colorMode": "value", "graphMode": "area", "justifyMode": "auto", "textMode": "auto", "reduceOptions": { "calcs": ["lastNotNull"], "fields": "", "values": false } },
      "title": "Total Objects",
      "type": "stat",
      "targets": [{ "expr": "sum(minio_bucket_usage_object_total)", "legendFormat": "Total", "refId": "A" }]
    },
    {
      "datasource": { "type": "prometheus", "uid": "${DS_PROMETHEUS}" },
      "fieldConfig": { "defaults": { "color": { "mode": "palette-classic" }, "unit": "binBps" }, "overrides": [] },
      "gridPos": { "h": 8, "w": 12, "x": 0, "y": 4 },
      "id": 4,
      "options": { "legend": { "displayMode": "list", "placement": "bottom" }, "tooltip": { "mode": "multi" } },
      "title": "S3 Traffic (bytes/sec)",
      "type": "timeseries",
      "targets": [
        { "expr": "sum(rate(minio_s3_traffic_received_bytes_total[5m]))", "legendFormat": "Received", "refId": "A" },
        { "expr": "sum(rate(minio_s3_traffic_sent_bytes_total[5m]))", "legendFormat": "Sent", "refId": "B" }
      ]
    },
    {
      "datasource": { "type": "prometheus", "uid": "${DS_PROMETHEUS}" },
      "fieldConfig": { "defaults": { "color": { "mode": "palette-classic" }, "unit": "ops" }, "overrides": [] },
      "gridPos": { "h": 8, "w": 12, "x": 12, "y": 4 },
      "id": 5,
      "options": { "legend": { "displayMode": "list", "placement": "bottom" }, "tooltip": { "mode": "multi" } },
      "title": "S3 Request Rate",
      "type": "timeseries",
      "targets": [{ "expr": "sum(rate(minio_s3_requests_total[5m])) by (api)", "legendFormat": "{{api}}", "refId": "A" }]
    },
    {
      "datasource": { "type": "prometheus", "uid": "${DS_PROMETHEUS}" },
      "fieldConfig": { "defaults": { "color": { "mode": "palette-classic" }, "unit": "bytes" }, "overrides": [] },
      "gridPos": { "h": 8, "w": 24, "x": 0, "y": 12 },
      "id": 6,
      "options": { "legend": { "displayMode": "list", "placement": "bottom" }, "tooltip": { "mode": "multi" } },
      "title": "Bucket Usage Over Time",
      "type": "timeseries",
      "targets": [{ "expr": "minio_bucket_usage_total_bytes", "legendFormat": "{{bucket}}", "refId": "A" }]
    }
  ],
  "schemaVersion": 39,
  "style": "dark",
  "tags": ["minio"],
  "templating": {
    "list": [
      { "current": {}, "hide": 0, "includeAll": false, "name": "DS_PROMETHEUS", "options": [], "query": "prometheus", "type": "datasource" }
    ]
  },
  "time": { "from": "now-1h", "to": "now" },
  "title": "MinIO Overview",
  "uid": "minio-overview",
  "version": 1
}
```

---

## Step 8: Update MinIO Manifest

**Depends on**: Steps 5-7

### Step 8.1 — Update `components/minio/manifest.yaml` (REPLACE entire file)

```yaml
id: minio
name: MinIO Object Store
category: storage
icon: minio
version: "latest"
image: minio/minio:latest
description: "S3-compatible high-performance object storage"

resources:
  memory: "256m"
  cpu: 0.5

ports:
  - name: api
    container: 9000
    protocol: tcp
  - name: console
    container: 9001
    protocol: tcp

environment:
  MINIO_ROOT_USER: "${MINIO_ROOT_USER:-minioadmin}"
  MINIO_ROOT_PASSWORD: "${MINIO_ROOT_PASSWORD:-minioadmin}"
  MINIO_BROWSER_REDIRECT_URL: ""
  MINIO_PROMETHEUS_AUTH_TYPE: "public"

volumes:
  - name: data
    path: /data
    size: 1g

command: ["server", "/data", "--console-address", ":9001"]

health_check:
  endpoint: /minio/health/live
  port: 9000
  interval: 10s
  timeout: 5s

secrets:
  - key: MINIO_ROOT_USER
    label: "Root User"
    default: "minioadmin"
  - key: MINIO_ROOT_PASSWORD
    label: "Root Password"
    default: "minioadmin"

web_ui:
  - name: console
    port: 9001
    path: "/"
    description: "MinIO Console — bucket management, monitoring, and admin"

terminal:
  shell: /bin/sh
  welcome_message: "MinIO container. 'mc' is available at /usr/bin/mc."
  quick_actions:
    - label: "mc admin info"
      command: "mc alias set local http://localhost:9000 $MINIO_ROOT_USER $MINIO_ROOT_PASSWORD && mc admin info local"
    - label: "mc ls"
      command: "mc alias set local http://localhost:9000 $MINIO_ROOT_USER $MINIO_ROOT_PASSWORD && mc ls local"
    - label: "Create test bucket"
      command: "mc alias set local http://localhost:9000 $MINIO_ROOT_USER $MINIO_ROOT_PASSWORD && mc mb local/test-bucket --ignore-existing"
    - label: "Setup site replication"
      command: "echo 'Use init scripts for automated replication setup'"

connections:
  provides:
    - type: s3
      port: 9000
      description: "S3-compatible API endpoint"
    - type: metrics
      port: 9000
      path: "/minio/v2/metrics/cluster"
      description: "Prometheus metrics endpoint"
  accepts:
    - type: s3
      description: "Replication target (site or bucket replication)"

init_scripts:
  - name: setup-alias
    description: "Configure mc alias for this MinIO instance"
    command: ["sh", "-c", "mc alias set local http://localhost:9000 $MINIO_ROOT_USER $MINIO_ROOT_PASSWORD"]
    wait_for_healthy: true
    delay_seconds: 3

  - name: create-demo-bucket
    description: "Create a default demo bucket"
    command: ["sh", "-c", "mc alias set local http://localhost:9000 $MINIO_ROOT_USER $MINIO_ROOT_PASSWORD && mc mb local/demo-bucket --ignore-existing"]
    wait_for_healthy: true
    delay_seconds: 5

variants:
  single:
    description: "Single node, single drive"
    command: ["server", "/data", "--console-address", ":9001"]
  distributed:
    description: "4-drive erasure coding (simulated)"
    command: ["server", "/data{1...4}", "--console-address", ":9001"]
```

---

# STREAM 3: FRONTEND

---

## Step 9: Update Frontend Types

**Depends on**: Step 1

### Step 9.1 — Update `frontend/src/types/index.ts` (REPLACE entire file)

```typescript
// --- Registry ---
export interface ConnectionTypeInfo {
  type: string;
  port: number;
  description: string;
}

export interface ComponentSummary {
  id: string;
  name: string;
  category: string;
  icon: string;
  description: string;
  variants: string[];
  provides: ConnectionTypeInfo[];
  accepts: string[];
}

// --- Demo ---
export interface DemoSummary {
  id: string;
  name: string;
  description: string;
  node_count: number;
  status: "stopped" | "deploying" | "running" | "error";
}

// --- Instances ---
export interface WebUILink {
  name: string;
  proxy_url: string;
  description: string;
}

export interface QuickAction {
  label: string;
  command: string;
}

export type HealthStatus = "healthy" | "starting" | "degraded" | "error" | "stopped";

export interface ContainerInstance {
  node_id: string;
  component_id: string;
  container_name: string;
  health: HealthStatus;
  web_uis: WebUILink[];
  has_terminal: boolean;
  quick_actions: QuickAction[];
  resource_usage?: Record<string, number>;
  site: string;
}

// --- Connection Types ---
export type ConnectionType = "s3" | "jdbc" | "metrics" | "http" | "default";

export const CONNECTION_COLORS: Record<ConnectionType, string> = {
  s3: "#10b981",
  jdbc: "#6366f1",
  metrics: "#f59e0b",
  http: "#3b82f6",
  default: "#9ca3af",
};

export const CONNECTION_LABELS: Record<ConnectionType, string> = {
  s3: "S3",
  jdbc: "JDBC",
  metrics: "Metrics",
  http: "HTTP",
  default: "Connection",
};

// --- React Flow node data ---
export interface ComponentNodeData {
  label: string;
  componentId: string;
  variant: string;
  config: Record<string, string>;
  health?: HealthStatus;
  site?: string;
  provides?: ConnectionTypeInfo[];
  accepts?: string[];
}

// --- Context Menu ---
export interface ContextMenuState {
  visible: boolean;
  x: number;
  y: number;
  nodeId: string | null;
  edgeId: string | null;
}

// --- Init Script Status ---
export interface InitScriptStatus {
  name: string;
  node_id: string;
  status: "pending" | "running" | "success" | "failed";
  output: string;
}
```

---

## Step 10: Animated Typed Edge Component

**Depends on**: Step 9

### Step 10.1 — Replace `frontend/src/components/canvas/edges/DataEdge.tsx` (REPLACE entire file)

```tsx
import {
  BaseEdge,
  EdgeLabelRenderer,
  getBezierPath,
  type EdgeProps,
} from "@xyflow/react";
import { CONNECTION_COLORS, CONNECTION_LABELS, type ConnectionType } from "../../../types";

export default function DataEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
  selected,
}: EdgeProps) {
  const connectionType = ((data as any)?.connectionType || "default") as ConnectionType;
  const isAnimated = (data as any)?.animated !== false;
  const color = CONNECTION_COLORS[connectionType] || CONNECTION_COLORS.default;
  const label = CONNECTION_LABELS[connectionType] || connectionType;

  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition,
  });

  const edgeId = `edge-${id}`;
  const particleCount = 3;
  const animDuration = 2;

  return (
    <>
      <defs>
        <linearGradient id={`${edgeId}-gradient`} x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" stopColor={color} stopOpacity="0.2" />
          <stop offset="50%" stopColor={color} stopOpacity="1" />
          <stop offset="100%" stopColor={color} stopOpacity="0.2" />
        </linearGradient>
      </defs>

      <BaseEdge
        id={id}
        path={edgePath}
        style={{ stroke: color, strokeWidth: selected ? 3 : 2, strokeOpacity: 0.6 }}
      />

      {isAnimated && (
        <>
          <path id={`${edgeId}-path`} d={edgePath} fill="none" stroke="none" />
          {Array.from({ length: particleCount }).map((_, i) => (
            <circle key={i} r="3" fill={color} opacity="0.9">
              <animateMotion
                dur={`${animDuration}s`}
                repeatCount="indefinite"
                begin={`${(i * animDuration) / particleCount}s`}
              >
                <mpath href={`#${edgeId}-path`} />
              </animateMotion>
            </circle>
          ))}
        </>
      )}

      <EdgeLabelRenderer>
        <div
          style={{
            position: "absolute",
            transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
            pointerEvents: "all",
          }}
          className="nodrag nopan"
        >
          <span
            style={{
              backgroundColor: color, color: "white",
              fontSize: "10px", fontWeight: 600,
              padding: "1px 6px", borderRadius: "8px", whiteSpace: "nowrap",
            }}
          >
            {label}
          </span>
        </div>
      </EdgeLabelRenderer>
    </>
  );
}
```

---

## Step 11: DiagramCanvas — Connection Validation, Right-Click Context Menu

**Depends on**: Step 10

### Step 11.1 — Create `frontend/src/components/canvas/ContextMenu.tsx` (NEW file)

```tsx
import type { ContextMenuState } from "../../types";
import { useDemoStore } from "../../stores/demoStore";
import { useDiagramStore } from "../../stores/diagramStore";
import { restartInstance } from "../../api/client";

interface Props {
  menu: ContextMenuState;
  onClose: () => void;
  onOpenTerminal: (nodeId: string) => void;
}

export default function ContextMenu({ menu, onClose, onOpenTerminal }: Props) {
  const { activeDemoId, instances } = useDemoStore();
  const { nodes, edges, setNodes, setEdges } = useDiagramStore();

  if (!menu.visible) return null;
  const instance = menu.nodeId ? instances.find((i) => i.node_id === menu.nodeId) : null;

  const handleDeleteNode = () => {
    if (!menu.nodeId) return;
    setNodes(nodes.filter((n) => n.id !== menu.nodeId));
    setEdges(edges.filter((e) => e.source !== menu.nodeId && e.target !== menu.nodeId));
    onClose();
  };

  const handleDeleteEdge = () => {
    if (!menu.edgeId) return;
    setEdges(edges.filter((e) => e.id !== menu.edgeId));
    onClose();
  };

  const handleRestart = () => {
    if (!activeDemoId || !menu.nodeId) return;
    restartInstance(activeDemoId, menu.nodeId);
    onClose();
  };

  const handleOpenTerminal = () => {
    if (!menu.nodeId) return;
    onOpenTerminal(menu.nodeId);
    onClose();
  };

  return (
    <>
      <div className="fixed inset-0 z-40" onClick={onClose} />
      <div
        className="fixed z-50 bg-white border border-gray-200 rounded-lg shadow-lg py-1 min-w-[160px]"
        style={{ left: menu.x, top: menu.y }}
      >
        {menu.nodeId && (
          <>
            {instance && (
              <>
                <button onClick={handleOpenTerminal} className="w-full text-left px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-100">Open Terminal</button>
                <button onClick={handleRestart} className="w-full text-left px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-100">Restart Container</button>
                {instance.web_uis.map((ui) => (
                  <button key={ui.name} onClick={() => { window.open(`http://localhost:8000${ui.proxy_url}`, "_blank"); onClose(); }} className="w-full text-left px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-100">Open {ui.name}</button>
                ))}
                <hr className="my-1 border-gray-200" />
              </>
            )}
            <button onClick={handleDeleteNode} className="w-full text-left px-3 py-1.5 text-sm text-red-600 hover:bg-red-50">Delete Node</button>
          </>
        )}
        {menu.edgeId && (
          <button onClick={handleDeleteEdge} className="w-full text-left px-3 py-1.5 text-sm text-red-600 hover:bg-red-50">Delete Connection</button>
        )}
      </div>
    </>
  );
}
```

### Step 11.2 — Update `frontend/src/components/canvas/nodes/ComponentNode.tsx` (REPLACE entire file)

```tsx
import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { ComponentNodeData } from "../../../types";
import { CONNECTION_COLORS, type ConnectionType } from "../../../types";
import { useDiagramStore } from "../../../stores/diagramStore";
import { useDemoStore } from "../../../stores/demoStore";
import { proxyUrl } from "../../../api/client";

export default function ComponentNode({ id, data }: NodeProps) {
  const nodeData = data as ComponentNodeData;
  const setSelectedNode = useDiagramStore((s) => s.setSelectedNode);
  const { instances, activeDemoId } = useDemoStore();

  const healthColors: Record<string, string> = {
    healthy: "bg-green-500", starting: "bg-yellow-400",
    degraded: "bg-orange-400", error: "bg-red-500", stopped: "bg-gray-400",
  };

  const handleDoubleClick = () => {
    if (!activeDemoId) return;
    const instance = instances.find((i) => i.node_id === id);
    if (instance && instance.web_uis.length > 0) {
      window.open(proxyUrl(instance.web_uis[0].proxy_url), "_blank");
    }
  };

  const provides = nodeData.provides || [];
  const accepts = nodeData.accepts || [];

  const iconMap: Record<string, string> = {
    minio: "\u{1FAA3}", nginx: "\u{1F500}", prometheus: "\u{1F4CA}", grafana: "\u{1F4C8}",
  };

  return (
    <div
      className="bg-white border-2 border-gray-300 rounded-lg shadow-sm px-4 py-3 min-w-[140px] cursor-pointer hover:border-blue-400 transition-colors"
      onClick={() => setSelectedNode(id)}
      onDoubleClick={handleDoubleClick}
    >
      {accepts.length > 0 ? (
        accepts.map((type, i) => (
          <Handle key={`target-${type}`} type="target" position={Position.Left} id={`target-${type}`}
            style={{ top: `${((i + 1) / (accepts.length + 1)) * 100}%`, background: CONNECTION_COLORS[type as ConnectionType] || CONNECTION_COLORS.default, width: 10, height: 10 }} />
        ))
      ) : (
        <Handle type="target" position={Position.Left} />
      )}

      <div className="flex items-center gap-2">
        <div className="text-2xl">{iconMap[nodeData.componentId] || "\u{1F4E6}"}</div>
        <div>
          <div className="font-semibold text-sm text-gray-800">{nodeData.label}</div>
          <div className="text-xs text-gray-500">{nodeData.variant}</div>
          {nodeData.site && nodeData.site !== "default" && (
            <div className="text-xs text-blue-500">{nodeData.site}</div>
          )}
        </div>
        {nodeData.health && (
          <span className={`ml-auto w-2.5 h-2.5 rounded-full ${healthColors[nodeData.health] ?? "bg-gray-400"}`} title={nodeData.health} />
        )}
      </div>

      {provides.length > 0 ? (
        provides.map((p, i) => (
          <Handle key={`source-${p.type}`} type="source" position={Position.Right} id={`source-${p.type}`}
            style={{ top: `${((i + 1) / (provides.length + 1)) * 100}%`, background: CONNECTION_COLORS[p.type as ConnectionType] || CONNECTION_COLORS.default, width: 10, height: 10 }} />
        ))
      ) : (
        <Handle type="source" position={Position.Right} />
      )}
    </div>
  );
}
```

### Step 11.3 — Update `frontend/src/components/canvas/DiagramCanvas.tsx` (REPLACE entire file)

```tsx
import { useCallback, useRef, useState } from "react";
import { ReactFlow, MiniMap, Controls, Background, type Node, type Connection } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useDiagramStore } from "../../stores/diagramStore";
import { useDemoStore } from "../../stores/demoStore";
import { saveDiagram, validateConnection } from "../../api/client";
import ComponentNode from "./nodes/ComponentNode";
import DataEdge from "./edges/DataEdge";
import ContextMenu from "./ContextMenu";
import type { ContextMenuState } from "../../types";

const nodeTypes = { component: ComponentNode };
const edgeTypes = { data: DataEdge };
let nodeCounter = 0;

function debounce<T extends (...args: any[]) => void>(fn: T, ms: number): T {
  let timer: ReturnType<typeof setTimeout>;
  return ((...args: any[]) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), ms); }) as T;
}

interface Props { onOpenTerminal: (nodeId: string) => void; }

export default function DiagramCanvas({ onOpenTerminal }: Props) {
  const { nodes, edges, onNodesChange, onEdgesChange, onConnect, addNode } = useDiagramStore();
  const activeDemoId = useDemoStore((s) => s.activeDemoId);
  const [contextMenu, setContextMenu] = useState<ContextMenuState>({ visible: false, x: 0, y: 0, nodeId: null, edgeId: null });

  const debouncedSave = useRef(
    debounce((demoId: string, ns: Node[], es: any[]) => { saveDiagram(demoId, ns, es).catch(() => {}); }, 500)
  ).current;

  const handleNodesChange = useCallback((changes: any) => {
    onNodesChange(changes);
    if (activeDemoId) debouncedSave(activeDemoId, useDiagramStore.getState().nodes, useDiagramStore.getState().edges);
  }, [onNodesChange, activeDemoId, debouncedSave]);

  const handleEdgesChange = useCallback((changes: any) => {
    onEdgesChange(changes);
    if (activeDemoId) debouncedSave(activeDemoId, useDiagramStore.getState().nodes, useDiagramStore.getState().edges);
  }, [onEdgesChange, activeDemoId, debouncedSave]);

  const handleConnect = useCallback((connection: Connection) => {
    const sourceHandle = connection.sourceHandle || "";
    const connectionType = sourceHandle.replace("source-", "") || "default";
    const sourceNode = nodes.find((n) => n.id === connection.source);
    const targetNode = nodes.find((n) => n.id === connection.target);

    if (sourceNode && targetNode) {
      const srcComp = (sourceNode.data as any).componentId;
      const tgtComp = (targetNode.data as any).componentId;
      validateConnection(srcComp, tgtComp, connectionType)
        .then((res) => {
          if (res.valid) {
            const edge = { ...connection, type: "data", data: { connectionType, animated: true } };
            onConnect(edge as any);
            if (activeDemoId) { const s = useDiagramStore.getState(); debouncedSave(activeDemoId, s.nodes, s.edges); }
          } else { console.warn(`Invalid connection: ${res.reason}`); }
        })
        .catch(() => {
          const edge = { ...connection, type: "data", data: { connectionType, animated: true } };
          onConnect(edge as any);
        });
    }
  }, [nodes, onConnect, activeDemoId, debouncedSave]);

  const onDrop = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    const componentId = e.dataTransfer.getData("componentId");
    const variant = e.dataTransfer.getData("variant") || "single";
    const label = e.dataTransfer.getData("label") || componentId;
    const provides = e.dataTransfer.getData("provides");
    const accepts = e.dataTransfer.getData("accepts");
    if (!componentId) return;
    const bounds = (e.target as HTMLDivElement).closest(".react-flow")?.getBoundingClientRect();
    const x = bounds ? e.clientX - bounds.left - 70 : e.clientX;
    const y = bounds ? e.clientY - bounds.top - 30 : e.clientY;
    nodeCounter += 1;
    const newNode: Node = {
      id: `${componentId}-${nodeCounter}`, type: "component", position: { x, y },
      data: { label, componentId, variant, config: {}, provides: provides ? JSON.parse(provides) : [], accepts: accepts ? JSON.parse(accepts) : [] },
    };
    addNode(newNode);
    if (activeDemoId) { const s = useDiagramStore.getState(); debouncedSave(activeDemoId, [...s.nodes, newNode], s.edges); }
  }, [addNode, activeDemoId, debouncedSave]);

  const onDragOver = (e: React.DragEvent) => { e.preventDefault(); e.dataTransfer.dropEffect = "move"; };

  const onNodeContextMenu = useCallback((event: React.MouseEvent, node: Node) => {
    event.preventDefault(); setContextMenu({ visible: true, x: event.clientX, y: event.clientY, nodeId: node.id, edgeId: null });
  }, []);

  const onEdgeContextMenu = useCallback((event: React.MouseEvent, edge: any) => {
    event.preventDefault(); setContextMenu({ visible: true, x: event.clientX, y: event.clientY, nodeId: null, edgeId: edge.id });
  }, []);

  const onPaneClick = useCallback(() => { setContextMenu((p) => ({ ...p, visible: false })); }, []);

  return (
    <div className="w-full h-full" onDrop={onDrop} onDragOver={onDragOver}>
      <ReactFlow nodes={nodes} edges={edges} onNodesChange={handleNodesChange} onEdgesChange={handleEdgesChange}
        onConnect={handleConnect} nodeTypes={nodeTypes} edgeTypes={edgeTypes}
        onNodeContextMenu={onNodeContextMenu} onEdgeContextMenu={onEdgeContextMenu} onPaneClick={onPaneClick}
        defaultEdgeOptions={{ type: "data" }} fitView>
        <MiniMap /><Controls /><Background />
      </ReactFlow>
      <ContextMenu menu={contextMenu} onClose={() => setContextMenu((p) => ({ ...p, visible: false }))} onOpenTerminal={onOpenTerminal} />
    </div>
  );
}
```

### Step 11.4 — Update `frontend/src/components/palette/ComponentPalette.tsx` (REPLACE entire file)

```tsx
import { useEffect, useState } from "react";
import { fetchComponents } from "../../api/client";
import type { ComponentSummary } from "../../types";

export default function ComponentPalette() {
  const [components, setComponents] = useState<ComponentSummary[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { fetchComponents().then((res) => setComponents(res.components)).catch((e) => setError(e.message)); }, []);

  const grouped = components.reduce<Record<string, ComponentSummary[]>>((acc, c) => {
    (acc[c.category] = acc[c.category] || []).push(c); return acc;
  }, {});

  const iconMap: Record<string, string> = { minio: "\u{1FAA3}", nginx: "\u{1F500}", prometheus: "\u{1F4CA}", grafana: "\u{1F4C8}" };

  const onDragStart = (e: React.DragEvent, component: ComponentSummary) => {
    e.dataTransfer.setData("componentId", component.id);
    e.dataTransfer.setData("variant", component.variants[0] ?? "single");
    e.dataTransfer.setData("label", component.name);
    e.dataTransfer.setData("provides", JSON.stringify(component.provides));
    e.dataTransfer.setData("accepts", JSON.stringify(component.accepts));
    e.dataTransfer.effectAllowed = "move";
  };

  return (
    <div className="w-full h-full overflow-y-auto bg-gray-50 border-r border-gray-200 p-2">
      <div className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2 px-1">Components</div>
      {error && <div className="text-xs text-red-500 px-1">{error}</div>}
      {Object.entries(grouped).map(([category, items]) => (
        <div key={category} className="mb-3">
          <div className="text-xs text-gray-400 font-medium uppercase px-1 mb-1">{category}</div>
          {items.map((c) => (
            <div key={c.id} draggable onDragStart={(e) => onDragStart(e, c)}
              className="flex items-center gap-2 px-2 py-2 mb-1 bg-white border border-gray-200 rounded cursor-grab hover:border-blue-400 hover:shadow-sm transition-all text-sm" title={c.description}>
              <span className="text-base">{iconMap[c.id] || "\u{1F4E6}"}</span>
              <div className="flex-1 min-w-0">
                <span className="font-medium text-gray-700 truncate block">{c.name}</span>
                {c.provides.length > 0 && <span className="text-xs text-gray-400">{c.provides.map((p) => p.type).join(", ")}</span>}
              </div>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
```

---

## Step 12: Control Plane v2

**Depends on**: Step 9

### Step 12.1 — Update `frontend/src/components/control-plane/ControlPlane.tsx` (REPLACE entire file)

```tsx
import { useEffect, useCallback, useState } from "react";
import { useDemoStore } from "../../stores/demoStore";
import { useDiagramStore } from "../../stores/diagramStore";
import { fetchInstances, fetchInitStatus } from "../../api/client";
import ComponentCard from "./ComponentCard";
import type { InitScriptStatus } from "../../types";

interface Props { onOpenTerminal: (nodeId: string) => void; }

export default function ControlPlane({ onOpenTerminal }: Props) {
  const { activeDemoId, instances, setInstances } = useDemoStore();
  const updateNodeHealth = useDiagramStore((s) => s.updateNodeHealth);
  const [initScripts, setInitScripts] = useState<InitScriptStatus[]>([]);
  const [groupBy, setGroupBy] = useState<"none" | "site">("none");

  const loadInstances = useCallback(() => {
    if (!activeDemoId) return;
    fetchInstances(activeDemoId).then((res) => { setInstances(res.instances); res.instances.forEach((inst) => updateNodeHealth(inst.node_id, inst.health)); }).catch(() => {});
    fetchInitStatus(activeDemoId).then((res) => setInitScripts(res.scripts)).catch(() => {});
  }, [activeDemoId, setInstances, updateNodeHealth]);

  useEffect(() => { loadInstances(); const iv = setInterval(loadInstances, 5000); return () => clearInterval(iv); }, [loadInstances]);

  if (!activeDemoId) return <div className="flex-1 flex items-center justify-center text-gray-400 text-sm">No active demo selected</div>;
  if (instances.length === 0) return <div className="flex-1 flex items-center justify-center text-gray-400 text-sm">No running instances. Deploy the demo first.</div>;

  const grouped: Record<string, typeof instances> = {};
  for (const inst of instances) {
    const key = groupBy === "site" ? (inst.site || "default") : "all";
    if (!grouped[key]) grouped[key] = [];
    grouped[key].push(inst);
  }

  return (
    <div className="flex-1 overflow-y-auto p-4">
      <div className="flex items-center gap-2 mb-3">
        <span className="text-xs text-gray-500 font-medium">Group by:</span>
        <button onClick={() => setGroupBy("none")} className={`px-2 py-0.5 rounded text-xs ${groupBy === "none" ? "bg-blue-600 text-white" : "bg-gray-200 text-gray-600"}`}>None</button>
        <button onClick={() => setGroupBy("site")} className={`px-2 py-0.5 rounded text-xs ${groupBy === "site" ? "bg-blue-600 text-white" : "bg-gray-200 text-gray-600"}`}>Site</button>
      </div>

      {initScripts.length > 0 && (
        <div className="mb-3 p-2 bg-gray-50 border border-gray-200 rounded-lg">
          <div className="text-xs font-semibold text-gray-600 mb-1">Init Scripts</div>
          <div className="flex flex-wrap gap-1">
            {initScripts.map((s) => (
              <span key={`${s.node_id}:${s.name}`} className={`px-2 py-0.5 rounded text-xs font-medium ${s.status === "success" ? "bg-green-100 text-green-700" : s.status === "failed" ? "bg-red-100 text-red-700" : s.status === "running" ? "bg-yellow-100 text-yellow-700" : "bg-gray-100 text-gray-500"}`} title={s.output}>
                {s.node_id}: {s.name} ({s.status})
              </span>
            ))}
          </div>
        </div>
      )}

      {Object.entries(grouped).map(([group, insts]) => (
        <div key={group}>
          {groupBy === "site" && <div className="text-xs font-semibold text-blue-600 uppercase tracking-wider mb-2 mt-3">Site: {group}</div>}
          {insts.map((inst) => <ComponentCard key={inst.node_id} instance={inst} demoId={activeDemoId} onOpenTerminal={onOpenTerminal} />)}
        </div>
      ))}
    </div>
  );
}
```

### Step 12.2 — Update `frontend/src/components/control-plane/ComponentCard.tsx` (REPLACE entire file)

```tsx
import { useState } from "react";
import type { ContainerInstance } from "../../types";
import HealthBadge from "./HealthBadge";
import WebUIFrame from "./WebUIFrame";
import { useDiagramStore } from "../../stores/diagramStore";
import { restartInstance, execCommand } from "../../api/client";

interface Props { instance: ContainerInstance; demoId: string; onOpenTerminal: (nodeId: string) => void; }

export default function ComponentCard({ instance, demoId, onOpenTerminal }: Props) {
  const [activeFrame, setActiveFrame] = useState<{ name: string; path: string } | null>(null);
  const [restarting, setRestarting] = useState(false);
  const [qaOutput, setQaOutput] = useState<string | null>(null);
  const setSelectedNode = useDiagramStore((s) => s.setSelectedNode);

  const handleRestart = (e: React.MouseEvent) => { e.stopPropagation(); setRestarting(true); restartInstance(demoId, instance.node_id).finally(() => setRestarting(false)); };

  const handleQA = (cmd: string) => {
    setQaOutput("Running...");
    execCommand(demoId, instance.node_id, cmd).then((r) => setQaOutput(r.stdout || r.stderr || `Exit: ${r.exit_code}`)).catch((e) => setQaOutput(`Error: ${e.message}`));
  };

  return (
    <div className="bg-white border border-gray-200 rounded-lg shadow-sm p-3 mb-3 cursor-pointer hover:border-blue-300 transition-colors" onClick={() => setSelectedNode(instance.node_id)}>
      <div className="flex items-center justify-between mb-2">
        <div>
          <div className="font-semibold text-sm text-gray-800">{instance.node_id}</div>
          <div className="text-xs text-gray-500">{instance.component_id}</div>
          {instance.site && instance.site !== "default" && <div className="text-xs text-blue-500">{instance.site}</div>}
        </div>
        <HealthBadge health={instance.health} />
      </div>

      {instance.web_uis.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-2">
          {instance.web_uis.map((ui) => (
            <button key={ui.name} onClick={(e) => { e.stopPropagation(); setActiveFrame({ name: ui.name, path: ui.proxy_url }); }}
              className="px-2 py-0.5 bg-blue-50 border border-blue-200 rounded text-xs text-blue-700 hover:bg-blue-100">{ui.name}</button>
          ))}
        </div>
      )}

      <div className="flex gap-1 mb-2">
        {instance.has_terminal && <button onClick={(e) => { e.stopPropagation(); onOpenTerminal(instance.node_id); }} className="px-2 py-0.5 bg-gray-800 text-white rounded text-xs hover:bg-gray-700">Terminal</button>}
        <button onClick={handleRestart} disabled={restarting} className="px-2 py-0.5 bg-yellow-600 text-white rounded text-xs hover:bg-yellow-500 disabled:opacity-50">{restarting ? "..." : "Restart"}</button>
      </div>

      {instance.quick_actions.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-2">
          {instance.quick_actions.map((qa) => (
            <button key={qa.label} onClick={(e) => { e.stopPropagation(); handleQA(qa.command); }}
              className="px-2 py-0.5 bg-indigo-50 border border-indigo-200 rounded-full text-xs text-indigo-700 hover:bg-indigo-100" title={qa.command}>{qa.label}</button>
          ))}
        </div>
      )}

      {qaOutput && (
        <div className="mt-1 p-2 bg-gray-900 rounded text-xs text-green-400 font-mono max-h-32 overflow-y-auto whitespace-pre-wrap">
          {qaOutput}
          <button onClick={(e) => { e.stopPropagation(); setQaOutput(null); }} className="ml-2 text-gray-500 hover:text-white">[close]</button>
        </div>
      )}

      {activeFrame && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center" onClick={(e) => e.stopPropagation()}>
          <div className="w-4/5 h-4/5 flex flex-col bg-white rounded-lg overflow-hidden shadow-xl">
            <WebUIFrame path={activeFrame.path} name={activeFrame.name} onClose={() => setActiveFrame(null)} />
          </div>
        </div>
      )}
    </div>
  );
}
```

### Step 12.3 — Update `frontend/src/api/client.ts` (REPLACE entire file)

```typescript
const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { headers: { "Content-Type": "application/json" }, ...options });
  if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`);
  return res.json();
}

export const fetchComponents = () => apiFetch<{ components: import("../types").ComponentSummary[] }>("/api/registry/components");
export const fetchDemos = () => apiFetch<{ demos: import("../types").DemoSummary[] }>("/api/demos");
export const createDemo = (name: string, description = "", sites: { name: string; label: string }[] = []) =>
  apiFetch<import("../types").DemoSummary>("/api/demos", { method: "POST", body: JSON.stringify({ name, description, sites }) });
export const fetchDemo = (id: string) => apiFetch<any>(`/api/demos/${id}`);
export const saveDiagram = (id: string, nodes: any[], edges: any[]) =>
  apiFetch<any>(`/api/demos/${id}/diagram`, { method: "PUT", body: JSON.stringify({ nodes, edges }) });
export const deleteDemo = (id: string) => apiFetch<any>(`/api/demos/${id}`, { method: "DELETE" });
export const deployDemo = (id: string) => apiFetch<{ demo_id: string; status: string; message?: string }>(`/api/demos/${id}/deploy`, { method: "POST" });
export const stopDemo = (id: string) => apiFetch<{ demo_id: string; status: string }>(`/api/demos/${id}/stop`, { method: "POST" });
export const fetchInstances = (demoId: string) => apiFetch<{ demo_id: string; status: string; instances: import("../types").ContainerInstance[] }>(`/api/demos/${demoId}/instances`);
export const restartInstance = (demoId: string, nodeId: string) => apiFetch<{ status: string }>(`/api/demos/${demoId}/instances/${nodeId}/restart`, { method: "POST" });
export const getInstanceHealth = (demoId: string, nodeId: string) => apiFetch<{ node_id: string; health: string }>(`/api/demos/${demoId}/instances/${nodeId}/health`);
export const execCommand = (demoId: string, nodeId: string, command: string) =>
  apiFetch<{ exit_code: number; stdout: string; stderr: string }>(`/api/demos/${demoId}/instances/${nodeId}/exec`, { method: "POST", body: JSON.stringify({ command }) });
export const validateConnection = (source: string, target: string, connectionType: string) =>
  apiFetch<{ valid: boolean; reason: string; connection_type: string; source_port: number | null }>("/api/connections/validate", { method: "POST", body: JSON.stringify({ source_component: source, target_component: target, connection_type: connectionType }) });
export const fetchConnectionTypes = () => apiFetch<{ types: string[] }>("/api/connections/types");
export const fetchInitStatus = (demoId: string) => apiFetch<{ demo_id: string; scripts: import("../types").InitScriptStatus[] }>(`/api/demos/${demoId}/init-status`);
export const terminalWsUrl = (demoId: string, nodeId: string) => `${API_BASE.replace("http", "ws")}/api/demos/${demoId}/instances/${nodeId}/terminal`;
export const proxyUrl = (path: string) => `${API_BASE}${path}`;
```

---

## Step 13: Update App.tsx

**Depends on**: Steps 11-12

### Step 13.1 — Update `frontend/src/App.tsx` (REPLACE entire file)

```tsx
import { useCallback, useEffect, useRef, useState } from "react";
import { useDemoStore } from "./stores/demoStore";
import { fetchDemos } from "./api/client";
import Toolbar from "./components/toolbar/Toolbar";
import ComponentPalette from "./components/palette/ComponentPalette";
import DiagramCanvas from "./components/canvas/DiagramCanvas";
import PropertiesPanel from "./components/properties/PropertiesPanel";
import ControlPlane from "./components/control-plane/ControlPlane";
import TerminalPanel from "./components/terminal/TerminalPanel";

export default function App() {
  const { setDemos, activeView } = useDemoStore();
  const [terminalTabs, setTerminalTabs] = useState<{ nodeId: string }[]>([]);
  const [terminalHeight, setTerminalHeight] = useState(256);
  const isDragging = useRef(false);

  useEffect(() => { fetchDemos().then((res) => setDemos(res.demos)).catch(() => {}); }, [setDemos]);

  const openTerminal = useCallback((nodeId: string) => {
    setTerminalTabs((prev) => prev.find((t) => t.nodeId === nodeId) ? prev : [...prev, { nodeId }]);
  }, []);

  const onResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault(); isDragging.current = true;
    const startY = e.clientY; const startH = terminalHeight;
    const onMove = (ev: MouseEvent) => { if (!isDragging.current) return; setTerminalHeight(Math.max(100, Math.min(600, startH + (startY - ev.clientY)))); };
    const onUp = () => { isDragging.current = false; window.removeEventListener("mousemove", onMove); window.removeEventListener("mouseup", onUp); };
    window.addEventListener("mousemove", onMove); window.addEventListener("mouseup", onUp);
  }, [terminalHeight]);

  return (
    <div className="flex flex-col h-screen bg-gray-100 overflow-hidden">
      <Toolbar />
      <div className="flex flex-1 min-h-0">
        <div className="w-48 flex-shrink-0 h-full"><ComponentPalette /></div>
        <div className="flex-1 min-w-0 h-full">
          {activeView === "diagram" ? <DiagramCanvas onOpenTerminal={openTerminal} /> : <ControlPlane onOpenTerminal={openTerminal} />}
        </div>
        <div className="w-72 flex-shrink-0 h-full"><PropertiesPanel /></div>
      </div>
      <div className="flex-shrink-0" style={{ height: terminalHeight }}>
        <div className="h-1.5 bg-gray-300 hover:bg-blue-400 cursor-row-resize border-t border-gray-300" onMouseDown={onResizeStart} />
        <div className="h-[calc(100%-6px)]"><TerminalPanel extraTabs={terminalTabs} /></div>
      </div>
    </div>
  );
}
```

---

# INTEGRATION TEST

---

## Step 14: End-to-End Validation — 3-Site Replication Demo

**Depends on**: ALL previous steps

### 14.1 — Manual test procedure

1. Start DemoForge: `docker compose up --build`
2. Open `http://localhost:3000`
3. Click **+ New Demo**, name it "3-Site Replication"
4. From the palette, drag onto the canvas:
   - 3x MinIO (assign site-a, site-b, site-c in Properties panel)
   - 1x NGINX (load balancer)
   - 1x Prometheus
   - 1x Grafana
5. Connect typed edges (colored handles visible on nodes):
   - Each MinIO `source-s3` -> NGINX `target-s3`
   - Each MinIO `source-metrics` -> Prometheus `target-metrics`
   - Prometheus `source-metrics` -> Grafana `target-metrics`
6. Verify animated particles flow along edges with correct colors (green=S3, amber=Metrics)
7. Click **Deploy**
8. Switch to **Control Plane** view:
   - All 6 containers show healthy (green dot)
   - Init script chips show success (green)
   - Group by Site to see site-a / site-b / site-c groupings
   - Click quick-action chips (mc admin info, Create test bucket) and see output
9. Open Grafana via component card -> MinIO Overview dashboard with live data
10. Open Prometheus -> verify targets page shows all 3 MinIO instances as UP
11. Right-click a MinIO node on diagram -> "Restart Container" -> container restarts without teardown
12. Right-click an edge -> "Delete Connection" -> edge removed
13. Open terminals for multiple MinIO instances simultaneously

### 14.2 — Acceptance criteria

- [ ] 6 containers running (3 MinIO + NGINX + Prometheus + Grafana)
- [ ] Multi-network: backend joined to all site networks (`docker inspect` confirms)
- [ ] Animated edges with correct type colors (green=S3, amber=Metrics, blue=HTTP)
- [ ] Connection validation prevents invalid edges (e.g. Grafana->MinIO S3 rejected)
- [ ] Prometheus scraping all 3 MinIO instances (`/api/v1/targets` all UP)
- [ ] Grafana MinIO Overview dashboard shows live metrics
- [ ] NGINX config auto-generated with all 3 MinIO backends
- [ ] Right-click context menu works on nodes (terminal, restart, open UI, delete)
- [ ] Right-click context menu works on edges (delete connection)
- [ ] Quick-action chips execute commands and display output inline
- [ ] Container restart works without full demo teardown
- [ ] Init scripts (alias setup, bucket creation) complete successfully
- [ ] Control Plane groups instances by site
