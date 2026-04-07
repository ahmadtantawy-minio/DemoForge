import { apiFetch } from "./client";

export interface AdminStats {
  total_fas: number;
  active_fas: number;
  total_events: number;
  events_last_7_days: number;
  events_last_30_days: number;
  top_templates: { payload: Record<string, unknown>; count: number }[];
  events_by_type: Record<string, number>;
}

export interface FAListItem {
  fa_id: string;
  fa_name: string;
  is_active: boolean;
  last_seen_at: string | null;
  registered_at: string;
  event_count: number;
}

export interface FAPermissions {
  manual_demo_creation: boolean;
  template_publish: boolean;
  template_fork: boolean;
  max_concurrent_demos: number;
}

export interface FAProfile {
  fa_id: string;
  fa_name: string;
  permissions: FAPermissions;
  registered_at: string;
  last_seen_at: string | null;
  is_active: boolean;
}

export interface FAActivity {
  id: number;
  fa_id: string;
  event_type: string;
  payload: Record<string, unknown>;
  timestamp: string;
  received_at: string;
}

export const fetchAdminStats = () =>
  apiFetch<AdminStats>("/api/fa-admin/stats");

export const fetchFAs = () =>
  apiFetch<FAListItem[]>("/api/fa-admin/fas");

export const fetchFA = (faId: string) =>
  apiFetch<FAProfile>(`/api/fa-admin/fas/${encodeURIComponent(faId)}`);

export const fetchFAActivity = (
  faId: string,
  params?: { event_type?: string; limit?: number; offset?: number }
) => {
  const qs = new URLSearchParams();
  if (params?.event_type) qs.set("event_type", params.event_type);
  if (params?.limit != null) qs.set("limit", String(params.limit));
  if (params?.offset != null) qs.set("offset", String(params.offset));
  const q = qs.toString();
  return apiFetch<FAActivity[]>(
    `/api/fa-admin/fas/${encodeURIComponent(faId)}/activity${q ? `?${q}` : ""}`
  );
};

export const updateFAPermissions = (faId: string, perms: Partial<FAPermissions>) =>
  apiFetch<FAProfile>(`/api/fa-admin/fas/${encodeURIComponent(faId)}/permissions`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(perms),
  });

export const updateFAStatus = (faId: string, isActive: boolean) =>
  apiFetch<FAProfile>(`/api/fa-admin/fas/${encodeURIComponent(faId)}/status`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ is_active: isActive }),
  });

export const purgeFA = (faId: string) =>
  apiFetch<{ detail: string }>(`/api/fa-admin/fas/${encodeURIComponent(faId)}`, {
    method: "DELETE",
  });

// FA creation + key management
export interface FACreateRequest {
  fa_id: string;
  fa_name: string;
  api_key?: string; // omit to auto-generate
}

export interface FAKeyResponse {
  fa_id: string;
  api_key: string;
}

export interface FAProfileWithKey {
  fa_id: string;
  fa_name: string;
  api_key: string;
  is_active: boolean;
  registered_at: string;
  last_seen_at: string | null;
  permissions: Record<string, unknown>;
  metadata: Record<string, unknown>;
}

export const createFA = (req: FACreateRequest) =>
  apiFetch<FAProfileWithKey>("/api/fa-admin/fas", {
    method: "POST",
    body: JSON.stringify(req),
  });

export const getFAKey = (faId: string) =>
  apiFetch<FAKeyResponse>(`/api/fa-admin/fas/${encodeURIComponent(faId)}/key`);

export const updateFAKey = (faId: string, apiKey?: string) =>
  apiFetch<FAKeyResponse>(`/api/fa-admin/fas/${encodeURIComponent(faId)}/key`, {
    method: "PUT",
    body: JSON.stringify(apiKey ? { api_key: apiKey } : {}),
  });
