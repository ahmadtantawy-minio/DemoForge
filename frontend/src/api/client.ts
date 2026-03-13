const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`);
  return res.json();
}

// Registry
export const fetchComponents = () =>
  apiFetch<{ components: import("../types").ComponentSummary[] }>("/api/registry/components");

// Demos
export const fetchDemos = () =>
  apiFetch<{ demos: import("../types").DemoSummary[] }>("/api/demos");

export const createDemo = (name: string, description = "") =>
  apiFetch<import("../types").DemoSummary>("/api/demos", {
    method: "POST",
    body: JSON.stringify({ name, description }),
  });

export const fetchDemo = (id: string) => apiFetch<any>(`/api/demos/${id}`);

export const saveDiagram = (id: string, nodes: any[], edges: any[]) =>
  apiFetch<any>(`/api/demos/${id}/diagram`, {
    method: "PUT",
    body: JSON.stringify({ nodes, edges }),
  });

export const deleteDemo = (id: string) =>
  apiFetch<any>(`/api/demos/${id}`, { method: "DELETE" });

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
