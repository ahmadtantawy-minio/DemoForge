import { apiFetch } from "./client";

export interface ComponentReadinessItem {
  component_id: string;
  component_name: string;
  category: string;
  fa_ready: boolean;
  notes: string;
  updated_at: string | null;
  updated_by: string | null;
  template_count: number;
  templates: {
    template_id: string;
    template_name: string;
    is_fa_ready: boolean;
    blocking_components: string[];
  }[];
}

export interface TemplateReadinessItem {
  template_id: string;
  template_name: string;
  source: string;
  is_fa_ready: boolean;
  component_count: number;
  components: string[];
  blocking_components: string[];
  ready_component_count: number;
}

export const fetchComponentReadiness = () =>
  apiFetch<{ components: ComponentReadinessItem[]; summary: { total: number; fa_ready: number; not_ready: number } }>(
    "/api/readiness/components"
  );

export const fetchTemplateReadiness = () =>
  apiFetch<{ templates: TemplateReadinessItem[]; summary: { total: number; fa_ready: number; not_ready: number } }>(
    "/api/readiness/templates"
  );

export const updateComponentReadiness = (componentId: string, faReady: boolean, notes?: string) =>
  apiFetch(`/api/readiness/components/${componentId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fa_ready: faReady, notes }),
  });
