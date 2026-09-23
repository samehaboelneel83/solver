/**
 * `GET /api/v1/runs/{id}/genui` into a store: frames parsed, each event
 * checked against the protocol, and applied in one batch per animation
 * frame -- a burst of solver reports costs one render, not one per report.
 *
 * Read with `fetch`, as the run events are (`api/runEvents.ts`): the token
 * travels in a header, never the URL. The server always replays from the
 * start, so a dropped connection resets the store and reads again; the
 * store's upserts make the replay land where it was.
 */
import { getToken } from "../../api/client";
import { validateEvent } from "../protocol/validation";
import type { GenUIEvent } from "../protocol/types";
import type { GenUIStore } from "../runtime/store";

const RETRIES = 3;
const RETRY_PAUSE_MS = 1000;
const FINAL_STATES = new Set(["complete", "warning", "error"]);

/** Split an SSE body into its `data:` payloads, keeping a half-written tail. */
export function parseGenUIFrames(buffer: string): { payloads: unknown[]; rest: string } {
  const payloads: unknown[] = [];
  const blocks = buffer.split("\n\n");
  const rest = blocks.pop() ?? "";
  for (const block of blocks) {
    const data = block
      .split("\n")
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trim())
      .join("");
    if (!data) continue; // a comment: the keep-alive
    try {
      payloads.push(JSON.parse(data));
    } catch {
      // A malformed frame is dropped, as an invalid event is.
    }
  }
  return { payloads, rest };
}

export type StreamOptions = {
  onEnd?: (why: "settled" | "failed") => void;
  /** Reported for each event the protocol refused; nothing of it is rendered. */
  onRefused?: (reason: string) => void;
  /** Batching tick; the default is the browser's animation frame. */
  schedule?: (flush: () => void) => void;
};

const nextFrame = (flush: () => void) =>
  typeof requestAnimationFrame === "function" ? requestAnimationFrame(() => flush()) : setTimeout(flush, 16);

export function streamRun(runId: number | string, store: GenUIStore, options: StreamOptions = {}): () => void {
  const controller = new AbortController();
  const schedule = options.schedule ?? nextFrame;
  let stopped = false;
  let queue: GenUIEvent[] = [];
  let pending = false;

  const flush = () => {
    pending = false;
    if (stopped || queue.length === 0) return;
    const batch = queue;
    queue = [];
    store.apply(batch);
  };
  const enqueue = (event: GenUIEvent) => {
    queue.push(event);
    if (!pending) {
      pending = true;
      schedule(flush);
    }
  };

  (async () => {
    for (let attempt = 0; attempt <= RETRIES && !stopped; attempt += 1) {
      let settled = false;
      try {
        const token = getToken();
        const response = await fetch(`/api/v1/runs/${runId}/genui`, {
          signal: controller.signal,
          headers: { Accept: "text/event-stream", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        });
        if (!response.ok || !response.body) throw new Error(`genui: ${response.status}`);
        if (attempt > 0) {
          queue = [];
          store.reset();
        }
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const { payloads, rest } = parseGenUIFrames(buffer);
          buffer = rest;
          for (const payload of payloads) {
            const checked = validateEvent(payload);
            if (!checked.ok) {
              options.onRefused?.(checked.reason);
              continue;
            }
            if (checked.event.event === "agent.state" && FINAL_STATES.has(checked.event.state)) settled = true;
            enqueue(checked.event);
          }
        }
        flush();
        if (stopped || settled) {
          options.onEnd?.("settled");
          return;
        }
        attempt = -1; // closed early (a proxy, a restart): read again
      } catch (error) {
        if (stopped || (error as { name?: string }).name === "AbortError") return;
        await new Promise((resolve) => setTimeout(resolve, RETRY_PAUSE_MS));
      }
    }
    if (!stopped) options.onEnd?.("failed");
  })();

  return () => {
    stopped = true;
    controller.abort();
  };
}
