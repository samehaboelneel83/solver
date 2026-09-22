/**
 * Watching a run: `GET /api/v1/runs/{id}/events` (server-sent events).
 *
 * Read with `fetch`, not `EventSource`: EventSource cannot send the
 * Authorization header, and putting a token in the URL would write it into
 * every proxy log. A dropped connection is retried from the last event seen
 * (`Last-Event-ID`), so nothing is missed and nothing is repeated; after a
 * few failures in a row it gives up and the page falls back to the polling
 * it already does.
 */

import { getToken } from "./client";

export type RunEvent = {
  seq: number;
  kind: "incumbent" | "bound" | "stage" | "log";
  at: string;
  /** Progress: seconds into the solve, the best answer, the proven bound. */
  t?: number;
  objective?: number | null;
  bound?: number | null;
  /** Stages: compiled, solving, settled. */
  stage?: string;
  [key: string]: unknown;
};

const RETRIES = 3;
const RETRY_PAUSE_MS = 1000;

/** Split an SSE body into events: blocks separated by a blank line. */
export function parseFrames(buffer: string): { events: RunEvent[]; rest: string } {
  const events: RunEvent[] = [];
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
      events.push(JSON.parse(data) as RunEvent);
    } catch {
      // A half-written frame is not an error worth showing anyone.
    }
  }
  return { events, rest };
}

export type WatchHandlers = {
  onEvent: (event: RunEvent) => void;
  /** The stream ended: `settled` when the run has finished, `failed` when
   * it could not be read and the page should fall back to polling. */
  onEnd?: (why: "settled" | "failed") => void;
};

/** Watch `runId`. Returns a function that stops watching. */
export function watchRun(runId: number | string, handlers: WatchHandlers): () => void {
  const controller = new AbortController();
  let last = 0;
  let stopped = false;

  (async () => {
    for (let attempt = 0; attempt <= RETRIES && !stopped; attempt += 1) {
      try {
        const token = getToken();
        const response = await fetch(`/api/v1/runs/${runId}/events`, {
          signal: controller.signal,
          headers: {
            Accept: "text/event-stream",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
            ...(last ? { "Last-Event-ID": String(last) } : {}),
          },
        });
        if (!response.ok || !response.body) throw new Error(`events: ${response.status}`);
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let settled = false;
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const { events, rest } = parseFrames(buffer);
          buffer = rest;
          for (const event of events) {
            last = Math.max(last, event.seq);
            if (event.kind === "stage" && event.stage === "settled") settled = true;
            handlers.onEvent(event);
          }
        }
        if (stopped || settled) {
          handlers.onEnd?.("settled");
          return;
        }
        // The server closed without settling (a run still going, a proxy
        // timeout): reconnect from where this left off.
        attempt = -1;
      } catch (error) {
        if (stopped || (error as { name?: string }).name === "AbortError") return;
        await new Promise((resolve) => setTimeout(resolve, RETRY_PAUSE_MS));
      }
    }
    if (!stopped) handlers.onEnd?.("failed");
  })();

  return () => {
    stopped = true;
    controller.abort();
  };
}
