export interface CanvasImagePreset {
  id: string;
  label: string;
  description: string;
  defaultWidth: number;
  defaultHeight: number;
  svgPath: string; // filename (without .svg) served from /canvas-images/
}

export const CANVAS_IMAGE_PRESETS: CanvasImagePreset[] = [
  { id: "minio-aistor-tables-logo", label: "AIStor Tables", description: "MinIO AIStor Tables logo", defaultWidth: 240, defaultHeight: 70, svgPath: "minio-aistor-tables-logo" },
  { id: "minio-logo", label: "MinIO", description: "MinIO logo", defaultWidth: 160, defaultHeight: 50, svgPath: "minio-logo" },
  { id: "trino-logo", label: "Trino", description: "Trino distributed SQL", defaultWidth: 140, defaultHeight: 50, svgPath: "trino-logo" },
  { id: "apache-iceberg-logo", label: "Apache Iceberg", description: "Apache Iceberg table format", defaultWidth: 180, defaultHeight: 55, svgPath: "apache-iceberg-logo" },
  { id: "zone-on-prem", label: "On-Premises Zone", description: "On-Premises zone badge", defaultWidth: 160, defaultHeight: 36, svgPath: "zone-on-prem" },
  { id: "zone-cloud", label: "Cloud Zone", description: "Cloud zone badge", defaultWidth: 140, defaultHeight: 36, svgPath: "zone-cloud" },
  { id: "zone-customer", label: "Customer Environment", description: "Customer environment badge", defaultWidth: 200, defaultHeight: 36, svgPath: "zone-customer" },
];

export function getPreset(id: string): CanvasImagePreset | undefined {
  return CANVAS_IMAGE_PRESETS.find(p => p.id === id);
}
