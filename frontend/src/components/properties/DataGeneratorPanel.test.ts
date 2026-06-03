import { describe, expect, it } from "vitest";
import { shouldShowKafkaTunables } from "./DataGeneratorPanel";

describe("shouldShowKafkaTunables", () => {
  it("returns true only for kafka format", () => {
    expect(shouldShowKafkaTunables("kafka")).toBe(true);
    expect(shouldShowKafkaTunables("parquet")).toBe(false);
    expect(shouldShowKafkaTunables("json")).toBe(false);
    expect(shouldShowKafkaTunables("csv")).toBe(false);
  });
});
