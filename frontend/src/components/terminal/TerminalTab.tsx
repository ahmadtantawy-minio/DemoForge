import { useEffect, useRef } from "react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { WebLinksAddon } from "@xterm/addon-web-links";
import "@xterm/xterm/css/xterm.css";
import { terminalWsUrl } from "../../api/client";
import type { QuickAction } from "../../types";

interface Props {
  demoId: string;
  nodeId: string;
  quickActions: QuickAction[];
}

export default function TerminalTab({ demoId, nodeId, quickActions }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<Terminal | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const term = new Terminal({
      cursorBlink: true,
      fontSize: 13,
      fontFamily: "monospace",
      theme: { background: "#09090b" },
    });
    const fitAddon = new FitAddon();
    const webLinksAddon = new WebLinksAddon();
    term.loadAddon(fitAddon);
    term.loadAddon(webLinksAddon);
    term.open(containerRef.current);
    // Delay fit to ensure container has dimensions after DOM layout
    requestAnimationFrame(() => {
      try { fitAddon.fit(); } catch {}
    });
    termRef.current = term;

    const ws = new WebSocket(terminalWsUrl(demoId, nodeId));
    wsRef.current = ws;

    ws.binaryType = "arraybuffer";

    ws.onopen = () => {
      term.write("\r\nConnected to " + nodeId + "\r\n");
    };

    ws.onmessage = (e) => {
      if (e.data instanceof ArrayBuffer) {
        term.write(new Uint8Array(e.data));
      } else {
        term.write(e.data);
      }
    };

    ws.onclose = () => {
      term.write("\r\n[Connection closed]\r\n");
    };

    ws.onerror = () => {
      term.write("\r\n[Connection error]\r\n");
    };

    term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(new TextEncoder().encode(data));
      }
    });

    const resizeObserver = new ResizeObserver(() => fitAddon.fit());
    resizeObserver.observe(containerRef.current);

    return () => {
      resizeObserver.disconnect();
      ws.close();
      term.dispose();
    };
  }, [demoId, nodeId]);

  const sendCommand = (command: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(new TextEncoder().encode(command + "\n"));
    }
  };

  return (
    <div className="flex flex-col h-full min-h-0 overflow-hidden">
      {quickActions.length > 0 && (
        <div className="flex flex-wrap gap-1 px-2 py-1 bg-card border-b border-border">
          {quickActions.map((qa) => (
            <button
              key={qa.label}
              onClick={() => sendCommand(qa.command)}
              className="px-2 py-0.5 bg-muted hover:bg-accent text-foreground rounded text-xs transition-colors"
            >
              {qa.label}
            </button>
          ))}
        </div>
      )}
      <div ref={containerRef} className="flex-1 min-h-0 overflow-hidden bg-background" />
    </div>
  );
}
