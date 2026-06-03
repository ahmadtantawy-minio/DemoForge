import { describe, expect, it } from "vitest";
import type { Node } from "@xyflow/react";
import {
  findInvalidDiagramEdges,
} from "./diagramEdgeIssues";
import {
  normalizeClusterComponentConnection,
  prepareConnectionForReactFlow,
} from "./clusterConnectionAnchors";

function clusterNode(id: string): Node {
  return { id, type: "cluster", position: { x: 0, y: 0 }, data: { componentId: "minio" } } as Node;
}

function componentNode(id: string, componentId: string): Node {
  return { id, type: "component", position: { x: 0, y: 0 }, data: { componentId } } as Node;
}

describe("prepareConnectionForReactFlow", () => {
  it("swaps cluster-as-source with data-in to kafka-connect → cluster", () => {
    const nodes = [clusterNode("mc"), componentNode("kc", "kafka-connect-s3")];
    const prepared = prepareConnectionForReactFlow(
      {
        source: "mc",
        target: "kc",
        sourceHandle: "data-in",
        targetHandle: null,
      },
      nodes,
      "s3",
    );
    expect(prepared.source).toBe("kc");
    expect(prepared.target).toBe("mc");
    expect(prepared.targetHandle).toBe("data-in");
  });

  it("keeps kafka-connect → cluster with valid handles", () => {
    const nodes = [componentNode("kc", "kafka-connect-s3"), clusterNode("mc")];
    const prepared = prepareConnectionForReactFlow(
      {
        source: "kc",
        target: "mc",
        sourceHandle: null,
        targetHandle: "data-in",
      },
      nodes,
      "s3",
    );
    expect(prepared.source).toBe("kc");
    expect(prepared.target).toBe("mc");
    expect(prepared.targetHandle).toBe("data-in");
  });
});

describe("findInvalidDiagramEdges", () => {
  it("flags cluster data-in used as sourceHandle", () => {
    const nodes = [clusterNode("mc"), componentNode("kc", "kafka-connect-s3")];
    const issues = findInvalidDiagramEdges(nodes, [
      {
        id: "bad",
        source: "mc",
        target: "kc",
        sourceHandle: "data-in",
        targetHandle: null,
      } as never,
    ]);
    expect(issues).toHaveLength(1);
    expect(issues[0]?.repairable).toBe(true);
    expect(issues[0]?.issues[0]).toContain("data-in");
  });
});

describe("normalizeClusterComponentConnection", () => {
  it("only swaps when cluster target handle is on source side", () => {
    const nodes = [clusterNode("mc"), componentNode("kc", "kafka-connect-s3")];
    const out = normalizeClusterComponentConnection(
      { source: "kc", target: "mc", sourceHandle: null, targetHandle: "data-in" },
      nodes,
    );
    expect(out.source).toBe("kc");
    expect(out.target).toBe("mc");
  });
});
