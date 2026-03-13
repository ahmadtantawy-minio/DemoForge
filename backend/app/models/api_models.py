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
