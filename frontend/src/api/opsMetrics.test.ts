import { describe, expect, it } from "vitest";
import { parseQueueMetrics } from "../api/v1";

describe("parseQueueMetrics", () => {
  it("reads per-org queue gauges from Prometheus text", () => {
    const text = `
# HELP queue_depth queued runs
queue_depth{org="aaa"} 2.0
runs_running{org="aaa"} 1.0
queue_oldest_wait_seconds{org="aaa"} 45.5
queue_depth{org="bbb"} 0.0
runs_running{org="bbb"} 3.0
queue_oldest_wait_seconds{org="bbb"} 0.0
`;
    expect(parseQueueMetrics(text)).toEqual([
      { org: "aaa", depth: 2, running: 1, oldestWaitSeconds: 45.5 },
      { org: "bbb", depth: 0, running: 3, oldestWaitSeconds: 0 },
    ]);
  });
});
