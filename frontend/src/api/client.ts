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

export const fetchGeneratedConfig = (id: string) =>
  apiFetch<{ demo_id: string; configs: Record<string, string> }>(`/api/demos/${id}/generated-config`);

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
  }>(`/api/demos/${demoId}/instances`);

export const restartInstance = (demoId: string, nodeId: string) =>
  apiFetch<{ demo_id: string; node_id: string; status: string }>(
    `/api/demos/${demoId}/instances/${nodeId}/restart`,
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
