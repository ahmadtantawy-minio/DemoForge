import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { CornerDownRight, X } from "lucide-react";
import { proxyUrl } from "../../api/client";

const STORAGE_KEY = "demoforge:designerWebUiOverlay:bounds";
const DEFAULT_WIDTH = 960;
const DEFAULT_HEIGHT = 560;
const MIN_WIDTH = 360;
const MIN_HEIGHT = 240;
const VIEW_MARGIN = 16;

interface PanelBounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

function clampBounds(b: PanelBounds): PanelBounds {
  const maxW = Math.max(MIN_WIDTH, window.innerWidth - VIEW_MARGIN * 2);
  const maxH = Math.max(MIN_HEIGHT, window.innerHeight - VIEW_MARGIN * 2);
  const width = Math.min(Math.max(MIN_WIDTH, b.width), maxW);
  const height = Math.min(Math.max(MIN_HEIGHT, b.height), maxH);
  const x = Math.min(Math.max(VIEW_MARGIN, b.x), window.innerWidth - width - VIEW_MARGIN);
  const y = Math.min(Math.max(VIEW_MARGIN, b.y), window.innerHeight - height - VIEW_MARGIN);
  return { x, y, width, height };
}

function defaultBottomRightBounds(): PanelBounds {
  return clampBounds({
    x: Math.max(VIEW_MARGIN, window.innerWidth - DEFAULT_WIDTH - 24),
    y: Math.max(VIEW_MARGIN, window.innerHeight - DEFAULT_HEIGHT - 24),
    width: DEFAULT_WIDTH,
    height: DEFAULT_HEIGHT,
  });
}

function loadStoredBounds(): PanelBounds {
  if (typeof window === "undefined") {
    return { x: VIEW_MARGIN, y: VIEW_MARGIN, width: DEFAULT_WIDTH, height: DEFAULT_HEIGHT };
  }
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return defaultBottomRightBounds();
    const p = JSON.parse(raw) as Partial<PanelBounds>;
    if (
      typeof p.x === "number" &&
      typeof p.y === "number" &&
      typeof p.width === "number" &&
      typeof p.height === "number"
    ) {
      return clampBounds({ x: p.x, y: p.y, width: p.width, height: p.height });
    }
  } catch {
    /* ignore */
  }
  return defaultBottomRightBounds();
}

function persistBounds(b: PanelBounds) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(b));
  } catch {
    /* ignore */
  }
}

interface Props {
  proxyPath: string;
  title: string;
  onClose: () => void;
}

/**
 * Draggable, resizable iframe shell for in-designer web UIs (Event Processor event viewer, etc.).
 */
export default function DesignerWebUIOverlay({ proxyPath, title, onClose }: Props) {
  const url = proxyUrl(proxyPath);
  const [bounds, setBounds] = useState<PanelBounds>(() => loadStoredBounds());
  const boundsRef = useRef(bounds);
  boundsRef.current = bounds;

  const dragRef = useRef<{ dragging: boolean; offsetX: number; offsetY: number }>({
    dragging: false,
    offsetX: 0,
    offsetY: 0,
  });
  const resizeRef = useRef<{
    resizing: boolean;
    startX: number;
    startY: number;
    startW: number;
    startH: number;
  }>({
    resizing: false,
    startX: 0,
    startY: 0,
    startW: 0,
    startH: 0,
  });

  useEffect(() => {
    const handleResize = () => {
      setBounds((prev) => {
        const next = clampBounds(prev);
        if (next.x !== prev.x || next.y !== prev.y || next.width !== prev.width || next.height !== prev.height) {
          persistBounds(next);
          return next;
        }
        return prev;
      });
    };
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  const onHeaderMouseDown = (e: React.MouseEvent<HTMLDivElement>) => {
    if ((e.target as HTMLElement).closest("a,button")) return;
    const b = boundsRef.current;
    dragRef.current = {
      dragging: true,
      offsetX: e.clientX - b.x,
      offsetY: e.clientY - b.y,
    };
  };

  const onResizeMouseDown = (e: React.MouseEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    const b = boundsRef.current;
    resizeRef.current = {
      resizing: true,
      startX: e.clientX,
      startY: e.clientY,
      startW: b.width,
      startH: b.height,
    };
  };

  const snapBottomRight = () => {
    const next = defaultBottomRightBounds();
    setBounds(next);
    persistBounds(next);
  };

  useEffect(() => {
    const onMouseMove = (e: MouseEvent) => {
      if (resizeRef.current.resizing) {
        const dx = e.clientX - resizeRef.current.startX;
        const dy = e.clientY - resizeRef.current.startY;
        const b = boundsRef.current;
        setBounds(
          clampBounds({
            ...b,
            width: resizeRef.current.startW + dx,
            height: resizeRef.current.startH + dy,
          })
        );
        return;
      }
      if (!dragRef.current.dragging) return;
      const b = boundsRef.current;
      const nextX = e.clientX - dragRef.current.offsetX;
      const nextY = e.clientY - dragRef.current.offsetY;
      setBounds(
        clampBounds({
          ...b,
          x: nextX,
          y: nextY,
        })
      );
    };
    const onMouseUp = () => {
      if (dragRef.current.dragging || resizeRef.current.resizing) {
        persistBounds(boundsRef.current);
      }
      dragRef.current.dragging = false;
      resizeRef.current.resizing = false;
    };
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
    return () => {
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
    };
  }, []);

  return createPortal(
    <div className="fixed inset-0 z-[10000] pointer-events-none">
      <div
        className="pointer-events-auto bg-card border border-border rounded-lg shadow-2xl flex flex-col overflow-hidden relative"
        style={{
          position: "fixed",
          left: bounds.x,
          top: bounds.y,
          width: bounds.width,
          height: bounds.height,
          maxWidth: "calc(100vw - 2rem)",
          maxHeight: "calc(100vh - 2rem)",
        }}
      >
        <div
          className="flex items-center justify-between px-3 py-2 border-b border-border shrink-0 cursor-move bg-muted/50"
          onMouseDown={onHeaderMouseDown}
        >
          <span className="text-sm font-semibold text-foreground truncate pr-2">{title}</span>
          <div className="flex items-center gap-2 shrink-0">
            <a
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-primary hover:underline"
              onClick={(e) => e.stopPropagation()}
            >
              Open in tab
            </a>
            <button
              type="button"
              onClick={snapBottomRight}
              className="p-1 rounded hover:bg-accent transition-colors"
              title="Snap to bottom-right"
            >
              <CornerDownRight className="w-3.5 h-3.5 text-muted-foreground" />
            </button>
            <button
              type="button"
              onClick={onClose}
              className="p-1 rounded hover:bg-accent transition-colors"
              title="Close"
            >
              <X className="w-3.5 h-3.5 text-muted-foreground" />
            </button>
          </div>
        </div>
        <iframe src={url} className="flex-1 w-full border-0 min-h-0 bg-background" title={title} />

        <div
          role="presentation"
          className="absolute bottom-0 right-0 w-4 h-4 cursor-se-resize rounded-br-lg group"
          onMouseDown={onResizeMouseDown}
          title="Resize"
        >
          <span className="absolute bottom-1 right-1 block w-2.5 h-2.5 border-r-2 border-b-2 border-muted-foreground/60 group-hover:border-muted-foreground" />
        </div>
      </div>
    </div>,
    document.body
  );
}
