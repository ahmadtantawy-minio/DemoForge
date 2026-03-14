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

class LicenseRequirement(BaseModel):
    license_id: str           # Global key, e.g. "minio-enterprise"
    label: str                # Human-readable: "MinIO Enterprise License"
    description: str = ""     # Help text
    injection_type: str = "env_var"  # "env_var" | "file_mount"
    env_var: str | None = None       # e.g. "MINIO_SUBNET_LICENSE"
    mount_path: str | None = None    # e.g. "/etc/minio/license.key"
    required: bool = True

class InitScriptDef(BaseModel):
    command: str
    wait_for_healthy: bool = True
    timeout: int = 60
    order: int = 0
    description: str = ""

class TemplateMountDef(BaseModel):
    template: str        # Filename in templates/ dir
    mount_path: str      # Container path

class StaticMountDef(BaseModel):
    host_path: str       # Relative to component dir
    mount_path: str      # Container path

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
    template_mounts: list[TemplateMountDef] = []
    static_mounts: list[StaticMountDef] = []
    init_scripts: list[InitScriptDef] = []
    license_requirements: list[LicenseRequirement] = []
