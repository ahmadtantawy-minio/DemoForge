import { apiUrl } from "./apiBase";
import { fetchInstances } from "../api/client";
import { useDemoStore } from "../stores/demoStore";
import { useDebugStore } from "../stores/debugStore";
import { useDiagramStore } from "../stores/diagramStore";

export type CopyDebugBundleResult = { ok: boolean; message: string; charCount?: number };

/**
 * Collects environment + recent client logs + backend health + same-origin fetch probes
 * (current URL, optional /proxy/... targets) for MinIO console / proxy debugging.
 * When component UIs load under `/proxy/...` (same origin as the SPA), iframe text may be captured.
 */
export async function copyDebugBundleToClipboard(): Promise<CopyDebugBundleResult> {
  if (typeof window === "undefined" || !navigator.clipboard?.writeText) {
    return { ok: false, message: "Clipboard (writeText) is not available in this context" };
  }

  const lines: string[] = [];
  lines.push("# DemoForge debug bundle");
  lines.push(`generated_utc: ${new Date().toISOString()}`);
  lines.push(`href: ${window.location.href}`);
  lines.push(`origin: ${window.location.origin}`);
  lines.push(`path: ${window.location.pathname}`);
  lines.push(`user_agent: ${navigator.userAgent}`);
  lines.push(`navigator.platform: ${typeof navigator.platform === "string" ? navigator.platform : "(n/a)"}`);
  try {
    const ua = (navigator as Navigator & { userAgentData?: { brands?: unknown; platform?: string; mobile?: boolean } })
      .userAgentData;
    if (ua) {
      lines.push(
        `user_agent_data: ${JSON.stringify({ brands: ua.brands, platform: ua.platform, mobile: ua.mobile })}`
      );
    }
  } catch {
    /* ignore */
  }
  lines.push(`viewport: ${window.innerWidth}x${window.innerHeight}`);
  lines.push(`language: ${navigator.language}`);
  lines.push("");
  lines.push(
    "# Screenshot (attach separately if needed — external UIs in iframes are often same-origin here as /proxy/...)"
  );
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

  let instancesSnapshot: Awaited<ReturnType<typeof fetchInstances>> | null = null;
  if (demoStore.activeDemoId) {
    lines.push("\n## instances snapshot (active demo)");
    try {
      instancesSnapshot = await fetchInstances(demoStore.activeDemoId);
      lines.push(JSON.stringify({ instances: instancesSnapshot.instances?.slice(0, 40) }, null, 2));
    } catch (e: unknown) {
      lines.push(`instances_fetch_failed: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  const appendFetchProbe = async (label: string, pathOrUrl: string, maxBytes: number) => {
    const url = pathOrUrl.startsWith("http")
      ? pathOrUrl
      : apiUrl(pathOrUrl.startsWith("/") ? pathOrUrl : `/${pathOrUrl}`);
    lines.push(`\n### ${label}`);
    lines.push(`url: ${url}`);
    try {
      const r = await fetch(url, { method: "GET", cache: "no-store", credentials: "same-origin" });
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
        const slice = buf.byteLength > maxBytes ? buf.slice(0, maxBytes) : buf;
        lines.push("body_prefix_utf8:");
        lines.push(new TextDecoder("utf-8", { fatal: false }).decode(slice));
      }
    } catch (e: unknown) {
      lines.push(`fetch_error: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  lines.push("\n## fetch_probe_proxy_paths (component UI / MinIO console)");
  if (diagram.designerWebUiOverlay?.proxyPath) {
    await appendFetchProbe("designer_web_ui_overlay", diagram.designerWebUiOverlay.proxyPath, 6000);
  } else {
    lines.push("\n(no designer_web_ui_overlay — open the web UI panel to include its /proxy/ URL here)");
  }
  const lbInst = instancesSnapshot?.instances?.find((i) => i.node_id?.endsWith("-lb"));
  const lbConsole = lbInst?.web_uis?.find((u) => u.name === "console");
  if (lbConsole?.proxy_url) {
    await appendFetchProbe("load_balancer_console_from_instances", lbConsole.proxy_url, 6000);
  }

  lines.push("\n## same_origin_iframe_snippets (/proxy/ only; best-effort)");
  try {
    const iframes = Array.from(document.querySelectorAll<HTMLIFrameElement>('iframe[src*="/proxy/"]'));
    lines.push(`iframe_count: ${iframes.length}`);
    for (let i = 0; i < iframes.length; i++) {
      const el = iframes[i];
      lines.push(`\n### iframe[${i}]`);
      lines.push(`src: ${el.src}`);
      try {
        const doc = el.contentDocument;
        if (!doc) {
          lines.push("contentDocument: null");
          continue;
        }
        lines.push(`document_title: ${doc.title || "(empty)"}`);
        const bodyTxt = doc.body?.innerText?.trim().slice(0, 2800) ?? "";
        if (bodyTxt.length > 0) {
          lines.push("body_innerText_snippet:");
          lines.push(bodyTxt);
        } else {
          const htmlSnippet = doc.documentElement?.outerHTML?.slice(0, 2000) ?? "";
          if (htmlSnippet) {
            lines.push("documentElement_outerHTML_snippet:");
            lines.push(htmlSnippet);
          }
        }
      } catch (e: unknown) {
        lines.push(`iframe_access_error: ${e instanceof Error ? e.message : String(e)}`);
      }
    }
  } catch (e: unknown) {
    lines.push(`iframe_walk_error: ${e instanceof Error ? e.message : String(e)}`);
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
