interface Step {
  name: string;
  ok: boolean;
  warn?: boolean;
  detail?: string;
}

interface CheckResult {
  label: string;
  description: string;
  ok: boolean;
  skipped?: boolean;
  warning?: boolean;
  optional?: boolean;
  error?: string;
  fa_id?: string;
  fa_name?: string;
  total_fas?: number;
  note?: string;
  steps?: Step[];
}

interface ConnectivityResult {
  overall: "ok" | "degraded";
  mode: string;
  hub_url: string;
  fa_id: string;
  fa_id_configured: boolean;
  api_key_configured: boolean;
  admin_key_configured: boolean | null;
  checks: Record<string, CheckResult>;
}

type NodeStatus = "ok" | "fail" | "warn" | "skip" | "idle";

interface NodeDef {
  id: string;
  label: string;
  sublabel?: string;
  x: number; // center x
  y: number; // center y
  status: NodeStatus;
  tooltip?: string;
  width?: number;
  height?: number;
}

interface EdgeDef {
  from: string;
  to: string;
  status: NodeStatus;
  label?: string;
}

const NODE_W = 140;
const NODE_H = 48;
const SMALL_W = 120;
const SMALL_H = 38;

const STATUS_STYLE: Record<NodeStatus, { border: string; fill: string; text: string; dot: string; edge: string }> = {
  ok:   { border: "#22c55e40", fill: "#22c55e0d", text: "#86efac", dot: "#22c55e", edge: "#22c55e" },
  fail: { border: "#ef444440", fill: "#ef44441a", text: "#fca5a5", dot: "#ef4444", edge: "#ef4444" },
  warn: { border: "#f59e0b40", fill: "#f59e0b0d", text: "#fcd34d", dot: "#f59e0b", edge: "#f59e0b" },
  skip: { border: "#52525240", fill: "#27272a33", text: "#71717a", dot: "#52525a", edge: "#52525a" },
  idle: { border: "#3f3f4640", fill: "#18181b40", text: "#52525a", dot: "#52525a", edge: "#3f3f46" },
};

function stepStatus(steps: Step[] | undefined, index: number): NodeStatus {
  if (!steps || steps.length <= index) return "idle";
  const s = steps[index];
  if (s.ok) return "ok";
  if (s.warn) return "warn";
  return "fail";
}

function checkStatus(check: CheckResult | undefined): NodeStatus {
  if (!check) return "idle";
  if (check.skipped) return "skip";
  if (check.ok) return "ok";
  if (check.warning) return "warn";
  if (check.optional) return "warn"; // optional failing = amber, not red
  return "fail";
}

function propagate(edges: EdgeDef[]): EdgeDef[] {
  let broken = false;
  return edges.map((e) => {
    if (broken) return { ...e, status: "idle" as NodeStatus };
    if (e.status === "fail") broken = true;
    return e;
  });
}

// Calculate connection point on box edge given source center and target center
function edgePoint(
  fromX: number,
  fromY: number,
  fromW: number,
  fromH: number,
  toX: number,
  toY: number,
): { x: number; y: number } {
  const dx = toX - fromX;
  const dy = toY - fromY;
  const halfW = fromW / 2;
  const halfH = fromH / 2;
  if (dx === 0 && dy === 0) return { x: fromX, y: fromY };
  const absDx = Math.abs(dx);
  const absDy = Math.abs(dy);
  // Determine which edge the line exits through
  const scaleX = absDx === 0 ? Infinity : halfW / absDx;
  const scaleY = absDy === 0 ? Infinity : halfH / absDy;
  const scale = Math.min(scaleX, scaleY);
  return { x: fromX + dx * scale, y: fromY + dy * scale };
}

function Node({ node }: { node: NodeDef }) {
  const style = STATUS_STYLE[node.status];
  const w = node.width ?? NODE_W;
  const h = node.height ?? NODE_H;
  const x = node.x - w / 2;
  const y = node.y - h / 2;
  const labelFontSize = node.width && node.width < NODE_W ? 10 : 11;
  const subFontSize = node.width && node.width < NODE_W ? 8 : 9;
  return (
    <g>
      {node.tooltip && <title>{node.tooltip}</title>}
      <rect
        x={x}
        y={y}
        width={w}
        height={h}
        rx={6}
        ry={6}
        fill={style.fill}
        stroke={style.border}
        strokeWidth={1}
      />
      <text
        x={node.x}
        y={node.y - (node.sublabel ? 2 : -3)}
        textAnchor="middle"
        fontSize={labelFontSize}
        fontWeight={500}
        fill={style.text}
      >
        {node.label}
      </text>
      {node.sublabel && (
        <text
          x={node.x}
          y={node.y + 12}
          textAnchor="middle"
          fontSize={subFontSize}
          fill="#71717a"
        >
          {node.sublabel}
        </text>
      )}
      <circle cx={x + w - 8} cy={y + 8} r={5} fill={style.dot} />
    </g>
  );
}

function Edge({
  edge,
  nodes,
}: {
  edge: EdgeDef;
  nodes: Record<string, NodeDef>;
}) {
  const from = nodes[edge.from];
  const to = nodes[edge.to];
  if (!from || !to) return null;
  const fromW = from.width ?? NODE_W;
  const fromH = from.height ?? NODE_H;
  const toW = to.width ?? NODE_W;
  const toH = to.height ?? NODE_H;
  const start = edgePoint(from.x, from.y, fromW, fromH, to.x, to.y);
  const end = edgePoint(to.x, to.y, toW, toH, from.x, from.y);
  const style = STATUS_STYLE[edge.status];
  const isIdle = edge.status === "idle";
  const isFail = edge.status === "fail";
  const strokeDasharray = isIdle ? "4 4" : isFail ? "6 4" : undefined;
  const strokeWidth = isIdle ? 1 : 1.5;
  const markerId = `arrow-${edge.status}`;
  const midX = (start.x + end.x) / 2;
  const midY = (start.y + end.y) / 2;
  const showLabel = (isFail || edge.status === "warn") && edge.label;
  return (
    <g>
      <line
        x1={start.x}
        y1={start.y}
        x2={end.x}
        y2={end.y}
        stroke={style.edge}
        strokeWidth={strokeWidth}
        strokeDasharray={strokeDasharray}
        markerEnd={`url(#${markerId})`}
        className={isFail ? "edge-broken" : undefined}
      />
      {showLabel && (
        <text
          x={midX}
          y={midY - 4}
          textAnchor="middle"
          fontSize={8}
          fill={style.text}
        >
          {edge.label}
        </text>
      )}
    </g>
  );
}

function ArrowMarkers() {
  const statuses: NodeStatus[] = ["ok", "fail", "warn", "skip", "idle"];
  return (
    <defs>
      {statuses.map((s) => (
        <marker
          key={s}
          id={`arrow-${s}`}
          viewBox="0 0 10 6"
          refX="8"
          refY="3"
          markerWidth="8"
          markerHeight="6"
          orient="auto-start-reverse"
        >
          <path d="M 0 0 L 10 3 L 0 6 z" fill={STATUS_STYLE[s].edge} />
        </marker>
      ))}
    </defs>
  );
}

function buildFaDiagram(result: ConnectivityResult): {
  nodes: NodeDef[];
  edges: EdgeDef[];
  viewBox: string;
} {
  const checks = result.checks;
  const faAuth = checks.fa_auth;
  const steps = faAuth?.steps;

  // steps[0] = API key configured, steps[1] = Hub gateway reachable, steps[2] = FA identity validated
  const eConnect = stepStatus(steps, 1);   // fa_pc → gateway
  const eRoute   = stepStatus(steps, 1);   // gateway → hub_api / minio
  const eFaAuth  = checkStatus(faAuth);

  const rawEdges: EdgeDef[] = [
    { from: "fa_pc",   to: "gateway",  status: eConnect },
    { from: "gateway", to: "hub_api",  status: eRoute },
    { from: "gateway", to: "minio",    status: eRoute },
    { from: "gateway", to: "fa_auth",  status: eFaAuth, label: faAuth?.error },
  ];

  const edges = propagate(rawEdges);

  const gatewayStatus: NodeStatus = edges[0].status;
  const hubApiStatus:  NodeStatus = edges[1].status;
  const minioStatus:   NodeStatus = edges[2].status;
  const faAuthStatus:  NodeStatus = edges[3].status;

  const nodes: NodeDef[] = [
    { id: "fa_pc",   label: "FA Laptop",        sublabel: "your machine",       x: 80,  y: 120, status: "ok" },
    { id: "gateway", label: "GCP Gateway",       sublabel: "Cloud Run",          x: 300, y: 120, status: gatewayStatus, tooltip: steps?.[1]?.detail },
    { id: "hub_api", label: "Hub API",           sublabel: ":8000 on VM",        x: 520, y: 55,  status: hubApiStatus },
    { id: "minio",   label: "MinIO / Registry",  sublabel: "VM storage",         x: 520, y: 175, status: minioStatus },
    { id: "fa_auth", label: "FA Auth",           sublabel: faAuth?.fa_name || "identity check", x: 520, y: 270, status: faAuthStatus, tooltip: faAuth?.error || faAuth?.description },
  ];

  return { nodes, edges, viewBox: "0 0 640 310" };
}

function buildDevDiagram(result: ConnectivityResult): {
  nodes: NodeDef[];
  edges: EdgeDef[];
  viewBox: string;
} {
  const checks = result.checks;
  const localHub = checks.local_hub_api;
  const faAuth = checks.fa_auth;
  const adminKey = checks.admin_key;

  const eDevLocal = checkStatus(localHub);
  const eLocalAuth = checkStatus(faAuth);
  const eAdmin = checkStatus(adminKey);

  // dev-start (local hub-api): Dev Machine → Local Hub → FA Auth / Admin Key
  // dev-start-gcp (no local hub): Dev Machine → GCP Gateway → FA Auth / Admin Key
  if (localHub) {
    const localBranch = propagate([
      { from: "dev_pc", to: "local_hub", status: eDevLocal, label: localHub?.error },
      { from: "local_hub", to: "fa_auth", status: faAuth?.optional && eLocalAuth === "fail" ? "warn" : eLocalAuth },
    ]);
    const adminBranch: EdgeDef[] = [{ from: "local_hub", to: "admin_key", status: eAdmin }];
    const edges = [...localBranch, ...adminBranch];

    const nodes: NodeDef[] = [
      { id: "dev_pc",    label: "Dev Machine",   sublabel: "localhost",   x: 80,  y: 130, status: "ok" },
      { id: "local_hub", label: "Local Hub API", sublabel: ":8000",       x: 300, y: 90,  status: localBranch[0].status, tooltip: localHub?.description },
      { id: "fa_auth",   label: "FA Auth",       sublabel: faAuth?.fa_name || "identity check", x: 510, y: 50, status: localBranch[1].status, tooltip: faAuth?.description },
      { id: "admin_key", label: "Admin Key",     sublabel: "hub admin",   x: 510, y: 170, status: adminBranch[0].status, tooltip: adminKey?.description, width: SMALL_W, height: SMALL_H },
    ];
    return { nodes, edges, viewBox: "0 0 640 230" };
  }

  // dev-gcp: direct gateway path (fa_auth steps carry gateway reachability)
  const faSteps = faAuth?.steps;
  const eGateway = stepStatus(faSteps, 1); // "Hub gateway reachable"
  const gwBranch = propagate([
    { from: "dev_pc",  to: "gateway",  status: eGateway },
    { from: "gateway", to: "fa_auth",  status: eLocalAuth },
    { from: "gateway", to: "admin_key", status: eAdmin },
  ]);

  const nodes: NodeDef[] = [
    { id: "dev_pc",    label: "Dev Machine", sublabel: "localhost",  x: 80,  y: 110, status: "ok" },
    { id: "gateway",   label: "GCP Gateway", sublabel: "Cloud Run",  x: 300, y: 110, status: gwBranch[0].status, tooltip: faSteps?.[1]?.detail },
    { id: "fa_auth",   label: "FA Auth",     sublabel: faAuth?.fa_name || "identity check", x: 510, y: 55, status: gwBranch[1].status, tooltip: faAuth?.description },
    { id: "admin_key", label: "Admin Key",   sublabel: "hub admin",  x: 510, y: 170, status: gwBranch[2].status, tooltip: adminKey?.description, width: SMALL_W, height: SMALL_H },
  ];
  return { nodes, edges: gwBranch, viewBox: "0 0 640 220" };
}

export function ConnectivityDiagram({ result }: { result: ConnectivityResult }) {
  const { nodes, edges, viewBox } =
    result.mode === "dev" ? buildDevDiagram(result) : buildFaDiagram(result);

  const nodeMap: Record<string, NodeDef> = {};
  for (const n of nodes) nodeMap[n.id] = n;

  return (
    <svg
      viewBox={viewBox}
      width="100%"
      style={{ maxWidth: "760px", height: "auto", display: "block" }}
      xmlns="http://www.w3.org/2000/svg"
    >
      <style>{`
        @keyframes dash {
          to { stroke-dashoffset: -20; }
        }
        .edge-broken { animation: dash 1.2s linear infinite; }
      `}</style>
      <ArrowMarkers />
      {edges.map((e, i) => (
        <Edge key={`${e.from}-${e.to}-${i}`} edge={e} nodes={nodeMap} />
      ))}
      {nodes.map((n) => (
        <Node key={n.id} node={n} />
      ))}
    </svg>
  );
}
