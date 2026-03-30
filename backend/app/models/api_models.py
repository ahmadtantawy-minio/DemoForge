"""Request/response models for all API endpoints."""
from typing import Literal, Optional
from pydantic import BaseModel
from enum import Enum

# --- Registry ---
class ComponentSummary(BaseModel):
    id: str
    name: str
    category: str
    icon: str
    description: str
    image: str = ""               # Docker image, e.g. "minio/minio:latest"
    variants: list[str]           # Just the variant names
    connections: dict = {}        # {provides: [...], accepts: [...]}
    image_size_mb: float | None = None

class RegistryResponse(BaseModel):
    components: list[ComponentSummary]

# --- Demos ---
class DemoSummary(BaseModel):
    id: str
    name: str
    description: str
    node_count: int
    status: str                   # "stopped", "deploying", "running", "error"
    mode: str = "standard"        # "standard" | "experience"

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

class NetworkMembership(BaseModel):
    network_name: str
    ip_address: str | None = None
    aliases: list[str] = []

class CredentialInfo(BaseModel):
    key: str
    label: str
    value: str

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
    networks: list[NetworkMembership] = []
    credentials: list[CredentialInfo] = []
    init_status: str = "pending"

class EdgeConfigStatus(BaseModel):
    edge_id: str
    connection_type: str
    status: str = "pending"  # "pending", "applied", "failed"
    description: str = ""
    error: str = ""

class InstancesResponse(BaseModel):
    demo_id: str
    status: str
    instances: list[ContainerInstance]
    init_results: list[dict] = []
    edge_configs: list[EdgeConfigStatus] = []

# --- Errors ---
class ErrorDetail(BaseModel):
    code: str        # e.g. "DOCKER_NOT_RUNNING", "COMPONENT_NOT_FOUND", "COMPOSE_FAILED"
    message: str
    details: str = ""

# --- Exec ---
class ExecRequest(BaseModel):
    command: str

class ExecResponse(BaseModel):
    exit_code: int
    stdout: str
    stderr: str

# --- Images ---
class ImageInfo(BaseModel):
    component_name: str
    image_ref: str
    category: Literal["vendor", "custom", "platform"]
    cached: bool
    local_size_mb: Optional[float] = None
    manifest_size_mb: Optional[float] = None
    effective_size_mb: Optional[float] = None
    pull_source: str
    status: Literal["cached", "missing", "unknown"]

class PullRequest(BaseModel):
    image_ref: str

class PullStatus(BaseModel):
    pull_id: str
    image_ref: str
    status: Literal["pulling", "complete", "error"]
    progress_pct: Optional[int] = None
    error: Optional[str] = None

class PullResponse(BaseModel):
    pull_id: str
