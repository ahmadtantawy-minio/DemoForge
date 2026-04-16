/**
 * API base URL for browser requests.
 * - Empty: same-origin — Vite (dev) and nginx (prod) proxy `/api` to the backend (no CORS issues).
 * - Set `VITE_API_URL` when the UI cannot proxy (e.g. unusual hosting).
 */
export function getApiOrigin(): string {
  const v = import.meta.env.VITE_API_URL as string | undefined;
  if (v !== undefined && v !== null && String(v).trim() !== "") {
    return String(v).replace(/\/$/, "");
  }
  return "";
}

/** Absolute or same-origin URL for an API path (path must start with `/`). */
export function apiUrl(path: string): string {
  const p = path.startsWith("/") ? path : `/${path}`;
  const o = getApiOrigin();
  return o ? `${o}${p}` : p;
}

/** WebSocket URL for paths under `/api` (terminal, etc.). */
export function apiWsUrl(path: string): string {
  const p = path.startsWith("/") ? path : `/${path}`;
  const o = getApiOrigin();
  if (o) {
    return `${o.replace(/^http/, "ws")}${p}`;
  }
  if (typeof window === "undefined") {
    return `ws:${p}`;
  }
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}${p}`;
}
