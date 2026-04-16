interface ComponentIconProps {
  icon: string;
  size?: number;
  className?: string;
}

function MinIOIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="32" height="32" rx="4" fill="#1F1F1F" />
      {/* MinIO brand "M" in red */}
      <path
        d="M7 25V8L16 19L25 8V25H21V16L16 22.5L11 16V25H7Z"
        fill="#C72C48"
      />
    </svg>
  );
}

function NGINXIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="32" height="32" rx="4" fill="#009639" />
      <polygon points="16,5 27,11 27,21 16,27 5,21 5,11" fill="#009639" stroke="white" strokeWidth="1.5" />
      <text x="50%" y="55%" dominantBaseline="middle" textAnchor="middle" fill="white" fontSize="11" fontWeight="bold" fontFamily="Arial, sans-serif">N</text>
    </svg>
  );
}

function PrometheusIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="32" height="32" rx="4" fill="#E6522C" />
      <circle cx="16" cy="14" r="7" fill="none" stroke="white" strokeWidth="2" />
      <circle cx="16" cy="14" r="3" fill="white" />
      <rect x="15" y="21" width="2" height="5" fill="white" />
      <rect x="11" y="25" width="10" height="2" fill="white" />
    </svg>
  );
}

function GrafanaIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="32" height="32" rx="4" fill="#F46800" />
      <path
        d="M16 7 A9 9 0 1 1 7.5 22"
        stroke="white"
        strokeWidth="2.5"
        strokeLinecap="round"
        fill="none"
      />
      <circle cx="16" cy="16" r="3" fill="white" />
    </svg>
  );
}

function FileGeneratorIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="32" height="32" rx="4" fill="#0891B2" />
      <path d="M10 7h8l5 5v13a2 2 0 01-2 2H10a2 2 0 01-2-2V9a2 2 0 012-2z" stroke="white" strokeWidth="1.5" fill="none" />
      <path d="M18 7v5h5" stroke="white" strokeWidth="1.5" />
      <path d="M12 18l2 2 4-4" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function DataGeneratorIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="32" height="32" rx="4" fill="#059669" />
      {/* Table grid: header row + two data rows, three columns */}
      <rect x="5" y="7" width="22" height="5" rx="1" fill="white" opacity="0.95" />
      <rect x="5" y="14" width="22" height="4" rx="1" fill="white" opacity="0.55" />
      <rect x="5" y="20" width="22" height="4" rx="1" fill="white" opacity="0.35" />
      {/* Column dividers */}
      <line x1="12" y1="7" x2="12" y2="24" stroke="#059669" strokeWidth="1" />
      <line x1="20" y1="7" x2="20" y2="24" stroke="#059669" strokeWidth="1" />
    </svg>
  );
}

function S3FileBrowserIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="32" height="32" rx="4" fill="#7C3AED" />
      {/* Folder body */}
      <path d="M5 12a2 2 0 012-2h5l2 2h11a2 2 0 012 2v9a2 2 0 01-2 2H7a2 2 0 01-2-2V12z" fill="none" stroke="white" strokeWidth="1.5" />
      {/* Magnifying glass */}
      <circle cx="20" cy="19" r="3.5" stroke="white" strokeWidth="1.5" fill="none" />
      <line x1="22.5" y1="21.5" x2="25" y2="24" stroke="white" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function IcebergIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="32" height="32" rx="4" fill="#1565C0" />
      {/* Iceberg shape: triangle top + wider base below waterline */}
      <polygon points="16,5 21,16 11,16" fill="white" />
      <polygon points="10,17 22,17 25,27 7,27" fill="white" opacity="0.6" />
      <line x1="6" y1="16.5" x2="26" y2="16.5" stroke="white" strokeWidth="0.8" strokeDasharray="2 1" />
    </svg>
  );
}

function TrinoIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="32" height="32" rx="4" fill="#DD00A1" />
      {/* Prism / triangle shape */}
      <polygon points="16,5 27,25 5,25" fill="none" stroke="white" strokeWidth="2" strokeLinejoin="round" />
      <text x="50%" y="72%" dominantBaseline="middle" textAnchor="middle" fill="white" fontSize="10" fontWeight="bold" fontFamily="Arial, sans-serif">T</text>
    </svg>
  );
}

function ClickHouseIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="32" height="32" rx="4" fill="#FFCC00" />
      {/* Column chart bars representing columnar storage */}
      <rect x="6" y="16" width="4" height="10" rx="1" fill="#1F1F1F" />
      <rect x="12" y="10" width="4" height="16" rx="1" fill="#1F1F1F" />
      <rect x="18" y="13" width="4" height="13" rx="1" fill="#1F1F1F" />
      <rect x="24" y="7" width="4" height="19" rx="1" fill="#1F1F1F" />
    </svg>
  );
}

function SparkIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="32" height="32" rx="4" fill="#e65100" />
      {/* Lightning bolt */}
      <path
        d="M18 5L10 18h7l-3 9 12-15h-8l2-7z"
        fill="white"
      />
    </svg>
  );
}

function HDFSIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="32" height="32" rx="4" fill="#ff6b35" />
      <circle cx="16" cy="16" r="9" fill="none" stroke="white" strokeWidth="2" />
      <text x="50%" y="56%" dominantBaseline="middle" textAnchor="middle" fill="white" fontSize="12" fontWeight="bold" fontFamily="Arial, sans-serif">H</text>
    </svg>
  );
}

function DremioIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="32" height="32" rx="4" fill="#00BFA5" />
      {/* Dremio swoosh: a bold "D" shape with a curved cutout suggesting speed/query */}
      <path d="M9 7h6c5 0 8 3.5 8 9s-3 9-8 9H9V7z" fill="white" />
      <path d="M13 11h2c2.5 0 4 1.8 4 5s-1.5 5-4 5h-2V11z" fill="#00BFA5" />
    </svg>
  );
}

function RedpandaIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="32" height="32" rx="4" fill="#DC382D" />
      {/* Stylized panda face: round head with two ear bumps */}
      {/* Ears */}
      <circle cx="10" cy="10" r="4" fill="#DC382D" stroke="white" strokeWidth="1.5" />
      <circle cx="22" cy="10" r="4" fill="#DC382D" stroke="white" strokeWidth="1.5" />
      {/* Face */}
      <circle cx="16" cy="18" r="8" fill="white" />
      {/* Eye patches */}
      <ellipse cx="13" cy="16.5" rx="2.2" ry="2.5" fill="#DC382D" />
      <ellipse cx="19" cy="16.5" rx="2.2" ry="2.5" fill="#DC382D" />
      {/* Eyes */}
      <circle cx="13" cy="16.5" r="1" fill="white" />
      <circle cx="19" cy="16.5" r="1" fill="white" />
      {/* Nose */}
      <ellipse cx="16" cy="20" rx="1.5" ry="1" fill="#DC382D" />
    </svg>
  );
}

function NessieIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="32" height="32" rx="4" fill="#4CAF50" />
      {/* Git branching: a trunk that forks into two paths */}
      {/* Main stem */}
      <line x1="16" y1="26" x2="16" y2="18" stroke="white" strokeWidth="2.5" strokeLinecap="round" />
      {/* Branch fork */}
      <path d="M16 18 Q16 14 10 10" stroke="white" strokeWidth="2.5" strokeLinecap="round" fill="none" />
      <path d="M16 18 Q16 14 22 10" stroke="white" strokeWidth="2.5" strokeLinecap="round" fill="none" />
      {/* Commit nodes */}
      <circle cx="10" cy="10" r="3" fill="white" />
      <circle cx="22" cy="10" r="3" fill="white" />
      <circle cx="16" cy="26" r="3" fill="white" />
    </svg>
  );
}

function KafkaConnectIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="32" height="32" rx="4" fill="#FF6D00" />
      {/* Two nodes connected by a line — connector metaphor */}
      {/* Left node: filled circle */}
      <circle cx="8" cy="16" r="4" fill="white" />
      {/* Right node: filled circle */}
      <circle cx="24" cy="16" r="4" fill="white" />
      {/* Connection line with arrow */}
      <line x1="12" y1="16" x2="20" y2="16" stroke="white" strokeWidth="2" strokeLinecap="round" />
      {/* Arrow head pointing right */}
      <path d="M18 13l4 3-4 3" fill="none" stroke="white" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      {/* Center plug indicator */}
      <circle cx="16" cy="16" r="1.5" fill="#FF6D00" />
    </svg>
  );
}

function MLflowIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="32" height="32" rx="4" fill="#0194E2" />
      {/* MLflow logo: a stylized flow/wave with an "ML" suggestion */}
      {/* Three horizontal bars tapering like a flow chart */}
      <rect x="5" y="8" width="14" height="4" rx="2" fill="white" />
      <rect x="5" y="14" width="20" height="4" rx="2" fill="white" opacity="0.85" />
      <rect x="5" y="20" width="11" height="4" rx="2" fill="white" opacity="0.65" />
      {/* Arrow indicating flow direction */}
      <path d="M22 21l4-3-4-3" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function AirflowIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="32" height="32" rx="4" fill="#017CEE" />
      {/* Airflow DAG: three nodes with directed edges */}
      {/* Top-left node */}
      <circle cx="8" cy="12" r="3.5" fill="white" />
      {/* Top-right node */}
      <circle cx="24" cy="12" r="3.5" fill="white" />
      {/* Bottom-center node */}
      <circle cx="16" cy="24" r="3.5" fill="white" />
      {/* Edges */}
      <line x1="11" y1="13" x2="21" y2="13" stroke="white" strokeWidth="1.5" strokeLinecap="round" />
      <line x1="10" y1="15" x2="14" y2="21" stroke="white" strokeWidth="1.5" strokeLinecap="round" />
      <line x1="22" y1="15" x2="18" y2="21" stroke="white" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function LabelStudioIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="32" height="32" rx="4" fill="#FF5733" />
      {/* Annotation/label tag shape */}
      <path d="M7 10h12l5 6-5 6H7V10z" fill="none" stroke="white" strokeWidth="2" strokeLinejoin="round" />
      {/* Label dot */}
      <circle cx="13" cy="16" r="2" fill="white" />
    </svg>
  );
}

function JupyterLabIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="32" height="32" rx="4" fill="#F37626" />
      {/* Jupyter logo: three orbital dots around a center */}
      {/* Large center circle */}
      <circle cx="16" cy="16" r="5" fill="white" />
      {/* Three orbital dots */}
      <circle cx="16" cy="5" r="2.5" fill="white" />
      <circle cx="6" cy="24" r="2.5" fill="white" />
      <circle cx="26" cy="24" r="2.5" fill="white" />
    </svg>
  );
}

function OllamaIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="32" height="32" rx="4" fill="#1a1a2e" />
      {/* Simplified llama head: readable at small sizes */}
      {/* Body/torso */}
      <rect x="10" y="16" width="12" height="11" rx="3" fill="white" opacity="0.9" />
      {/* Head */}
      <circle cx="16" cy="12" r="6" fill="white" />
      {/* Two ear bumps on top */}
      <circle cx="12" cy="7" r="2.5" fill="white" />
      <circle cx="20" cy="7" r="2.5" fill="white" />
      {/* Eyes */}
      <circle cx="14" cy="12" r="1.2" fill="#1a1a2e" />
      <circle cx="18" cy="12" r="1.2" fill="#1a1a2e" />
    </svg>
  );
}

function LiteLLMIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="32" height="32" rx="4" fill="#6366F1" />
      {/* LLM gateway: stacked layers suggesting model abstraction */}
      <rect x="6" y="7" width="20" height="5" rx="2.5" fill="white" />
      <rect x="6" y="14" width="20" height="5" rx="2.5" fill="white" opacity="0.7" />
      <rect x="6" y="21" width="20" height="5" rx="2.5" fill="white" opacity="0.4" />
      {/* Router arrow on left side */}
      <path d="M3 16l3-3v6l-3-3z" fill="white" />
    </svg>
  );
}

function EtcdIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="32" height="32" rx="4" fill="#419EDA" />
      {/* etcd: distributed key-value — three nodes in a ring */}
      <circle cx="16" cy="7" r="3.5" fill="white" />
      <circle cx="7" cy="23" r="3.5" fill="white" />
      <circle cx="25" cy="23" r="3.5" fill="white" />
      {/* Connection lines between nodes */}
      <line x1="13" y1="9" x2="9.5" y2="20" stroke="white" strokeWidth="1.5" strokeLinecap="round" />
      <line x1="19" y1="9" x2="22.5" y2="20" stroke="white" strokeWidth="1.5" strokeLinecap="round" />
      <line x1="10.5" y1="23" x2="21.5" y2="23" stroke="white" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function MilvusIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="32" height="32" rx="4" fill="#00A1EA" />
      {/* Vector database: a grid of dots suggesting embedding space */}
      <circle cx="9" cy="9" r="2" fill="white" />
      <circle cx="16" cy="9" r="2" fill="white" />
      <circle cx="23" cy="9" r="2" fill="white" />
      <circle cx="9" cy="16" r="2" fill="white" opacity="0.7" />
      <circle cx="16" cy="16" r="2.5" fill="white" />
      <circle cx="23" cy="16" r="2" fill="white" opacity="0.7" />
      <circle cx="9" cy="23" r="2" fill="white" opacity="0.4" />
      <circle cx="16" cy="23" r="2" fill="white" opacity="0.7" />
      <circle cx="23" cy="23" r="2" fill="white" opacity="0.4" />
      {/* Highlight lines from center suggesting nearest-neighbor search */}
      <line x1="16" y1="16" x2="9" y2="9" stroke="white" strokeWidth="1" strokeDasharray="2 1.5" opacity="0.6" />
      <line x1="16" y1="16" x2="23" y2="9" stroke="white" strokeWidth="1" strokeDasharray="2 1.5" opacity="0.6" />
    </svg>
  );
}

function RedpandaConsoleIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="32" height="32" rx="4" fill="#a01f1a" />
      {/* Console: terminal with a stream of messages */}
      <rect x="5" y="7" width="22" height="18" rx="2" fill="none" stroke="white" strokeWidth="1.5" />
      <line x1="9" y1="12" x2="23" y2="12" stroke="white" strokeWidth="1.2" strokeLinecap="round" opacity="0.9" />
      <line x1="9" y1="16" x2="19" y2="16" stroke="white" strokeWidth="1.2" strokeLinecap="round" opacity="0.7" />
      <line x1="9" y1="20" x2="21" y2="20" stroke="white" strokeWidth="1.2" strokeLinecap="round" opacity="0.5" />
      {/* Blinking cursor */}
      <rect x="9" y="22.5" width="4" height="1.5" rx="0.5" fill="white" />
    </svg>
  );
}

function SupersetIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="32" height="32" rx="4" fill="#20A7C9" />
      {/* Official Apache Superset "S" — two overlapping arcs */}
      <path
        d="M20.5 9C18.0 9 16 11.0 16 13.5C16 15.4 17.1 17.0 18.7 17.7C17.6 18.1 16.9 19.1 16.9 20.2C16.9 21.6 18.0 22.8 19.4 23H12.5C11.1 23 10 21.9 10 20.5C10 19.1 11.1 18 12.5 18H15C17.5 18 19.5 16.0 19.5 13.5C19.5 11.0 17.5 9 15 9H20.5Z"
        fill="white"
        opacity="0.15"
      />
      {/* Top arc (upper lobe of S) */}
      <path
        d="M13 10.5 C13 10.5 14.5 9 17 9 C19.5 9 21.5 11 21.5 13.5 C21.5 16 19.5 18 17 18 L15 18 C13.3 18 12 19.3 12 21 C12 22.7 13.3 24 15 24 C15 24 13.5 24 12 23.5"
        stroke="white"
        strokeWidth="2.2"
        strokeLinecap="round"
        fill="none"
      />
      {/* Bottom arc (lower lobe of S) */}
      <path
        d="M19 21.5 C19 21.5 17.5 23 15 23 C12.5 23 10.5 21 10.5 18.5 C10.5 16 12.5 14 15 14 L17 14 C18.7 14 20 12.7 20 11 C20 9.3 18.7 8 17 8 C17 8 18.5 8 20 8.5"
        stroke="white"
        strokeWidth="2.2"
        strokeLinecap="round"
        fill="none"
      />
    </svg>
  );
}

function MetabaseIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="32" height="32" rx="4" fill="#509EE3" />
      {/* Bar chart with a trend line — Metabase analytics */}
      <rect x="6" y="20" width="4" height="6" rx="1" fill="white" />
      <rect x="12" y="14" width="4" height="12" rx="1" fill="white" />
      <rect x="18" y="17" width="4" height="9" rx="1" fill="white" />
      <rect x="24" y="10" width="4" height="16" rx="1" fill="white" opacity="0.7" />
      {/* Trend line */}
      <path d="M8 19 L14 13 L20 16 L26 9" stroke="white" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" fill="none" opacity="0.9" />
    </svg>
  );
}

function QdrantIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="32" height="32" rx="4" fill="#DC244C" />
      {/* Qdrant: a hexagon (their logo shape) */}
      <polygon
        points="16,5 25,10 25,22 16,27 7,22 7,10"
        fill="none"
        stroke="white"
        strokeWidth="2"
        strokeLinejoin="round"
      />
      {/* Inner dot */}
      <circle cx="16" cy="16" r="3.5" fill="white" />
    </svg>
  );
}

function RAGAppIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="32" height="32" rx="4" fill="#7C3AED" />
      {/* Document with magnifier overlay — retrieval-augmented generation */}
      {/* Document */}
      <rect x="5" y="6" width="14" height="18" rx="2" fill="none" stroke="white" strokeWidth="1.8" />
      <line x1="8" y1="11" x2="16" y2="11" stroke="white" strokeWidth="1.3" strokeLinecap="round" opacity="0.8" />
      <line x1="8" y1="15" x2="14" y2="15" stroke="white" strokeWidth="1.3" strokeLinecap="round" opacity="0.8" />
      {/* Magnifying glass overlaid bottom-right */}
      <circle cx="21" cy="21" r="5" fill="#7C3AED" stroke="white" strokeWidth="2" />
      <line x1="24.5" y1="24.5" x2="27" y2="27" stroke="white" strokeWidth="2.2" strokeLinecap="round" />
    </svg>
  );
}

function MLTrainerIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="32" height="32" rx="4" fill="#059669" />
      {/* Neural network: 2-3-2 layer diagram */}
      {/* Input layer */}
      <circle cx="7" cy="12" r="2.5" fill="white" />
      <circle cx="7" cy="20" r="2.5" fill="white" />
      {/* Hidden layer */}
      <circle cx="16" cy="9" r="2.5" fill="white" />
      <circle cx="16" cy="16" r="2.5" fill="white" />
      <circle cx="16" cy="23" r="2.5" fill="white" />
      {/* Output layer */}
      <circle cx="25" cy="12" r="2.5" fill="white" />
      <circle cx="25" cy="20" r="2.5" fill="white" />
      {/* Connections (input to hidden) */}
      <line x1="9.5" y1="12" x2="13.5" y2="10" stroke="white" strokeWidth="0.8" opacity="0.5" />
      <line x1="9.5" y1="12" x2="13.5" y2="16" stroke="white" strokeWidth="0.8" opacity="0.5" />
      <line x1="9.5" y1="20" x2="13.5" y2="16" stroke="white" strokeWidth="0.8" opacity="0.5" />
      <line x1="9.5" y1="20" x2="13.5" y2="23" stroke="white" strokeWidth="0.8" opacity="0.5" />
      {/* Connections (hidden to output) */}
      <line x1="18.5" y1="10" x2="22.5" y2="12" stroke="white" strokeWidth="0.8" opacity="0.5" />
      <line x1="18.5" y1="16" x2="22.5" y2="12" stroke="white" strokeWidth="0.8" opacity="0.5" />
      <line x1="18.5" y1="16" x2="22.5" y2="20" stroke="white" strokeWidth="0.8" opacity="0.5" />
      <line x1="18.5" y1="23" x2="22.5" y2="20" stroke="white" strokeWidth="0.8" opacity="0.5" />
    </svg>
  );
}

function InferenceClientIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="32" height="32" rx="4" fill="#1a1a2e" />
      {/* Terminal/client icon */}
      <rect x="6" y="8" width="20" height="16" rx="2" stroke="#76b900" strokeWidth="1.5" fill="none" />
      <text x="16" y="19" textAnchor="middle" fill="#76b900" fontSize="8" fontWeight="bold" fontFamily="monospace">&gt;_</text>
    </svg>
  );
}

function InferenceSimIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="32" height="32" rx="4" fill="#1a1a2e" />
      {/* GPU chip outline */}
      <rect x="8" y="8" width="16" height="16" rx="2" stroke="#76b900" strokeWidth="1.5" fill="#76b900" fillOpacity="0.15" />
      {/* Memory tier bars */}
      <rect x="10" y="10" width="12" height="2" rx="0.5" fill="#ef4444" opacity="0.9" />
      <rect x="10" y="13.5" width="10" height="2" rx="0.5" fill="#f97316" opacity="0.9" />
      <rect x="10" y="17" width="8" height="2" rx="0.5" fill="#eab308" opacity="0.9" />
      <rect x="10" y="20.5" width="12" height="2" rx="0.5" fill="#22c55e" opacity="0.9" />
      {/* NVIDIA green accent */}
      <line x1="6" y1="16" x2="8" y2="16" stroke="#76b900" strokeWidth="1.5" strokeLinecap="round" />
      <line x1="24" y1="16" x2="26" y2="16" stroke="#76b900" strokeWidth="1.5" strokeLinecap="round" />
      <line x1="16" y1="6" x2="16" y2="8" stroke="#76b900" strokeWidth="1.5" strokeLinecap="round" />
      <line x1="16" y1="24" x2="16" y2="26" stroke="#76b900" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function SolaceIcon({ size }: { size: number }) {
  // Solace brand green #00BF6F, stylised S-curve mark
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="32" height="32" rx="4" fill="#00BF6F" />
      {/* Upper arc: curves right from top-left to mid */}
      <path d="M10 9 C10 9 22 9 22 13 C22 17 10 15 10 19 C10 23 22 23 22 23" stroke="white" strokeWidth="3" strokeLinecap="round" fill="none" />
    </svg>
  );
}

function KongIcon({ size }: { size: number }) {
  // Official Kong icon from Simple Icons (viewBox 0 0 24 24), scaled to 32×32
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="24" height="24" rx="3" fill="#003459" />
      <path d="M7.88 18.96h4.405l2.286 2.876-.393.979h-5.69l.139-.979-1.341-2.117.594-.759Zm3.152-12.632 2.36-.004L24 18.97l-.824 3.845h-4.547l.283-1.083L9 9.912l2.032-3.584Zm4.17-5.144 4.932 3.876-.632.651.855 1.191v1.273l-2.458 2.004-4.135-4.884h-2.407l.969-1.777 2.876-2.334ZM4.852 13.597l3.44-2.989 4.565 5.494-1.296 2.012h-4.21l-2.912 3.822-.665.879H0v-4.689l3.517-4.529h1.335Z" fill="white" />
    </svg>
  );
}

function EventBridgeIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="32" height="32" rx="4" fill="#0E7490" />
      {/* Bridge / relay arrows */}
      <path d="M5 16h8" stroke="white" strokeWidth="2" strokeLinecap="round" />
      <path d="M19 16h8" stroke="white" strokeWidth="2" strokeLinecap="round" />
      <rect x="12" y="11" width="8" height="10" rx="2" fill="white" opacity="0.9" />
      <path d="M16 14v4M14 16l2-2 2 2" stroke="#0E7490" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function EventProducerIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="32" height="32" rx="4" fill="#7C3AED" />
      {/* Broadcast / emit waves */}
      <circle cx="12" cy="16" r="2.5" fill="white" />
      <path d="M16 10 A8 8 0 0 1 16 22" stroke="white" strokeWidth="1.8" strokeLinecap="round" fill="none" />
      <path d="M19 7 A12 12 0 0 1 19 25" stroke="white" strokeWidth="1.5" strokeLinecap="round" fill="none" opacity="0.6" />
      <path d="M13.5 16 L26 16" stroke="white" strokeWidth="1.5" strokeLinecap="round" />
      <path d="M23 13 L26 16 L23 19" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function ExternalSystemIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="32" height="32" rx="4" fill="#475569" />
      {/* Building outline */}
      <rect x="7" y="10" width="18" height="16" rx="1" stroke="white" strokeWidth="1.5" fill="none" />
      {/* Roof / top bar */}
      <rect x="7" y="10" width="18" height="3" rx="1" fill="white" opacity="0.9" />
      {/* Windows row 1 */}
      <rect x="10" y="16" width="3" height="3" rx="0.5" fill="white" opacity="0.85" />
      <rect x="14.5" y="16" width="3" height="3" rx="0.5" fill="white" opacity="0.85" />
      <rect x="19" y="16" width="3" height="3" rx="0.5" fill="white" opacity="0.85" />
      {/* Windows row 2 */}
      <rect x="10" y="21" width="3" height="3" rx="0.5" fill="white" opacity="0.6" />
      <rect x="14.5" y="21" width="3" height="3" rx="0.5" fill="white" opacity="0.6" />
      <rect x="19" y="21" width="3" height="3" rx="0.5" fill="white" opacity="0.6" />
    </svg>
  );
}

function DefaultIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="32" height="32" rx="4" fill="#6B7280" />
      <rect x="8" y="8" width="16" height="16" rx="2" stroke="white" strokeWidth="2" fill="none" />
      <line x1="12" y1="14" x2="20" y2="14" stroke="white" strokeWidth="1.5" strokeLinecap="round" />
      <line x1="12" y1="18" x2="18" y2="18" stroke="white" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

export default function ComponentIcon({ icon, size = 24, className }: ComponentIconProps) {
  const id = icon.toLowerCase();

  const svgIcon = (() => {
    if (id.includes("minio")) return <MinIOIcon size={size} />;
    if (id.includes("nginx")) return <NGINXIcon size={size} />;
    if (id.includes("prometheus")) return <PrometheusIcon size={size} />;
    if (id.includes("grafana")) return <GrafanaIcon size={size} />;
    if (id.includes("data-generator") || id.includes("data-gen")) return <DataGeneratorIcon size={size} />;
    if (id.includes("file-generator")) return <FileGeneratorIcon size={size} />;
    if (id.includes("s3-file-browser") || id.includes("s3-browser")) return <S3FileBrowserIcon size={size} />;
    if (id.includes("iceberg")) return <IcebergIcon size={size} />;
    if (id.includes("trino")) return <TrinoIcon size={size} />;
    if (id.includes("clickhouse")) return <ClickHouseIcon size={size} />;
    if (id.includes("spark")) return <SparkIcon size={size} />;
    if (id.includes("hdfs")) return <HDFSIcon size={size} />;
    if (id.includes("dremio")) return <DremioIcon size={size} />;
    if (id.includes("redpanda-console") || id.includes("redpanda_console")) return <RedpandaConsoleIcon size={size} />;
    if (id.includes("redpanda")) return <RedpandaIcon size={size} />;
    if (id.includes("nessie")) return <NessieIcon size={size} />;
    if (id.includes("kafka-connect") || id.includes("kafka_connect")) return <KafkaConnectIcon size={size} />;
    if (id.includes("mlflow") || id === "ml-flow") return <MLflowIcon size={size} />;
    if (id.includes("airflow")) return <AirflowIcon size={size} />;
    if (id.includes("label-studio") || id.includes("label_studio")) return <LabelStudioIcon size={size} />;
    if (id.includes("jupyter")) return <JupyterLabIcon size={size} />;
    if (id.includes("ollama")) return <OllamaIcon size={size} />;
    if (id.includes("litellm")) return <LiteLLMIcon size={size} />;
    if (id.includes("etcd")) return <EtcdIcon size={size} />;
    if (id.includes("milvus")) return <MilvusIcon size={size} />;
    if (id.includes("superset")) return <SupersetIcon size={size} />;
    if (id.includes("metabase")) return <MetabaseIcon size={size} />;
    if (id.includes("qdrant")) return <QdrantIcon size={size} />;
    if (id === "rag" || id.startsWith("rag-") || id.endsWith("-rag")) return <RAGAppIcon size={size} />;
    if (id.includes("ml-trainer") || id.includes("ml_trainer")) return <MLTrainerIcon size={size} />;
    if (id.includes("inference-client") || id.includes("inference_client")) return <InferenceClientIcon size={size} />;
    if (id.includes("inference-sim") || id.includes("inference_sim")) return <InferenceSimIcon size={size} />;
    if (id.includes("solace")) return <SolaceIcon size={size} />;
    if (id.includes("kong")) return <KongIcon size={size} />;
    if (id.includes("event-bridge") || id.includes("event_bridge")) return <EventBridgeIcon size={size} />;
    if (id.includes("event-producer") || id.includes("event_producer")) return <EventProducerIcon size={size} />;
    if (id.includes("webhook-receiver") || id.includes("webhook_receiver")) return <EventProducerIcon size={size} />;
    if (id.includes("external-system") || id.includes("external_system")) return <ExternalSystemIcon size={size} />;
    return <DefaultIcon size={size} />;
  })();

  if (className) {
    return <span className={className}>{svgIcon}</span>;
  }

  return svgIcon;
}
