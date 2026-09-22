import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import RunProgress from "./RunProgress";
import type { RunEvent, WatchHandlers } from "../api/runEvents";

vi.mock("../api/runEvents", async () => {
  const actual = await vi.importActual<typeof import("../api/runEvents")>("../api/runEvents");
  return { ...actual, watchRun: vi.fn() };
});

const { watchRun } = await import("../api/runEvents");
const mockWatch = watchRun as unknown as ReturnType<typeof vi.fn>;

/** Feed `events` to whatever the component subscribed with. */
function serve(events: RunEvent[], settle = true) {
  mockWatch.mockImplementation((_runId: number | string, handlers: WatchHandlers) => {
    events.forEach((event) => handlers.onEvent(event));
    if (settle) handlers.onEnd?.("settled");
    return () => {};
  });
}

const progress = (seq: number, t: number, objective: number | null, bound: number | null): RunEvent => ({
  seq,
  kind: "incumbent",
  at: "2026-09-22T10:00:00Z",
  t,
  objective,
  bound,
});

beforeEach(() => {
  // A block, not a one-line arrow: returning the mock would make vitest
  // treat it as this test's cleanup and call it with no arguments.
  mockWatch.mockReset();
});

describe("watching a run", () => {
  it("draws the answer and the bound, and says where they stand", async () => {
    serve([
      { seq: 1, kind: "stage", at: "", stage: "solving" },
      progress(2, 0.1, 100, 400),
      progress(3, 0.9, 260, 280),
    ]);
    render(<RunProgress runId={5} live={false} />);

    await waitFor(() => expect(screen.getByRole("img")).toBeInTheDocument());
    expect(screen.getByRole("img")).toHaveAccessibleName(/0.9 seconds/);
    expect(screen.getByText(/best 260 · bound 280/)).toBeInTheDocument();
    // Two series: the answer solid, the bound dashed.
    expect(document.querySelectorAll("path")).toHaveLength(2);
  });

  it("waits, rather than drawing nothing, while a live run has said little", async () => {
    serve([{ seq: 1, kind: "stage", at: "", stage: "compiled" }], false);
    render(<RunProgress runId={5} live />);

    expect(await screen.findByText(/Waiting for the solver/)).toBeInTheDocument();
    expect(screen.getByText("compiled")).toBeInTheDocument();
  });

  it("says a finished run that reported nothing was simply quick", async () => {
    serve([{ seq: 1, kind: "stage", at: "", stage: "settled" }]);
    render(<RunProgress runId={5} live={false} />);

    expect(await screen.findByText(/finished too quickly/)).toBeInTheDocument();
  });

  it("tells the page when the run settles, so it can show the answer", async () => {
    const onSettled = vi.fn();
    serve([progress(1, 0.2, 5, 5)]);
    render(<RunProgress runId={5} live onSettled={onSettled} />);

    await waitFor(() => expect(onSettled).toHaveBeenCalled());
  });

  it("shows nothing at all when the stream cannot be read", async () => {
    mockWatch.mockImplementation((_runId: number | string, handlers: WatchHandlers) => {
      handlers.onEnd?.("failed");
      return () => {};
    });
    const { container } = render(<RunProgress runId={5} live />);

    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });
});
