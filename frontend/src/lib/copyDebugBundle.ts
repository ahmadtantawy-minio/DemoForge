import { apiUrl, getApiOrigin } from "./apiBase";
import { fetchInstances } from "../api/client";
import { useDemoStore } from "../stores/demoStore";
import { useDebugStore } from "../stores/debugStore";
import { useDiagramStore } from "../stores/diagramStore";

export type CopyDebugBundleResult = { ok: boolean; message: string; charCount?: number };

/** Bump when diagnostics shape or probes change (so pasted bundles are identifiable). */
const DEBUG_BUNDLE_FORMAT = 6;

/** Avoid multi-minute exports on huge demos; paths beyond this are listed but not probed. */
const MAX_AUTO_PROXY_PROBE_PATHS = 80;

type AutoProxyTarget = {
  label: string;
  path: string;
  /** MinIO Console uses `/ws/objectManager` under the `/console/` proxy root. */
  wsMode: "minio_object_manager" | "none";
};

function normalizeProxyPath(p: string): string {
  const t = p.trim();
  if (!t) return t;
  return t.startsWith("/") ? t : `/${t}`;
}

function isMinioConsoleProxyRoot(path: string): boolean {
  const withSlash = normalizeProxyPath(path).replace(/\/*$/, "/");
  return withSlash.includes("/console/");
}

function pathToWebSocketUrl(pathFromOrigin: string): string {
  const p = pathFromOrigin.startsWith("/") ? pathFromOrigin : `/${pathFromOrigin}`;
  const proto = typeof window !== "undefined" && window.location.protocol === "https:" ? "wss:" : "ws:";
  const host = typeof window !== "undefined" ? window.location.host : "localhost";
  return `${proto}//${host}${p}`;
}

function proxyRootToObjectManagerWsPath(proxyRoot: string): string {
  const root = proxyRoot.replace(/\/?$/, "");
  return `${root}/ws/objectManager`;
}

function sniffConsoleHtmlForProxyHints(html: string, maxScan: number): string[] {
  const slice = html.length > maxScan ? html.slice(0, maxScan) : html;
  const needles = ['"/ws/', "'/ws/", "`/ws/", '"/api/v1/', "'/api/v1/", "WebSocket(", "new WebSocket", "wss://", "ws://"];
  const hints: string[] = [];
  for (const n of needles) {
    const i = slice.indexOf(n);
    if (i >= 0) {
      const ctx = slice.slice(i, i + 96).replace(/\s+/g, " ");
      hints.push(`${n} @${i}: ${ctx}`);
    }
  }
  return hints;
}

async function websocketSmokeTest(wsUrl: string, timeoutMs: number): Promise<string> {
  return new Promise((resolve) => {
    let ws: WebSocket;
    try {
      ws = new WebSocket(wsUrl);
    } catch (e) {
      resolve(`FAIL constructor: ${e instanceof Error ? e.message : String(e)}`);
      return;
    }
    let done = false;
    const finish = (msg: string) => {
      if (done) return;
      done = true;
      try {
        ws.close();
      } catch {
        /* noop */
      }
      clearTimeout(tid);
      resolve(msg);
    };
    const tid = setTimeout(() => finish(`FAIL timeout ${timeoutMs}ms (no open, no close)`), timeoutMs);
    ws.addEventListener("open", () => finish(`OK socket opened (closed locally; auth may still fail on server)`));
    ws.addEventListener("error", () => {
      /* browsers give no details; rely on close */
    });
    ws.addEventListener("close", (ev) => {
      if (done) return;
      finish(`FAIL closed before open code=${ev.code} reason=${(ev.reason || "").slice(0, 120) || "(empty)"} clean=${ev.wasClean}`);
    });
  });
}

function pickResponseHeaderLines(r: Response, names: string[]): string[] {
  const out: string[] = [];
  for (const n of names) {
    const v = r.headers.get(n);
    if (v) out.push(`${n}: ${v}`);
  }
  return out;
}

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
  lines.push(`debug_bundle_format: ${DEBUG_BUNDLE_FORMAT}`);
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

  lines.push("\n## versions (compare with repo / release to confirm this is the latest UI + API)");
  lines.push(`ui_package_version (npm): ${typeof __DF_UI_PKG_VERSION__ !== "undefined" ? __DF_UI_PKG_VERSION__ : "(vite define missing)"}`);
  const embeddedRelease =
    typeof import.meta.env.VITE_DEMOFORGE_RELEASE_VERSION === "string"
      ? import.meta.env.VITE_DEMOFORGE_RELEASE_VERSION
      : "(missing)";
  lines.push(
    `frontend_release_version_embedded (git describe at Vite build; hub-push sets for FA images): ${embeddedRelease}`
  );
  lines.push(`vite_mode: ${import.meta.env.MODE}`);
  lines.push(`vite_dev: ${String(import.meta.env.DEV)}`);
  lines.push(`vite_prod: ${String(import.meta.env.PROD)}`);
  lines.push(`import_meta_env.BASE_URL: ${import.meta.env.BASE_URL}`);
  let backendVersionFromApi = "(not parsed)";
  try {
    const vr = await fetch(apiUrl("/api/version"), { cache: "no-store" });
    const bodyText = await vr.text();
    lines.push(`GET /api/version http_status: ${vr.status}`);
    lines.push(bodyText);
    try {
      const j = JSON.parse(bodyText) as { version?: string };
      if (typeof j.version === "string") backendVersionFromApi = j.version;
    } catch {
      /* non-JSON */
    }
  } catch (e: unknown) {
    lines.push(`GET /api/version failed: ${e instanceof Error ? e.message : String(e)}`);
  }
  lines.push(
    `release_version_match (embedded SPA vs GET /api/version): ${
      embeddedRelease === backendVersionFromApi
        ? "match"
        : `differ — embedded="${embeddedRelease}" api="${backendVersionFromApi}"`
    }`
  );
  try {
    const mr = await fetch(apiUrl("/api/settings/mode"), { cache: "no-store" });
    lines.push(`GET /api/settings/mode http_status: ${mr.status}`);
    lines.push(await mr.text());
  } catch (e: unknown) {
    lines.push(`GET /api/settings/mode failed: ${e instanceof Error ? e.message : String(e)}`);
  }

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

  lines.push("\n## client_routing");
  const apiOrigin = getApiOrigin();
  lines.push(`VITE_API_URL / getApiOrigin(): ${apiOrigin === "" ? "(empty — same-origin relative /api and /proxy)" : apiOrigin}`);
  lines.push(`sessionStorage._dfproxy: ${(() => {
    try {
      return sessionStorage.getItem("_dfproxy") ?? "(not set)";
    } catch {
      return "(unreadable)";
    }
  })()}`);

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

  lines.push("\n## automated_proxy_diagnostics (run when you click copy debug bundle)");
  lines.push(
    "# Probes each unique `proxy_url` from the active demo's instances (every node / LB web UI), plus the designer overlay if open."
  );

  const proxyTargets: AutoProxyTarget[] = [];
  if (diagram.designerWebUiOverlay?.proxyPath) {
    const p = normalizeProxyPath(diagram.designerWebUiOverlay.proxyPath);
    proxyTargets.push({
      label: "designer_web_ui_overlay",
      path: p,
      wsMode: isMinioConsoleProxyRoot(p) ? "minio_object_manager" : "none",
    });
  }

  const sortedInstances = [...(instancesSnapshot?.instances ?? [])].sort((a, b) =>
    (a.node_id || "").localeCompare(b.node_id || "", undefined, { sensitivity: "base" })
  );
  for (const inst of sortedInstances) {
    for (const wu of inst.web_uis ?? []) {
      const raw = wu.proxy_url?.trim();
      if (!raw || !raw.includes("/proxy/")) continue;
      const p = normalizeProxyPath(raw);
      proxyTargets.push({
        label: `instance:${inst.node_id}:${wu.name}`,
        path: p,
        wsMode: wu.name === "console" && isMinioConsoleProxyRoot(p) ? "minio_object_manager" : "none",
      });
    }
  }

  const seenPaths = new Set<string>();
  const uniqueTargets: AutoProxyTarget[] = [];
  for (const t of proxyTargets) {
    if (seenPaths.has(t.path)) continue;
    seenPaths.add(t.path);
    uniqueTargets.push(t);
  }

  const probeList = uniqueTargets.slice(0, MAX_AUTO_PROXY_PROBE_PATHS);
  const omitted = uniqueTargets.length - probeList.length;

  if (uniqueTargets.length === 0) {
    lines.push(
      "(skipped — no /proxy targets: need active demo with instances + web_uis, or open a component web UI overlay)"
    );
  } else {
    lines.push(`unique_proxy_paths: ${uniqueTargets.length}`);
    if (omitted > 0) {
      lines.push(
        `(only first ${MAX_AUTO_PROXY_PROBE_PATHS} paths probed; ${omitted} omitted — raise MAX_AUTO_PROXY_PROBE_PATHS in copyDebugBundle.ts if needed)`
      );
    }
  }

  for (const t of probeList) {
    const url = apiUrl(t.path.startsWith("/") ? t.path : `/${t.path}`);
    lines.push(`\n### automated target: ${t.label}`);
    lines.push(`path: ${t.path}`);
    lines.push(`resolved_fetch_url: ${url}`);

    try {
      const t0 = performance.now();
      const head = await fetch(url, { method: "HEAD", cache: "no-store", credentials: "same-origin" });
      lines.push(
        `test HEAD: status=${head.status} elapsed_ms=${Math.round(performance.now() - t0)}`
      );
      const hh = pickResponseHeaderLines(head, [
        "content-type",
        "content-length",
        "cache-control",
        "via",
        "x-frame-options",
        "content-security-policy",
      ]);
      if (hh.length) lines.push(...hh.map((h) => `  ${h}`));
    } catch (e: unknown) {
      lines.push(`test HEAD: ERROR ${e instanceof Error ? e.message : String(e)}`);
    }

    try {
      const opt = await fetch(url, { method: "OPTIONS", cache: "no-store", credentials: "same-origin" });
      lines.push(`test OPTIONS: status=${opt.status}`);
      const oh = pickResponseHeaderLines(opt, ["allow", "access-control-allow-origin", "access-control-allow-methods"]);
      if (oh.length) lines.push(...oh.map((h) => `  ${h}`));
    } catch (e: unknown) {
      lines.push(`test OPTIONS: ERROR ${e instanceof Error ? e.message : String(e)}`);
    }

    try {
      const t0 = performance.now();
      const gr = await fetch(url, { method: "GET", cache: "no-store", credentials: "same-origin" });
      const elapsed = Math.round(performance.now() - t0);
      const ct = (gr.headers.get("content-type") || "").toLowerCase();
      const buf = await gr.arrayBuffer();
      lines.push(`test GET: status=${gr.status} body_bytes=${buf.byteLength} elapsed_ms=${elapsed} content_type=${ct}`);
      const htmlDecoder = new TextDecoder("utf-8", { fatal: false });
      const text = htmlDecoder.decode(buf.byteLength > 14000 ? buf.slice(0, 14000) : buf);
      const hints = sniffConsoleHtmlForProxyHints(text, 14000);
      if (hints.length) {
        lines.push("html_sniff_ws_and_api_hints (first matches in first ~14k of body):");
        for (const h of hints) lines.push(`  ${h}`);
      } else if (t.wsMode === "minio_object_manager") {
        lines.push(
          "html_sniff_ws_and_api_hints: (none in first ~14k — common when shell is tiny and /ws/ lives only in lazy chunks)"
        );
      } else {
        lines.push("html_sniff_ws_and_api_hints: (none in first ~14k — typical for non-MinIO-console UIs)");
      }
      lines.push("get_body_prefix_utf8 (first 1800 chars):");
      lines.push(text.slice(0, 1800));
    } catch (e: unknown) {
      lines.push(`test GET: ERROR ${e instanceof Error ? e.message : String(e)}`);
    }

    if (t.wsMode === "minio_object_manager") {
      const wsPath = proxyRootToObjectManagerWsPath(t.path);
      const wsUrl = pathToWebSocketUrl(wsPath);
      lines.push(`test WebSocket smoke (MinIO objectManager path): ${wsUrl}`);
      const wsResult = await websocketSmokeTest(wsUrl, 3500);
      lines.push(`  result: ${wsResult}`);
    } else {
      lines.push("test WebSocket smoke: skipped (not a …/console/ MinIO Console proxy root)");
    }
  }

  if (omitted > 0) {
    lines.push("\n### proxy paths listed but not probed (truncation — paths only)");
    for (const t of uniqueTargets.slice(MAX_AUTO_PROXY_PROBE_PATHS)) {
      lines.push(`- ${t.label}: ${t.path}`);
    }
  }

  lines.push("\n## fetch_probe_proxy_paths (full GET up to 6k — only paths not already exercised above)");
  const autoProbedPaths = new Set(probeList.map((x) => x.path));
  const designerNorm = diagram.designerWebUiOverlay?.proxyPath
    ? normalizeProxyPath(diagram.designerWebUiOverlay.proxyPath)
    : "";
  if (designerNorm && !autoProbedPaths.has(designerNorm)) {
    await appendFetchProbe("designer_web_ui_overlay", designerNorm, 6000);
  } else if (!designerNorm) {
    lines.push("\n(no designer_web_ui_overlay — open the web UI panel to probe that /proxy/ URL here)");
  }
  const lbInst = instancesSnapshot?.instances?.find((i) => i.node_id?.endsWith("-lb"));
  const lbConsole = lbInst?.web_uis?.find((u) => u.name === "console");
  const lbConsolePath = lbConsole?.proxy_url ? normalizeProxyPath(lbConsole.proxy_url) : "";
  if (lbConsolePath && !autoProbedPaths.has(lbConsolePath)) {
    await appendFetchProbe("load_balancer_console_from_instances", lbConsolePath, 6000);
  }
  if (autoProbedPaths.size > 0) {
    lines.push("\n(paths already covered by automated_proxy_diagnostics GET/HEAD/OPTIONS/WS are not duplicated here)");
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
  return {
    ok: true,
    message: `Copied debug bundle (${body.length} chars, diagnostics format ${DEBUG_BUNDLE_FORMAT})`,
    charCount: body.length,
  };
}
