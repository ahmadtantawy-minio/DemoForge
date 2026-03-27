import { BaseEdge, getBezierPath, type EdgeProps } from "@xyflow/react";

export default function AnnotationPointerEdge({
  sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition,
}: EdgeProps) {
  const [edgePath] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition });

  return (
    <BaseEdge
      path={edgePath}
      style={{
        stroke: "var(--color-muted-foreground, #6b7280)",
        strokeWidth: 0.5,
        strokeDasharray: "4 3",
        opacity: 0.4,
      }}
    />
  );
}
