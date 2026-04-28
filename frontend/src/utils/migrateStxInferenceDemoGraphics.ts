/**
 * Upgrade persisted STX inference experience layouts from Vera Rubin / Rubin Ultra
 * naming to H100 SXM + GPU A/B (matches current demo-templates/experience-stx-inference.yaml).
 */
const LEGACY_GROUP_LABEL = /vera\s*rubin|compute\s*tray/i;
const LEGACY_GPU_SUB = /\brubin\b/i;
/** Legacy schematic primary label (hyphenated), e.g. GPU-A / GPU-B */
const LEGACY_GPU_LABEL = /^GPU-[AB]$/i;

function migrateTierChildLabel(label: string): string {
  if (/G1\s*—\s*GPU HBM/i.test(label)) return label.replace(/G1\s*—\s*GPU HBM/i, "G1 — HBM3");
  return label;
}

function migrateGpuSchematic(s: Record<string, unknown>): Record<string, unknown> {
  if (s.variant !== "gpu") return s;
  const sub = String(s.sublabel ?? "");
  const lab = String(s.label ?? "").trim();
  if (/^h100\s*sxm/i.test(lab)) return s;

  const needsRename = LEGACY_GPU_SUB.test(sub) || LEGACY_GPU_LABEL.test(lab);
  if (!needsRename) return s;

  const id = String(s.id ?? "");
  let slot: "A" | "B" | null = null;
  if (/sch-gpu-a$/i.test(id) || /^GPU-A$/i.test(lab)) slot = "A";
  else if (/sch-gpu-b$/i.test(id) || /^GPU-B$/i.test(lab)) slot = "B";
  if (!slot) return s;

  const children = Array.isArray(s.children)
    ? (s.children as { label?: string }[]).map((c) =>
        typeof c.label === "string"
          ? { ...c, label: migrateTierChildLabel(c.label) }
          : c
      )
    : s.children;

  return {
    ...s,
    label: "H100 SXM",
    sublabel: `GPU ${slot}`,
    children,
  };
}

/** Match tops of sch-gpu-a / sch-gpu-b (legacy template had mismatched y). */
function alignStxGpuSchematicTops(schematics: Record<string, unknown>[]): Record<string, unknown>[] {
  const a = schematics.find((s) => s.id === "sch-gpu-a");
  const b = schematics.find((s) => s.id === "sch-gpu-b");
  if (!a || !b) return schematics;
  const posA = (a.position as { y?: number } | undefined) || {};
  const posB = (b.position as { y?: number } | undefined) || {};
  if (typeof posA.y !== "number" || typeof posB.y !== "number") return schematics;
  const y = Math.min(posA.y, posB.y);
  return schematics.map((s) => {
    if (s.id !== "sch-gpu-a" && s.id !== "sch-gpu-b") return s;
    const pos = (typeof s.position === "object" && s.position ? s.position : {}) as Record<string, unknown>;
    return { ...s, position: { ...pos, y } };
  });
}

/** STX template used to draw sim → MinIO; compose maps group edges onto inference-sim in that group. */
function migrateStxGpuStorageEdges(edges: unknown[]): unknown[] {
  return edges.map((raw) => {
    const edge = raw as Record<string, unknown>;
    const id = String(edge.id ?? "");
    const src = String(edge.source ?? "");
    const tgt = String(edge.target ?? "");
    const cfg = (edge.connection_config || {}) as Record<string, unknown>;
    if (edge.connection_type !== "s3") return edge;
    if (src === "sim-1" && tgt === "minio-g35" && String(cfg.tier_role ?? "") === "g35-cmx") {
      return {
        ...edge,
        id: id === "e-sim-g35" ? "e-gpu-g35" : edge.id,
        source: "gpu-server",
        source_handle: "group-bottom-out",
        target_handle: "cluster-in-top",
        label:
          typeof edge.label === "string" && edge.label
            ? edge.label
            : "MinIO AIStor · G3.5 CMX — low-latency shared context",
        protocol: (edge as { protocol?: string }).protocol || "NVMe-oF / RDMA",
        latency: (edge as { latency?: string }).latency || "~200-500 μs",
        bandwidth: (edge as { bandwidth?: string }).bandwidth || "800 Gb/s",
      };
    }
    if (src === "sim-1" && tgt === "minio-g4" && String(cfg.tier_role ?? "") === "g4-archive") {
      return {
        ...edge,
        id: id === "e-sim-g4" ? "e-gpu-g4" : edge.id,
        source: "gpu-server",
        source_handle: "group-bottom-out",
        target_handle: "cluster-in-top",
        label:
          typeof edge.label === "string" && edge.label && /archive|G4|enterprise/i.test(edge.label)
            ? edge.label
            : "MinIO AIStor · G4 — enterprise object storage",
        protocol: (edge as { protocol?: string }).protocol || "S3 over TCP",
        latency: (edge as { latency?: string }).latency || "~5-50 ms",
        bandwidth: (edge as { bandwidth?: string }).bandwidth || "100 Gb/s",
      };
    }
    if (tgt === "minio-g35" && String(edge.target_handle ?? "") === "data-in-top") {
      return { ...edge, target_handle: "cluster-in-top" };
    }
    if (
      tgt === "minio-g4" &&
      String(cfg.tier_role ?? "") === "g4-archive" &&
      String(edge.target_handle ?? "") === "data-in"
    ) {
      return { ...edge, target_handle: "cluster-in-top" };
    }
    return edge;
  });
}

const STX_G4_CLUSTER_LABEL = "MinIO AIStor (G4)";
const STX_G4_EDGE_LABEL_LONG = "MinIO AIStor · G4 — enterprise object storage";
const STX_G4_EDGE_LABEL_SHORT = "G4 storage";

/** Normalize legacy "G4 Archive" / "G4 archive storage" copy on load (persisted demos + old YAML). */
function migrateStxG4DisplayCopy(demo: Record<string, unknown>): Record<string, unknown> {
  let clusters = demo.clusters;
  if (Array.isArray(clusters)) {
    clusters = (clusters as Record<string, unknown>[]).map((c) => {
      if (c.id !== "minio-g4" || typeof c.label !== "string") return c;
      const lab = c.label as string;
      if (/archive|G4 only/i.test(lab)) return { ...c, label: STX_G4_CLUSTER_LABEL };
      return c;
    });
  }

  let edges = demo.edges;
  if (Array.isArray(edges)) {
    edges = (edges as Record<string, unknown>[]).map((e) => {
      if (String(e.target ?? "") !== "minio-g4") return e;
      const cfg = (e.connection_config || {}) as Record<string, unknown>;
      if (String(cfg.tier_role ?? "") !== "g4-archive") return e;
      if (typeof e.label !== "string" || !e.label) return e;
      const lab = e.label as string;
      if (!/archive|G4 only|G4 archive storage/i.test(lab)) return e;
      const looksLong = /MinIO|AIStor|enterprise/i.test(lab);
      return { ...e, label: looksLong ? STX_G4_EDGE_LABEL_LONG : STX_G4_EDGE_LABEL_SHORT };
    });
  }

  return { ...demo, ...(clusters !== undefined ? { clusters } : {}), ...(edges !== undefined ? { edges } : {}) };
}

export function migrateStxInferenceDemoGraphics<T extends Record<string, unknown>>(demo: T): T {
  if (!demo || demo.mode !== "experience") return demo;
  const nodes = demo.nodes as { component?: string }[] | undefined;
  if (!Array.isArray(nodes) || !nodes.some((n) => n?.component === "inference-sim")) {
    return demo;
  }

  const groups = Array.isArray(demo.groups)
    ? (demo.groups as Record<string, unknown>[]).map((g) => {
        if (g.id !== "gpu-server" || typeof g.label !== "string") return g;
        if (!LEGACY_GROUP_LABEL.test(g.label)) return g;
        return { ...g, label: "GPU Server — dual NVIDIA H100 SXM" };
      })
    : demo.groups;

  const schematics = Array.isArray(demo.schematics)
    ? alignStxGpuSchematicTops(
        (demo.schematics as Record<string, unknown>[]).map(migrateGpuSchematic)
      )
    : demo.schematics;

  const edges = Array.isArray(demo.edges) ? migrateStxGpuStorageEdges(demo.edges as unknown[]) : demo.edges;

  return migrateStxG4DisplayCopy({ ...demo, groups, schematics, edges } as Record<string, unknown>) as T;
}
