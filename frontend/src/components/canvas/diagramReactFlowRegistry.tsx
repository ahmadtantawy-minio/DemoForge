import type { EdgeTypes, NodeTypes } from "@xyflow/react";
import ComponentNode from "./nodes/ComponentNode";
import GroupNode from "./nodes/GroupNode";
import StickyNoteNode from "./nodes/StickyNoteNode";
import ClusterNode from "./nodes/ClusterNode";
import AnnotationNode from "./nodes/AnnotationNode";
import SchematicNode from "./nodes/SchematicNode";
import CanvasImageNode from "./nodes/CanvasImageNode";
import AnimatedDataEdge from "./edges/AnimatedDataEdge";
import AnnotationPointerEdge from "./edges/AnnotationPointerEdge";

/**
 * Single module-level registry for React Flow — avoids dev warnings about new
 * `nodeTypes` / `edgeTypes` object identity on each render when defined inline in a component.
 */
export const DIAGRAM_NODE_TYPES = {
  component: ComponentNode,
  group: GroupNode,
  sticky: StickyNoteNode,
  cluster: ClusterNode,
  annotation: AnnotationNode,
  schematic: SchematicNode,
  "canvas-image": CanvasImageNode,
} as const satisfies NodeTypes;

export const DIAGRAM_EDGE_TYPES = {
  data: AnimatedDataEdge,
  animated: AnimatedDataEdge,
  "annotation-pointer": AnnotationPointerEdge,
} as const satisfies EdgeTypes;
