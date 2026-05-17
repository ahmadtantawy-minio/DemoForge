import { describe, expect, it } from "vitest";
import type { Edge, Node } from "@xyflow/react";
import { resolveSparkIcebergCatalogName } from "./sparkIcebergCatalog";

function node(id: string, componentId: string, extra: Record<string, unknown> = {}): Node {
  return {
    id,
    type: "component",
    position: { x: 0, y: 0 },
    data: { componentId, label: id, config: {}, ...extra },
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

describe("resolveSparkIcebergCatalogName", () => {
  it("uses job ICEBERG_SPARK_CATALOG_NAME override first", () => {
    const nodes = [
      node("job", "spark-etl-job", { config: { ICEBERG_SPARK_CATALOG_NAME: "job_cat" } }),
      node("m1", "minio", {
        aistorTablesEnabled: true,
        config: { AISTOR_TABLES_CATALOG_NAME: "peer_cat" },
      }),
    ];
    const edges = [edge("e1", "job", "m1", "aistor-tables")];
    expect(resolveSparkIcebergCatalogName("job", { ICEBERG_SPARK_CATALOG_NAME: "job_cat" }, nodes, edges)).toBe(
      "job_cat",
    );
  });

  it("infers from MinIO AISTOR_TABLES_CATALOG_NAME when Tables enabled", () => {
    const nodes = [
      node("job", "spark-etl-job"),
      node("m1", "minio", {
        aistorTablesEnabled: true,
        config: { AISTOR_TABLES_CATALOG_NAME: "datalake" },
      }),
    ];
    const edges = [edge("e1", "job", "m1", "aistor-tables")];
    expect(resolveSparkIcebergCatalogName("job", {}, nodes, edges)).toBe("datalake");
  });

  it("defaults to aistor when Tables on but catalog name unset", () => {
    const nodes = [node("job", "spark-etl-job"), node("m1", "minio", { aistorTablesEnabled: true })];
    const edges = [edge("e1", "job", "m1", "s3")];
    expect(resolveSparkIcebergCatalogName("job", {}, nodes, edges)).toBe("aistor");
  });
});
