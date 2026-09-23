import { afterEach, describe, expect, it, vi } from "vitest";
import { GenUIStore } from "../runtime/store";
import { parseGenUIFrames, streamRun } from "./streamManager";

function streamOf(chunks: string[], ok = true) {
  const encoder = new TextEncoder();
  let i = 0;
  return {
    ok,
    status: ok ? 200 : 500,
    body: {
      getReader: () => ({
        read: async () =>
          i < chunks.length ? { value: encoder.encode(chunks[i++]), done: false } : { value: undefined, done: true },
      }),
    },
  } as unknown as Response;
}

const frame = (payload: unknown) => `event: genui\ndata: ${JSON.stringify(payload)}\n\n`;

afterEach(() => vi.unstubAllGlobals());

describe("the GenUI stream", () => {
  it("keeps a half-arrived frame and passes over keep-alives", () => {
    const first = parseGenUIFrames(`${frame({ event: "agent.state", state: "solving" })}: keep-alive\n\nevent: genui\ndata: {"ev`);
    expect(first.payloads).toEqual([{ event: "agent.state", state: "solving" }]);
    expect(parseGenUIFrames(`${first.rest}ent":"agent.message","text":"hi"}\n\n`).payloads).toEqual([
      { event: "agent.message", text: "hi" },
    ]);
  });

  it("applies valid events in batches, refuses the rest, and ends at a final state", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        streamOf([
          frame({ event: "component.created", component: { id: "run-3-summary", type: "optimization-summary", state: "skeleton" } }) +
            frame({ event: "component.data", id: "run-3-summary", data: { status: "optimal", objective: 7 } }),
          frame({ event: "component.created", component: { id: "x", type: "raw-html", state: "hydrated" } }),
          frame({ event: "agent.state", state: "complete" }),
        ])
      )
    );
    const store = new GenUIStore();
    const applied = vi.spyOn(store, "apply");
    const refused: string[] = [];
    const ended: string[] = [];
    const flushes: (() => void)[] = [];
    streamRun(3, store, {
      onEnd: (why) => ended.push(why),
      onRefused: (reason) => refused.push(reason),
      schedule: (flush) => flushes.push(flush),
    });
    await vi.waitFor(() => expect(ended).toEqual(["settled"]));

    expect(refused).toEqual(['unknown component type "raw-html"']);
    expect(store.getComponent("x")).toBeUndefined();
    expect(store.getComponent("run-3-summary")!.data).toEqual({ status: "optimal", objective: 7 });
    expect(store.getStructure().agentState).toBe("complete");
    // Everything arrived before a frame passed: one batch, not four renders.
    expect(applied).toHaveBeenCalledTimes(1);
    expect((fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0]).toBe("/api/v1/runs/3/genui");
  });
});
