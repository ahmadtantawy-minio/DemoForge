import { describe, expect, it } from "vitest";
import { getEventProcessorConnectionRouting } from "./eventProcessorRouting";

describe("getEventProcessorConnectionRouting", () => {
  it("collects webhook and s3 bucket fields for the selected node", () => {
    const edges = [
      {
        source: "ep1",
        target: "minio1",
        data: {
          connectionType: "webhook",
          connectionConfig: { webhook_bucket: "b1", webhook_prefix: "p/", webhook_events: "put" },
        },
      },
      {
        source: "ep1",
        target: "c-lb",
        data: {
          connectionType: "s3",
          connectionConfig: { target_bucket: "lake" },
        },
      },
    ];
    const r = getEventProcessorConnectionRouting("ep1", edges);
    expect(r.webhookBucket).toBe("b1");
    expect(r.webhookPrefix).toBe("p/");
    expect(r.webhookEvents).toBe("put");
    expect(r.s3TargetBucket).toBe("lake");
  });
});
