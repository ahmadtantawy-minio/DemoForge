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
