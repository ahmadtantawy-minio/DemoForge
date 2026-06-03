import { describe, expect, it } from "vitest";
import type { Node } from "@xyflow/react";
import { findInvalidDiagramEdges } from "./diagramEdgeIssues";

describe("findInvalidDiagramEdges", () => {
  it("reports missing nodes as non-repairable", () => {
    const issues = findInvalidDiagramEdges(
      [],
      [{ id: "e1", source: "gone", target: "also-gone" } as never],
    );
    expect(issues[0]?.repairable).toBe(false);
  });
});
