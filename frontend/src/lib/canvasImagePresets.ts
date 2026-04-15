import aistorLogo from "../assets/canvas-images/aistor-logo.png";
import aistorTablesLogo from "../assets/canvas-images/minio-aistor-tables-logo.png";
import minioLogo from "../assets/canvas-images/minio-logo.svg";
import trinoLogo from "../assets/canvas-images/trino-logo.svg";
import apacheIcebergLogo from "../assets/canvas-images/apache-iceberg-logo.svg";
import zoneOnPrem from "../assets/canvas-images/zone-on-prem.svg";
import zoneCloud from "../assets/canvas-images/zone-cloud.svg";
import zoneCustomer from "../assets/canvas-images/zone-customer.svg";

export interface CanvasImagePreset {
  id: string;
  label: string;
  description: string;
  defaultWidth: number;
  defaultHeight: number;
  svgUrl: string; // bundled asset URL resolved by Vite at build time — works offline
}

export const CANVAS_IMAGE_PRESETS: CanvasImagePreset[] = [
  { id: "minio-aistor-tables-logo", label: "AIStor", description: "MinIO AIStor logo", defaultWidth: 153, defaultHeight: 78, svgUrl: aistorLogo },
  { id: "aistor-tables-logo", label: "AIStor Tables", description: "MinIO AIStor Tables logo", defaultWidth: 240, defaultHeight: 100, svgUrl: aistorTablesLogo },
  { id: "minio-logo", label: "MinIO", description: "MinIO logo", defaultWidth: 160, defaultHeight: 50, svgUrl: minioLogo },
  { id: "trino-logo", label: "Trino", description: "Trino distributed SQL", defaultWidth: 140, defaultHeight: 50, svgUrl: trinoLogo },
  { id: "apache-iceberg-logo", label: "Apache Iceberg", description: "Apache Iceberg table format", defaultWidth: 180, defaultHeight: 55, svgUrl: apacheIcebergLogo },
  { id: "zone-on-prem", label: "On-Premises Zone", description: "On-Premises zone badge", defaultWidth: 160, defaultHeight: 36, svgUrl: zoneOnPrem },
  { id: "zone-cloud", label: "Cloud Zone", description: "Cloud zone badge", defaultWidth: 140, defaultHeight: 36, svgUrl: zoneCloud },
  { id: "zone-customer", label: "Customer Environment", description: "Customer environment badge", defaultWidth: 200, defaultHeight: 36, svgUrl: zoneCustomer },
];

export function getPreset(id: string): CanvasImagePreset | undefined {
  return CANVAS_IMAGE_PRESETS.find(p => p.id === id);
}
