"""Pydantic models for demo definitions (saved/loaded as YAML)."""
from typing import Any
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
    networks: dict[str, NodeNetworkConfig] = {}
    display_name: str = ""          # User-editable label
    labels: dict[str, str] = {}     # Key-value annotations
    group_id: str | None = None     # References a DemoGroup.id

class DemoEdge(BaseModel):
    id: str
    source: str                   # Node ID
    target: str                   # Node ID
    connection_type: str = "data" # Connection type (s3, jdbc, etc.)
    network: str = "default"      # Which network this edge traverses
    connection_config: dict[str, Any] = {}  # Type-specific config
    auto_configure: bool = True             # Auto-generate init scripts
    label: str = ""
    protocol: str = ""                # e.g. "NVMe-oF / RDMA", "S3 over TCP"
    latency: str = ""                 # e.g. "~200-500 μs", "~5-50 ms"
    bandwidth: str = ""               # e.g. "800 Gb/s"
    source_handle: str | None = None  # React Flow handle ID
    target_handle: str | None = None  # React Flow handle ID

class DemoGroup(BaseModel):
    id: str
    label: str
    description: str = ""
    color: str = "#3b82f6"
    style: str = "solid"        # solid | dashed | dotted
    position: NodePosition
    width: float = 400
    height: float = 300
    mode: str = "visual"           # "visual" | "cluster"
    cluster_config: dict[str, Any] = {}  # e.g. {"drives_per_node": 1}

class DemoCluster(BaseModel):
    id: str
    component: str = "minio"          # "minio" or "minio-aistore"
    label: str = "MinIO Cluster"
    position: NodePosition
    node_count: int = 4
    drives_per_node: int = 1
    credentials: dict[str, str] = {}  # root_user, root_password
    config: dict[str, str] = {}
    width: float = 280
    height: float = 200
    mcp_enabled: bool = True          # Deploy MCP sidecar for AI tool access
    aistor_tables_enabled: bool = False  # Enable AIStor Tables (direct Trino connection)

class DemoStickyNote(BaseModel):
    id: str
    text: str = ""
    color: str = "#eab308"
    position: NodePosition
    width: float = 200
    height: float = 120

class SchematicChild(BaseModel):
    id: str
    label: str
    detail: str = ""
    color: str = "gray"          # "red" | "amber" | "blue" | "teal" | "gray"

class DemoSchematicNode(BaseModel):
    id: str
    position: NodePosition
    label: str
    sublabel: str = ""
    variant: str = "generic"      # "gpu" | "tier" | "generic"
    children: list[SchematicChild] = []
    parent_group: str | None = None
    width: int | None = None
    height: int | None = None

class DemoAnnotation(BaseModel):
    id: str
    position: NodePosition
    width: int = 300
    title: str = ""
    body: str = ""
    style: str = "info"                      # "info" | "callout" | "warning" | "step"
    step_number: int | None = None
    pointer_target: str | None = None
    collapsed: bool = False

class DemoNetwork(BaseModel):
    name: str
    subnet: str = "172.20.0.0/16"
    dns_suffix: str = "demo.local"
    driver: str = "bridge"

class DemoResourceSettings(BaseModel):
    """Demo-level resource limits applied to all containers."""
    default_memory: str = ""       # e.g. "512m", "1g" — per-container default, empty = use manifest
    default_cpu: float = 0         # e.g. 0.5, 1.0 — per-container default, 0 = use manifest
    max_memory: str = ""           # Per-container cap — empty = no cap
    max_cpu: float = 0             # Per-container cap — 0 = no cap
    total_memory: str = ""         # Total demo budget — e.g. "32g", empty = no limit
    total_cpu: float = 0           # Total demo budget — e.g. 16.0, 0 = no limit

class DemoDefinition(BaseModel):
    """Complete demo definition — serializable to/from YAML."""
    id: str
    name: str
    description: str = ""
    mode: str = "standard"          # "standard" | "experience"
    networks: list[DemoNetwork] = [DemoNetwork(name="default")]
    nodes: list[DemoNode] = []
    edges: list[DemoEdge] = []
    groups: list[DemoGroup] = []
    sticky_notes: list[DemoStickyNote] = []
    annotations: list[DemoAnnotation] = []
    schematics: list[DemoSchematicNode] = []
    clusters: list[DemoCluster] = []
    resources: DemoResourceSettings = DemoResourceSettings()
    deploy_timeout_seconds: int | None = None  # None = use global default (180s)
