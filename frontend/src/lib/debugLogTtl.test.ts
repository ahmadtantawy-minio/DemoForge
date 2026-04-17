import { describe, expect, it } from "vitest";
import { DEBUG_LOG_TTL_MS, pruneByAge } from "./debugLogTtl";

describe("pruneByAge", () => {
  it("drops entries older than TTL", () => {
    const now = 1_000_000;
    const items = [
      { id: "a", createdAtMs: now - DEBUG_LOG_TTL_MS - 1 },
      { id: "b", createdAtMs: now - DEBUG_LOG_TTL_MS },
      { id: "c", createdAtMs: now },
    ];
    expect(pruneByAge(items, DEBUG_LOG_TTL_MS, now).map((e) => e.id)).toEqual(["b", "c"]);
  });

  it("treats missing createdAtMs as 0 (pruned when old)", () => {
    const now = 1_000_000;
    const items = [{ id: "x" }, { id: "y", createdAtMs: now }];
    expect(pruneByAge(items, DEBUG_LOG_TTL_MS, now).map((e) => e.id)).toEqual(["y"]);
  });
});
