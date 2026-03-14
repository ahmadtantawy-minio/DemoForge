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
    return <DefaultIcon size={size} />;
  })();

  if (className) {
    return <span className={className}>{svgIcon}</span>;
  }

  return svgIcon;
}
