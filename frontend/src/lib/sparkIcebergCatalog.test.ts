import { describe, expect, it } from "vitest";
import type { Edge, Node } from "@xyflow/react";
import { catalogFromMinioPeerNode, resolveSparkIcebergCatalogFromDiagram } from "./minioIcebergPeer";
import { resolveSparkIcebergCatalogName } from "./sparkIcebergCatalog";

function node(id: string, kind: "component" | "cluster", extra: Record<string, unknown> = {}): Node {
  return {
    id,
    type: kind,
    position: { x: 0, y: 0 },
    data: { componentId: kind === "cluster" ? "minio" : "spark-etl-job", label: id, config: {}, ...extra },
  };
}

function edge(id: string, source: string, target: string, connectionType: string): Edge {
  return {
    id,
    source,
    target,
    data: { connectionType },
  } as Edge;
}

describe("catalogFromMinioPeerNode", () => {
  it("reads AISTOR_TABLES_CATALOG_NAME from MinIO cluster", () => {
    const cluster = node("minio-cluster-1", "cluster", {
      aistorTablesEnabled: true,
      config: { AISTOR_TABLES_CATALOG_NAME: "aistor" },
    });
    expect(catalogFromMinioPeerNode(cluster)).toBe("aistor");
  });
});

describe("resolveSparkIcebergCatalogName", () => {
  it("uses job ICEBERG_SPARK_CATALOG_NAME override first", () => {
    const nodes = [
      node("job", "component", { componentId: "spark-etl-job", config: { ICEBERG_SPARK_CATALOG_NAME: "job_cat" } }),
      node("mc", "cluster", { aistorTablesEnabled: true, config: { AISTOR_TABLES_CATALOG_NAME: "peer_cat" } }),
    ];
    const edges = [edge("e1", "mc", "job", "aistor-tables")];
    expect(resolveSparkIcebergCatalogName("job", { ICEBERG_SPARK_CATALOG_NAME: "job_cat" }, nodes, edges)).toBe(
      "job_cat",
    );
  });

  it("infers from MinIO cluster link when job override unset", () => {
    const nodes = [
      node("job", "component", { componentId: "spark-etl-job" }),
      node("mc", "cluster", {
        aistorTablesEnabled: true,
        config: { AISTOR_TABLES_CATALOG_NAME: "datalake" },
      }),
    ];
    const edges = [edge("e1", "job", "mc", "aistor-tables")];
    expect(resolveSparkIcebergCatalogFromDiagram("job", {}, nodes, edges)).toBe("datalake");
  });
});
