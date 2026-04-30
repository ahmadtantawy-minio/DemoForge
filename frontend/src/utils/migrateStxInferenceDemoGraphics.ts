/**
 * Upgrade persisted STX inference experience layouts from Vera Rubin / Rubin Ultra
 * naming through H100 SXM GPU A/B to **2× DGX H100** node schematics (matches
 * demo-templates/experience-stx-inference.yaml).
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
  if (/sch-(gpu|dgx)-a$/i.test(id) || /^GPU-A$/i.test(lab)) slot = "A";
  else if (/sch-(gpu|dgx)-b$/i.test(id) || /^GPU-B$/i.test(lab)) slot = "B";
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

/** Match tops of paired DGX/GPU schematics (legacy template had mismatched y). */
function alignStxGpuSchematicTops(schematics: Record<string, unknown>[]): Record<string, unknown>[] {
  const idsA = ["sch-dgx-a", "sch-gpu-a"];
  const idsB = ["sch-dgx-b", "sch-gpu-b"];
  const a = schematics.find((s) => idsA.includes(String(s.id)));
  const b = schematics.find((s) => idsB.includes(String(s.id)));
  if (!a || !b) return schematics;
  const posA = (a.position as { y?: number } | undefined) || {};
  const posB = (b.position as { y?: number } | undefined) || {};
  if (typeof posA.y !== "number" || typeof posB.y !== "number") return schematics;
  const y = Math.min(posA.y, posB.y);
  const alignIds = new Set([...idsA, ...idsB]);
  return schematics.map((s) => {
    if (!alignIds.has(String(s.id))) return s;
    const pos = (typeof s.position === "object" && s.position ? s.position : {}) as Record<string, unknown>;
    return { ...s, position: { ...pos, y } };
  });
}

const DGX_SCHEMATIC_CHILDREN_A = [
  { id: "g1a", label: "G1 — HBM3 (×8)", detail: "640 GB HBM class · per-GPU KV math ×8", color: "red" },
  { id: "g2a", label: "G2 — system DRAM", detail: "~4 TB aggregate · ~100 ns access", color: "amber" },
  { id: "g3a", label: "G3 — local NVMe", detail: "~32 TB aggregate · ~100 μs access", color: "blue" },
];
const DGX_SCHEMATIC_CHILDREN_B = [
  { id: "g1b", label: "G1 — HBM3 (×8)", detail: "640 GB HBM class · per-GPU KV math ×8", color: "red" },
  { id: "g2b", label: "G2 — system DRAM", detail: "~4 TB aggregate · ~100 ns access", color: "amber" },
  { id: "g3b", label: "G3 — local NVMe", detail: "~32 TB aggregate · ~100 μs access", color: "blue" },
];

/** Rename legacy sch-gpu-* to sch-dgx-* and refresh labels for 2×8 topology. */
function migrateSchGpuToDgxSchematics(schematics: Record<string, unknown>[]): Record<string, unknown>[] {
  return schematics.map((s) => {
    const id = String(s.id ?? "");
    if (id === "sch-gpu-a") {
      return {
        ...s,
        id: "sch-dgx-a",
        label: "DGX H100",
        sublabel: "Node A · 8× aggregate · NVLink",
        children: DGX_SCHEMATIC_CHILDREN_A,
      };
    }
    if (id === "sch-gpu-b") {
      return {
        ...s,
        id: "sch-dgx-b",
        label: "DGX H100",
        sublabel: "Node B · 8× aggregate · NVLink",
        children: DGX_SCHEMATIC_CHILDREN_B,
      };
    }
    return s;
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

function migrateStxInferenceSimNodeConfig(nodes: unknown[]): unknown[] {
  return nodes.map((raw) => {
    const n = raw as Record<string, unknown>;
    if (String(n.component ?? "") !== "inference-sim" || String(n.id ?? "") !== "sim-1") return n;
    const cfg = (
      typeof n.config === "object" && n.config ? { ...(n.config as Record<string, unknown>) } : {}
    ) as Record<string, unknown>;
    const gc = String(cfg.GPU_COUNT ?? "").trim();
    const hasNodeCount = cfg.NODE_COUNT != null && String(cfg.NODE_COUNT).trim().length > 0;
    if (gc === "2" && !hasNodeCount) {
      cfg.NODE_COUNT = "2";
      cfg.GPUS_PER_NODE = "8";
      cfg.REPLICA_COUNT = "8";
      cfg.GPU_COUNT = "16";
    }
    return { ...n, config: cfg };
  });
}

export function migrateStxInferenceDemoGraphics<T extends Record<string, unknown>>(demo: T): T {
  if (!demo || demo.mode !== "experience") return demo;
  const nodes = demo.nodes as { component?: string }[] | undefined;
  if (!Array.isArray(nodes) || !nodes.some((n) => n?.component === "inference-sim")) {
    return demo;
  }

  const migratedNodes = migrateStxInferenceSimNodeConfig(nodes as unknown[]);

  const groups = Array.isArray(demo.groups)
    ? (demo.groups as Record<string, unknown>[]).map((g) => {
        if (g.id !== "gpu-server" || typeof g.label !== "string") return g;
        const lab = g.label as string;
        if (LEGACY_GROUP_LABEL.test(lab)) {
          return { ...g, label: "STX rack — 2× NVIDIA DGX H100 (16 GPUs)" };
        }
        if (/GPU\s*Server|dual\s*NVIDIA\s*H100|dual\s*H100/i.test(lab)) {
          return { ...g, label: "STX rack — 2× NVIDIA DGX H100 (16 GPUs)" };
        }
        return g;
      })
    : demo.groups;

  const schematics = Array.isArray(demo.schematics)
    ? alignStxGpuSchematicTops(
        migrateSchGpuToDgxSchematics(
          (demo.schematics as Record<string, unknown>[]).map(migrateGpuSchematic)
        )
      )
    : demo.schematics;

  const edges = Array.isArray(demo.edges) ? migrateStxGpuStorageEdges(demo.edges as unknown[]) : demo.edges;

  return migrateStxG4DisplayCopy({
    ...demo,
    nodes: migratedNodes,
    groups,
    schematics,
    edges,
  } as Record<string, unknown>) as T;
}
