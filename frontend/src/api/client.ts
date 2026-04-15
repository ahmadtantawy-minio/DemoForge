import { createElement } from "react";
import { Copy } from "lucide-react";
import { useDebugStore } from "../stores/debugStore";
import { toast } from "../lib/toast";

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:9210";

function debugLog(level: "info" | "warn" | "error", source: string, message: string, details?: string) {
  try { useDebugStore.getState().addEntry(level, source, message, details); } catch {}
}

export async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const method = options?.method || "GET";
  debugLog("info", "API", `${method} ${path}`);
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    if (!res.ok) {
      const body = await res.text();
      debugLog("error", "API", `${method} ${path} → ${res.status}`, body);
      // Toast on non-GET errors (user-initiated actions), skip polling endpoints
      if (method !== "GET" && !path.endsWith("/exec")) {
        toast.error(`API Error: ${method} ${path}`, {
          description: body.slice(0, 200),
          duration: 10000,
          action: { label: createElement(Copy, { className: "w-3.5 h-3.5", strokeWidth: 1.5 }) as unknown as string, onClick: () => navigator.clipboard.writeText(body) },
        });
      }
      throw new Error(`API error ${res.status}: ${body}`);
    }
    const data = await res.json();
    debugLog("info", "API", `${method} ${path} → ${res.status}`);
    return data;
  } catch (err: any) {
    if (!err.message?.startsWith("API error")) {
      debugLog("error", "API", `${method} ${path} failed`, err.message);
    }
    throw err;
  }
}

// Registry
export const fetchComponents = () =>
  apiFetch<{ components: import("../types").ComponentSummary[] }>("/api/registry/components");

export const fetchComponentManifest = (componentId: string) =>
  apiFetch<any>(`/api/registry/components/${componentId}`);

export const fetchComponentScenarios = (componentId: string) =>
  apiFetch<{ scenarios: import("../types").ScenarioOption[]; component_id: string }>(
    `/api/registry/components/${componentId}/scenarios`
  );

// Demos
export const fetchDemos = () =>
  apiFetch<{ demos: import("../types").DemoSummary[] }>("/api/demos");

export const createDemo = (name: string, description = "") =>
  apiFetch<import("../types").DemoSummary>("/api/demos", {
    method: "POST",
    body: JSON.stringify({ name, description }),
  });

export const fetchDemo = (id: string) => apiFetch<any>(`/api/demos/${id}`);

export const updateDemo = (id: string, patch: { name?: string; description?: string }) =>
  apiFetch<import("../types").DemoSummary>(`/api/demos/${id}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });

export const fetchGeneratedConfig = (id: string) =>
  apiFetch<{ demo_id: string; configs: Record<string, string> }>(`/api/demos/${id}/generated-config`);

export const fetchConfigScript = (id: string) =>
  apiFetch<{ demo_id: string; script: string; sections: { name: string; commands: string[] }[] }>(`/api/demos/${id}/config-script`);

export const saveLayout = (id: string, positions: { id: string; x: number; y: number }[]) =>
  apiFetch<{ status: string; positions_updated: number }>(`/api/demos/${id}/layout`, {
    method: "PUT",
    body: JSON.stringify({ positions }),
  });

export const saveDiagram = (id: string, nodes: any[], edges: any[]) =>
  apiFetch<any>(`/api/demos/${id}/diagram`, {
    method: "PUT",
    body: JSON.stringify({ nodes, edges }),
  });

export const saveDiagramWithGroups = (id: string, nodes: any[], edges: any[], groups: any[]) =>
  apiFetch<any>(`/api/demos/${id}/diagram`, {
    method: "PUT",
    body: JSON.stringify({ nodes: [...nodes, ...groups], edges }),
  });

// Demo Export/Import
export const exportDemo = (demoId: string) => {
  window.open(`${API_BASE}/api/demos/${demoId}/export`, '_blank');
};

export const importDemo = async (file: File): Promise<{ id: string; name: string }> => {
  const formData = new FormData();
  formData.append('file', file);
  const res = await fetch(`${API_BASE}/api/demos/import`, {
    method: 'POST',
    body: formData,
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || 'Import failed');
  }
  return res.json();
};

export const deleteDemo = (id: string, opts?: { destroyContainers?: boolean; removeImages?: boolean }) => {
  const params = new URLSearchParams();
  if (opts?.destroyContainers) params.set("destroy_containers", "true");
  if (opts?.removeImages) params.set("remove_images", "true");
  const qs = params.toString();
  return apiFetch<any>(`/api/demos/${id}${qs ? `?${qs}` : ""}`, { method: "DELETE" });
};

export const fetchInventory = () =>
  apiFetch<{
    containers: Array<{
      id: string; name: string; image: string; status: string;
      demo_id: string; node_id: string; component: string; created: string;
    }>;
    images: Array<{
      id: string; tags: string[]; size_mb: number; created: string;
    }>;
  }>("/api/inventory");

// Deploy
export const deployDemo = (id: string) =>
  apiFetch<{ demo_id: string; status: string; task_id?: string; message?: string }>(
    `/api/demos/${id}/deploy`,
    { method: "POST" }
  );

export const stopDemo = (id: string) =>
  apiFetch<{ demo_id: string; status: string; task_id?: string }>(
    `/api/demos/${id}/stop`,
    { method: "POST" }
  );

export const startDemo = (id: string) =>
  apiFetch<{ demo_id: string; status: string; task_id?: string }>(`/api/demos/${id}/start`, { method: "POST" });

export const destroyDemo = (id: string) =>
  apiFetch<{ demo_id: string; status: string; task_id?: string }>(`/api/demos/${id}/destroy`, { method: "POST" });

export const fetchTaskStatus = (demoId: string, taskId: string) =>
  apiFetch<{ task_id: string; demo_id: string; operation: string; status: string; error: string; steps: any[]; finished: boolean }>(
    `/api/demos/${demoId}/task/${taskId}`
  );

// Instances
export const fetchInstances = (demoId: string) =>
  apiFetch<{
    demo_id: string;
    status: string;
    instances: import("../types").ContainerInstance[];
    edge_configs?: { edge_id: string; connection_type: string; status: string; description: string; error: string }[];
    cluster_health?: Record<string, string>;
  }>(`/api/demos/${demoId}/instances`);

export const activateEdgeConfig = (demoId: string, edgeId: string) =>
  apiFetch<{ status: string; edge_id: string; error?: string }>(
    `/api/demos/${demoId}/edges/${edgeId}/activate`,
    { method: "POST" }
  );

export const pauseEdgeConfig = (demoId: string, edgeId: string) =>
  apiFetch<{ status: string; edge_id: string }>(
    `/api/demos/${demoId}/edges/${edgeId}/pause`,
    { method: "POST" }
  );

export const resyncEdge = (demoId: string, edgeId: string) =>
  apiFetch<{ status: string; edge_id: string; error?: string; output?: string }>(
    `/api/demos/${demoId}/edges/${edgeId}/resync`,
    { method: "POST" }
  );

export const restartInstance = (demoId: string, nodeId: string) =>
  apiFetch<{ demo_id: string; node_id: string; status: string }>(
    `/api/demos/${demoId}/instances/${nodeId}/restart`,
    { method: "POST" }
  );

export const stopInstance = (demoId: string, nodeId: string) =>
  apiFetch<{ status: string; node_id: string }>(
    `/api/demos/${demoId}/instances/${nodeId}/stop`,
    { method: "POST" }
  );

export const startInstance = (demoId: string, nodeId: string) =>
  apiFetch<{ status: string; node_id: string }>(
    `/api/demos/${demoId}/instances/${nodeId}/start`,
    { method: "POST" }
  );

export const stopDrive = (demoId: string, nodeId: string, driveNum: number) =>
  apiFetch<{ status: string }>(`/api/demos/${demoId}/instances/${nodeId}/drives/${driveNum}/stop`, { method: "POST" });

export const startDrive = (demoId: string, nodeId: string, driveNum: number) =>
  apiFetch<{ status: string }>(`/api/demos/${demoId}/instances/${nodeId}/drives/${driveNum}/start`, { method: "POST" });

export const resetCluster = (demoId: string, clusterId: string) =>
  apiFetch<{ status: string; cluster_id: string; buckets_removed: number }>(
    `/api/demos/${demoId}/clusters/${clusterId}/reset`,
    { method: "POST" }
  );

export const startPoolDecommission = (demoId: string, clusterId: string, poolId: string) =>
  apiFetch<{ status: string; pool_id: string; output: string }>(
    `/api/demos/${demoId}/clusters/${clusterId}/pools/${poolId}/decommission`,
    { method: "POST" }
  );

export const getPoolDecommissionStatus = (demoId: string, clusterId: string, poolId: string) =>
  apiFetch<{ pool_id: string; raw: string; status: "active" | "decommissioning" | "decommissioned" }>(
    `/api/demos/${demoId}/clusters/${clusterId}/pools/${poolId}/decommission/status`
  );

export const cancelPoolDecommission = (demoId: string, clusterId: string, poolId: string) =>
  apiFetch<{ status: string; pool_id: string; output: string }>(
    `/api/demos/${demoId}/clusters/${clusterId}/pools/${poolId}/decommission/cancel`,
    { method: "POST" }
  );

export const fetchMinioCommands = (demoId: string) =>
  apiFetch<{
    demo_id: string;
    commands: Array<{ category: string; description: string; command: string }>;
  }>(`/api/demos/${demoId}/minio-commands`);

export const getInstanceHealth = (demoId: string, nodeId: string) =>
  apiFetch<{ node_id: string; health: string }>(
    `/api/demos/${demoId}/instances/${nodeId}/health`
  );

// Exec
export const execCommand = (demoId: string, nodeId: string, command: string) =>
  apiFetch<{ exit_code: number; stdout: string; stderr: string }>(
    `/api/demos/${demoId}/instances/${nodeId}/exec`,
    { method: "POST", body: JSON.stringify({ command }) }
  );

// Logs
export const fetchContainerLogs = (demoId: string, nodeId: string, tail = 200, since = "60s") =>
  apiFetch<{ lines: string[]; container: string; truncated: boolean }>(
    `/api/demos/${demoId}/instances/${nodeId}/logs?tail=${tail}&since=${since}`
  );

export const execContainerLog = (demoId: string, nodeId: string, command: string) =>
  apiFetch<{ lines: string[]; container: string; truncated: boolean }>(
    `/api/demos/${demoId}/instances/${nodeId}/exec-log`,
    { method: "POST", body: JSON.stringify({ command }) }
  );

// Terminal WebSocket URL
export const terminalWsUrl = (demoId: string, nodeId: string) =>
  `${API_BASE.replace("http", "ws")}/api/demos/${demoId}/instances/${nodeId}/terminal`;

// Proxy URL (for opening web UIs)
export const proxyUrl = (path: string) => `${API_BASE}${path}`;

// System Health
export const fetchSystemHealth = () =>
  apiFetch<{ status: string; checks: Record<string, any> }>("/api/health/system");

// Templates
export const fetchTemplates = ({ includeArchived = false }: { includeArchived?: boolean } = {}) =>
  apiFetch<{ templates: import("../types").DemoTemplate[] }>(`/api/templates${includeArchived ? "?include_archived=true" : ""}`);

export const fetchTemplate = (templateId: string) =>
  apiFetch<import("../types").DemoTemplateDetail>(`/api/templates/${templateId}`);

export const updateTemplate = (templateId: string, patch: { name?: string; description?: string; objective?: string; minio_value?: string }) =>
  apiFetch<import("../types").DemoTemplate>(`/api/templates/${templateId}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });

export const createFromTemplate = (templateId: string) =>
  apiFetch<import("../types").DemoSummary>(`/api/demos/from-template/${templateId}`, {
    method: "POST",
  });

// Licenses
export const fetchLicenseStatus = () =>
  apiFetch<Array<{ license_id: string; label: string; description: string; components: string[]; configured: boolean; component_id: string; component_name: string; required: boolean }>>("/api/settings/licenses/status");

export const setLicense = (licenseId: string, value: string, label: string) =>
  apiFetch<{ status: string }>("/api/settings/licenses", {
    method: "POST",
    body: JSON.stringify({ license_id: licenseId, value, label }),
  });

export const deleteLicense = (licenseId: string) =>
  apiFetch<{ status: string }>(`/api/settings/licenses/${licenseId}`, { method: "DELETE" });

// LLM Config
export const getLlmConfig = () =>
  apiFetch<{ endpoint: string; model: string; api_type: string }>("/api/settings/llm");

export const setLlmConfig = (config: { endpoint?: string; model?: string; api_type?: string }) =>
  apiFetch<{ status: string }>("/api/settings/llm", {
    method: "POST",
    body: JSON.stringify(config),
  });

// MinIO Actions (Phase 4)
export const setBucketPolicy = (demoId: string, clusterId: string, bucket: string, policy: string) =>
  apiFetch<{ status: string; cluster_id: string; bucket: string; policy: string }>(
    `/api/demos/${demoId}/minio/${clusterId}/policy`,
    { method: "POST", body: JSON.stringify({ bucket, policy }) }
  );

export const setBucketVersioning = (demoId: string, clusterId: string, bucket: string, enabled: boolean) =>
  apiFetch<{ status: string; cluster_id: string; bucket: string; versioning: boolean }>(
    `/api/demos/${demoId}/minio/${clusterId}/versioning`,
    { method: "POST", body: JSON.stringify({ bucket, enabled }) }
  );

export const setupIAMUser = (demoId: string, clusterId: string, username: string, password: string, policy: string) =>
  apiFetch<{ status: string; cluster_id: string; username: string; policy: string }>(
    `/api/demos/${demoId}/minio/${clusterId}/iam`,
    { method: "POST", body: JSON.stringify({ username, password, policy }) }
  );

// Failover status
export const getFailoverStatus = (demoId: string) =>
  apiFetch<{ demo_id: string; failover: Array<{ gateway: string; active_upstream: string; healthy: boolean }> }>(
    `/api/demos/${demoId}/failover-status`
  );

// Generator control
export const getGeneratorStatus = (demoId: string, nodeId: string) =>
  apiFetch<{
    state: string;
    scenario?: string;
    format?: string;
    rate_profile?: string;
    rows_generated?: number;
    rows_per_sec?: number;
    batches_sent?: number;
    last_batch_ts?: string;
    errors?: number;
  }>(`/api/demos/${demoId}/generator-status/${nodeId}`);

export const startGenerator = (
  demoId: string,
  nodeId: string,
  config: { scenario: string; format: string; rate_profile: string }
) =>
  apiFetch<{ state: string; scenario: string; format: string; rate_profile: string }>(
    `/api/demos/${demoId}/generator-start/${nodeId}`,
    { method: "POST", body: JSON.stringify(config) }
  );

export const stopGenerator = (demoId: string, nodeId: string) =>
  apiFetch<{ state: string }>(
    `/api/demos/${demoId}/generator-stop/${nodeId}`,
    { method: "POST" }
  );

// Resilience tester status
export const getResilienceStatus = (demoId: string) =>
  apiFetch<{
    demo_id: string;
    probes: Array<{
      node_id: string;
      last_line: string;
      status: "ok" | "fail" | "unknown";
      seq: number | null;
      write_ms: number | null;
      read_ms: number | null;
      objects: number | null;
      upstream: string;
    }>;
  }>(`/api/demos/${demoId}/resilience-status`);

// Walkthrough
export interface WalkthroughStep {
  step: string;
  description: string;
}

export const getWalkthrough = (demoId: string) =>
  apiFetch<{ demo_id: string; walkthrough: WalkthroughStep[] }>(
    `/api/demos/${demoId}/walkthrough`
  );

// MCP Tools (Phase 8)
export interface McpTool {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
}

export const listMcpTools = (demoId: string, clusterId: string) =>
  apiFetch<{ tools: McpTool[] }>(
    `/api/demos/${demoId}/minio/${clusterId}/mcp/tools/list`,
    { method: "POST" }
  );

export const callMcpTool = (demoId: string, clusterId: string, toolName: string, args: Record<string, unknown>) =>
  apiFetch<{ result: unknown; error?: string }>(
    `/api/demos/${demoId}/minio/${clusterId}/mcp/tools/call`,
    { method: "POST", body: JSON.stringify({ tool_name: toolName, arguments: args }) }
  );

// SQL Editor
export const fetchScenarioQueries = (demoId: string, scenarioId: string) =>
  apiFetch<{
    scenario_id: string;
    queries: Array<{ id: string; name: string; sql: string; chart_type: string }>;
  }>(`/api/demos/${demoId}/scenario-queries/${scenarioId}`);

export const fetchAllScenarioQueries = (demoId: string) =>
  apiFetch<{
    scenarios: Array<{
      id: string;
      name: string;
      queries: Array<{ id: string; name: string; sql: string; chart_type: string }>;
    }>;
  }>(`/api/demos/${demoId}/scenario-queries/all`);

export const executeTrinoQuery = (demoId: string, sql: string) =>
  apiFetch<{
    columns: string[];
    rows: any[][];
    row_count: number;
    duration_ms: number;
    truncated?: boolean;
    error?: string;
  }>(`/api/demos/${demoId}/trino-query`, {
    method: "POST",
    body: JSON.stringify({ sql }),
  });

// SQL Playbook
export const fetchPlaybook = (demoId: string) =>
  apiFetch<{
    scenario_id: string;
    scenario_name: string;
    steps: { step: number; title: string; description: string; sql: string; expected: string }[];
  }>(`/api/demos/${demoId}/playbook`);

export const executeSql = (demoId: string, sql: string, catalog?: string, schema_name?: string) =>
  apiFetch<{
    success: boolean;
    columns: { name: string; type: string }[];
    rows: any[][];
    row_count: number;
    error: string;
    execution_time_ms: number;
  }>(`/api/demos/${demoId}/sql`, {
    method: "POST",
    body: JSON.stringify({ sql, catalog: catalog || "iceberg", schema_name: schema_name || "default" }),
  });

// Field Architect Guide
export const fetchTemplateGuide = (templateId: string) =>
  apiFetch<any>(`/api/templates/${templateId}/guide`);

// FA Identity
export const fetchIdentity = () =>
  apiFetch<{ fa_id: string; identified: boolean; mode: string; hub_local: boolean | null }>("/api/identity");

// Dev mode: push builtin templates to hub
export const pushBuiltinTemplates = () =>
  apiFetch<{ status: string; uploaded: number; errors: number }>("/api/templates/push-all-builtin", { method: "POST" });

// Set custom template display order (dev mode only)
export const setTemplateOrder = (order: string[]) =>
  apiFetch<{ ok: boolean; count: number }>("/api/templates/order", {
    method: "PUT",
    body: JSON.stringify({ order }),
  });

// Template management
export const saveAsTemplate = (payload: {
  demo_id: string;
  template_name: string;
  description?: string;
  tier?: string;
  category?: string;
  tags?: string[];
  objective?: string;
  minio_value?: string;
  overwrite?: boolean;
}) =>
  apiFetch<{ template_id: string; source: string; message: string }>(
    "/api/templates/save-from-demo",
    { method: "POST", body: JSON.stringify(payload) }
  );

export const deleteTemplate = (templateId: string) =>
  apiFetch<{ deleted: string }>(`/api/templates/${templateId}`, {
    method: "DELETE",
  });

export const forkTemplate = (templateId: string, name?: string) =>
  apiFetch<{ template_id: string; source: string; forked_from: string }>(
    `/api/templates/${templateId}/fork`,
    { method: "POST", body: JSON.stringify(name ? { name } : {}) }
  );

export const publishTemplate = (templateId: string) =>
  apiFetch<{ status: string; template_id: string; remote_key: string }>(
    `/api/templates/${templateId}/publish`,
    { method: "POST" }
  );

export const overrideTemplate = (templateId: string, demoId: string) =>
  apiFetch<{ template_id: string; overridden: boolean }>(`/api/templates/${templateId}/override`, {
    method: "POST",
    body: JSON.stringify({ demo_id: demoId }),
  });

export const revertTemplate = (templateId: string) =>
  apiFetch<{ reverted: string }>(`/api/templates/${templateId}/revert`, {
    method: "POST",
  });

export const promoteTemplate = (templateId: string) =>
  apiFetch<{ promoted: string; source_path: string; pushed: boolean; push_warning: string | null; steps: Record<string, boolean | "skipped">; steps_errors: Record<string, string> }>(`/api/templates/${templateId}/promote`, {
    method: "POST",
  });

export const validateTemplate = (templateId: string, validated: boolean) =>
  apiFetch<{ template_id: string; validated: boolean }>(`/api/templates/${templateId}/validate`, {
    method: "POST",
    body: JSON.stringify({ validated }),
  });

export const getAppMode = () =>
  apiFetch<{ mode: string }>("/api/settings/mode");

export const triggerTemplateSync = () =>
  apiFetch<{ status: string; downloaded: number; unchanged: number; deleted: number; errors: number }>(
    "/api/templates/sync",
    { method: "POST" }
  );

export const getTemplateSyncStatus = () =>
  apiFetch<{
    enabled: boolean;
    endpoint: string;
    bucket: string;
    prefix: string;
    synced_count: number;
    last_sync: string | null;
  }>("/api/templates/sync/status");

export const hubPushImages = () =>
  apiFetch<{ pushed: number; failed: number; results: { component: string; tag: string; status: string; error?: string }[] }>(
    "/api/images/hub-push", { method: "POST" }
  );

export const fetchMe = () =>
  apiFetch<{ ok: boolean; fa_id?: string; fa_name?: string; is_active?: boolean; permissions?: Record<string, unknown> }>("/api/connectivity/me");
