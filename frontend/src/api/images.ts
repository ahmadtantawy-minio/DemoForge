import { apiFetch } from "./client";

export interface ImageInfo {
  component_name: string;
  image_ref: string;
  category: "vendor" | "custom" | "platform";
  cached: boolean;
  local_size_mb: number | null;
  manifest_size_mb: number | null;
  effective_size_mb: number | null;
  pull_source: string;
  status: "cached" | "missing" | "unknown";
}

export interface PullStatus {
  pull_id: string;
  image_ref: string;
  status: "pulling" | "complete" | "error";
  progress_pct: number | null;
  error: string | null;
}

export async function getImageStatus(): Promise<ImageInfo[]> {
  return apiFetch<ImageInfo[]>("/api/images/status");
}

export async function pullImage(imageRef: string): Promise<{ pull_id: string }> {
  return apiFetch<{ pull_id: string }>("/api/images/pull", {
    method: "POST",
    body: JSON.stringify({ image_ref: imageRef }),
  });
}

export async function getPullStatus(pullId: string): Promise<PullStatus> {
  return apiFetch<PullStatus>(`/api/images/pull/${pullId}`);
}

export async function pullAllMissing(): Promise<{ pull_ids: string[] }> {
  return apiFetch<{ pull_ids: string[] }>("/api/images/pull-all-missing", {
    method: "POST",
  });
}

export interface DanglingInfo {
  count: number;
  reclaimable_mb: number;
}

export interface StorageInfo {
  total_images: number;
  total_size_mb: number;
  reclaimable_mb: number;
}

export async function getDanglingImages(): Promise<DanglingInfo> {
  return apiFetch<DanglingInfo>("/api/images/dangling");
}

export async function pruneDanglingImages(): Promise<{ removed: number; reclaimed_mb: number }> {
  return apiFetch<{ removed: number; reclaimed_mb: number }>("/api/images/prune", { method: "POST" });
}
