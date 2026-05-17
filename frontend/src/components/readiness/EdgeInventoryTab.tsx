import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown, Search } from "lucide-react";
import { fetchComponents } from "../../api/client";
import type { ComponentSummary } from "../../types";
import { Input } from "../ui/input";
import { Badge } from "../ui/badge";
import { cn } from "../../lib/utils";
import {
  buildDiagramEdgeInventory,
  displayInventoryEndpoint,
  filterAndSortEdgeInventory,
  type DiagramEdgeInventoryRow,
  type EdgeInventorySortKey,
} from "../../lib/diagramEdgeInventory";
import { getConnectionLabel } from "../../lib/connectionMeta";

const COLUMNS: { key: EdgeInventorySortKey; label: string; className?: string }[] = [
  { key: "from", label: "From" },
  { key: "to", label: "To" },
  { key: "edgeType", label: "Edge type" },
  { key: "color", label: "Color", className: "w-[100px]" },
  { key: "pointerDirection", label: "Pointer" },
  { key: "dynamic", label: "Dynamic", className: "w-[72px] text-center" },
  { key: "ruleSource", label: "Source", className: "w-[88px]" },
  { key: "notes", label: "Notes" },
];

export function EdgeInventoryTab() {
  const [components, setComponents] = useState<ComponentSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [globalSearch, setGlobalSearch] = useState("");
  const [columnFilters, setColumnFilters] = useState<Partial<Record<EdgeInventorySortKey, string>>>({});
  const [sortKey, setSortKey] = useState<EdgeInventorySortKey>("from");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchComponents();
      setComponents(res.components);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load component registry");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const inventory = useMemo(() => buildDiagramEdgeInventory(components), [components]);

  const displayFrom = useCallback(
    (id: string) => displayInventoryEndpoint(id, components),
    [components],
  );
  const displayTo = displayFrom;

  const filtered = useMemo(
    () =>
      filterAndSortEdgeInventory(inventory, {
        globalSearch,
        columnFilters,
        sortKey,
        sortDir,
        displayFrom,
        displayTo,
      }),
    [inventory, globalSearch, columnFilters, sortKey, sortDir, displayFrom, displayTo],
  );

  const toggleSort = (key: EdgeInventorySortKey) => {
    if (sortKey === key) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortKey(key);
      setSortDir("asc");
    }
  };

  const SortIcon = ({ col }: { col: EdgeInventorySortKey }) => {
    if (sortKey !== col) return <ArrowUpDown className="w-3 h-3 opacity-40" />;
    return sortDir === "asc" ? <ArrowUp className="w-3 h-3" /> : <ArrowDown className="w-3 h-3" />;
  };

  if (loading) {
    return (
      <div className="space-y-3">
        {[1, 2, 3, 4, 5, 6].map((i) => (
          <div key={i} className="h-10 bg-muted rounded animate-pulse" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-card border rounded-lg p-8 text-center">
        <p className="text-sm text-muted-foreground mb-4">{error}</p>
        <button
          type="button"
          onClick={load}
          className="px-4 py-2 text-sm rounded-md bg-muted border text-foreground hover:bg-accent transition-colors"
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div data-testid="edge-inventory-tab">
      <p className="text-sm text-muted-foreground mb-4">
        Supported diagram edges from designer wiring rules and component manifest provides/accepts.{" "}
        <span className="text-foreground">{filtered.length}</span> of {inventory.length} rows shown.
      </p>

      <div className="relative max-w-sm mb-4">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
        <Input
          placeholder="Search all columns…"
          value={globalSearch}
          onChange={(e) => setGlobalSearch(e.target.value)}
          className="pl-9 h-9"
        />
      </div>

      <div className="bg-card border rounded-lg overflow-x-auto">
        <table className="w-full min-w-[960px] text-sm">
          <thead>
            <tr className="bg-muted border-b border-border">
              {COLUMNS.map((col) => (
                <th key={col.key} className={cn("px-2 py-2 align-bottom", col.className)}>
                  <button
                    type="button"
                    onClick={() => toggleSort(col.key)}
                    className="flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground w-full"
                  >
                    {col.label}
                    <SortIcon col={col.key} />
                  </button>
                  <Input
                    placeholder="Filter"
                    value={columnFilters[col.key] ?? ""}
                    onChange={(e) =>
                      setColumnFilters((prev) => ({ ...prev, [col.key]: e.target.value }))
                    }
                    className="mt-1 h-7 text-xs font-normal"
                    onClick={(e) => e.stopPropagation()}
                  />
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={COLUMNS.length} className="px-4 py-8 text-center text-muted-foreground">
                  No edges match the current filters.
                </td>
              </tr>
            ) : (
              filtered.map((row) => (
                <InventoryRow
                  key={row.id}
                  row={row}
                  fromLabel={displayFrom(row.from)}
                  toLabel={displayTo(row.to)}
                />
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function InventoryRow({
  row,
  fromLabel,
  toLabel,
}: {
  row: DiagramEdgeInventoryRow;
  fromLabel: string;
  toLabel: string;
}) {
  const types = row.edgeType.split("|").map((t) => t.trim()).filter(Boolean);

  return (
    <tr className="hover:bg-muted/40 transition-colors">
      <td className="px-2 py-2 font-mono text-xs text-foreground">{fromLabel}</td>
      <td className="px-2 py-2 font-mono text-xs text-foreground">{toLabel}</td>
      <td className="px-2 py-2">
        <div className="flex flex-wrap gap-1">
          {types.map((t) => (
            <Badge key={t} variant="outline" className="text-[10px] font-mono px-1.5 py-0" title={getConnectionLabel(t)}>
              {t}
            </Badge>
          ))}
        </div>
      </td>
      <td className="px-2 py-2">
        <div className="flex items-center gap-2">
          <span
            className="inline-block w-4 h-4 rounded border border-border shrink-0"
            style={{ backgroundColor: row.color }}
            title={row.color}
          />
          <span className="font-mono text-[10px] text-muted-foreground">{row.color}</span>
        </div>
      </td>
      <td className="px-2 py-2 text-xs text-muted-foreground max-w-[200px]">{row.pointerDirection}</td>
      <td className="px-2 py-2 text-center">
        {row.dynamic ? (
          <Badge className="text-[10px] bg-amber-500/15 text-amber-600 border-amber-500/30">Yes</Badge>
        ) : (
          <Badge variant="secondary" className="text-[10px]">
            No
          </Badge>
        )}
      </td>
      <td className="px-2 py-2">
        <Badge
          variant="secondary"
          className={cn(
            "text-[10px]",
            row.ruleSource === "hardcoded"
              ? "bg-violet-500/10 text-violet-600 border-violet-500/25"
              : "bg-sky-500/10 text-sky-600 border-sky-500/25",
          )}
        >
          {row.ruleSource}
        </Badge>
      </td>
      <td className="px-2 py-2 text-xs text-muted-foreground max-w-[240px]">{row.notes}</td>
    </tr>
  );
}
