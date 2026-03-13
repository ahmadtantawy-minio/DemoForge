# DemoForge — Phase 1 Execution Spec

This is the build spec for Phase 1. Follow the steps in exact order.
Refer to `minio-demo-generator-plan.md` for architectural context and future-phase direction.

---

## 0. Constraints

- **Runtime**: Docker Compose v2, laptop target (16GB RAM, 8 cores).
- **No host port exposure from demo containers** — all component UIs are accessed through DemoForge's reverse proxy. Only DemoForge itself exposes ports (3000 for UI, 8000 for API).
- **The DemoForge backend container joins each demo's Docker network** at deploy time so it can reach containers by hostname:internal_port.
- **Phase 1 scope**: one component only — `minio` (single variant). No replication, no traffic generator, no analytics stack yet. The goal is: drag MinIO onto the canvas → deploy → access MinIO Console through the proxy → open a terminal → run `mc` commands. Everything else comes in Phase 2+.

---

## 1. Project Bootstrap

### 1.1 Directory structure

```
demoforge/
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── main.tsx
│   │   ├── api/
│   │   │   └── client.ts                  # fetch + WebSocket helpers
│   │   ├── stores/
│   │   │   ├── diagramStore.ts            # Zustand: nodes, edges, selected node
│   │   │   └── demoStore.ts               # Zustand: demo list, active demo, deploy state
│   │   ├── components/
│   │   │   ├── canvas/
│   │   │   │   ├── DiagramCanvas.tsx       # React Flow wrapper
│   │   │   │   ├── nodes/
│   │   │   │   │   └── ComponentNode.tsx   # Generic component node (Phase 1: just one type)
│   │   │   │   └── edges/
│   │   │   │       └── DataEdge.tsx        # Simple labeled edge
│   │   │   ├── palette/
│   │   │   │   └── ComponentPalette.tsx    # Left sidebar, drag source
│   │   │   ├── properties/
│   │   │   │   └── PropertiesPanel.tsx     # Right sidebar, selected node config
│   │   │   ├── control-plane/
│   │   │   │   ├── ControlPlane.tsx        # List of component cards for running demo
│   │   │   │   ├── ComponentCard.tsx       # Single component: health, web UI links, terminal btn
│   │   │   │   ├── HealthBadge.tsx         # Colored dot + label
│   │   │   │   └── WebUIFrame.tsx          # Iframe wrapper for proxied web UI
│   │   │   ├── terminal/
│   │   │   │   ├── TerminalPanel.tsx       # Bottom panel with tabs
│   │   │   │   └── TerminalTab.tsx         # Single xterm.js instance
│   │   │   └── toolbar/
│   │   │       └── Toolbar.tsx             # Top bar: demo selector, deploy/stop buttons
│   │   └── types/
│   │       └── index.ts                    # Shared TypeScript types
│   ├── index.html
│   ├── package.json
│   ├── tsconfig.json
│   ├── tailwind.config.js
│   └── vite.config.ts
│
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                         # FastAPI app, CORS, lifespan
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── registry.py                 # GET /api/registry/components
│   │   │   ├── demos.py                    # CRUD /api/demos
│   │   │   ├── deploy.py                   # POST /api/demos/{id}/deploy, /stop
│   │   │   ├── instances.py                # GET /api/demos/{id}/instances
│   │   │   ├── proxy.py                    # ANY /proxy/{demo_id}/{node_id}/{ui_name}/{path}
│   │   │   ├── terminal.py                 # WS /api/demos/{id}/instances/{node}/terminal
│   │   │   └── health.py                   # GET /api/demos/{id}/instances/{node}/health
│   │   ├── engine/
│   │   │   ├── __init__.py
│   │   │   ├── compose_generator.py        # Diagram → docker-compose.yml
│   │   │   ├── docker_manager.py           # docker compose up/down, network join
│   │   │   ├── network_manager.py          # Create/remove networks, join backend to them
│   │   │   ├── proxy_gateway.py            # httpx-based reverse proxy logic
│   │   │   ├── terminal_bridge.py          # WebSocket ↔ docker exec subprocess
│   │   │   └── health_monitor.py           # Background task polling container health
│   │   ├── registry/
│   │   │   ├── __init__.py
│   │   │   └── loader.py                   # Parse YAML manifests from components/ dir
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── component.py                # Pydantic models for component manifest
│   │   │   ├── demo.py                     # Pydantic models for demo definition
│   │   │   └── api_models.py               # Request/response models for all API endpoints
│   │   └── state/
│   │       ├── __init__.py
│   │       └── store.py                    # In-memory state: running demos, container map
│   ├── requirements.txt
│   └── Dockerfile
│
├── components/
│   └── minio/
│       └── manifest.yaml
│
├── demos/                                   # Saved demo definitions (YAML)
│   └── .gitkeep
│
├── data/                                    # Runtime data (volumes, state)
│   └── .gitkeep
│
├── docker-compose.yml                       # DemoForge itself (frontend + backend)
├── Makefile
└── README.md
```

### 1.2 Pinned dependencies

**frontend/package.json**:
```json
{
  "name": "demoforge-ui",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "@xyflow/react": "^12.6.0",
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "zustand": "^5.0.3",
    "@xterm/xterm": "^5.5.0",
    "@xterm/addon-fit": "^0.10.0",
    "@xterm/addon-web-links": "^0.11.0"
  },
  "devDependencies": {
    "@types/react": "^18.3.18",
    "@types/react-dom": "^18.3.5",
    "@vitejs/plugin-react": "^4.3.4",
    "autoprefixer": "^10.4.20",
    "postcss": "^8.5.3",
    "tailwindcss": "^3.4.17",
    "typescript": "^5.7.3",
    "vite": "^6.2.0"
  }
}
```

**backend/requirements.txt**:
```
fastapi==0.115.12
uvicorn[standard]==0.34.0
httpx==0.28.1
websockets==14.2
docker==7.1.0
pyyaml==6.0.2
jinja2==3.1.5
pydantic==2.11.1
```

### 1.3 DemoForge's own docker-compose.yml

```yaml
# docker-compose.yml — runs DemoForge itself
services:
  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock   # Docker-in-Docker control
      - ./components:/app/components:ro              # Component manifests
      - ./demos:/app/demos                           # Saved demo definitions
      - ./data:/app/data                             # Runtime state
    environment:
      - DEMOFORGE_COMPONENTS_DIR=/app/components
      - DEMOFORGE_DEMOS_DIR=/app/demos
      - DEMOFORGE_DATA_DIR=/app/data
    labels:
      - "demoforge.role=backend"                     # So we can find ourselves

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    ports:
      - "3000:3000"
    depends_on:
      - backend
    environment:
      - VITE_API_URL=http://localhost:8000
```

**backend/Dockerfile**:
```dockerfile
FROM python:3.12-slim

# Install docker CLI (needed for `docker compose` commands)
RUN apt-get update && apt-get install -y --no-install-recommends \
    docker.io docker-compose-v2 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## 2. Build Order (follow sequentially)

### Step 1: Backend models (no dependencies, pure Python)

Build these first — everything else imports them.

**File: `backend/app/models/component.py`**

```python
"""Pydantic models for component manifests (parsed from YAML)."""
from pydantic import BaseModel

class PortDef(BaseModel):
    name: str                     # "api", "console"
    container: int                # 9000, 9001
    protocol: str = "tcp"

class ResourceDef(BaseModel):
    memory: str = "256m"          # Docker memory limit string
    cpu: float = 0.5

class VolumeDef(BaseModel):
    name: str
    path: str                     # Mount path inside container
    size: str = "1g"

class HealthCheckDef(BaseModel):
    endpoint: str                 # "/minio/health/live"
    port: int                     # Which container port to hit
    interval: str = "10s"
    timeout: str = "5s"

class SecretDef(BaseModel):
    key: str                      # ENV var name
    label: str                    # Human-readable label for UI
    default: str | None = None
    required: bool = True

class WebUIDef(BaseModel):
    name: str                     # "MinIO Console"
    port: int                     # Container port
    path: str = "/"               # URL path within that port
    description: str = ""

class QuickActionDef(BaseModel):
    label: str
    command: str

class TerminalDef(BaseModel):
    shell: str = "/bin/sh"
    welcome_message: str = ""
    quick_actions: list[QuickActionDef] = []

class ConnectionProvides(BaseModel):
    type: str                     # "s3", "metrics", "jdbc"
    port: int
    description: str = ""
    path: str = ""

class ConnectionAccepts(BaseModel):
    type: str

class ConnectionsDef(BaseModel):
    provides: list[ConnectionProvides] = []
    accepts: list[ConnectionAccepts] = []

class VariantDef(BaseModel):
    description: str = ""
    command: list[str] | None = None
    replicas: int = 1

class ComponentManifest(BaseModel):
    """Full component manifest parsed from YAML."""
    id: str
    name: str
    category: str                 # "storage", "analytics", "streaming", "ai", "database", "cloud", "infra", "tooling"
    icon: str = ""
    version: str = ""
    image: str                    # Docker image reference
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
```

**File: `backend/app/models/demo.py`**

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

class DemoEdge(BaseModel):
    id: str
    source: str                   # Node ID
    target: str                   # Node ID
    type: str = "default"         # Connection type (s3, jdbc, etc.)
    label: str = ""

class DemoNetwork(BaseModel):
    name: str
    subnet: str = "172.20.0.0/16"
    dns_suffix: str = "demo.local"

class DemoDefinition(BaseModel):
    """Complete demo definition — serializable to/from YAML."""
    id: str
    name: str
    description: str = ""
    network: DemoNetwork = DemoNetwork(name="default")
    nodes: list[DemoNode] = []
    edges: list[DemoEdge] = []
```

**File: `backend/app/models/api_models.py`**

```python
"""Request/response models for all API endpoints."""
from pydantic import BaseModel
from enum import Enum

# --- Registry ---
class ComponentSummary(BaseModel):
    id: str
    name: str
    category: str
    icon: str
    description: str
    variants: list[str]           # Just the variant names

class RegistryResponse(BaseModel):
    components: list[ComponentSummary]

# --- Demos ---
class DemoSummary(BaseModel):
    id: str
    name: str
    description: str
    node_count: int
    status: str                   # "stopped", "deploying", "running", "error"

class DemoListResponse(BaseModel):
    demos: list[DemoSummary]

class CreateDemoRequest(BaseModel):
    name: str
    description: str = ""

class SaveDiagramRequest(BaseModel):
    """Sent by the frontend whenever the diagram changes."""
    nodes: list[dict]             # React Flow node objects (we extract what we need)
    edges: list[dict]             # React Flow edge objects

# --- Deploy ---
class DeployResponse(BaseModel):
    demo_id: str
    status: str                   # "deploying", "running", "error"
    message: str = ""

# --- Instances (running containers) ---
class ContainerHealthStatus(str, Enum):
    HEALTHY = "healthy"
    STARTING = "starting"
    DEGRADED = "degraded"
    ERROR = "error"
    STOPPED = "stopped"

class WebUILink(BaseModel):
    name: str
    proxy_url: str                # "/proxy/{demo}/{node}/{ui_name}/"
    description: str

class ContainerInstance(BaseModel):
    node_id: str                  # Matches DemoNode.id
    component_id: str             # Manifest ID
    container_name: str           # Docker container name
    health: ContainerHealthStatus
    web_uis: list[WebUILink]
    has_terminal: bool
    quick_actions: list[dict]     # [{label, command}]
    resource_usage: dict = {}     # {"memory_mb": 124, "cpu_pct": 12.5}

class InstancesResponse(BaseModel):
    demo_id: str
    status: str
    instances: list[ContainerInstance]

# --- Exec ---
class ExecRequest(BaseModel):
    command: str

class ExecResponse(BaseModel):
    exit_code: int
    stdout: str
    stderr: str
```

### Step 2: Component registry loader

**File: `backend/app/registry/loader.py`**

```python
"""Load component manifests from YAML files on disk."""
import os
import yaml
from ..models.component import ComponentManifest

_registry: dict[str, ComponentManifest] = {}

def load_registry(components_dir: str) -> dict[str, ComponentManifest]:
    """Scan components_dir for manifest.yaml files and parse them."""
    global _registry
    _registry = {}
    for entry in os.listdir(components_dir):
        manifest_path = os.path.join(components_dir, entry, "manifest.yaml")
        if os.path.isfile(manifest_path):
            with open(manifest_path) as f:
                raw = yaml.safe_load(f)
            manifest = ComponentManifest(**raw)
            _registry[manifest.id] = manifest
    return _registry

def get_registry() -> dict[str, ComponentManifest]:
    return _registry

def get_component(component_id: str) -> ComponentManifest | None:
    return _registry.get(component_id)
```

### Step 3: MinIO component manifest

**File: `components/minio/manifest.yaml`**

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

connections:
  provides:
    - type: s3
      port: 9000
      description: "S3-compatible API endpoint"

variants:
  single:
    description: "Single node, single drive"
    command: ["server", "/data", "--console-address", ":9001"]
  distributed:
    description: "4-drive erasure coding (simulated)"
    command: ["server", "/data{1...4}", "--console-address", ":9001"]
```

### Step 4: In-memory state store

**File: `backend/app/state/store.py`**

```python
"""
In-memory state for running demos.
Tracks which demos are deployed, their container names, and network memberships.
No persistence needed — if backend restarts, demos are still running in Docker
and we can re-discover them via labels.
"""
from dataclasses import dataclass, field
from ..models.api_models import ContainerHealthStatus

@dataclass
class RunningContainer:
    node_id: str                      # e.g. "minio-1"
    component_id: str                 # e.g. "minio"
    container_name: str               # Docker container name
    networks: list[str]               # Docker network names this container is on
    health: ContainerHealthStatus = ContainerHealthStatus.STARTING

@dataclass
class RunningDemo:
    demo_id: str
    status: str = "stopped"           # "stopped", "deploying", "running", "error"
    compose_project: str = ""         # Docker Compose project name
    networks: list[str] = field(default_factory=list)
    containers: dict[str, RunningContainer] = field(default_factory=dict)  # node_id → RunningContainer
    compose_file_path: str = ""       # Path to generated docker-compose.yml

class StateStore:
    def __init__(self):
        self.running_demos: dict[str, RunningDemo] = {}   # demo_id → RunningDemo

    def get_demo(self, demo_id: str) -> RunningDemo | None:
        return self.running_demos.get(demo_id)

    def set_demo(self, demo: RunningDemo):
        self.running_demos[demo.demo_id] = demo

    def remove_demo(self, demo_id: str):
        self.running_demos.pop(demo_id, None)

    def list_demos(self) -> list[RunningDemo]:
        return list(self.running_demos.values())

# Singleton
state = StateStore()
```

### Step 5: Compose generator

**File: `backend/app/engine/compose_generator.py`**

Takes a `DemoDefinition` + component manifests → writes a `docker-compose.yml` file to disk. Key rules:
- NO `ports:` mappings (sandboxed)
- Uses `expose:` for inter-container communication
- Applies `mem_limit`, `cpus` from manifest resources
- Generates unique container names: `demoforge-{demo_id}-{node_id}`
- Creates a dedicated network: `demoforge-{demo_id}-net`
- Adds labels so we can identify our containers: `demoforge.demo={demo_id}`, `demoforge.node={node_id}`, `demoforge.component={component_id}`
- Resolves environment variables: merge manifest defaults with node-level `config` overrides, substituting secret defaults
- Generates a healthcheck from manifest `health_check` (using `curl` or `wget` to hit the endpoint inside the container)

```python
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
```

### Step 6: Docker manager

**File: `backend/app/engine/docker_manager.py`**

Wraps `docker compose` CLI and Docker SDK for network operations. Key operations:
- `deploy_demo()` → generates compose, runs `docker compose up -d`, joins backend to the demo network
- `stop_demo()` → runs `docker compose down`, disconnects backend from network
- `get_container_status()` → inspects container health via Docker SDK
- `restart_container()` → restarts a single container
- `find_self()` → finds the DemoForge backend container ID (by label `demoforge.role=backend`)

```python
"""Docker operations: compose up/down, network join, container inspection."""
import asyncio
import docker
from docker.errors import NotFound, APIError
from ..models.demo import DemoDefinition
from ..state.store import state, RunningDemo, RunningContainer
from ..models.api_models import ContainerHealthStatus
from .compose_generator import generate_compose

docker_client = docker.from_env()

def _find_self_container_id() -> str | None:
    """Find the DemoForge backend container by its label."""
    containers = docker_client.containers.list(
        filters={"label": "demoforge.role=backend"}
    )
    if containers:
        return containers[0].id
    # Fallback: we might be running outside Docker (dev mode)
    return None

async def deploy_demo(demo: DemoDefinition, data_dir: str) -> RunningDemo:
    """Generate compose file, bring up containers, join network."""
    project_name = f"demoforge-{demo.id}"
    network_name = f"{project_name}-net"
    compose_path = generate_compose(demo, data_dir)

    running = RunningDemo(
        demo_id=demo.id,
        status="deploying",
        compose_project=project_name,
        networks=[network_name],
        compose_file_path=compose_path,
    )
    state.set_demo(running)

    # Run docker compose up
    proc = await asyncio.create_subprocess_exec(
        "docker", "compose", "-f", compose_path, "-p", project_name, "up", "-d",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        running.status = "error"
        state.set_demo(running)
        raise RuntimeError(f"docker compose up failed: {stderr.decode()}")

    # Join backend container to demo network
    self_id = _find_self_container_id()
    if self_id:
        try:
            network = docker_client.networks.get(network_name)
            network.connect(self_id)
        except APIError:
            pass  # May already be connected

    # Discover running containers
    containers = docker_client.containers.list(
        filters={"label": f"demoforge.demo={demo.id}"}
    )
    for c in containers:
        node_id = c.labels.get("demoforge.node", "")
        component_id = c.labels.get("demoforge.component", "")
        running.containers[node_id] = RunningContainer(
            node_id=node_id,
            component_id=component_id,
            container_name=c.name,
            networks=[network_name],
        )

    running.status = "running"
    state.set_demo(running)
    return running

async def stop_demo(demo_id: str):
    """Bring down containers, disconnect from network, clean up."""
    running = state.get_demo(demo_id)
    if not running:
        return

    # Disconnect backend from demo network first
    self_id = _find_self_container_id()
    if self_id:
        for net_name in running.networks:
            try:
                network = docker_client.networks.get(net_name)
                network.disconnect(self_id)
            except (NotFound, APIError):
                pass

    # Docker compose down
    if running.compose_file_path:
        proc = await asyncio.create_subprocess_exec(
            "docker", "compose", "-f", running.compose_file_path,
            "-p", running.compose_project, "down", "-v",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

    state.remove_demo(demo_id)

def get_container_health(container_name: str) -> ContainerHealthStatus:
    """Check a container's health status via Docker API."""
    try:
        c = docker_client.containers.get(container_name)
        if c.status != "running":
            return ContainerHealthStatus.STOPPED
        health = c.attrs.get("State", {}).get("Health", {})
        health_status = health.get("Status", "none")
        if health_status == "healthy":
            return ContainerHealthStatus.HEALTHY
        elif health_status == "starting":
            return ContainerHealthStatus.STARTING
        elif health_status == "unhealthy":
            return ContainerHealthStatus.ERROR
        else:
            # No healthcheck defined — if running, assume healthy
            return ContainerHealthStatus.HEALTHY if c.status == "running" else ContainerHealthStatus.STOPPED
    except NotFound:
        return ContainerHealthStatus.STOPPED

async def restart_container(container_name: str):
    """Restart a single container."""
    try:
        c = docker_client.containers.get(container_name)
        c.restart(timeout=10)
    except NotFound:
        raise ValueError(f"Container {container_name} not found")

async def exec_in_container(container_name: str, command: str) -> tuple[int, str, str]:
    """Run a one-shot command in a container. Returns (exit_code, stdout, stderr)."""
    try:
        c = docker_client.containers.get(container_name)
        result = c.exec_run(command, demux=True)
        stdout = result.output[0].decode() if result.output[0] else ""
        stderr = result.output[1].decode() if result.output[1] else ""
        return result.exit_code, stdout, stderr
    except NotFound:
        raise ValueError(f"Container {container_name} not found")
```

### Step 7: Reverse proxy gateway

**File: `backend/app/engine/proxy_gateway.py`**

This is the critical piece. Routes browser requests to internal containers.

```python
"""
Reverse proxy: forwards /proxy/{demo}/{node}/{ui_name}/* to the container's
internal port over the Docker network.

The backend must be connected to the demo's Docker network for this to work.
Container is reached by its Docker Compose service hostname (node_id).
"""
import httpx
from fastapi import Request, Response
from fastapi.responses import StreamingResponse
from ..registry.loader import get_component
from ..state.store import state

# Persistent async HTTP client — connection pooling across requests
_http_client: httpx.AsyncClient | None = None

def get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=5.0),
            follow_redirects=False,          # We handle redirects ourselves
            limits=httpx.Limits(max_connections=100),
        )
    return _http_client

def resolve_target(demo_id: str, node_id: str, ui_name: str) -> tuple[str, str]:
    """
    Given demo/node/ui_name, return (base_url, ui_path).
    e.g. ("http://demoforge-lakehouse-minio-1:9001", "/")

    The hostname is the Docker Compose container name.
    """
    running = state.get_demo(demo_id)
    if not running:
        raise ValueError(f"Demo {demo_id} is not running")

    container_info = running.containers.get(node_id)
    if not container_info:
        raise ValueError(f"Node {node_id} not found in demo {demo_id}")

    manifest = get_component(container_info.component_id)
    if not manifest:
        raise ValueError(f"Component {container_info.component_id} not in registry")

    # Find the matching web_ui entry
    ui_def = None
    for ui in manifest.web_ui:
        if ui.name == ui_name:
            ui_def = ui
            break

    if not ui_def:
        # Fallback: if ui_name matches a port name, proxy to that port
        for port in manifest.ports:
            if port.name == ui_name:
                return f"http://{container_info.container_name}:{port.container}", "/"
        raise ValueError(f"UI '{ui_name}' not found for component {manifest.id}")

    base_url = f"http://{container_info.container_name}:{ui_def.port}"
    return base_url, ui_def.path

async def forward_request(
    request: Request,
    demo_id: str,
    node_id: str,
    ui_name: str,
    subpath: str = "",
) -> Response:
    """
    Forward an HTTP request to the target container.
    Handles: method, headers, body, query params, streaming response.
    Rewrites Location headers and Set-Cookie paths.
    """
    base_url, ui_base_path = resolve_target(demo_id, node_id, ui_name)

    # Build target URL
    target_path = f"{ui_base_path.rstrip('/')}/{subpath}" if subpath else ui_base_path
    target_url = f"{base_url}{target_path}"
    if request.url.query:
        target_url += f"?{request.url.query}"

    # Proxy prefix for rewriting
    proxy_prefix = f"/proxy/{demo_id}/{node_id}/{ui_name}"

    # Forward headers (remove host, adjust origin)
    headers = dict(request.headers)
    headers.pop("host", None)
    headers.pop("Host", None)

    # Read request body
    body = await request.body()

    client = get_http_client()
    upstream_resp = await client.request(
        method=request.method,
        url=target_url,
        headers=headers,
        content=body if body else None,
    )

    # Build response headers, rewriting as needed
    resp_headers = {}
    for key, value in upstream_resp.headers.multi_items():
        lower = key.lower()
        if lower in ("transfer-encoding", "content-encoding", "content-length"):
            continue
        if lower == "location":
            # Rewrite redirects to go through proxy
            value = _rewrite_location(value, base_url, proxy_prefix)
        if lower == "set-cookie":
            # Scope cookies to proxy path
            value = _rewrite_cookie_path(value, proxy_prefix)
        resp_headers[key] = value

    return Response(
        content=upstream_resp.content,
        status_code=upstream_resp.status_code,
        headers=resp_headers,
        media_type=upstream_resp.headers.get("content-type"),
    )

def _rewrite_location(location: str, base_url: str, proxy_prefix: str) -> str:
    """Rewrite an absolute Location header to route through the proxy."""
    if location.startswith(base_url):
        return proxy_prefix + location[len(base_url):]
    if location.startswith("/"):
        return proxy_prefix + location
    return location

def _rewrite_cookie_path(cookie: str, proxy_prefix: str) -> str:
    """Rewrite Path= in Set-Cookie to scope to the proxy prefix."""
    if "Path=" in cookie:
        import re
        return re.sub(r'Path=/[^;]*', f'Path={proxy_prefix}/', cookie)
    return cookie + f"; Path={proxy_prefix}/"
```

**File: `backend/app/api/proxy.py`** (API route that uses the gateway)

```python
"""Reverse proxy route: /proxy/{demo_id}/{node_id}/{ui_name}/{path:path}"""
from fastapi import APIRouter, Request
from ..engine.proxy_gateway import forward_request

router = APIRouter()

@router.api_route(
    "/proxy/{demo_id}/{node_id}/{ui_name}/{subpath:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
)
async def proxy_handler(
    request: Request,
    demo_id: str,
    node_id: str,
    ui_name: str,
    subpath: str = "",
):
    return await forward_request(request, demo_id, node_id, ui_name, subpath)

# Also handle the root path (no subpath)
@router.api_route(
    "/proxy/{demo_id}/{node_id}/{ui_name}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
)
async def proxy_handler_root(
    request: Request,
    demo_id: str,
    node_id: str,
    ui_name: str,
):
    return await forward_request(request, demo_id, node_id, ui_name, "")
```

### Step 8: Terminal bridge

**File: `backend/app/engine/terminal_bridge.py`**

```python
"""
WebSocket ↔ docker exec bridge.
Each WebSocket connection spawns a `docker exec -it <container> <shell>` subprocess.
stdin/stdout/stderr are relayed bidirectionally.
"""
import asyncio
import docker
from fastapi import WebSocket, WebSocketDisconnect

docker_client = docker.from_env()

async def terminal_session(websocket: WebSocket, container_name: str, shell: str = "/bin/sh"):
    """
    Open an interactive shell inside a container and relay I/O over WebSocket.
    Uses asyncio subprocess with docker exec for true PTY support.
    """
    await websocket.accept()

    proc = await asyncio.create_subprocess_exec(
        "docker", "exec", "-i", container_name, shell,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,  # Merge stderr into stdout
    )

    async def read_stdout():
        """Read from container stdout and send to WebSocket."""
        try:
            while True:
                data = await proc.stdout.read(4096)
                if not data:
                    break
                await websocket.send_bytes(data)
        except (WebSocketDisconnect, ConnectionError):
            pass
        finally:
            if proc.returncode is None:
                proc.kill()

    async def read_websocket():
        """Read from WebSocket and write to container stdin."""
        try:
            while True:
                data = await websocket.receive_bytes()
                if proc.stdin:
                    proc.stdin.write(data)
                    await proc.stdin.drain()
        except (WebSocketDisconnect, ConnectionError):
            pass
        finally:
            if proc.returncode is None:
                proc.kill()

    # Run both directions concurrently
    try:
        await asyncio.gather(read_stdout(), read_websocket())
    except Exception:
        pass
    finally:
        if proc.returncode is None:
            proc.kill()
        try:
            await websocket.close()
        except Exception:
            pass
```

### Step 9: Health monitor background task

**File: `backend/app/engine/health_monitor.py`**

```python
"""Background task that polls container health every 5 seconds."""
import asyncio
from ..state.store import state
from .docker_manager import get_container_health

async def health_monitor_loop():
    """Run forever, updating container health in the state store."""
    while True:
        for demo in state.list_demos():
            if demo.status != "running":
                continue
            for node_id, container in demo.containers.items():
                container.health = get_container_health(container.container_name)
        await asyncio.sleep(5)
```

### Step 10: API routes

**File: `backend/app/api/registry.py`**

```python
from fastapi import APIRouter
from ..registry.loader import get_registry
from ..models.api_models import RegistryResponse, ComponentSummary

router = APIRouter()

@router.get("/api/registry/components", response_model=RegistryResponse)
async def list_components():
    registry = get_registry()
    return RegistryResponse(
        components=[
            ComponentSummary(
                id=m.id,
                name=m.name,
                category=m.category,
                icon=m.icon,
                description=m.description,
                variants=list(m.variants.keys()),
            )
            for m in registry.values()
        ]
    )
```

**File: `backend/app/api/demos.py`**

```python
import os
import uuid
import yaml
from fastapi import APIRouter, HTTPException
from ..models.demo import DemoDefinition, DemoNetwork, DemoNode, DemoEdge, NodePosition
from ..models.api_models import (
    DemoListResponse, DemoSummary, CreateDemoRequest, SaveDiagramRequest,
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
                        id=d.id,
                        name=d.name,
                        description=d.description,
                        node_count=len(d.nodes),
                        status=running.status if running else "stopped",
                    ))
    return DemoListResponse(demos=demos)

@router.post("/api/demos", response_model=DemoSummary)
async def create_demo(req: CreateDemoRequest):
    demo_id = str(uuid.uuid4())[:8]
    demo = DemoDefinition(
        id=demo_id,
        name=req.name,
        description=req.description,
        network=DemoNetwork(name=f"demoforge-{demo_id}-net"),
    )
    _save_demo(demo)
    return DemoSummary(id=demo.id, name=demo.name, description=demo.description, node_count=0, status="stopped")

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

    # Convert React Flow nodes → DemoNodes
    demo.nodes = []
    for rf_node in req.nodes:
        data = rf_node.get("data", {})
        demo.nodes.append(DemoNode(
            id=rf_node["id"],
            component=data.get("componentId", ""),
            variant=data.get("variant", "single"),
            position=NodePosition(x=rf_node.get("position", {}).get("x", 0),
                                   y=rf_node.get("position", {}).get("y", 0)),
            config=data.get("config", {}),
        ))

    demo.edges = []
    for rf_edge in req.edges:
        demo.edges.append(DemoEdge(
            id=rf_edge["id"],
            source=rf_edge["source"],
            target=rf_edge["target"],
            label=rf_edge.get("label", ""),
        ))

    _save_demo(demo)
    return {"status": "saved"}

@router.delete("/api/demos/{demo_id}")
async def delete_demo(demo_id: str):
    path = os.path.join(DEMOS_DIR, f"{demo_id}.yaml")
    if os.path.exists(path):
        os.remove(path)
    return {"status": "deleted"}
```

**File: `backend/app/api/deploy.py`**

```python
import os
from fastapi import APIRouter, HTTPException
from ..models.api_models import DeployResponse
from ..engine.docker_manager import deploy_demo, stop_demo
from ..state.store import state
from .demos import _load_demo

router = APIRouter()
DATA_DIR = os.environ.get("DEMOFORGE_DATA_DIR", "./data")

@router.post("/api/demos/{demo_id}/deploy", response_model=DeployResponse)
async def deploy(demo_id: str):
    demo = _load_demo(demo_id)
    if not demo:
        raise HTTPException(404, "Demo not found")
    if not demo.nodes:
        raise HTTPException(400, "Demo has no nodes to deploy")

    existing = state.get_demo(demo_id)
    if existing and existing.status == "running":
        raise HTTPException(409, "Demo is already running")

    try:
        running = await deploy_demo(demo, DATA_DIR)
        return DeployResponse(demo_id=demo_id, status=running.status)
    except Exception as e:
        return DeployResponse(demo_id=demo_id, status="error", message=str(e))

@router.post("/api/demos/{demo_id}/stop", response_model=DeployResponse)
async def stop(demo_id: str):
    try:
        await stop_demo(demo_id)
        return DeployResponse(demo_id=demo_id, status="stopped")
    except Exception as e:
        return DeployResponse(demo_id=demo_id, status="error", message=str(e))
```

**File: `backend/app/api/instances.py`**

```python
from fastapi import APIRouter, HTTPException
from ..state.store import state
from ..registry.loader import get_component
from ..engine.docker_manager import get_container_health, restart_container, exec_in_container
from ..models.api_models import (
    InstancesResponse, ContainerInstance, WebUILink,
    ExecRequest, ExecResponse,
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
        container.health = health  # Update cache

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
            node_id=node_id,
            component_id=container.component_id,
            container_name=container.container_name,
            health=health,
            web_uis=web_uis,
            has_terminal=True,
            quick_actions=quick_actions,
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

**File: `backend/app/api/terminal.py`**

```python
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from ..state.store import state
from ..registry.loader import get_component
from ..engine.terminal_bridge import terminal_session

router = APIRouter()

@router.websocket("/api/demos/{demo_id}/instances/{node_id}/terminal")
async def terminal_endpoint(websocket: WebSocket, demo_id: str, node_id: str):
    running = state.get_demo(demo_id)
    if not running or node_id not in running.containers:
        await websocket.close(code=4004, reason="Instance not found")
        return

    container = running.containers[node_id]
    manifest = get_component(container.component_id)
    shell = manifest.terminal.shell if manifest else "/bin/sh"

    await terminal_session(websocket, container.container_name, shell)
```

**File: `backend/app/api/health.py`**

```python
from fastapi import APIRouter, HTTPException
from ..state.store import state
from ..engine.docker_manager import get_container_health

router = APIRouter()

@router.get("/api/demos/{demo_id}/instances/{node_id}/health")
async def get_health(demo_id: str, node_id: str):
    running = state.get_demo(demo_id)
    if not running or node_id not in running.containers:
        raise HTTPException(404, "Instance not found")
    container = running.containers[node_id]
    health = get_container_health(container.container_name)
    return {"node_id": node_id, "health": health.value}
```

### Step 11: FastAPI app assembly

**File: `backend/app/main.py`**

```python
import os
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .registry.loader import load_registry
from .engine.health_monitor import health_monitor_loop
from .api import registry, demos, deploy, instances, proxy, terminal, health

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    components_dir = os.environ.get("DEMOFORGE_COMPONENTS_DIR", "./components")
    load_registry(components_dir)
    monitor_task = asyncio.create_task(health_monitor_loop())
    yield
    # Shutdown
    monitor_task.cancel()

app = FastAPI(title="DemoForge API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(registry.router)
app.include_router(demos.router)
app.include_router(deploy.router)
app.include_router(instances.router)
app.include_router(health.router)
app.include_router(terminal.router)

# Proxy routes (must be last — catch-all pattern)
app.include_router(proxy.router)
```

### Step 12: Frontend — types and API client

**File: `frontend/src/types/index.ts`**

```typescript
// --- Registry ---
export interface ComponentSummary {
  id: string;
  name: string;
  category: string;
  icon: string;
  description: string;
  variants: string[];
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
}

// --- React Flow node data ---
export interface ComponentNodeData {
  label: string;
  componentId: string;
  variant: string;
  config: Record<string, string>;
  health?: HealthStatus;
}
```

**File: `frontend/src/api/client.ts`**

```typescript
const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`);
  return res.json();
}

// Registry
export const fetchComponents = () =>
  apiFetch<{ components: import("../types").ComponentSummary[] }>("/api/registry/components");

// Demos
export const fetchDemos = () =>
  apiFetch<{ demos: import("../types").DemoSummary[] }>("/api/demos");

export const createDemo = (name: string, description = "") =>
  apiFetch<import("../types").DemoSummary>("/api/demos", {
    method: "POST",
    body: JSON.stringify({ name, description }),
  });

export const fetchDemo = (id: string) => apiFetch<any>(`/api/demos/${id}`);

export const saveDiagram = (id: string, nodes: any[], edges: any[]) =>
  apiFetch<any>(`/api/demos/${id}/diagram`, {
    method: "PUT",
    body: JSON.stringify({ nodes, edges }),
  });

export const deleteDemo = (id: string) =>
  apiFetch<any>(`/api/demos/${id}`, { method: "DELETE" });

// Deploy
export const deployDemo = (id: string) =>
  apiFetch<{ demo_id: string; status: string; message?: string }>(
    `/api/demos/${id}/deploy`,
    { method: "POST" }
  );

export const stopDemo = (id: string) =>
  apiFetch<{ demo_id: string; status: string }>(
    `/api/demos/${id}/stop`,
    { method: "POST" }
  );

// Instances
export const fetchInstances = (demoId: string) =>
  apiFetch<{
    demo_id: string;
    status: string;
    instances: import("../types").ContainerInstance[];
  }>(`/api/demos/${demoId}/instances`);

// Exec
export const execCommand = (demoId: string, nodeId: string, command: string) =>
  apiFetch<{ exit_code: number; stdout: string; stderr: string }>(
    `/api/demos/${demoId}/instances/${nodeId}/exec`,
    { method: "POST", body: JSON.stringify({ command }) }
  );

// Terminal WebSocket URL
export const terminalWsUrl = (demoId: string, nodeId: string) =>
  `${API_BASE.replace("http", "ws")}/api/demos/${demoId}/instances/${nodeId}/terminal`;

// Proxy URL (for opening web UIs)
export const proxyUrl = (path: string) => `${API_BASE}${path}`;
```

### Step 13: Frontend — Zustand stores

**File: `frontend/src/stores/diagramStore.ts`**

```typescript
import { create } from "zustand";
import { Node, Edge, OnNodesChange, OnEdgesChange, applyNodeChanges, applyEdgeChanges, Connection, addEdge } from "@xyflow/react";

interface DiagramState {
  nodes: Node[];
  edges: Edge[];
  selectedNodeId: string | null;
  onNodesChange: OnNodesChange;
  onEdgesChange: OnEdgesChange;
  onConnect: (connection: Connection) => void;
  addNode: (node: Node) => void;
  setSelectedNode: (id: string | null) => void;
  setNodes: (nodes: Node[]) => void;
  setEdges: (edges: Edge[]) => void;
  updateNodeHealth: (nodeId: string, health: string) => void;
}

export const useDiagramStore = create<DiagramState>((set, get) => ({
  nodes: [],
  edges: [],
  selectedNodeId: null,

  onNodesChange: (changes) =>
    set({ nodes: applyNodeChanges(changes, get().nodes) }),

  onEdgesChange: (changes) =>
    set({ edges: applyEdgeChanges(changes, get().edges) }),

  onConnect: (connection) =>
    set({ edges: addEdge(connection, get().edges) }),

  addNode: (node) => set({ nodes: [...get().nodes, node] }),

  setSelectedNode: (id) => set({ selectedNodeId: id }),

  setNodes: (nodes) => set({ nodes }),
  setEdges: (edges) => set({ edges }),

  updateNodeHealth: (nodeId, health) =>
    set({
      nodes: get().nodes.map((n) =>
        n.id === nodeId ? { ...n, data: { ...n.data, health } } : n
      ),
    }),
}));
```

**File: `frontend/src/stores/demoStore.ts`**

```typescript
import { create } from "zustand";
import type { DemoSummary, ContainerInstance } from "../types";

interface DemoState {
  demos: DemoSummary[];
  activeDemoId: string | null;
  instances: ContainerInstance[];
  activeView: "diagram" | "control-plane";
  setDemos: (demos: DemoSummary[]) => void;
  setActiveDemoId: (id: string | null) => void;
  setInstances: (instances: ContainerInstance[]) => void;
  setActiveView: (view: "diagram" | "control-plane") => void;
  updateDemoStatus: (id: string, status: DemoSummary["status"]) => void;
}

export const useDemoStore = create<DemoState>((set, get) => ({
  demos: [],
  activeDemoId: null,
  instances: [],
  activeView: "diagram",

  setDemos: (demos) => set({ demos }),
  setActiveDemoId: (id) => set({ activeDemoId: id }),
  setInstances: (instances) => set({ instances }),
  setActiveView: (view) => set({ activeView: view }),

  updateDemoStatus: (id, status) =>
    set({
      demos: get().demos.map((d) => (d.id === id ? { ...d, status } : d)),
    }),
}));
```

### Step 14: Frontend — React components

Build in this order: `Toolbar` → `ComponentPalette` → `ComponentNode` → `DiagramCanvas` → `PropertiesPanel` → `ControlPlane` components → `TerminalPanel` → `App.tsx`

Each component is described here by its **contract** — what props it takes, what it renders, what actions it triggers. Claude Code should implement the full component.

**`Toolbar.tsx`**: Top bar. Shows demo name, a dropdown to select/create demos, Deploy button (calls `deployDemo()`), Stop button (calls `stopDemo()`), and a toggle between "Diagram" and "Control Plane" views. Uses `useDemoStore`.

**`ComponentPalette.tsx`**: Left sidebar. Fetches `/api/registry/components` on mount. Renders a list of component cards grouped by category. Each card is draggable (HTML5 drag). On drag start, sets `dataTransfer` with component ID and variant. Styled with Tailwind, compact.

**`ComponentNode.tsx`**: Custom React Flow node. Receives `ComponentNodeData` as `data`. Renders: component name, variant label, a colored health dot (if deployed), and category icon placeholder. On click, sets `selectedNodeId` in diagramStore. On double-click, if the demo is running and the component has a web UI, opens the proxy URL.

**`DiagramCanvas.tsx`**: Wraps `<ReactFlow>`. Connects to `useDiagramStore` for nodes/edges/handlers. Implements `onDrop` handler: reads component ID from `dataTransfer`, creates a new node at drop position with a unique ID (`{componentId}-{counter}`), adds it to the store. Includes `<MiniMap>`, `<Controls>`, `<Background>`. Calls `saveDiagram()` debounced (500ms) after any node/edge change.

**`PropertiesPanel.tsx`**: Right sidebar. When `selectedNodeId` is set, shows: component name, variant selector (dropdown from manifest variants), environment variable overrides (editable key-value pairs from manifest `secrets`), and if running: health badge, web UI links, terminal button.

**`ControlPlane.tsx`**: Shown when `activeView === "control-plane"`. Fetches `/api/demos/{id}/instances` on mount and polls every 5 seconds. Renders a `ComponentCard` for each instance.

**`ComponentCard.tsx`**: Shows: node name, component name, `HealthBadge`, list of web UI buttons (each opens an iframe or new tab), terminal button (opens a terminal tab), quick-action chips. Clicking the card calls `setSelectedNode` to sync with diagram.

**`HealthBadge.tsx`**: Colored circle + text. Green=healthy, yellow=starting, orange=degraded, red=error, gray=stopped.

**`WebUIFrame.tsx`**: Full-width iframe that loads a proxy URL. Includes a "pop out" button to open in new tab. Shown when a web UI link is clicked.

**`TerminalPanel.tsx`**: Bottom panel with tabs. Each tab is a `TerminalTab` for a different container. "+" button adds a new tab (lets you pick which container).

**`TerminalTab.tsx`**: Mounts an xterm.js `Terminal` instance. On mount, opens a WebSocket to `/api/demos/{demoId}/instances/{nodeId}/terminal`. Relays input/output between xterm and WebSocket. Shows quick-action chips above the terminal that send commands on click.

**`App.tsx`**: Root layout. Fetches demos on mount. Renders: `Toolbar` (top), three-column layout with `ComponentPalette` (left, 200px), `DiagramCanvas` or `ControlPlane` depending on `activeView` (center, flex), `PropertiesPanel` (right, 280px), `TerminalPanel` (bottom, 250px, resizable).

---

## 3. Verification Checklist

After building everything, test these in order:

1. **Backend starts**: `cd backend && uvicorn app.main:app` — no import errors, registry loads 1 component (minio)
2. **Registry API**: `GET /api/registry/components` returns minio with its variants
3. **Demo CRUD**: Create a demo, get it back, delete it
4. **Frontend renders**: Vite dev server shows the canvas with MinIO in the palette
5. **Drag and drop**: Drag MinIO onto canvas, see a node appear
6. **Save diagram**: Node positions and component IDs persist to YAML on disk
7. **Deploy**: Click Deploy → `docker compose up` runs → MinIO container starts → health turns green
8. **Instances API**: `GET /api/demos/{id}/instances` returns the running MinIO with proxy URL
9. **Proxy works**: Open `/proxy/{demo}/minio-1/console/` → see MinIO Console login page
10. **Terminal works**: Open terminal tab for minio-1 → type `ls /data` → see output
11. **Stop**: Click Stop → containers removed → network cleaned up
12. **Re-deploy**: Deploy again → works cleanly (no stale state)

---

## 4. What is NOT in Phase 1

Do not build any of these yet:
- Multiple component types (only `minio` manifest exists)
- Replication setup scripts
- Traffic generator
- Prometheus/Grafana monitoring stack
- Secret vault (use hardcoded defaults for now)
- Network latency simulation
- Demo templates gallery
- Embedded iframe previews (just open in new tab for now)
- Persistent terminal history
- WebSocket-based live health push (use polling for now)
- Edge animations or live traffic indicators

These all come in Phase 2+. Phase 1's job is to prove the core loop: diagram → compose → deploy → proxy → terminal.
