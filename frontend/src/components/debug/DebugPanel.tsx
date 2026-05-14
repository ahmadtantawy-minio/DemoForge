import { useEffect, useRef, useState, useCallback } from "react";
import { useDebugStore, type DebugEntry } from "../../stores/debugStore";
import { fetchSystemHealth } from "../../api/client";
import {
  classifyIntegrationDomain,
  parseIntegrationDetails,
  stripInlineCmdFromMessage,
} from "../../lib/integrationLogDisplay";

const levelColors: Record<DebugEntry["level"], string> = {
  info: "text-blue-400",
  warn: "text-yellow-400",
  error: "text-red-400",
};

const levelBg: Record<DebugEntry["level"], string> = {
  info: "",
  warn: "",
  error: "bg-red-950/30",
};

type Tab = "logs" | "health" | "lifecycle" | "integrations";

function HealthPanel() {
  const [checks, setChecks] = useState<Record<string, any> | null>(null);
  const [status, setStatus] = useState<string>("loading");
  const [error, setError] = useState<string>("");

  const refresh = () => {
    setStatus("loading");
    setError("");
    fetchSystemHealth()
      .then((res) => {
        setChecks(res.checks);
        setStatus(res.status);
      })
      .catch((err) => {
        setError(err.message);
        setStatus("error");
      });
  };

  useEffect(() => { refresh(); }, []);

  const checkItems: { key: string; label: string; critical: boolean }[] = [
    { key: "docker_cli", label: "Docker CLI", critical: true },
    { key: "docker_daemon", label: "Docker Daemon", critical: true },
    { key: "docker_compose", label: "Docker Compose", critical: true },
    { key: "docker_socket", label: "Docker Socket Mounted", critical: true },
    { key: "host_data_dir", label: "Host Data Dir (DEMOFORGE_HOST_DATA_DIR)", critical: true },
    { key: "host_components_dir", label: "Host Components Dir (DEMOFORGE_HOST_COMPONENTS_DIR)", critical: true },
    { key: "components_loaded", label: "Components Loaded", critical: false },
  ];

  return (
    <div className="p-3 text-xs space-y-2">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-foreground">System Health</span>
          <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
            status === "ok" ? "bg-green-900/50 text-green-400" :
            status === "degraded" ? "bg-yellow-900/50 text-yellow-400" :
            status === "loading" ? "bg-muted text-muted-foreground" :
            "bg-red-900/50 text-red-400"
          }`}>
            {status.toUpperCase()}
          </span>
        </div>
        <button onClick={refresh} className="text-muted-foreground hover:text-foreground transition-colors">
          Refresh
        </button>
      </div>
      {error && <div className="text-red-400">Failed to fetch: {error}</div>}
      {checks && (
        <div className="space-y-1">
          {checkItems.map(({ key, label, critical }) => {
            const value = checks[key];
            const passed = typeof value === "number" ? value > 0 : !!value;
            return (
              <div key={key} className="flex items-center gap-2">
                <span className={`w-4 text-center ${passed ? "text-green-400" : critical ? "text-red-400" : "text-yellow-400"}`}>
                  {passed ? "+" : critical ? "x" : "!"}
                </span>
                <span className={passed ? "text-foreground" : critical ? "text-red-400" : "text-yellow-400"}>
                  {label}
                </span>
                {key === "components_loaded" && typeof value === "number" && (
                  <span className="text-muted-foreground">({value})</span>
                )}
                {key === "docker_compose" && checks.docker_compose_version && (
                  <span className="text-muted-foreground">({checks.docker_compose_version})</span>
                )}
                {!passed && checks[`${key}_error`] && (
                  <span className="text-muted-foreground truncate" title={checks[`${key}_error`]}>
                    — {checks[`${key}_error`]}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = (e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };
  return (
    <button
      onClick={handleCopy}
      className="flex-shrink-0 px-1 text-[10px] text-muted-foreground hover:text-foreground transition-colors"
      title="Copy to clipboard"
    >
      {copied ? "✓" : "⎘"}
    </button>
  );
}

function LogEntry({ entry }: { entry: DebugEntry }) {
  const [expanded, setExpanded] = useState(false);
  const isExpandable = !!entry.details && (entry.level === "error" || entry.source === "Integration");
  const copyText = [entry.timestamp, `[${entry.level.toUpperCase()}]`, `[${entry.source}]`, entry.message, entry.details].filter(Boolean).join(" ");

  const expandHover =
    isExpandable && entry.level === "error"
      ? "cursor-pointer hover:bg-red-950/50"
      : isExpandable
        ? "cursor-pointer hover:bg-muted/50"
        : "hover:bg-muted/50";

  return (
    <div
      className={`group px-2 py-0.5 ${levelBg[entry.level]} ${expandHover}`}
      onClick={isExpandable ? () => setExpanded((v) => !v) : undefined}
    >
      <div className="flex gap-2 items-start">
        <span className="text-muted-foreground flex-shrink-0">{entry.timestamp}</span>
        <span className={`flex-shrink-0 w-12 ${levelColors[entry.level]}`}>
          [{entry.level.toUpperCase()}]
        </span>
        <span className="text-muted-foreground flex-shrink-0">[{entry.source}]</span>
        <span className="text-foreground flex-1 min-w-0">{entry.message}</span>
        <span className="flex-shrink-0 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          <CopyButton text={copyText} />
          {isExpandable && (
            <span className="text-muted-foreground text-[10px]">{expanded ? "▲" : "▼"}</span>
          )}
        </span>
        {!isExpandable && entry.details && (
          <span className="text-muted-foreground ml-1 truncate" title={entry.details}>
            — {entry.details}
          </span>
        )}
      </div>
      {expanded && entry.details && (
        <div
          className={`mt-1 ml-28 whitespace-pre-wrap break-all rounded px-2 py-1 text-[11px] relative ${
            entry.level === "error"
              ? "text-red-300 bg-red-950/40"
              : "text-zinc-200 bg-zinc-900/80"
          }`}
        >
          <CopyButton text={entry.details} />
          {entry.details}
        </div>
      )}
    </div>
  );
}

function IntegrationLogEntry({ entry }: { entry: DebugEntry }) {
  const [expanded, setExpanded] = useState(false);
  const summary = stripInlineCmdFromMessage(entry.message);
  const haystack = `${entry.message}\n${entry.details || ""}`;
  const domain = classifyIntegrationDomain(haystack);
  const parsed = parseIntegrationDetails(entry.details);
  const hasBody = !!(parsed.command || parsed.output);
  const isExpandable = hasBody || (!!entry.details && entry.level === "error");

  const copyText = [entry.timestamp, `[${entry.level.toUpperCase()}]`, entry.message, entry.details].filter(Boolean).join("\n");

  const expandHover = isExpandable
    ? entry.level === "error"
      ? "cursor-pointer hover:bg-red-950/50"
      : "cursor-pointer hover:bg-muted/50"
    : "hover:bg-muted/50";

  const domainBadge =
    domain === "site_replication" ? (
      <span className="flex-shrink-0 px-1.5 py-0.5 rounded border border-fuchsia-500/45 bg-fuchsia-950/40 text-fuchsia-200 text-[10px] font-semibold">
        Site replication
      </span>
    ) : domain === "ilm_tiering" ? (
      <span className="flex-shrink-0 px-1.5 py-0.5 rounded border border-amber-500/45 bg-amber-950/40 text-amber-200 text-[10px] font-semibold">
        ILM tiering
      </span>
    ) : (
      <span className="flex-shrink-0 px-1.5 py-0.5 rounded border border-zinc-600 bg-zinc-900/70 text-zinc-400 text-[10px]">
        Other
      </span>
    );

  return (
    <div
      className={`group px-2 py-1 rounded-sm ${levelBg[entry.level]} ${expandHover}`}
      onClick={isExpandable ? () => setExpanded((v) => !v) : undefined}
    >
      <div className="flex gap-2 items-start flex-wrap">
        <span className="text-muted-foreground flex-shrink-0">{entry.timestamp}</span>
        <span className={`flex-shrink-0 w-11 text-[10px] ${levelColors[entry.level]}`}>{entry.level.toUpperCase()}</span>
        {domainBadge}
        <span className="text-foreground flex-1 min-w-[100px] leading-snug">{summary}</span>
        <span className="flex-shrink-0 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity ml-auto">
          <CopyButton text={copyText} />
          {isExpandable && <span className="text-muted-foreground text-[10px]">{expanded ? "▲" : "▼"}</span>}
        </span>
      </div>
      {expanded && isExpandable && (
        <div
          className={`mt-2 space-y-2 border-l-2 pl-2 ml-1 ${
            entry.level === "error" ? "border-red-500/40" : "border-primary/35"
          }`}
        >
          {parsed.command ? (
            <div>
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground mb-0.5">Command</div>
              <pre
                className={`whitespace-pre-wrap break-all rounded px-2 py-1 text-[11px] max-h-40 overflow-y-auto border border-border ${
                  entry.level === "error" ? "bg-red-950/35 text-red-100" : "bg-zinc-950/80 text-zinc-200"
                }`}
              >
                {parsed.command}
              </pre>
            </div>
          ) : null}
          {parsed.output ? (
            <div>
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground mb-0.5">Output</div>
              <pre
                className={`whitespace-pre-wrap break-all rounded px-2 py-1 text-[11px] max-h-56 overflow-y-auto border border-border ${
                  entry.level === "error" ? "bg-red-950/30 text-red-200" : "bg-zinc-950/80 text-zinc-300"
                }`}
              >
                {parsed.output}
              </pre>
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}

export default function DebugPanel() {
  const { entries, integrationBuffer, clear, clearIntegrationBuffer } = useDebugStore();
  const [tab, setTab] = useState<Tab>("health");

  const sortedEntries = [...entries].reverse();
  const errorCount = entries.filter((e) => e.level === "error").length;
  const warnCount = entries.filter((e) => e.level === "warn").length;
  const integrationEntriesView = [...integrationBuffer].reverse();

  return (
    <div className="flex flex-col h-full bg-background">
      <div className="flex items-center justify-between px-3 py-1.5 bg-card border-b border-border">
        <div className="flex items-center gap-3 text-xs">
          <div className="flex items-center gap-0.5 bg-muted rounded p-0.5">
            <button
              onClick={() => setTab("health")}
              className={`px-2 py-0.5 rounded transition-colors ${tab === "health" ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
            >
              Health
            </button>
            <button
              onClick={() => setTab("logs")}
              className={`px-2 py-0.5 rounded transition-colors ${tab === "logs" ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
            >
              Logs
            </button>
            <button
              onClick={() => setTab("lifecycle")}
              className={`px-2 py-0.5 rounded transition-colors ${tab === "lifecycle" ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
            >
              Lifecycle
            </button>
            <button
              onClick={() => setTab("integrations")}
              className={`px-2 py-0.5 rounded transition-colors ${tab === "integrations" ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
            >
              Integrations
            </button>
          </div>
          {tab === "logs" && (
            <>
              <span className="text-muted-foreground">{entries.length} entries</span>
              {errorCount > 0 && <span className="text-red-400">{errorCount} errors</span>}
              {warnCount > 0 && <span className="text-yellow-400">{warnCount} warnings</span>}
            </>
          )}
          {tab === "lifecycle" && (
            <span className="text-muted-foreground">{entries.filter((e) => e.source === "Lifecycle" || e.source === "Deploy").length} events</span>
          )}
          {tab === "integrations" && (
            <span className="text-muted-foreground">{integrationBuffer.length} events</span>
          )}
        </div>
        {tab === "logs" && (
          <button onClick={clear} className="text-xs text-muted-foreground hover:text-foreground transition-colors">
            Clear logs
          </button>
        )}
        {tab === "integrations" && integrationBuffer.length > 0 && (
          <button
            onClick={clearIntegrationBuffer}
            className="text-xs text-muted-foreground hover:text-foreground transition-colors"
            type="button"
          >
            Clear integration
          </button>
        )}
      </div>
      <div className="flex-1 overflow-y-auto">
        {tab === "health" ? (
          <HealthPanel />
        ) : tab === "lifecycle" ? (
          <div className="font-mono text-xs p-1">
            {(() => {
              const lifecycleEntries = [...entries].filter((e) => e.source === "Lifecycle" || e.source === "Deploy").reverse();
              return lifecycleEntries.length === 0 ? (
                <div className="flex items-center justify-center h-32 text-muted-foreground">
                  No lifecycle events yet. Deploy a demo to see container events here.
                </div>
              ) : (
                lifecycleEntries.map((entry) => <LogEntry key={entry.id} entry={entry} />)
              );
            })()}
          </div>
        ) : tab === "integrations" ? (
          <div className="font-mono text-xs p-1">
            {integrationEntriesView.length === 0 ? (
              <div className="flex items-center justify-center h-32 text-muted-foreground px-4 text-center leading-relaxed">
                No integration events yet. Deploy a demo to see mc / bucket / ILM init scripts, edge activation (site
                replication vs ILM tiering — each row is labeled and expandable for command + output), webhooks, and audit
                lines.
              </div>
            ) : (
              integrationEntriesView.map((entry) => <IntegrationLogEntry key={entry.id} entry={entry} />)
            )}
          </div>
        ) : (
          <div className="font-mono text-xs p-1">
            {sortedEntries.length === 0 ? (
              <div className="flex items-center justify-center h-32 text-muted-foreground">
                No log entries yet. Deploy a demo to see output here.
              </div>
            ) : (
              sortedEntries.map((entry) => <LogEntry key={entry.id} entry={entry} />)
            )}
          </div>
        )}
      </div>
    </div>
  );
}
