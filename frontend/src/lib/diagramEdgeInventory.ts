import type { ComponentSummary } from "../types";
import { getConnectionColor } from "./connectionMeta";

/** Synthetic id for MinIO cluster nodes in the designer. */
export const CLUSTER_NODE_ID = "__cluster__";

export interface DiagramEdgeInventoryRow {
  id: string;
  from: string;
  to: string;
  edgeType: string;
  color: string;
  /** How the arrow is drawn on the canvas (AnimatedDataEdge / onConnect). */
  pointerDirection: string;
  dynamic: boolean;
  notes: string;
  ruleSource: "hardcoded" | "manifest";
}

function isMinioPeer(id: string): boolean {
  return id === "minio" || id === CLUSTER_NODE_ID;
}

/** Pairs handled in diagramStore.onConnect before manifest intersection. */
export function isHardcodedManifestPair(from: string, to: string): boolean {
  if (from === CLUSTER_NODE_ID && to === CLUSTER_NODE_ID) return true;
  if (from === "nginx" || to === "nginx") return true;
  if (isMinioPeer(from) && to === "s3-file-browser") return true;
  if (from === "s3-file-browser" && isMinioPeer(to)) return true;
  if (from === CLUSTER_NODE_ID && to === "trino") return true;
  if (from === "external-system" && (isMinioPeer(to) || to === "minio")) return true;
  if (from === "data-generator" && (isMinioPeer(to) || to === "minio")) return true;
  if (isMinioPeer(from) && to === "iceberg-browser") return true;
  if (from === "iceberg-browser" && isMinioPeer(to)) return true;
  if (isMinioPeer(from) && to === "spark-etl-job") return true;
  if (from === "spark-etl-job" && isMinioPeer(to)) return true;
  return false;
}

function row(
  partial: Omit<DiagramEdgeInventoryRow, "id" | "color"> & { color?: string },
): DiagramEdgeInventoryRow {
  return {
    color: partial.color ?? getConnectionColor(partial.edgeType),
    ...partial,
    id: `${partial.ruleSource}:${partial.from}:${partial.to}:${partial.edgeType}:${partial.pointerDirection}`,
  };
}

function hardcodedRules(): DiagramEdgeInventoryRow[] {
  const minioSparkPointer =
    "MinIO → Spark (edge flipped if drawn Spark → MinIO); rendered bidirectional for s3 / aistor-tables";
  const minioBrowserPointer = "MinIO → browser (edge flipped if drawn browser → MinIO)";

  return [
    row({
      from: CLUSTER_NODE_ID,
      to: CLUSTER_NODE_ID,
      edgeType: "cluster-replication | cluster-site-replication | cluster-tiering",
      pointerDirection: "source → target (swap allowed in picker)",
      dynamic: true,
      notes: "Connection type picker; optional endpoint swap",
      ruleSource: "hardcoded",
    }),
    row({
      from: "nginx",
      to: "*",
      edgeType: "nginx-backend",
      pointerDirection: "source → target",
      dynamic: false,
      notes: "Any nginx component to cluster or backend node",
      ruleSource: "hardcoded",
    }),
    row({
      from: "*",
      to: "nginx",
      edgeType: "nginx-backend",
      pointerDirection: "source → target",
      dynamic: false,
      notes: "Reverse drag still uses nginx-backend",
      ruleSource: "hardcoded",
    }),
    row({
      from: CLUSTER_NODE_ID,
      to: "s3-file-browser",
      edgeType: "s3",
      pointerDirection: minioBrowserPointer,
      dynamic: false,
      notes: "Standalone minio node uses same rule",
      ruleSource: "hardcoded",
    }),
    row({
      from: "s3-file-browser",
      to: CLUSTER_NODE_ID,
      edgeType: "s3",
      pointerDirection: minioBrowserPointer,
      dynamic: false,
      notes: "Auto-orients to MinIO → browser",
      ruleSource: "hardcoded",
    }),
    row({
      from: CLUSTER_NODE_ID,
      to: "trino",
      edgeType: "aistor-tables",
      pointerDirection: "cluster → trino",
      dynamic: false,
      notes: "Requires aistorTablesEnabled on cluster",
      ruleSource: "hardcoded",
    }),
    row({
      from: "external-system",
      to: CLUSTER_NODE_ID,
      edgeType: "s3",
      pointerDirection: "source → target",
      dynamic: true,
      notes: "When ES_SINK_MODE=files_only or AIStor Tables disabled",
      ruleSource: "hardcoded",
    }),
    row({
      from: "external-system",
      to: CLUSTER_NODE_ID,
      edgeType: "aistor-tables",
      pointerDirection: "source → target",
      dynamic: true,
      notes: "When not files_only and AIStor Tables enabled",
      ruleSource: "hardcoded",
    }),
    row({
      from: "data-generator",
      to: CLUSTER_NODE_ID,
      edgeType: "s3",
      pointerDirection: "source → target",
      dynamic: true,
      notes: "Auto when AIStor Tables disabled on target",
      ruleSource: "hardcoded",
    }),
    row({
      from: "data-generator",
      to: CLUSTER_NODE_ID,
      edgeType: "s3 | aistor-tables",
      pointerDirection: "source → target",
      dynamic: true,
      notes: "Picker when AIStor Tables enabled on target",
      ruleSource: "hardcoded",
    }),
    row({
      from: CLUSTER_NODE_ID,
      to: "iceberg-browser",
      edgeType: "aistor-tables",
      pointerDirection: minioBrowserPointer,
      dynamic: false,
      notes: "Requires AIStor Tables; no S3 vs Iceberg picker",
      ruleSource: "hardcoded",
    }),
    row({
      from: CLUSTER_NODE_ID,
      to: "spark-etl-job",
      edgeType: "s3",
      pointerDirection: minioSparkPointer,
      dynamic: true,
      notes: "JOB_MODE=raw_to_parquet",
      ruleSource: "hardcoded",
    }),
    row({
      from: CLUSTER_NODE_ID,
      to: "spark-etl-job",
      edgeType: "aistor-tables",
      pointerDirection: minioSparkPointer,
      dynamic: true,
      notes: "Iceberg / compaction modes; requires AIStor Tables on MinIO",
      ruleSource: "hardcoded",
    }),
    row({
      from: "*",
      to: "*",
      edgeType: "data",
      pointerDirection: "source → target",
      dynamic: false,
      notes: "Fallback when component manifest missing",
      ruleSource: "hardcoded",
    }),
  ];
}

function manifestRules(components: ComponentSummary[]): DiagramEdgeInventoryRow[] {
  const out: DiagramEdgeInventoryRow[] = [];

  for (const src of components) {
    if (src.virtual) continue;
    for (const tgt of components) {
      if (tgt.virtual || src.id === tgt.id) continue;
      if (isHardcodedManifestPair(src.id, tgt.id)) continue;

      const srcConn = src.connections;
      const tgtConn = tgt.connections;
      if (!srcConn?.provides?.length && !tgtConn?.provides?.length) continue;

      const forwardTypes = (srcConn?.provides ?? [])
        .map((p) => p.type)
        .filter((t) => (tgtConn?.accepts ?? []).some((a) => a.type === t));
      const reverseTypes = (tgtConn?.provides ?? [])
        .map((p) => p.type)
        .filter((t) => (srcConn?.accepts ?? []).some((a) => a.type === t));

      if (forwardTypes.length === 0 && reverseTypes.length === 0) continue;

      const optionCount = forwardTypes.length + reverseTypes.length;
      const dynamic = optionCount > 1;

      for (const edgeType of forwardTypes) {
        const pointerDirection =
          forwardTypes.length === 1 && reverseTypes.length === 0
            ? "source → target (auto)"
            : "source → target";
        out.push(
          row({
            from: src.id,
            to: tgt.id,
            edgeType,
            pointerDirection,
            dynamic,
            notes: dynamic ? "Manifest intersection; picker if multiple options" : "Single compatible type — auto-connect",
            ruleSource: "manifest",
          }),
        );
      }

      for (const edgeType of reverseTypes) {
        const pointerDirection =
          reverseTypes.length === 1 && forwardTypes.length === 0
            ? "target → source (auto-flip)"
            : "target → source (auto-flip)";
        out.push(
          row({
            from: src.id,
            to: tgt.id,
            edgeType,
            pointerDirection,
            dynamic,
            notes: dynamic
              ? "Target provides, source accepts; picker may reverse endpoints"
              : "Only reverse path — endpoints swapped on connect",
            ruleSource: "manifest",
          }),
        );
      }
    }
  }

  // De-dupe identical rows (multiple provides entries of same type)
  const seen = new Set<string>();
  return out.filter((r) => {
    const key = `${r.from}|${r.to}|${r.edgeType}|${r.pointerDirection}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function buildDiagramEdgeInventory(components: ComponentSummary[]): DiagramEdgeInventoryRow[] {
  return [...hardcodedRules(), ...manifestRules(components)].sort((a, b) => {
    const from = a.from.localeCompare(b.from);
    if (from !== 0) return from;
    const to = a.to.localeCompare(b.to);
    if (to !== 0) return to;
    return a.edgeType.localeCompare(b.edgeType);
  });
}

export function displayInventoryEndpoint(id: string, components: ComponentSummary[]): string {
  if (id === CLUSTER_NODE_ID) return "MinIO cluster";
  if (id === "*") return "*";
  return components.find((c) => c.id === id)?.name ?? id;
}

export type EdgeInventorySortKey = keyof Pick<
  DiagramEdgeInventoryRow,
  "from" | "to" | "edgeType" | "color" | "pointerDirection" | "dynamic" | "notes" | "ruleSource"
>;

export function filterAndSortEdgeInventory(
  rows: DiagramEdgeInventoryRow[],
  opts: {
    globalSearch: string;
    columnFilters: Partial<Record<EdgeInventorySortKey, string>>;
    sortKey: EdgeInventorySortKey;
    sortDir: "asc" | "desc";
    displayFrom: (id: string) => string;
    displayTo: (id: string) => string;
  },
): DiagramEdgeInventoryRow[] {
  const q = opts.globalSearch.trim().toLowerCase();
  const col = opts.columnFilters;

  let filtered = rows.filter((r) => {
    const fromLabel = opts.displayFrom(r.from).toLowerCase();
    const toLabel = opts.displayTo(r.to).toLowerCase();
    const hay = [
      fromLabel,
      toLabel,
      r.from,
      r.to,
      r.edgeType,
      r.color,
      r.pointerDirection,
      r.notes,
      r.ruleSource,
      r.dynamic ? "yes dynamic" : "no static",
    ]
      .join(" ")
      .toLowerCase();

    if (q && !hay.includes(q)) return false;

    const matchCol = (key: EdgeInventorySortKey, value: string) => {
      const f = (col[key] ?? "").trim().toLowerCase();
      if (!f) return true;
      return value.toLowerCase().includes(f);
    };

    if (!matchCol("from", fromLabel) && !matchCol("from", r.from)) return false;
    if (!matchCol("to", toLabel) && !matchCol("to", r.to)) return false;
    if (!matchCol("edgeType", r.edgeType)) return false;
    if (!matchCol("color", r.color)) return false;
    if (!matchCol("pointerDirection", r.pointerDirection)) return false;
    if (!matchCol("notes", r.notes)) return false;
    if (!matchCol("ruleSource", r.ruleSource)) return false;
    if (col.dynamic?.trim()) {
      const want = col.dynamic.trim().toLowerCase();
      const dynLabel = r.dynamic ? "yes" : "no";
      if (!dynLabel.includes(want) && !want.includes(dynLabel)) return false;
    }
    return true;
  });

  const dir = opts.sortDir === "asc" ? 1 : -1;
  const key = opts.sortKey;
  filtered = [...filtered].sort((a, b) => {
    let av: string | boolean = a[key] as string | boolean;
    let bv: string | boolean = b[key] as string | boolean;
    if (key === "from") {
      av = opts.displayFrom(a.from);
      bv = opts.displayFrom(b.from);
    } else if (key === "to") {
      av = opts.displayTo(a.to);
      bv = opts.displayTo(b.to);
    } else if (key === "dynamic") {
      return (a.dynamic === b.dynamic ? 0 : a.dynamic ? 1 : -1) * dir;
    }
    return String(av).localeCompare(String(bv)) * dir;
  });

  return filtered;
}
