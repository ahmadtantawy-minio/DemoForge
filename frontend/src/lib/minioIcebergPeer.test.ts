import { describe, expect, it } from "vitest";
import type { Node } from "@xyflow/react";
import {
  inferIcebergBrowserMinioConnectionType,
  inferSparkEtlMinioConnectionType,
} from "./minioIcebergPeer";

function cluster(id: string, tables: boolean): Node {
  return {
    id,
    type: "cluster",
    position: { x: 0, y: 0 },
    data: { aistorTablesEnabled: tables, config: { AISTOR_TABLES_CATALOG_NAME: "aistor" } },
  };
}

function spark(id: string, jobMode: string): Node {
  return {
    id,
    type: "component",
    position: { x: 0, y: 0 },
    data: { componentId: "spark-etl-job", config: { JOB_MODE: jobMode } },
  };
}

describe("inferSparkEtlMinioConnectionType", () => {
  it("uses s3 for raw_to_parquet without requiring Tables", () => {
    expect(inferSparkEtlMinioConnectionType(cluster("c1", false), spark("j1", "raw_to_parquet"))).toBe("s3");
  });

  it("uses aistor-tables for iceberg_compaction when Tables enabled", () => {
    expect(inferSparkEtlMinioConnectionType(cluster("c1", true), spark("j1", "iceberg_compaction"))).toBe(
      "aistor-tables",
    );
  });

  it("returns null for iceberg job when Tables disabled", () => {
    expect(inferSparkEtlMinioConnectionType(cluster("c1", false), spark("j1", "raw_to_iceberg"))).toBeNull();
  });
});

describe("inferIcebergBrowserMinioConnectionType", () => {
  it("requires aistor-tables when Tables enabled", () => {
    expect(inferIcebergBrowserMinioConnectionType(cluster("c1", true))).toBe("aistor-tables");
  });

  it("returns null when Tables disabled", () => {
    expect(inferIcebergBrowserMinioConnectionType(cluster("c1", false))).toBeNull();
  });
});
