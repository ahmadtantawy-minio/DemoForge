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

class DemoGroup(BaseModel):
    id: str
    label: str
    description: str = ""
    color: str = "#3b82f6"
    style: str = "solid"        # solid | dashed | dotted
    position: NodePosition
    width: float = 400
    height: float = 300

class DemoStickyNote(BaseModel):
    id: str
    text: str = ""
    color: str = "#eab308"
    position: NodePosition
    width: float = 200
    height: float = 120

class DemoNetwork(BaseModel):
    name: str
    subnet: str = "172.20.0.0/16"
    dns_suffix: str = "demo.local"
    driver: str = "bridge"

class DemoDefinition(BaseModel):
    """Complete demo definition — serializable to/from YAML."""
    id: str
    name: str
    description: str = ""
    networks: list[DemoNetwork] = [DemoNetwork(name="default")]
    nodes: list[DemoNode] = []
    edges: list[DemoEdge] = []
    groups: list[DemoGroup] = []
    sticky_notes: list[DemoStickyNote] = []
