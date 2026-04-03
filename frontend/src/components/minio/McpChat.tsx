import { useState, useRef, useEffect, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { toast } from "../../lib/toast";
import { ChevronDown, ChevronRight, Send } from "lucide-react";

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:9210";

interface ToolCall {
  name: string;
  args: any;
  result: any;
}

interface Message {
  role: "user" | "assistant";
  content: string;
  toolCalls?: ToolCall[];
}

interface Props {
  demoId: string;
  clusterId: string;
}

const WELCOME = "Ask me anything about your MinIO storage. I can list buckets, check admin status, manage objects, and more.";

const SUGGESTIONS = [
  "List all buckets",
  "Show cluster status",
  "How much storage is used?",
  "Create a bucket called test-data",
];

interface McpInfo {
  mcpUrl: string;
  llmEndpoint: string;
  llmModel: string;
}

export default function McpChat({ demoId, clusterId }: Props) {
  const [messages, setMessages] = useState<Message[]>([
    { role: "assistant", content: WELCOME },
  ]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [expandedToolCalls, setExpandedToolCalls] = useState<Set<number>>(new Set());
  const [mcpInfo, setMcpInfo] = useState<McpInfo | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Fetch MCP + LLM connection info
  useEffect(() => {
    Promise.all([
      fetch(`${API_BASE}/api/settings/llm`).then(r => r.ok ? r.json() : null),
    ]).then(([llmSettings]) => {
      setMcpInfo({
        mcpUrl: `http://demoforge-${demoId}-${clusterId}-mcp:8090/mcp`,
        llmEndpoint: llmSettings?.endpoint || "http://host.docker.internal:11434",
        llmModel: llmSettings?.model || "qwen2.5:14b",
      });
    }).catch(() => {});
  }, [demoId, clusterId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streaming]);

  const toggleToolCall = (msgIdx: number) => {
    setExpandedToolCalls((prev) => {
      const next = new Set(prev);
      if (next.has(msgIdx)) next.delete(msgIdx);
      else next.add(msgIdx);
      return next;
    });
  };

  const sendMessage = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || streaming) return;

      const userMsg: Message = { role: "user", content: trimmed };
      const history = [...messages, userMsg];
      setMessages(history);
      setInput("");
      setStreaming(true);

      // Placeholder assistant message we'll build up
      const assistantIdx = history.length;
      setMessages((prev) => [...prev, { role: "assistant", content: "" }]);

      abortRef.current = new AbortController();

      try {
        const res = await fetch(
          `${API_BASE}/api/demos/${demoId}/minio/${clusterId}/mcp/chat`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              messages: history.map((m) => ({ role: m.role, content: m.content })),
            }),
            signal: abortRef.current.signal,
          }
        );

        if (!res.ok || !res.body) {
          const body = await res.text();
          throw new Error(`API error ${res.status}: ${body}`);
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        // Local mutable state for the assistant message being built
        let assistantContent = "";
        let pendingToolCalls: ToolCall[] = [];

        const flush = () => {
          setMessages((prev) => {
            const next = [...prev];
            next[assistantIdx] = {
              role: "assistant",
              content: assistantContent,
              toolCalls: pendingToolCalls.length > 0 ? [...pendingToolCalls] : undefined,
            };
            return next;
          });
        };

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() ?? "";

          for (const line of lines) {
            if (!line.startsWith("data: ")) continue;
            const raw = line.slice(6).trim();
            if (!raw || raw === "[DONE]") continue;

            let event: any;
            try {
              event = JSON.parse(raw);
            } catch {
              continue;
            }

            if (event.type === "text") {
              assistantContent += event.content ?? "";
              flush();
            } else if (event.type === "tool_call") {
              pendingToolCalls = [
                ...pendingToolCalls,
                { name: event.name, args: event.arguments ?? {}, result: null },
              ];
              flush();
            } else if (event.type === "tool_result") {
              // Match by name — update last pending entry with this name
              const idx = [...pendingToolCalls].reverse().findIndex((tc) => tc.name === event.name && tc.result === null);
              if (idx !== -1) {
                const realIdx = pendingToolCalls.length - 1 - idx;
                pendingToolCalls = pendingToolCalls.map((tc, i) =>
                  i === realIdx ? { ...tc, result: event.result } : tc
                );
              } else {
                pendingToolCalls = [
                  ...pendingToolCalls,
                  { name: event.name, args: {}, result: event.result },
                ];
              }
              flush();
            } else if (event.type === "done") {
              break;
            } else if (event.type === "error") {
              toast.error("Chat error", { description: event.message });
              assistantContent += event.message ? `\n\nError: ${event.message}` : "";
              flush();
              break;
            }
          }
        }
      } catch (e: any) {
        if (e.name === "AbortError") return;
        toast.error("Chat failed", { description: e.message });
        setMessages((prev) => {
          const next = [...prev];
          next[assistantIdx] = {
            role: "assistant",
            content: `Error: ${e.message}`,
          };
          return next;
        });
      } finally {
        setStreaming(false);
        abortRef.current = null;
      }
    },
    [demoId, clusterId, messages, streaming]
  );

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input);
    }
  };

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Connection info bar */}
      {mcpInfo && (
        <div className="mb-2 px-2.5 py-1.5 rounded bg-violet-500/10 border border-violet-500/20 text-[10px] font-mono text-muted-foreground space-y-0.5">
          <div><span className="text-violet-400">MCP:</span> {mcpInfo.mcpUrl}</div>
          <div><span className="text-violet-400">LLM:</span> {mcpInfo.llmEndpoint} <span className="text-violet-400/60">({mcpInfo.llmModel})</span></div>
        </div>
      )}
      {/* Message list */}
      <div className="flex-1 overflow-y-auto flex flex-col gap-2 pr-1 min-h-0">
        {messages.map((msg, msgIdx) => (
          <div
            key={msgIdx}
            className={`flex flex-col gap-1 ${msg.role === "user" ? "items-end" : "items-start"}`}
          >
            {/* Bubble */}
            <div
              className={`max-w-[85%] rounded px-2.5 py-1.5 text-xs whitespace-pre-wrap ${
                msg.role === "user"
                  ? "bg-primary/10 text-foreground border border-primary/20"
                  : "text-foreground"
              }`}
            >
              {msg.content || (streaming && msgIdx === messages.length - 1 ? "" : "\u200b")}
              {streaming && msgIdx === messages.length - 1 && (
                <span className="inline-block w-1.5 h-3 bg-primary/70 animate-pulse ml-0.5 rounded-sm align-middle" />
              )}
            </div>

            {/* Suggestion chips — only on the first assistant message */}
            {msg.role === "assistant" && msgIdx === 0 && (
              <div className="flex flex-wrap gap-1 mt-0.5">
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    disabled={streaming}
                    onClick={() => sendMessage(s)}
                    className="px-2 py-0.5 text-[10px] bg-muted rounded hover:bg-accent text-muted-foreground hover:text-foreground transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {s}
                  </button>
                ))}
              </div>
            )}

            {/* Tool calls */}
            {msg.toolCalls && msg.toolCalls.length > 0 && (
              <div className="flex flex-col gap-1 w-full max-w-[95%]">
                {msg.toolCalls.map((tc, tcIdx) => {
                  const key = msgIdx * 1000 + tcIdx;
                  const expanded = expandedToolCalls.has(key);
                  return (
                    <div
                      key={tcIdx}
                      className="border border-border bg-muted/30 rounded text-[10px]"
                    >
                      <button
                        className="flex items-center gap-1 w-full px-2 py-1 hover:bg-muted/50 transition-colors text-left"
                        onClick={() => toggleToolCall(key)}
                      >
                        {expanded ? (
                          <ChevronDown className="w-3 h-3 text-muted-foreground flex-shrink-0" />
                        ) : (
                          <ChevronRight className="w-3 h-3 text-muted-foreground flex-shrink-0" />
                        )}
                        <span className="font-mono text-primary">{tc.name}</span>
                        {tc.result === null && (
                          <span className="ml-auto text-muted-foreground animate-pulse">running...</span>
                        )}
                        {tc.result !== null && (
                          <span className="ml-auto text-green-500/70">done</span>
                        )}
                      </button>
                      {expanded && (
                        <div className="px-2 pb-2 flex flex-col gap-1">
                          {Object.keys(tc.args).length > 0 && (
                            <div>
                              <div className="text-[9px] text-muted-foreground uppercase tracking-wide mb-0.5">Args</div>
                              <pre className="font-mono text-[10px] text-muted-foreground bg-zinc-950 rounded p-1.5 overflow-x-auto">
                                {JSON.stringify(tc.args, null, 2)}
                              </pre>
                            </div>
                          )}
                          {tc.result !== null && (
                            <div>
                              <div className="text-[9px] text-muted-foreground uppercase tracking-wide mb-0.5">Result</div>
                              <pre className="font-mono text-[10px] text-green-400 bg-zinc-950 rounded p-1.5 overflow-x-auto max-h-40">
                                {typeof tc.result === "string"
                                  ? tc.result
                                  : JSON.stringify(tc.result, null, 2)}
                              </pre>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Input bar */}
      <div className="flex gap-1.5 pt-2 border-t border-border mt-2 flex-shrink-0">
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask about your MinIO storage..."
          className="h-8 text-xs font-mono flex-1"
          disabled={streaming}
        />
        <Button
          size="sm"
          className="h-8 px-2.5"
          onClick={() => sendMessage(input)}
          disabled={!input.trim() || streaming}
        >
          <Send className="w-3 h-3" />
        </Button>
      </div>
    </div>
  );
}
