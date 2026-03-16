import { useDebugStore } from "../stores/debugStore";
import { toast } from "sonner";

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

function debugLog(level: "info" | "warn" | "error", source: string, message: string, details?: string) {
  try { useDebugStore.getState().addEntry(level, source, message, details); } catch {}
}

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
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
      // Toast on non-GET errors (user-initiated actions)
      if (method !== "GET") {
        toast.error(`API Error: ${method} ${path}`, { description: body.slice(0, 200) });
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
  apiFetch<{ demo_id: string; status: string; message?: string }>(
    `/api/demos/${id}/deploy`,
    { method: "POST" }
  );

export const stopDemo = (id: string) =>
  apiFetch<{ demo_id: string; status: string }>(
    `/api/demos/${id}/stop`,
    { method: "POST" }
  );

// Instances
export const fetchInstances = (demoId: string) =>
  apiFetch<{
    demo_id: string;
    status: string;
    instances: import("../types").ContainerInstance[];
    edge_configs?: { edge_id: string; connection_type: string; status: string; description: string; error: string }[];
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

// Terminal WebSocket URL
export const terminalWsUrl = (demoId: string, nodeId: string) =>
  `${API_BASE.replace("http", "ws")}/api/demos/${demoId}/instances/${nodeId}/terminal`;

// Proxy URL (for opening web UIs)
export const proxyUrl = (path: string) => `${API_BASE}${path}`;

// System Health
export const fetchSystemHealth = () =>
  apiFetch<{ status: string; checks: Record<string, any> }>("/api/health/system");

// Templates
export const fetchTemplates = () =>
  apiFetch<{ templates: import("../types").DemoTemplate[] }>("/api/templates");

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
