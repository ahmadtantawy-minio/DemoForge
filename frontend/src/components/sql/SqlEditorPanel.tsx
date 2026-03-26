import { useState, useEffect, useRef } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { fetchAllScenarioQueries, executeTrinoQuery } from "../../api/client";

interface ScenarioQuery {
  id: string;
  name: string;
  sql: string;
}

interface ScenarioTab {
  id: string;
  name: string;
  queries: ScenarioQuery[];
}

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  demoId: string;
  scenarioId?: string;
}

interface QueryResult {
  columns: string[];
  rows: any[][];
  row_count: number;
  duration_ms: number;
  truncated?: boolean;
  error?: string;
}


export default function SqlEditorPanel({ open, onOpenChange, demoId, scenarioId }: Props) {
  const [allScenarios, setAllScenarios] = useState<ScenarioTab[]>([]);
  const [activeTab, setActiveTab] = useState<string>(scenarioId ?? "ecommerce-orders");
  const [sql, setSql] = useState("");
  const [selectedQueryId, setSelectedQueryId] = useState<string | null>(null);
  const [result, setResult] = useState<QueryResult | null>(null);
  const [running, setRunning] = useState(false);
  const [loadingQueries, setLoadingQueries] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Load all scenarios' queries when panel opens or demoId changes
  useEffect(() => {
    if (!open || !demoId) return;
    setLoadingQueries(true);
    fetchAllScenarioQueries(demoId)
      .then((res) => {
        setAllScenarios(res.scenarios);
        // Set active tab to the current scenario if provided, else first scenario
        if (scenarioId && res.scenarios.some((s) => s.id === scenarioId)) {
          setActiveTab(scenarioId);
        } else if (res.scenarios.length > 0) {
          setActiveTab(res.scenarios[0].id);
        }
      })
      .catch(() => setAllScenarios([]))
      .finally(() => setLoadingQueries(false));
  }, [open, demoId]);

  // When scenarioId prop changes (user switched scenario in properties panel),
  // update the active tab if that scenario exists
  useEffect(() => {
    if (scenarioId && allScenarios.some((s) => s.id === scenarioId)) {
      setActiveTab(scenarioId);
    }
  }, [scenarioId, allScenarios]);

  // Reset state when closed
  useEffect(() => {
    if (!open) {
      setResult(null);
      setSelectedQueryId(null);
    }
  }, [open]);

  const activeScenario = allScenarios.find((s) => s.id === activeTab);
  const queries = activeScenario?.queries ?? [];


  const loadQuery = (q: ScenarioQuery) => {
    setSelectedQueryId(q.id);
    setSql(q.sql);
    setResult(null);
  };

  // Clear selected query when switching tabs
  const switchTab = (tabId: string) => {
    setActiveTab(tabId);
    setSelectedQueryId(null);
  };

  const runQuery = async () => {
    if (!sql.trim() || running) return;
    setRunning(true);
    setResult(null);
    try {
      const res = await executeTrinoQuery(demoId, sql.trim());
      setResult(res);
    } catch (err: any) {
      setResult({
        columns: [],
        rows: [],
        row_count: 0,
        duration_ms: 0,
        error: err.message || "Query failed",
      });
    } finally {
      setRunning(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      runQuery();
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-5xl max-h-[85vh] overflow-hidden flex flex-col p-0 gap-0 bg-card text-foreground">
        <DialogHeader className="px-4 py-3 border-b border-border shrink-0">
          <DialogTitle className="text-base font-semibold">SQL Editor</DialogTitle>
        </DialogHeader>

        {/* Scenario tabs */}
        {!loadingQueries && allScenarios.length > 0 && (
          <div className="flex border-b border-border shrink-0 bg-muted/10">
            {allScenarios.map((s) => (
              <button
                key={s.id}
                onClick={() => switchTab(s.id)}
                className={`px-4 py-2 text-xs font-medium whitespace-nowrap transition-colors border-b-2 -mb-px ${
                  activeTab === s.id
                    ? "border-primary text-primary bg-background"
                    : "border-transparent text-muted-foreground hover:text-foreground hover:bg-accent"
                }`}
              >
                {s.name}
              </button>
            ))}
          </div>
        )}
        {loadingQueries && (
          <div className="px-4 py-2 text-xs text-muted-foreground border-b border-border shrink-0">
            Loading scenarios...
          </div>
        )}

        <div className="flex flex-1 min-h-0">
          {/* Left sidebar: pre-built queries */}
          {queries.length > 0 ? (
            <div className="w-48 shrink-0 border-r border-border overflow-y-auto bg-muted/20">
              <div className="px-3 py-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground border-b border-border">
                Pre-built Queries
              </div>
              {queries.map((q) => (
                <button
                  key={q.id}
                  onClick={() => loadQuery(q)}
                  className={`w-full text-left px-3 py-2 text-xs transition-colors border-b border-border/50 ${
                    selectedQueryId === q.id
                      ? "bg-primary/15 text-primary border-l-2 border-l-primary"
                      : "text-foreground hover:bg-accent"
                  }`}
                >
                  {q.name}
                </button>
              ))}
            </div>
          ) : null}

          {/* Main area */}
          <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
            {/* SQL textarea */}
            <div className="px-4 pt-3 pb-2 shrink-0">
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-[10px] text-muted-foreground uppercase tracking-wider font-medium">
                  SQL Query
                </span>
                <span className="text-[10px] text-muted-foreground">
                  Ctrl+Enter to run
                </span>
              </div>
              <textarea
                ref={textareaRef}
                value={sql}
                onChange={(e) => setSql(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="SELECT * FROM iceberg.demo.orders LIMIT 10"
                rows={7}
                className="w-full bg-background border border-input rounded-md px-3 py-2 text-sm font-mono resize-none focus:outline-none focus:ring-1 focus:ring-ring"
                spellCheck={false}
              />
              <div className="mt-2">
                <button
                  onClick={runQuery}
                  disabled={running || !sql.trim()}
                  className="px-4 py-1.5 text-sm font-medium rounded bg-green-600 text-white hover:bg-green-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  {running ? "Running..." : "Run Query"}
                </button>
              </div>
            </div>

            {/* Results area */}
            <div className="flex-1 overflow-auto px-4 pb-4 min-h-0">
              {running && (
                <div className="flex items-center gap-2 text-sm text-muted-foreground py-4">
                  <span className="inline-block w-4 h-4 border-2 border-primary border-t-transparent rounded-full animate-spin" />
                  Executing query...
                </div>
              )}

              {!running && result && result.error && (
                <div className="mt-2 p-3 rounded border border-destructive/40 bg-destructive/10">
                  <div className="text-xs font-semibold text-destructive mb-1">Query Error</div>
                  <pre className="text-xs text-destructive/90 whitespace-pre-wrap font-mono">{result.error}</pre>
                </div>
              )}

              {!running && result && !result.error && result.columns.length > 0 && (
                <div className="mt-2">
                  <div className="flex items-center gap-3 mb-2 text-xs text-muted-foreground">
                    <span>{result.row_count.toLocaleString()} row{result.row_count !== 1 ? "s" : ""}</span>
                    <span>&bull;</span>
                    <span>{result.duration_ms}ms</span>
                    {result.truncated && (
                      <>
                        <span>&bull;</span>
                        <span className="text-amber-400">Limited to 1,000 rows</span>
                      </>
                    )}
                  </div>
                  <div className="overflow-x-auto border border-border rounded">
                    <table className="w-full text-xs font-mono border-collapse text-foreground">
                      <thead>
                        <tr className="bg-muted/50">
                          {result.columns.map((col) => (
                            <th
                              key={col}
                              className="text-left px-3 py-1.5 text-muted-foreground font-semibold border-b border-border whitespace-nowrap"
                            >
                              {col}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {result.rows.map((row, i) => (
                          <tr
                            key={i}
                            className={i % 2 === 0 ? "bg-background" : "bg-muted/20"}
                          >
                            {row.map((cell, j) => (
                              <td
                                key={j}
                                className="px-3 py-1.5 border-b border-border/50 whitespace-nowrap max-w-[300px] truncate text-foreground"
                                title={cell !== null && cell !== undefined ? String(cell) : "NULL"}
                              >
                                {cell === null || cell === undefined ? (
                                  <span className="text-muted-foreground/50 italic">NULL</span>
                                ) : (
                                  String(cell)
                                )}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {!running && result && !result.error && result.columns.length === 0 && (
                <div className="mt-2 text-xs text-muted-foreground py-4">
                  Query executed successfully. No rows returned. ({result.duration_ms}ms)
                </div>
              )}
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
