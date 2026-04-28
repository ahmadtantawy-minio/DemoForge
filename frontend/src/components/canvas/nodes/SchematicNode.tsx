import { memo } from "react";
import { type NodeProps } from "@xyflow/react";

interface SchematicChild {
  id: string;
  label: string;
  detail?: string;
  color: string;
}

interface SchematicNodeData {
  label: string;
  sublabel?: string;
  children?: SchematicChild[];
  variant: "gpu" | "tier" | "generic";
  width?: number;
  height?: number;
}

const tierColors: Record<string, { bg: string; border: string; text: string }> = {
  red:   { bg: "bg-red-500/10",   border: "border-red-400/40",   text: "text-red-300" },
  amber: { bg: "bg-amber-500/10", border: "border-amber-400/40", text: "text-amber-300" },
  blue:  { bg: "bg-blue-500/10",  border: "border-blue-400/40",  text: "text-blue-300" },
  teal:  { bg: "bg-teal-500/10",  border: "border-teal-400/40",  text: "text-teal-300" },
  gray:  { bg: "bg-zinc-500/10",  border: "border-zinc-400/40",  text: "text-zinc-400" },
};

function SchematicNode({ data }: NodeProps) {
  const d = data as unknown as SchematicNodeData;

  if (d.variant === "gpu") {
    return (
      <div
        className="rounded-lg border border-dashed border-violet-600/45 dark:border-purple-400/35 bg-violet-500/[0.08] dark:bg-purple-500/5 p-3"
        style={{ width: d.width || 200, minHeight: d.height || 160 }}
      >
        <div className="flex items-center gap-2 mb-3">
          <div className="w-2 h-2 rounded-full bg-green-600 dark:bg-green-400 shrink-0 animate-pulse" />
          <span className="text-xs font-semibold text-violet-950 dark:text-purple-100">{d.label}</span>
          {d.sublabel && (
            <span className="text-[10px] font-medium text-violet-800 dark:text-purple-300 ml-auto">{d.sublabel}</span>
          )}
        </div>
        <div className="space-y-1.5">
          {d.children?.map((child) => {
            const colors = tierColors[child.color] || tierColors.gray;
            return (
              <div
                key={child.id}
                className={`rounded px-2 py-1.5 border ${colors.bg} ${colors.border}`}
              >
                <div className={`text-[11px] font-medium ${colors.text}`}>
                  {child.label}
                </div>
                {child.detail && (
                  <div className="text-[9px] text-zinc-500 mt-0.5">{child.detail}</div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  return (
    <div
      className="rounded border border-dashed border-zinc-600 bg-zinc-800/30 px-3 py-2"
      style={{ width: d.width || 150 }}
    >
      <div className="text-xs font-medium text-zinc-300">{d.label}</div>
      {d.sublabel && (
        <div className="text-[10px] text-zinc-500 mt-0.5">{d.sublabel}</div>
      )}
    </div>
  );
}

export default memo(SchematicNode);
