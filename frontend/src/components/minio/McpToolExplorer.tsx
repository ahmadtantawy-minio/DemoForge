import { useState, useEffect, useCallback } from "react";
import { listMcpTools, callMcpTool, type McpTool } from "../../api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";
import { Loader2 } from "lucide-react";

interface Props {
  demoId: string;
  clusterId: string;
}

const TOOL_CATEGORIES: Record<string, string[]> = {
  "Bucket Ops": ["list_buckets", "create_bucket", "delete_bucket", "get_bucket_tags", "set_bucket_tags", "get_bucket_versioning", "set_bucket_versioning", "get_bucket_lifecycle", "get_bucket_replication"],
  "Object Ops": ["list_bucket_contents", "get_object_metadata", "get_object_tags", "set_object_tags", "get_object_versions", "get_object_presigned_url", "upload_object", "download_object", "delete_object", "copy_object", "move_object", "text_to_object", "compose_object"],
  "Admin": ["get_admin_info", "get_data_usage_info"],
  "AI": ["ask_object"],
  "Local": ["list_local_files", "list_allowed_directories"],
};

function categorize(toolName: string): string {
  for (const [cat, names] of Object.entries(TOOL_CATEGORIES)) {
    if (names.includes(toolName)) return cat;
  }
  return "Other";
}

const QUICK_ACTIONS = [
  { label: "List Buckets", tool: "list_buckets", args: {} },
  { label: "Admin Info", tool: "get_admin_info", args: {} },
  { label: "Data Usage", tool: "get_data_usage_info", args: {} },
];

export default function McpToolExplorer({ demoId, clusterId }: Props) {
  const [tools, setTools] = useState<McpTool[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedTool, setSelectedTool] = useState<McpTool | null>(null);
  const [params, setParams] = useState<Record<string, string>>({});
  const [result, setResult] = useState<string>("");
  const [executing, setExecuting] = useState(false);
  const [activeCategory, setActiveCategory] = useState<string | null>(null);

  const fetchTools = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listMcpTools(demoId, clusterId);
      setTools(res.tools || []);
    } catch (e: any) {
      setError(e.message || "Failed to load MCP tools");
    }
    setLoading(false);
  }, [demoId, clusterId]);

  useEffect(() => {
    fetchTools();
  }, [fetchTools]);

  const handleSelectTool = (tool: McpTool) => {
    setSelectedTool(tool);
    setResult("");
    // Initialize params from schema
    const schema = tool.inputSchema as any;
    const initial: Record<string, string> = {};
    if (schema?.properties) {
      for (const [key, prop] of Object.entries(schema.properties as Record<string, any>)) {
        initial[key] = prop.default?.toString() || "";
      }
    }
    setParams(initial);
  };

  const handleExecute = async () => {
    if (!selectedTool) return;
    setExecuting(true);
    setResult("");
    try {
      // Convert string params to appropriate types
      const args: Record<string, unknown> = {};
      for (const [key, val] of Object.entries(params)) {
        if (val === "") continue;
        if (val === "true") args[key] = true;
        else if (val === "false") args[key] = false;
        else if (!isNaN(Number(val)) && val.trim() !== "") args[key] = Number(val);
        else args[key] = val;
      }
      const res = await callMcpTool(demoId, clusterId, selectedTool.name, args);
      setResult(JSON.stringify(res.result, null, 2));
      if (res.error) toast.error("Tool error", { description: res.error });
    } catch (e: any) {
      setResult(`Error: ${e.message}`);
      toast.error("Failed to execute tool");
    }
    setExecuting(false);
  };

  const handleQuickAction = async (action: typeof QUICK_ACTIONS[0]) => {
    const tool = tools.find(t => t.name === action.tool);
    if (tool) {
      setSelectedTool(tool);
      setParams({});
    }
    setExecuting(true);
    setResult("");
    try {
      const res = await callMcpTool(demoId, clusterId, action.tool, action.args);
      setResult(JSON.stringify(res.result, null, 2));
    } catch (e: any) {
      setResult(`Error: ${e.message}`);
    }
    setExecuting(false);
  };

  // Group tools by category
  const grouped: Record<string, McpTool[]> = {};
  for (const tool of tools) {
    const cat = categorize(tool.name);
    if (!grouped[cat]) grouped[cat] = [];
    grouped[cat].push(tool);
  }

  const categories = Object.keys(grouped);
  const filteredTools = activeCategory ? (grouped[activeCategory] || []) : tools;

  if (loading) {
    return (
      <div className="flex items-center justify-center py-8 gap-2 text-muted-foreground text-xs">
        <Loader2 className="w-4 h-4 animate-spin" /> Loading MCP tools...
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-8 gap-2 text-center">
        <p className="text-xs text-red-400">{error}</p>
        <button className="text-xs text-primary hover:underline" onClick={fetchTools}>Retry</button>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full gap-2">
      {/* Quick actions */}
      <div className="flex gap-1 flex-wrap">
        {QUICK_ACTIONS.map((qa) => (
          <button
            key={qa.tool}
            className="px-2 py-0.5 text-[10px] bg-muted rounded hover:bg-accent text-muted-foreground hover:text-foreground transition-colors"
            onClick={() => handleQuickAction(qa)}
            disabled={executing}
          >
            {qa.label}
          </button>
        ))}
        <span className="ml-auto text-[10px] text-muted-foreground">{tools.length} tools available</span>
      </div>

      <div className="flex gap-2 flex-1 min-h-0">
        {/* Left: Tool list */}
        <div className="w-2/5 flex flex-col gap-1 overflow-y-auto min-h-0 pr-1">
          {/* Category filter */}
          <div className="flex gap-1 flex-wrap mb-1">
            <button
              className={`px-1.5 py-0.5 text-[9px] rounded ${!activeCategory ? "bg-primary/20 text-primary" : "bg-muted text-muted-foreground hover:text-foreground"}`}
              onClick={() => setActiveCategory(null)}
            >All</button>
            {categories.map((cat) => (
              <button
                key={cat}
                className={`px-1.5 py-0.5 text-[9px] rounded ${activeCategory === cat ? "bg-primary/20 text-primary" : "bg-muted text-muted-foreground hover:text-foreground"}`}
                onClick={() => setActiveCategory(activeCategory === cat ? null : cat)}
              >{cat} ({grouped[cat].length})</button>
            ))}
          </div>
          {filteredTools.map((tool) => (
            <button
              key={tool.name}
              onClick={() => handleSelectTool(tool)}
              className={`text-left px-2 py-1.5 rounded text-xs transition-colors ${
                selectedTool?.name === tool.name
                  ? "bg-primary/15 text-primary border border-primary/30"
                  : "hover:bg-muted text-muted-foreground hover:text-foreground"
              }`}
            >
              <div className="font-mono text-[11px] font-medium">{tool.name}</div>
              <div className="text-[10px] opacity-70 line-clamp-1">{tool.description}</div>
            </button>
          ))}
        </div>

        {/* Right: Tool detail + execution */}
        <div className="w-3/5 flex flex-col gap-2 min-h-0">
          {selectedTool ? (
            <>
              <div className="text-xs">
                <span className="font-mono font-medium text-foreground">{selectedTool.name}</span>
                <p className="text-[10px] text-muted-foreground mt-0.5">{selectedTool.description}</p>
              </div>

              {/* Parameter form */}
              {(() => {
                const schema = selectedTool.inputSchema as any;
                const properties = schema?.properties || {};
                const required = new Set(schema?.required || []);
                const keys = Object.keys(properties);
                if (keys.length === 0) return <div className="text-[10px] text-muted-foreground">No parameters required</div>;
                return (
                  <div className="space-y-1.5">
                    {keys.map((key) => {
                      const prop = properties[key];
                      return (
                        <div key={key}>
                          <label className="text-[10px] text-muted-foreground block mb-0.5">
                            {key}{required.has(key) ? " *" : ""}
                            {prop.description && <span className="ml-1 opacity-60">— {prop.description}</span>}
                          </label>
                          <Input
                            value={params[key] || ""}
                            onChange={(e) => setParams((p) => ({ ...p, [key]: e.target.value }))}
                            placeholder={prop.default?.toString() || prop.type || ""}
                            className="h-7 text-xs font-mono"
                          />
                        </div>
                      );
                    })}
                  </div>
                );
              })()}

              <Button size="sm" className="h-7 text-xs w-fit" onClick={handleExecute} disabled={executing}>
                {executing ? <><Loader2 className="w-3 h-3 animate-spin mr-1" /> Running...</> : "Execute"}
              </Button>

              {/* Result */}
              <pre className="text-xs font-mono whitespace-pre-wrap text-green-400 bg-zinc-950 rounded p-2 flex-1 min-h-[100px] max-h-[35vh] overflow-y-auto border border-border">
                {result || "# Result will appear here"}
              </pre>
            </>
          ) : (
            <div className="flex items-center justify-center h-full text-xs text-muted-foreground">
              Select a tool from the list or use a quick action
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
