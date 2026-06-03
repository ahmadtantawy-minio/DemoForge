import { describe, expect, it } from "vitest";
import type { Node } from "@xyflow/react";
import {
  defaultStreamingConnectionConfig,
  inferStreamingEdgeKind,
  preserveStreamingConnection,
  streamingConfigSourceNode,
  streamingConnectionType,
} from "./streamingConnectionRouting";

function node(id: string, componentId: string, type: "component" | "cluster" = "component"): Node {
  return {
    id,
    type,
    position: { x: 0, y: 0 },
    data: { componentId, label: id, config: { KAFKA_TOPIC: "clickstream" } },
  } as Node;
}

describe("inferStreamingEdgeKind", () => {
  it("detects kafka connect to minio cluster", () => {
    expect(inferStreamingEdgeKind(node("kc", "kafka-connect-s3"), node("mc", "minio", "cluster"))).toBe(
      "connect-to-minio",
    );
  });

  it("detects data generator and console to redpanda", () => {
    expect(inferStreamingEdgeKind(node("dg", "data-generator"), node("rp", "redpanda"))).toBe(
      "data-generator-to-broker",
    );
    expect(inferStreamingEdgeKind(node("c", "redpanda-console"), node("rp", "redpanda"))).toBe(
      "console-to-broker",
    );
    expect(inferStreamingEdgeKind(node("rp", "redpanda"), node("c", "redpanda-console"))).toBe(
      "console-to-broker",
    );
  });
});

describe("preserveStreamingConnection", () => {
  it("keeps user-chosen endpoints and handles", () => {
    const c = preserveStreamingConnection({
      source: "rp",
      target: "kc",
      sourceHandle: "right-handle",
      targetHandle: "left-handle",
    });
    expect(c.source).toBe("rp");
    expect(c.target).toBe("kc");
    expect(c.sourceHandle).toBe("right-handle");
    expect(c.targetHandle).toBe("left-handle");
  });
});

describe("streamingConfigSourceNode", () => {
  it("picks data-generator for topic config regardless of drag direction", () => {
    const dg = node("dg", "data-generator");
    const rp = node("rp", "redpanda");
    expect(streamingConfigSourceNode("data-generator-to-broker", rp, dg).id).toBe("dg");
    expect(streamingConfigSourceNode("data-generator-to-broker", dg, rp).id).toBe("dg");
  });
});

describe("streamingConnectionType", () => {
  it("uses s3 only for connect-to-minio", () => {
    expect(streamingConnectionType("connect-to-minio")).toBe("s3");
    expect(streamingConnectionType("connect-to-broker")).toBe("kafka");
  });
});

describe("defaultStreamingConnectionConfig", () => {
  it("passes topic and sink bucket defaults", () => {
    const dg = node("dg", "data-generator");
    expect(defaultStreamingConnectionConfig("data-generator-to-broker", dg)).toEqual({
      topic: "clickstream",
    });
    const kc = node("kc", "kafka-connect-s3");
    expect(defaultStreamingConnectionConfig("connect-to-minio", kc)).toEqual({
      bucket: "streaming-data",
      sink_bucket: "streaming-data",
    });
  });
});
