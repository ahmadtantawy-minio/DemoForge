import type { Edge } from "@xyflow/react";
import type { ScenarioOption } from "../types";
import { nonemptyTrim } from "./utils";

export type EsSinkMode = "files_and_iceberg" | "files_only";

const DEFAULT_SINK: EsSinkMode = "files_and_iceberg";

export function normalizeEsSinkMode(v: string | undefined): EsSinkMode {
  return v === "files_only" ? "files_only" : DEFAULT_SINK;
}

function edgeBucket(conn: Record<string, string | undefined>): string | null {
  return nonemptyTrim(conn.target_bucket) ?? nonemptyTrim(conn.bucket);
}

/** Build pill label for edges from external-system → MinIO (s3 / aistor-tables). */
export function buildExternalSystemOutgoingEdgeLabel(
  connectionType: string | undefined,
  sinkMode: EsSinkMode,
  scenario: ScenarioOption | undefined,
  edgeConn?: Record<string, string | undefined> | null,
  /** Raw object format from external-system node config (`ES_DG_FORMAT` / `DG_FORMAT`); overrides legacy edge `format`. */
  nodeRawFormat?: string | null
): string {
  const conn = edgeConn ?? {};
  const ct = connectionType ?? "";
  const sinkTag =
    sinkMode === "files_only"
      ? "Raw only"
      : ct === "aistor-tables"
        ? "Iceberg"
        : "Catalog";

  if (sinkMode === "files_only") {
    const sid = scenario?.id ?? "";
    const fromScenarioFmt = nonemptyTrim(scenario?.default_raw_format) ?? nonemptyTrim(scenario?.format) ?? "csv";
    const fromScenarioBucket =
      nonemptyTrim(scenario?.default_raw_bucket) ?? (sid ? `es-raw-${sid}` : null);
    const fmt = (
      nonemptyTrim(nodeRawFormat) ?? nonemptyTrim(conn.format) ?? fromScenarioFmt
    ).toLowerCase();
    const bucket = edgeBucket(conn) ?? fromScenarioBucket;
    const parts = [sinkTag, fmt.toUpperCase()];
    if (bucket) parts.push(bucket);
    return parts.join(" · ");
  }

  const format = scenario?.format;
  const primaryTable = scenario?.primary_table;
  const parts = [sinkTag, format, primaryTable].filter(Boolean) as string[];
  return parts.join(" · ");
}

/** Apply labels + generation_mode on all edges sourced by this external-system node. */
export function mapEdgesForExternalSystemLabels(
  edges: Edge[],
  sourceNodeId: string,
  sinkMode: EsSinkMode,
  scenario: ScenarioOption | undefined,
  /** From node `config.ES_DG_FORMAT` or `config.DG_FORMAT` (not stored on the edge). */
  nodeRawFormat?: string | null
): Edge[] {
  const primaryMode = scenario?.datasets?.[0]?.generation_mode ?? "";
  return edges.map((e) => {
    if (e.source !== sourceNodeId) return e;
    const ct = (e.data as { connectionType?: string } | undefined)?.connectionType as string | undefined;
    if (ct !== "s3" && ct !== "aistor-tables") return e;
    const prev = ((e.data as { connectionConfig?: Record<string, string> }).connectionConfig ?? {}) as Record<
      string,
      string
    >;
    const merged: Record<string, string> = { ...prev };
    merged.generation_mode = primaryMode;
    merged.es_sink_mode = sinkMode;

    if (sinkMode === "files_only" && scenario) {
      const sid = scenario.id ?? "";
      const defBucket = nonemptyTrim(scenario.default_raw_bucket) ?? (sid ? `es-raw-${sid}` : null);
      if (!edgeBucket(merged)) {
        if (defBucket) merged.target_bucket = defBucket;
      }
    }

    const label = buildExternalSystemOutgoingEdgeLabel(ct, sinkMode, scenario, merged, nodeRawFormat);
    return {
      ...e,
      data: {
        ...e.data,
        label,
        connectionConfig: merged,
      },
    };
  });
}
