import { afterEach, describe, expect, it, vi } from "vitest";
import { parseFrames, watchRun, type RunEvent } from "./runEvents";

/** A response whose body yields `chunks`, as `fetch` would. */
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

const frame = (seq: number, kind: string, extra: Record<string, unknown> = {}) =>
  `id: ${seq}\nevent: ${kind}\ndata: ${JSON.stringify({ seq, kind, ...extra })}\n\n`;

afterEach(() => vi.unstubAllGlobals());

describe("reading an event stream", () => {
  it("keeps a half-arrived frame until the rest of it comes", () => {
    const first = parseFrames(`${frame(1, "incumbent", { objective: 5 })}id: 2\nevent: bo`);
    expect(first.events.map((event) => event.seq)).toEqual([1]);
    const second = parseFrames(`${first.rest}und\ndata: {"seq":2,"kind":"bound"}\n\n`);
    expect(second.events.map((event) => event.kind)).toEqual(["bound"]);
  });

  it("passes over keep-alive comments and anything unreadable", () => {
    const { events } = parseFrames(`: keep-alive\n\ndata: not json\n\n${frame(3, "stage", { stage: "settled" })}`);
    expect(events.map((event) => event.seq)).toEqual([3]);
  });

  it("reports every event and ends when the run settles", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      streamOf([frame(1, "incumbent", { objective: 10, bound: 20 }), frame(2, "stage", { stage: "settled" })])
    );
    vi.stubGlobal("fetch", fetchMock);
    const seen: RunEvent[] = [];
    const ended: string[] = [];

    watchRun(7, { onEvent: (event) => seen.push(event), onEnd: (why) => ended.push(why) });
    await vi.waitFor(() => expect(ended).toEqual(["settled"]));

    expect(seen.map((event) => event.seq)).toEqual([1, 2]);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/runs/7/events");
  });

  it("resumes from the last event it saw when the stream drops", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(streamOf([frame(4, "incumbent", { objective: 1 })]))
      .mockResolvedValueOnce(streamOf([frame(5, "stage", { stage: "settled" })]));
    vi.stubGlobal("fetch", fetchMock);
    const ended: string[] = [];

    watchRun(9, { onEvent: () => {}, onEnd: (why) => ended.push(why) });
    await vi.waitFor(() => expect(ended).toEqual(["settled"]));

    const headers = fetchMock.mock.calls[1][1].headers as Record<string, string>;
    expect(headers["Last-Event-ID"]).toBe("4");
  });

  it("gives up after repeated failures, so the page can fall back to polling", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(streamOf([], false)));
    const ended: string[] = [];

    watchRun(11, { onEvent: () => {}, onEnd: (why) => ended.push(why) });
    await vi.waitFor(() => expect(ended).toEqual(["failed"]), { timeout: 10000 });
  });

  it("stops watching when told to", async () => {
    const aborted: boolean[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((_url: string, options: RequestInit) => {
        (options.signal as AbortSignal).addEventListener("abort", () => aborted.push(true));
        return new Promise(() => {});
      })
    );

    const stop = watchRun(13, { onEvent: () => {} });
    stop();
    await vi.waitFor(() => expect(aborted).toEqual([true]));
  });
});
