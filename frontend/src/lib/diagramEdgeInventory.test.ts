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

  it("treats streaming pairs as hardcoded (no duplicate manifest rows)", () => {
    expect(isHardcodedManifestPair("data-generator", "redpanda")).toBe(true);
    expect(isHardcodedManifestPair("kafka-connect-s3", "redpanda")).toBe(true);
    expect(isHardcodedManifestPair("kafka-connect-s3", "__cluster__")).toBe(true);
    expect(isHardcodedManifestPair("redpanda-console", "redpanda")).toBe(true);
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

  it("includes hardcoded streaming kafka / s3 rows", () => {
    const rows = buildDiagramEdgeInventory([]);
    expect(
      rows.some((r) => r.from === "data-generator" && r.to === "redpanda" && r.edgeType === "kafka" && r.ruleSource === "hardcoded"),
    ).toBe(true);
    expect(
      rows.some((r) => r.from === "kafka-connect-s3" && r.to === "redpanda" && r.edgeType === "kafka"),
    ).toBe(true);
    expect(
      rows.some((r) => r.from === "kafka-connect-s3" && r.to === "__cluster__" && r.edgeType === "s3"),
    ).toBe(true);
    expect(
      rows.some((r) => r.from === "kafka-connect-s3" && r.to === "minio" && r.edgeType === "s3"),
    ).toBe(true);
    expect(
      rows.some(
        (r) => r.from === "redpanda-console" && r.to === "redpanda" && r.edgeType === "schema-registry",
      ),
    ).toBe(true);
  });

  it("does not duplicate streaming pairs from manifest intersection", () => {
    const components = [
      minimalComponent("data-generator", ["kafka", "structured-data"], ["kafka", "s3"]),
      minimalComponent("redpanda", ["kafka"], ["kafka"]),
      minimalComponent("kafka-connect-s3", ["kafka-connect"], ["kafka", "s3"]),
      minimalComponent("minio", ["s3"], []),
    ];
    const rows = buildDiagramEdgeInventory(components);
    const dgRp = rows.filter((r) => r.from === "data-generator" && r.to === "redpanda");
    expect(dgRp.length).toBe(1);
    expect(dgRp[0]?.ruleSource).toBe("hardcoded");
    const kcRp = rows.filter((r) => r.from === "kafka-connect-s3" && r.to === "redpanda");
    expect(kcRp.length).toBe(1);
    expect(kcRp[0]?.ruleSource).toBe("hardcoded");
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
