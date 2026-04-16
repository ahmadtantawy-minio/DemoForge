// --- Connection types ---
export type ConnectionType = "s3" | "http" | "metrics" | "replication" | "site-replication" | "load-balance" | "data" | "metrics-query" | "tiering" | "file-push" | "cluster-replication" | "cluster-site-replication" | "cluster-tiering" | "iceberg-catalog" | "sql-query" | "s3-queue" | "spark-submit" | "hdfs" | "failover" | "llm-api" | "vector-db" | "mlflow-tracking" | "labeling-api" | "vector-db-milvus" | "etcd" | "workflow-api" | "llm-gateway" | "structured-data" | "kafka" | "kafka-connect" | "dremio-sql" | "dremio-flight" | "schema-registry" | "aistor-tables" | "inference-api" | "nginx-backend" | "external-api" | "dashboard-provision" | "webhook";

// --- Edge data ---
export interface ComponentEdgeData {
  connectionType: ConnectionType;
  network: string;
  label: string;
  status?: "active" | "idle" | "error";
  connectionConfig?: Record<string, any>;
  autoConfigure?: boolean;
}

// --- Network ---
export interface NetworkMembership {
  network_name: string;
  ip_address?: string;
  aliases: string[];
}

// --- Credentials ---
export interface CredentialInfo {
  key: string;
  label: string;
  value: string;
}

// --- Demo Template ---
export interface DemoTemplate {
  id: string;
  name: string;
  description: string;
  tier: "essentials" | "advanced" | "experience";
  category: string;
  tags: string[];
  objective: string;
  minio_value: string;
  mode?: "standard" | "experience";
  component_count: number;
  container_count: number;
  estimated_resources: {
    memory?: string;
    cpu?: number;
    containers?: number;
  };
  walkthrough: { step: string; description: string }[];
  external_dependencies: string[];
  has_se_guide: boolean;
  source: "builtin" | "synced" | "user";
  editable: boolean;
  customized?: boolean;
  origin?: string;  // "builtin" | "synced" | "user"
  saved_by?: string;
  validated?: boolean;
  archived?: boolean;
  updated_at?: string;  // ISO date of most recent changelog entry (builtin/synced only)
  changelog?: Array<{ date: string; summary: string; changed_by?: string }>;
}

// --- Demo Template Detail (includes demo definition fields) ---
export interface DemoTemplateDetail extends DemoTemplate {
  nodes: any[];
  edges: any[];
  clusters: any[];
  networks: any[];
  groups: any[];
}

// --- Connection schema ---
export interface ConnectionConfigField {
  key: string;
  label: string;
  type: string; // "string" | "number" | "boolean" | "select"
  default: string;
  required: boolean;
  options: string[];
  description: string;
}

export interface ConnectionProvides {
  type: string;
  port: number;
  description: string;
  path: string;
  config_schema: ConnectionConfigField[];
  env_map?: { config_key: string; env_var: string }[];
}

export interface ConnectionAccepts {
  type: string;
  config_schema: ConnectionConfigField[];
}

export interface ConnectionsDef {
  provides: ConnectionProvides[];
  accepts: ConnectionAccepts[];
}

// --- Registry ---
export interface ComponentSummary {
  id: string;
  name: string;
  category: string;
  icon: string;
  description: string;
  image: string;
  variants: string[];
  connections: ConnectionsDef;
  virtual?: boolean;
  properties?: ConnectionConfigField[];
}

// --- Demo ---
export interface DemoSummary {
  id: string;
  name: string;
  description: string;
  node_count: number;
  status: "not_deployed" | "stopped" | "deploying" | "running" | "stopping" | "error";
  mode?: "standard" | "experience";
  updated_at?: string;
  source_template_id?: string;
}

export interface AnnotationNodeData {
  title: string;
  body: string;
  style: "info" | "callout" | "warning" | "step";
  stepNumber?: number;
  width?: number;
  height?: number;
  fontSize?: "sm" | "base" | "lg" | "xl";
  pointerTarget?: string;
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
  networks: NetworkMembership[];
  credentials: CredentialInfo[];
  init_status: "pending" | "running" | "completed" | "failed" | "timeout";
  stopped_drives?: number[];
  is_sidecar?: boolean;
}

// --- React Flow node data ---
export interface ComponentNodeData {
  label: string;
  componentId: string;
  variant: string;
  config: Record<string, string>;
  health?: HealthStatus;
  networks?: string[];
  displayName?: string;
  labels?: Record<string, string>;
  groupId?: string | null;
  aistorTablesEnabled?: boolean;
  mcpEnabled?: boolean;
}

export type DiskType = "nvme" | "ssd" | "hdd";

export interface CanvasImage {
  id: string;
  image_id: string;
  position: { x: number; y: number };
  width: number;
  height: number;
  opacity: number;
  layer: "background" | "foreground";
  label: string;
  locked: boolean;
}

export interface MinioServerPool {
  id: string;
  nodeCount: number;
  drivesPerNode: number;
  diskSizeTb: number;
  diskType: DiskType;
  ecParity: number;
  ecParityUpgradePolicy: string;
  volumePath: string;
}

export interface ClusterNodeData {
  label: string;
  componentId: string;
  credentials: Record<string, string>;
  config: Record<string, string>;
  health?: HealthStatus;
  loadBalancer?: boolean;
  mcpEnabled?: boolean;
  aistorTablesEnabled?: boolean;
  serverPools?: MinioServerPool[];
  /** Persisted pool lifecycle (idle | decommissioning | decommissioned) from demo YAML */
  poolLifecycle?: Record<string, string>;
  // DEPRECATED flat fields — present in old data, migrated on load
  nodeCount?: number;
  drivesPerNode?: number;
  ecParity?: number;
  ecParityUpgradePolicy?: string;
  diskSizeTb?: number;
}

export interface ScenarioDataset {
  id: string;
  target: "table" | "object" | string;
  format?: string;
  namespace: string;
  table_name: string;
  generation_mode: string;
  description: string;
  stream_rate?: string;
  seed_rows?: number;
  has_raw_landing?: boolean;
  seed_count?: number;
}

export interface ScenarioOption {
  id: string;
  name: string;
  description: string;
  category: string;
  icon: string;
  default_name: string;
  default_subtitle: string;
  format?: string;
  primary_table?: string;
  datasets?: ScenarioDataset[];
}

export interface DemoGroup {
  id: string;
  label: string;
  description?: string;
  color?: string;
  style?: string;
  position: { x: number; y: number };
  width?: number;
  height?: number;
  mode?: "visual" | "cluster";
  cluster_config?: Record<string, any>;
}
