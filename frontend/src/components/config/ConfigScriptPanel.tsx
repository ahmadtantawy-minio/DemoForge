import { useState, useEffect, useMemo } from "react";
import { fetchConfigScript } from "../../api/client";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Copy, Check, Download } from "lucide-react";
import { toast } from "sonner";

interface ConfigScriptPanelProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  demoId: string;
}

/** Syntax-highlight a shell script line for display. */
function highlightLine(line: string): React.ReactNode {
  const trimmed = line.trimStart();

  // Section headers: # ===== ... =====
  if (/^#\s*=====/.test(trimmed)) {
    return <span className="text-yellow-400 font-bold">{line}</span>;
  }

  // Comments
  if (trimmed.startsWith("#")) {
    return <span className="text-green-400">{line}</span>;
  }

  // mc commands - highlight the "mc" keyword and string arguments
  if (/^\s*mc\s/.test(line)) {
    return highlightCommand(line);
  }

  // Fallback
  return <span>{line}</span>;
}

/** Highlight mc commands: mc keyword in cyan, quoted strings in orange. */
function highlightCommand(line: string): React.ReactNode {
  const parts: React.ReactNode[] = [];
  // Split on quoted strings to colorize them
  const regex = /((?:'[^']*')|(?:"[^"]*"))/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let key = 0;

  while ((match = regex.exec(line)) !== null) {
    // Text before the quoted string
    if (match.index > lastIndex) {
      parts.push(
        <span key={key++} className="text-cyan-400">
          {line.slice(lastIndex, match.index)}
        </span>
      );
    }
    // The quoted string itself
    parts.push(
      <span key={key++} className="text-orange-400">
        {match[1]}
      </span>
    );
    lastIndex = regex.lastIndex;
  }

  // Remaining text after last quoted string
  if (lastIndex < line.length) {
    parts.push(
      <span key={key++} className="text-cyan-400">
        {line.slice(lastIndex)}
      </span>
    );
  }

  return <>{parts}</>;
}

export default function ConfigScriptPanel({ open, onOpenChange, demoId }: ConfigScriptPanelProps) {
  const [script, setScript] = useState("");
  const [sections, setSections] = useState<{ name: string; commands: string[] }[]>([]);
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!open || !demoId) return;
    setLoading(true);
    fetchConfigScript(demoId)
      .then((res) => {
        setScript(res.script);
        setSections(res.sections);
      })
      .catch(() => toast.error("Failed to load config script"))
      .finally(() => setLoading(false));
  }, [open, demoId]);

  const highlighted = useMemo(() => {
    if (!script) return null;
    return script.split("\n").map((line, i) => (
      <div key={i}>{highlightLine(line) || "\u00A0"}</div>
    ));
  }, [script]);

  const handleCopy = () => {
    navigator.clipboard.writeText(script).then(() => {
      setCopied(true);
      toast.success("Script copied to clipboard");
      setTimeout(() => setCopied(false), 2000);
    });
  };

  const handleDownload = () => {
    const blob = new Blob([script], { type: "text/x-shellscript" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `demoforge-${demoId}-setup.sh`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    toast.success("Script downloaded");
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl max-h-[85vh] flex flex-col">
        <DialogHeader>
          <div className="flex items-center justify-between">
            <DialogTitle className="text-base">Setup Script (mc commands)</DialogTitle>
            <div className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="sm"
                className="h-7 px-2 gap-1 text-xs"
                onClick={handleCopy}
                disabled={!script}
              >
                {copied ? (
                  <><Check className="w-3 h-3" /> Copied</>
                ) : (
                  <><Copy className="w-3 h-3" /> Copy Script</>
                )}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="h-7 px-2 gap-1 text-xs"
                onClick={handleDownload}
                disabled={!script}
              >
                <Download className="w-3 h-3" /> Download .sh
              </Button>
            </div>
          </div>
        </DialogHeader>

        {loading && (
          <div className="flex-1 flex items-center justify-center text-sm text-muted-foreground">
            Generating script...
          </div>
        )}

        {!loading && !script && (
          <div className="flex-1 flex items-center justify-center text-sm text-muted-foreground">
            No mc commands to generate. Add clusters and connections to your demo first.
          </div>
        )}

        {!loading && script && (
          <>
            {sections.length > 0 && (
              <div className="flex flex-wrap gap-1 mb-2">
                {sections.map((s) => (
                  <span
                    key={s.name}
                    className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground border border-border"
                  >
                    {s.name} ({s.commands.length})
                  </span>
                ))}
              </div>
            )}
            <div className="flex-1 overflow-auto rounded border border-border bg-[#1e1e2e] min-h-0">
              <pre className="text-xs font-mono p-3 whitespace-pre leading-relaxed">
                {highlighted}
              </pre>
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
