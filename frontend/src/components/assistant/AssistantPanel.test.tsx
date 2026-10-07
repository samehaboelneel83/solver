import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import AssistantPanel, { describeStep } from "./AssistantPanel";
import Markdown from "./Markdown";

type Call = { url: string; body: Record<string, unknown> | null };

function ndjson(events: unknown[]): Response {
  return new Response(events.map((e) => JSON.stringify(e)).join("\n") + "\n", {
    status: 200,
    headers: { "Content-Type": "application/x-ndjson" },
  });
}

const HISTORY = [{ role: "user", content: "fund projects" }];
const PENDING = [...HISTORY, {
  role: "assistant", content: null,
  tool_calls: [{ id: "c1", type: "function", function: { name: "propose_plan", arguments: "{}" } }],
}];

function mockFetch(chatReplies: Response[], status: Record<string, unknown> = { enabled: true, model: "qwen3.5", confirm: "delete", reachable: true }) {
  const calls: Call[] = [];
  const replies = [...chatReplies];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, body: init?.body ? JSON.parse(String(init.body)) : null });
    if (init?.method === "DELETE") return new Response(null, { status: 204 });
    if (url.endsWith("/agent/status")) return new Response(JSON.stringify(status), { status: 200, headers: { "Content-Type": "application/json" } });
    return replies.shift() ?? ndjson([{ type: "state", messages: [], wrote: false }]);
  }));
  return calls;
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <AssistantPanel open onClose={() => {}} context={{ page: "/domains/3/problems", domain_id: 3, problem_id: null }} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  sessionStorage.clear();
  localStorage.setItem("solver_assistant_mode", "model");
});

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("AssistantPanel, describing a problem", () => {
  it("shows the server's reason under a rejected assistant action", async () => {
    mockFetch([ndjson([
      { type: "tool", name: "call_api", args: { method: "POST", path: "/api/v1/problems/from-spec" } },
      { type: "result", name: "call_api", ok: false, preview: "HTTP 422: problem_name is required" },
      { type: "answer", text: "I stopped after repeated validation errors." },
      { type: "state", messages: [], wrote: false },
    ])]);
    renderPanel();

    fireEvent.change(screen.getByLabelText("Message to the assistant"), { target: { value: "Create this" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText("HTTP 422: problem_name is required")).toBeInTheDocument();
    expect(screen.getByText("I stopped after repeated validation errors.")).toBeInTheDocument();
  });

  it("shows the plan, builds only on approval and links what was built", async () => {
    const calls = mockFetch([
      ndjson([
        { type: "thinking" },
        { type: "tool", name: "propose_plan", args: { summary: "fund" } },
        { type: "plan", summary: "**Problem** Fund the best projects.\n\n| Project | Cost |\n|---|---|\n| Roof | 200 |",
          counts: { entities: 4, constraints: 2, objective_terms: 1 }, spec: { problem_name: "Choose projects" } },
        { type: "state", messages: PENDING, wrote: false },
      ]),
      ndjson([
        { type: "built", domain_id: 3, problem_id: 41, model_version_id: 7, scenario_id: 12, domain_created: false, created: {} },
        { type: "answer", text: "Built **Choose projects**: 4 projects, 2 rules and 1 goal." },
        { type: "state", messages: [...PENDING, { role: "assistant", content: "Built" }], wrote: true },
      ]),
    ]);
    renderPanel();

    fireEvent.change(screen.getByLabelText("Message to the assistant"), { target: { value: "Pick city projects within 500k" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByRole("region", { name: "Proposed model" })).toBeInTheDocument();
    expect(screen.getByText("4 records · 2 rules · 1 goal", { exact: false })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "Roof" })).toBeInTheDocument();
    const first = calls.find((c) => c.url.endsWith("/agent/chat"))!;
    expect(first.body).toMatchObject({ mode: "model", text: "Pick city projects within 500k", context: { domain_id: 3 } });

    fireEvent.click(await screen.findByRole("button", { name: /Approve and build/ }));
    expect(await screen.findByText(/Built$/)).toBeInTheDocument();
    const second = calls.filter((c) => c.url.endsWith("/agent/chat"))[1];
    expect(second.body).toMatchObject({ confirm: { allow: true }, messages: PENDING, mode: "model" });
    expect(screen.getByRole("link", { name: "Open the problem" })).toHaveAttribute("href", "/domains/3/problems/41");
    expect(screen.getByRole("link", { name: "Base scenario" })).toHaveAttribute("href", "/domains/3/problems/41/scenarios/12");
    expect(screen.getByText("Approved")).toBeInTheDocument();
  });

  it("asks for changes in words instead of building", async () => {
    const calls = mockFetch([
      ndjson([
        { type: "plan", summary: "plan", counts: {}, spec: {} },
        { type: "state", messages: PENDING, wrote: false },
      ]),
      ndjson([{ type: "answer", text: "Revised." }, { type: "state", messages: [], wrote: false }]),
    ]);
    renderPanel();
    fireEvent.change(screen.getByLabelText("Message to the assistant"), { target: { value: "projects" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    fireEvent.click(await screen.findByRole("button", { name: /Request changes/ }));
    const input = screen.getByLabelText("Message to the assistant");
    expect(input).toHaveAttribute("placeholder", "What should change in the plan?");
    expect(calls.filter((c) => c.url.endsWith("/agent/chat"))).toHaveLength(1);

    fireEvent.change(input, { target: { value: "District B gets at most one too" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByText("Revised.");
    const feedback = calls.filter((c) => c.url.endsWith("/agent/chat"))[1];
    expect(feedback.body).toMatchObject({ text: "District B gets at most one too", messages: PENDING });
    expect(feedback.body).not.toHaveProperty("confirm");
    expect(screen.getByText("Changes requested")).toBeInTheDocument();
  });

  it("says so when the model cannot be reached", async () => {
    mockFetch([], { enabled: true, model: "qwen3.5", confirm: "delete", reachable: false, error: "timed out" });
    renderPanel();
    expect(await screen.findByRole("status")).toHaveTextContent("qwen3.5");
    expect(screen.getByRole("status")).toHaveTextContent("timed out");
  });

  it("explains that an interrupted assistant turn may have saved earlier changes", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url.endsWith("/agent/status")) return new Response(JSON.stringify({ enabled: true, model: "qwen3.5", reachable: true }));
      throw new TypeError("Failed to fetch");
    }));
    renderPanel();

    fireEvent.change(screen.getByLabelText("Message to the assistant"), { target: { value: "Continue the layout" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("The connection ended before the assistant finished");
    expect(screen.getByRole("alert")).toHaveTextContent("may still be saved");
  });
});

describe("AssistantPanel, attached files", () => {
  it("reads a file, shows it, and sends it with every turn until removed", async () => {
    const shops = { name: "shops.csv", sheets: [{ name: "shops", columns: ["shop", "demand"], rows: [["S1", 20]], total_rows: 1, truncated: false }] };
    const calls: { url: string; body: unknown }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, body: init?.body });
      if (url.endsWith("/agent/status")) return new Response(JSON.stringify({ enabled: true, model: "qwen3.5", confirm: "delete", reachable: true }), { headers: { "Content-Type": "application/json" } });
      if (url.endsWith("/agent/files")) return new Response(JSON.stringify(shops), { headers: { "Content-Type": "application/json" } });
      return ndjson([{ type: "answer", text: "Got it." }, { type: "state", messages: [], wrote: false }]);
    }));
    renderPanel();
    fireEvent.change(screen.getByTestId("assistant-file"), { target: { files: [new File(["shop,demand\nS1,20"], "shops.csv", { type: "text/csv" })] } });
    expect(await screen.findByText("shops.csv")).toBeInTheDocument();
    expect(screen.getByText("· 1 rows")).toBeInTheDocument();
    expect(calls.find((c) => c.url.endsWith("/agent/files"))?.body).toBeInstanceOf(FormData);

    fireEvent.change(screen.getByLabelText("Message to the assistant"), { target: { value: "use the attached shops" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByText("Got it.");
    const chat = calls.find((c) => c.url.endsWith("/agent/chat"))!;
    expect(JSON.parse(String(chat.body)).files).toEqual([shops]);
    // Still attached after the first message; the next one names it and does not send it again.
    expect(screen.getByText("shops.csv")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Message to the assistant"), { target: { value: "and again" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(calls.filter((c) => c.url.endsWith("/agent/chat"))).toHaveLength(2));
    const second = JSON.parse(String(calls.filter((c) => c.url.endsWith("/agent/chat"))[1].body));
    expect(second.files).toEqual([]);
    expect(second.keep_files).toEqual(["shops.csv"]);
    expect(screen.getByText("shops.csv")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Remove shops.csv" }));
    expect(screen.queryByText("shops.csv")).toBeNull();
  });
});

describe("AssistantPanel, map files", () => {
  it("takes a dropped drawing, says it needs its coordinate system, and swaps in the placed file", async () => {
    const unplaced = { name: "site.dxf", sheets: [{ name: "WELLS", columns: ["feature", "kind", "x", "y"], rows: [], total_rows: 2, truncated: false }],
      spatial: { format: "AC1027", upload_id: "u1", placed: false, placement: null, layers: 2, candidates: [] } };
    const placed = { ...unplaced, spatial: { ...unplaced.spatial, placed: true, placement: { kind: "epsg", code: 32636, name: "WGS 84 / UTM zone 36N" } } };
    const forms: FormData[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/agent/status")) return new Response(JSON.stringify({ enabled: true, model: "qwen3.5", confirm: "delete", reachable: true }), { headers: { "Content-Type": "application/json" } });
      if (url.endsWith("/agent/files")) {
        forms.push(init?.body as FormData);
        return new Response(JSON.stringify(unplaced), { headers: { "Content-Type": "application/json" } });
      }
      return ndjson([
        { type: "tool", name: "place_file", args: { file: "site.dxf", epsg: 32636 } },
        { type: "file", file: placed },
        { type: "result", name: "place_file", ok: true, preview: "Placed" },
        { type: "answer", text: "It lands in Cairo. Right?" },
        { type: "state", messages: [], wrote: false },
      ]);
    }));
    renderPanel();
    const panel = screen.getByRole("complementary", { name: "Assistant" });
    fireEvent.drop(panel, { dataTransfer: { files: [new File(["0\nSECTION"], "site.dxf")], types: ["Files"] } });
    expect(await screen.findByText(/AC1027 · 2 layers · coordinate system to confirm/)).toBeInTheDocument();
    expect(forms[0].get("domain_id")).toBe("3");

    fireEvent.change(screen.getByLabelText("Message to the assistant"), { target: { value: "It is UTM 36N" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByText("It lands in Cairo. Right?");
    expect(screen.getByText(/2 layers · EPSG:32636/)).toBeInTheDocument();
  });

  it("offers every map format the Map Import page takes", () => {
    mockFetch([]);
    renderPanel();
    const accept = screen.getByTestId("assistant-file").getAttribute("accept") ?? "";
    for (const ext of [".dxf", ".geojson", ".kml", ".kmz", ".gpx", ".zip", ".gpkg", ".csv", ".xlsx"]) expect(accept).toContain(ext);
  });
});

describe("AssistantPanel, the workbench", () => {
  it("keeps one conversation id and adds the files run_python writes", async () => {
    const bodies: Record<string, unknown>[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/agent/status")) return new Response(JSON.stringify({ enabled: true, model: "qwen3.5", confirm: "delete", reachable: true }), { headers: { "Content-Type": "application/json" } });
      bodies.push(JSON.parse(String(init?.body)));
      return ndjson([
        { type: "tool", name: "run_python", args: { code: "..." } },
        { type: "file", file: { name: "pairs.csv", sheets: [{ name: "pairs", columns: ["a", "b"], rows: [], total_rows: 6, truncated: false }] } },
        { type: "result", name: "run_python", ok: true, preview: "{}" },
        { type: "answer", text: "Made the pairs." },
        { type: "state", messages: [], wrote: false },
      ]);
    }));
    renderPanel();
    for (const text of ["make pairs", "again"]) {
      fireEvent.change(screen.getByLabelText("Message to the assistant"), { target: { value: text } });
      fireEvent.click(screen.getByRole("button", { name: "Send" }));
      await waitFor(() => expect(bodies).toHaveLength(text === "again" ? 2 : 1));
      await screen.findAllByText("Made the pairs.");
    }
    expect(screen.getByText("pairs.csv")).toBeInTheDocument();
    expect(bodies[0].conversation_id).toMatch(/^[A-Za-z0-9_-]+$/);
    expect(bodies[1].conversation_id).toBe(bodies[0].conversation_id);
    // The server keeps the files run_python wrote: the browser names them, it does not send them back.
    expect(bodies[1].files).toEqual([]);
    expect(bodies[1].keep_files).toEqual(["pairs.csv"]);
    expect(bodies[1].server_history).toBe(true);
    expect(bodies[1].messages).toEqual([]);
  });

  it("shows the active long-running step and explains what Stop does", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/agent/status")) return new Response(JSON.stringify({ enabled: true, model: "qwen3.5", reachable: true }));
      const stream = new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(new TextEncoder().encode(`${JSON.stringify({ type: "tool", name: "make_layout", args: {} })}\n`));
          init?.signal?.addEventListener("abort", () => controller.error(new DOMException("aborted", "AbortError")), { once: true });
        },
      });
      return new Response(stream, { status: 200, headers: { "Content-Type": "application/x-ndjson" } });
    }));
    renderPanel();

    fireEvent.change(screen.getByLabelText("Message to the assistant"), { target: { value: "Lay out the beds" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("Working on: Building a layout from the drawing")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Stop" }));
    expect(await screen.findByText(/Stop requested.*may still finish/)).toBeInTheDocument();
  });
});

describe("AssistantPanel, asking", () => {
  it("shows a delete for approval and sends the answer", async () => {
    localStorage.setItem("solver_assistant_mode", "assistant");
    const pending = [{ role: "user", content: "x" }, { role: "assistant", content: null,
      tool_calls: [{ id: "c1", type: "function", function: { name: "call_api", arguments: "{}" } }] }];
    const calls = mockFetch([
      ndjson([
        { type: "tool", name: "call_api", args: { method: "GET", path: "/api/v1/runs" } },
        { type: "result", name: "call_api", ok: true, preview: "{}" },
        { type: "confirm", calls: [{ method: "DELETE", path: "/api/v1/runs/9" }] },
        { type: "state", messages: pending, wrote: false },
      ]),
      ndjson([{ type: "answer", text: "Left it." }, { type: "state", messages: [], wrote: false }]),
    ]);
    renderPanel();
    fireEvent.change(screen.getByLabelText("Message to the assistant"), { target: { value: "delete run 9" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("DELETE /api/v1/runs/9")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Deny" }));
    await screen.findByText("Left it.");
    await waitFor(() => expect(calls.filter((c) => c.url.endsWith("/agent/chat"))[1].body).toMatchObject({ confirm: { allow: false } }));
    expect(screen.getByRole("button", { name: /1 step/ })).toBeInTheDocument();
  });

  it("says each step in words", () => {
    expect(describeStep("call_api", { method: "POST", path: "/api/v1/scenarios/4/runs" })).toBe("POST /api/v1/scenarios/4/runs");
    expect(describeStep("search_endpoints", { query: "runs" })).toBe("Looked for “runs”");
    expect(describeStep("propose_plan", {})).toBe("Checked the plan builds");
  });
});

describe("AssistantPanel, chat commands", () => {
  function type(text: string) {
    fireEvent.change(screen.getByLabelText("Message to the assistant"), { target: { value: text } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
  }

  it("/help lists the commands without asking the model", async () => {
    const calls = mockFetch([]);
    renderPanel();
    type("/help");
    expect(await screen.findByText(/start a new conversation/)).toBeInTheDocument();
    expect(calls.filter((c) => c.url.endsWith("/agent/chat"))).toHaveLength(0);
  });

  it("/reset starts a new conversation: the next turn sends no history", async () => {
    const calls = mockFetch([
      ndjson([{ type: "answer", text: "Noted." }, { type: "state", messages: [{ role: "user", content: "beds" }, { role: "assistant", content: "Noted." }], wrote: false }]),
      ndjson([{ type: "answer", text: "Fresh." }, { type: "state", messages: [], wrote: false }]),
    ]);
    renderPanel();
    type("beds");
    await screen.findByText("Noted.");
    type("/reset");
    await waitFor(() => expect(screen.queryByText("Noted.")).not.toBeInTheDocument());
    type("hello");
    await screen.findByText("Fresh.");
    const chats = calls.filter((c) => c.url.endsWith("/agent/chat"));
    expect(chats).toHaveLength(2);
    expect(chats[1].body).toMatchObject({ messages: [], text: "hello", server_history: true });
    expect(calls.some((c) => c.url.endsWith(`/agent/conversations/${chats[0].body?.conversation_id}`))).toBe(true);
    expect(chats[1].body?.conversation_id).not.toEqual(chats[0].body?.conversation_id);
  });

  it("/compact goes to the server, and the footer shows how much memory the chat uses", async () => {
    const calls = mockFetch([
      ndjson([{ type: "answer", text: "I summarized our conversation." }, { type: "state", messages: [], wrote: false }]),
    ], { enabled: true, model: "qwen3.5", confirm: "delete", reachable: true, context: 262144 });
    renderPanel();
    expect(await screen.findByText(/of 262k tokens/)).toBeInTheDocument();
    type("/compact");
    await screen.findByText("I summarized our conversation.");
    expect(calls.filter((c) => c.url.endsWith("/agent/chat"))[0].body).toMatchObject({ text: "/compact" });
  });
});

describe("Markdown", () => {
  it("renders what a model writes as elements, never as HTML", () => {
    const { container } = render(
      <MemoryRouter>
        <Markdown text={"# Plan\n- **budget** within `500`\n- see [the problem](/domains/3/problems/4) or [docs](https://example.com)\n\n<script>alert(1)</script> [bad](javascript:alert(1))"} />
      </MemoryRouter>,
    );
    expect(screen.getByText("budget").tagName).toBe("STRONG");
    expect(screen.getByRole("link", { name: "the problem" })).toHaveAttribute("href", "/domains/3/problems/4");
    expect(screen.getByRole("link", { name: "docs" })).toHaveAttribute("target", "_blank");
    expect(screen.queryByRole("link", { name: "bad" })).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect(screen.getByText(/<script>alert\(1\)<\/script>/)).toBeInTheDocument();
  });
});

describe("AssistantPanel, a turn the server ran on with", () => {
  function stubTurn(turns: unknown[]) {
    const calls: string[] = [];
    const queue = [...turns];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? "GET"} ${url}`);
      if (url.endsWith("/agent/status")) return new Response(JSON.stringify({ enabled: true, model: "qwen3.5", confirm: "delete", reachable: true }), { headers: { "Content-Type": "application/json" } });
      if (url.includes("/turn")) return new Response(JSON.stringify(queue.shift() ?? { running: false, known: true, events: [], count: 0 }), { headers: { "Content-Type": "application/json" } });
      return new Response(null, { status: 204 });
    }));
    return calls;
  }

  it("picks a turn up again after the pane or tab was closed (kept in localStorage)", async () => {
    localStorage.setItem("solver_assistant_model", JSON.stringify({
      id: "conv2", messages: [], files: [],
      items: [{ kind: "user", text: "build it" }, { kind: "steps", steps: [], notes: [] }],
    }));
    const calls = stubTurn([{ running: false, known: true, count: 1, events: [
      { type: "answer", text: "Built and solved while you were away." },
    ] }]);
    renderPanel();
    expect(await screen.findByText("Built and solved while you were away.")).toBeInTheDocument();
    expect(calls.some((c) => c.includes("/agent/conversations/conv2/turn?after=0"))).toBe(true);
    expect(JSON.parse(localStorage.getItem("solver_assistant_model") ?? "{}").id).toBe("conv2");
  });

  it("shows the answer that arrived while the page was away, once, in place of the half-shown steps", async () => {
    sessionStorage.setItem("solver_assistant_model", JSON.stringify({
      id: "conv1", messages: [], files: [],
      items: [{ kind: "user", text: "go ahead" }, { kind: "steps", steps: [{ name: "check_spec", label: "check_spec" }], notes: [] }],
    }));
    const calls = stubTurn([{ running: false, known: true, count: 3, events: [
      { type: "tool", name: "check_spec", args: {} },
      { type: "result", name: "check_spec", ok: true },
      { type: "answer", text: "The plan is ready for you." },
    ] }]);
    renderPanel();
    expect(await screen.findByText("The plan is ready for you.")).toBeInTheDocument();
    expect(calls.some((c) => c.includes("/agent/conversations/conv1/turn?after=0"))).toBe(true);
    expect(screen.getByText("1 step")).toBeInTheDocument();
    expect(screen.queryByText("2 steps")).toBeNull();
  });

  it("leaves a finished conversation alone", async () => {
    sessionStorage.setItem("solver_assistant_model", JSON.stringify({
      id: "conv2", messages: [], files: [], items: [{ kind: "user", text: "hi" }, { kind: "answer", text: "Hello." }],
    }));
    const calls = stubTurn([]);
    renderPanel();
    expect(await screen.findByText("Hello.")).toBeInTheDocument();
    expect(calls.some((c) => c.includes("/turn"))).toBe(false);
  });
});

describe("AssistantPanel, a turn that ended with nothing to show", () => {
  it("says so instead of leaving the message unanswered", async () => {
    sessionStorage.setItem("solver_assistant_model", JSON.stringify({
      id: "conv3", messages: [], files: [], items: [{ kind: "user", text: "go ahead" }],
    }));
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url.endsWith("/agent/status")) return new Response(JSON.stringify({ enabled: true, model: "qwen3.5", confirm: "delete", reachable: true }), { headers: { "Content-Type": "application/json" } });
      if (url.includes("/turn")) return new Response(JSON.stringify({ running: false, known: true, count: 1, events: [{ type: "state", messages: [], wrote: false }] }), { headers: { "Content-Type": "application/json" } });
      return new Response(null, { status: 204 });
    }));
    renderPanel();
    expect(await screen.findByText(/ended without an answer/)).toBeInTheDocument();
  });
});

describe("AssistantPanel, a problem asked in the Ask tab", () => {
  it("offers Describe a problem and carries the message and files there", async () => {
    localStorage.setItem("solver_assistant_mode", "assistant");
    const calls: { url: string; body: unknown }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, body: init?.body ? JSON.parse(String(init.body)) : null });
      const json = (v: unknown) => new Response(JSON.stringify(v), { headers: { "Content-Type": "application/json" } });
      if (url.endsWith("/agent/status")) return json({ enabled: true, model: "qwen3.5", confirm: "delete", reachable: true });
      if (url.endsWith("/handover")) return json({ conversation_id: "m1", text: "Place beds in my camp", files: [{ name: "camp.dxf", sheets: [] }] });
      if (url.endsWith("/agent/chat") && calls.filter((c) => c.url.endsWith("/agent/chat")).length === 1) {
        return ndjson([{ type: "tool", name: "hand_to_describe", args: {} }, { type: "result", name: "hand_to_describe", ok: true, preview: "" },
          { type: "handover", mode: "model", text: "A layout problem." }, { type: "answer", text: "A layout problem." },
          { type: "state", messages: [], wrote: false }]);
      }
      if (url.endsWith("/agent/chat")) return ndjson([{ type: "answer", text: "What size is each bed?" }, { type: "state", messages: [], wrote: false }]);
      return new Response(null, { status: 204 });
    }));
    renderPanel();
    fireEvent.change(screen.getByLabelText("Message to the assistant"), { target: { value: "Place beds in my camp" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    fireEvent.click(await screen.findByRole("button", { name: /Continue in Describe a problem/ }));
    await waitFor(() => expect(calls.filter((c) => c.url.endsWith("/agent/chat"))).toHaveLength(2));
    expect(await screen.findByText("What size is each bed?")).toBeInTheDocument();
    const second = calls.filter((c) => c.url.endsWith("/agent/chat"))[1].body as Record<string, unknown>;
    expect(second).toMatchObject({ mode: "model", conversation_id: "m1", text: "Place beds in my camp", server_history: true,
                                   keep_files: ["camp.dxf"] });
  });
});
