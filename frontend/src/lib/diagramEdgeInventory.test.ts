import { describe, expect, it } from "vitest";
import type { ComponentSummary } from "../types";
import {
  buildDiagramEdgeInventory,
  isHardcodedManifestPair,
  filterAndSortEdgeInventory,
  displayInventoryEndpoint,
} from "./diagramEdgeInventory";

const minimalComponent = (id: string, provides: string[] = [], accepts: string[] = []): ComponentSummary =>
  ({
    id,
    name: id,
    category: "test",
    icon: "",
    description: "",
    image: "",
    variants: [],
    connections: {
      provides: provides.map((type) => ({ type, port: 0, description: "", path: "", config_schema: [] })),
      accepts: accepts.map((type) => ({ type, config_schema: [] })),
    },
  }) as ComponentSummary;

describe("isHardcodedManifestPair", () => {
  it("treats minio cluster spark link as hardcoded", () => {
    expect(isHardcodedManifestPair("__cluster__", "spark-etl-job")).toBe(true);
  });

  it("allows manifest pairing for unrelated components", () => {
    expect(isHardcodedManifestPair("spark", "trino")).toBe(false);
  });
});

describe("buildDiagramEdgeInventory", () => {
  it("includes hardcoded minio spark rows", () => {
    const rows = buildDiagramEdgeInventory([]);
    expect(rows.some((r) => r.from === "__cluster__" && r.to === "spark-etl-job" && r.edgeType === "s3")).toBe(true);
  });

  it("expands manifest provides/accepts", () => {
    const components = [
      minimalComponent("spark", ["spark-submit"], []),
      minimalComponent("spark-etl-job", [], ["spark-submit"]),
    ];
    const rows = buildDiagramEdgeInventory(components);
    expect(rows.some((r) => r.from === "spark" && r.to === "spark-etl-job" && r.edgeType === "spark-submit")).toBe(
      true,
    );
  });
});

describe("filterAndSortEdgeInventory", () => {
  const rows = buildDiagramEdgeInventory([minimalComponent("trino", [], ["sql-query"])]);
  const display = (id: string) => displayInventoryEndpoint(id, []);

  it("filters by edge type column", () => {
    const out = filterAndSortEdgeInventory(rows, {
      globalSearch: "",
      columnFilters: { edgeType: "aistor" },
      sortKey: "from",
      sortDir: "asc",
      displayFrom: display,
      displayTo: display,
    });
    expect(out.every((r) => r.edgeType.toLowerCase().includes("aistor"))).toBe(true);
  });
});
