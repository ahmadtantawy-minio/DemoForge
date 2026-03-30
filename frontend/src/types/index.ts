// --- Connection types ---
export type ConnectionType = "s3" | "http" | "metrics" | "replication" | "site-replication" | "load-balance" | "data" | "metrics-query" | "tiering" | "file-push" | "cluster-replication" | "cluster-site-replication" | "cluster-tiering" | "iceberg-catalog" | "sql-query" | "s3-queue" | "spark-submit" | "hdfs" | "failover" | "llm-api" | "vector-db" | "mlflow-tracking" | "labeling-api" | "vector-db-milvus" | "etcd" | "workflow-api" | "llm-gateway" | "structured-data" | "kafka" | "kafka-connect" | "dremio-sql" | "dremio-flight" | "schema-registry" | "aistor-tables" | "inference-api";

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
}

// --- Demo ---
export interface DemoSummary {
  id: string;
  name: string;
  description: string;
  node_count: number;
  status: "stopped" | "deploying" | "running" | "error";
  mode?: "standard" | "experience";
}

export interface AnnotationNodeData {
  title: string;
  body: string;
  style: "info" | "callout" | "warning" | "step";
  stepNumber?: number;
  width?: number;
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
  init_status: "pending" | "running" | "completed" | "failed";
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
}

export interface ClusterNodeData {
  label: string;
  componentId: string;
  nodeCount: number;
  drivesPerNode: number;
  credentials: Record<string, string>;
  config: Record<string, string>;
  health?: HealthStatus;
  mcpEnabled?: boolean;
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
