import type { Connection, Node } from "@xyflow/react";
import { isMinioDiagramPeer } from "./minioIcebergPeer";

export const REDPANDA_ID = "redpanda";
export const REDPANDA_CONSOLE_ID = "redpanda-console";
export const KAFKA_CONNECT_S3_ID = "kafka-connect-s3";
export const DATA_GENERATOR_ID = "data-generator";

export type StreamingEdgeKind =
  | "data-generator-to-broker"
  | "connect-to-broker"
  | "connect-to-minio"
  | "console-to-broker";

export function componentIdOf(node: Node | undefined): string {
  return String((node?.data as { componentId?: string } | undefined)?.componentId ?? "");
}

/** Detect streaming-lakehouse pairs that need explicit edge typing (not generic `data`). */
export function inferStreamingEdgeKind(sourceNode: Node, targetNode: Node): StreamingEdgeKind | null {
  const src = componentIdOf(sourceNode);
  const tgt = componentIdOf(targetNode);

  if (src === DATA_GENERATOR_ID && tgt === REDPANDA_ID) return "data-generator-to-broker";
  if (src === REDPANDA_ID && tgt === DATA_GENERATOR_ID) return "data-generator-to-broker";

  if (src === KAFKA_CONNECT_S3_ID && tgt === REDPANDA_ID) return "connect-to-broker";
  if (src === REDPANDA_ID && tgt === KAFKA_CONNECT_S3_ID) return "connect-to-broker";

  if (src === KAFKA_CONNECT_S3_ID && isMinioDiagramPeer(targetNode)) return "connect-to-minio";
  if (isMinioDiagramPeer(sourceNode) && tgt === KAFKA_CONNECT_S3_ID) return "connect-to-minio";

  if (src === REDPANDA_CONSOLE_ID && tgt === REDPANDA_ID) return "console-to-broker";
  if (src === REDPANDA_ID && tgt === REDPANDA_CONSOLE_ID) return "console-to-broker";

  return null;
}

/**
 * Keep the handles the user dragged. Compose resolves kafka/s3 peers from either
 * edge direction; swapping endpoints breaks handle polarity (source vs target sides).
 */
export function preserveStreamingConnection(connection: Connection): Connection {
  return {
    ...connection,
    sourceHandle: connection.sourceHandle ?? null,
    targetHandle: connection.targetHandle ?? null,
  };
}

/** Node whose config seeds edge defaults (topic, sink bucket). */
export function streamingConfigSourceNode(
  kind: StreamingEdgeKind,
  sourceNode: Node,
  targetNode: Node,
): Node {
  const src = componentIdOf(sourceNode);
  const tgt = componentIdOf(targetNode);
  switch (kind) {
    case "data-generator-to-broker":
      return src === DATA_GENERATOR_ID ? sourceNode : targetNode;
    case "connect-to-minio":
      return src === KAFKA_CONNECT_S3_ID ? sourceNode : targetNode;
    case "connect-to-broker":
    case "console-to-broker":
    default:
      return sourceNode;
  }
}

export function streamingConnectionType(kind: StreamingEdgeKind): "kafka" | "s3" {
  return kind === "connect-to-minio" ? "s3" : "kafka";
}

export function streamingEdgeLabel(kind: StreamingEdgeKind): string {
  switch (kind) {
    case "data-generator-to-broker":
      return "Produce events";
    case "connect-to-broker":
      return "Consume";
    case "connect-to-minio":
      return "S3 Sink";
    case "console-to-broker":
      return "Manage";
    default:
      return "";
  }
}

export function defaultStreamingConnectionConfig(
  kind: StreamingEdgeKind,
  sourceNode: Node,
): Record<string, string> {
  const cfg = (sourceNode.data as { config?: Record<string, string> } | undefined)?.config ?? {};
  switch (kind) {
    case "data-generator-to-broker":
      return { topic: cfg.KAFKA_TOPIC?.trim() || "data-generator" };
    case "connect-to-minio": {
      const bucket = cfg.S3_BUCKET?.trim() || "streaming-data";
      // `bucket` matches kafka-connect-s3 manifest; `sink_bucket` kept for older saved demos.
      return { bucket, sink_bucket: bucket };
    }
    default:
      return {};
  }
}
