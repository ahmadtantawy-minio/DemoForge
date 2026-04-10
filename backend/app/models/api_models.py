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
    status: str                   # "deploying", "running", "error", "queued"
    message: str = ""
    task_id: str = ""             # Non-empty when operation is backgrounded

class TaskStatusResponse(BaseModel):
    task_id: str
    demo_id: str
    operation: str                # "deploy" | "stop" | "destroy" | "start"
    status: str                   # "queued" | "running" | "done" | "error" | "timeout"
    error: str = ""
    steps: list[dict] = []
    finished: bool = False

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
    stopped_drives: list[int] = []

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
    cluster_health: dict[str, str] = {}  # cluster_id → "healthy" | "degraded" | "unreachable"

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

class ExecLogRequest(BaseModel):
    command: str

class LogResponse(BaseModel):
    lines: list[str]
    container: str
    truncated: bool

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
    built_at: Optional[str] = None

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
