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
    if (id.includes("file-generator") || id.includes("data-gen")) return <FileGeneratorIcon size={size} />;
    if (id.includes("s3-file-browser") || id.includes("s3-browser")) return <S3FileBrowserIcon size={size} />;
    if (id.includes("iceberg")) return <IcebergIcon size={size} />;
    if (id.includes("trino")) return <TrinoIcon size={size} />;
    if (id.includes("clickhouse")) return <ClickHouseIcon size={size} />;
    if (id.includes("spark")) return <SparkIcon size={size} />;
    if (id.includes("hdfs")) return <HDFSIcon size={size} />;
    return <DefaultIcon size={size} />;
  })();

  if (className) {
    return <span className={className}>{svgIcon}</span>;
  }

  return svgIcon;
}
