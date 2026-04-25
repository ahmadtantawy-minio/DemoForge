import { apiUrl } from "./apiBase";
import { fetchInstances } from "../api/client";
import { useDemoStore } from "../stores/demoStore";
import { useDebugStore } from "../stores/debugStore";
import { useDiagramStore } from "../stores/diagramStore";

export type CopyDebugBundleResult = { ok: boolean; message: string; charCount?: number };

/**
 * Collects environment + recent client logs + backend health + a same-origin fetch probe
 * of the current URL (useful for broken MinIO console / proxy asset debugging).
 * Screenshots cannot be taken from JS for cross-origin iframes — bundle includes OS hints.
 */
export async function copyDebugBundleToClipboard(): Promise<CopyDebugBundleResult> {
  if (typeof window === "undefined" || !navigator.clipboard?.writeText) {
    return { ok: false, message: "Clipboard (writeText) is not available in this context" };
  }

  const lines: string[] = [];
  lines.push("# DemoForge debug bundle");
  lines.push(`generated_utc: ${new Date().toISOString()}`);
  lines.push(`href: ${window.location.href}`);
  lines.push(`path: ${window.location.pathname}`);
  lines.push(`user_agent: ${navigator.userAgent}`);
  lines.push(`viewport: ${window.innerWidth}x${window.innerHeight}`);
  lines.push(`language: ${navigator.language}`);
  lines.push("");
  lines.push("# Screenshot (attach separately — JS cannot capture cross-origin iframes)");
  lines.push("# Windows: Win+Shift+S  |  macOS: Cmd+Shift+4  |  Linux: use your compositor/screenshot tool");

  const demoStore = useDemoStore.getState();
  lines.push("\n## demos (UI store)");
  lines.push(
    JSON.stringify(
      demoStore.demos.map((d) => ({ id: d.id, name: d.name, status: d.status, mode: d.mode })),
      null,
      2
    )
  );
  lines.push(`active_demo_id: ${demoStore.activeDemoId ?? "(none)"}`);
  lines.push(`current_page: ${demoStore.currentPage}`);
  lines.push(`active_view: ${demoStore.activeView}`);
  lines.push(`fa_mode: ${demoStore.faMode}`);

  const diagram = useDiagramStore.getState();
  lines.push("\n## diagram");
  lines.push(`nodes: ${diagram.nodes.length} edges: ${diagram.edges.length}`);
  if (diagram.designerWebUiOverlay) {
    lines.push(`designer_web_ui_overlay: ${JSON.stringify(diagram.designerWebUiOverlay)}`);
  }

  const debug = useDebugStore.getState();
  lines.push("\n## client logs (main, last 120)");
  for (const e of debug.entries.slice(-120)) {
    const d = e.details ? `\n${e.details}` : "";
    lines.push(`[${e.timestamp}] ${e.level.toUpperCase()} ${e.source}: ${e.message}${d}`);
  }
  lines.push("\n## client logs (integrations, last 40)");
  for (const e of debug.integrationBuffer.slice(-40)) {
    const d = e.details ? `\n${e.details}` : "";
    lines.push(`[${e.timestamp}] ${e.level.toUpperCase()} ${e.source}: ${e.message}${d}`);
  }

  lines.push("\n## GET /api/health/system");
  try {
    const r = await fetch(apiUrl("/api/health/system"));
    lines.push(`http_status: ${r.status}`);
    lines.push(JSON.stringify(await r.json(), null, 2));
  } catch (e: unknown) {
    lines.push(`fetch_failed: ${e instanceof Error ? e.message : String(e)}`);
  }

  lines.push("\n## fetch_probe_current_location (same-origin; first 8k text if text-like)");
  try {
    const r = await fetch(window.location.href, {
      method: "GET",
      cache: "no-store",
      credentials: "same-origin",
    });
    const ct = (r.headers.get("content-type") || "").toLowerCase();
    const buf = await r.arrayBuffer();
    lines.push(`status: ${r.status} ${r.statusText}`);
    lines.push(`content_type: ${ct}`);
    lines.push(`body_bytes: ${buf.byteLength}`);
    const textish =
      ct.includes("text/") ||
      ct.includes("json") ||
      ct.includes("javascript") ||
      ct.includes("xml") ||
      ct.includes("html");
    if (textish && buf.byteLength > 0) {
      const slice = buf.byteLength > 8000 ? buf.slice(0, 8000) : buf;
      lines.push("body_prefix_utf8:");
      lines.push(new TextDecoder("utf-8", { fatal: false }).decode(slice));
    }
  } catch (e: unknown) {
    lines.push(`fetch_probe_error: ${e instanceof Error ? e.message : String(e)}`);
  }

  if (demoStore.activeDemoId) {
    lines.push("\n## instances snapshot (active demo)");
    try {
      const inst = await fetchInstances(demoStore.activeDemoId);
      lines.push(JSON.stringify({ instances: inst.instances?.slice(0, 40) }, null, 2));
    } catch (e: unknown) {
      lines.push(`instances_fetch_failed: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  const body = lines.join("\n");
  try {
    await navigator.clipboard.writeText(body);
  } catch (e: unknown) {
    return {
      ok: false,
      message: e instanceof Error ? e.message : "Clipboard write was rejected (try clicking the page first)",
    };
  }
  return { ok: true, message: `Copied debug bundle (${body.length} characters)`, charCount: body.length };
}
