import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle, Check, ChevronDown, ChevronRight, CircleCheck, FileSpreadsheet, Loader2, Map as MapIcon, MessageSquare, Paperclip,
  PencilLine, RotateCcw, Send, Sparkles, Square, Workflow, X, XCircle,
} from "lucide-react";
import {
  ATTACHABLE, getTurn, handOver, stopTurn, streamChat, uploadAgentFile, useAgentStatus,
  type AgentContext, type AgentEvent, type AgentMessage, type AgentMode, type AttachedFile, type PlanCounts,
  type RunFacts,
} from "../../api/agent";
import { apiFetch } from "../../api/client";
import { downloadFrom } from "../../api/download";
import Markdown from "./Markdown";

/**
 * The Assistant (backend app/api/agent.py), beside every page.
 *
 * Two conversations, one per tab:
 * - Ask: do anything in the platform, as you, with your permissions.
 * - Describe a problem: tell it the problem in your own words; it asks until it
 *   understands, shows the model it would build, and builds it when you approve.
 *
 * The conversation is kept on the server (by its id): the browser sends only each new message, and keeps
 * what it shows (sessionStorage). A new chat is a new id.
 */

type Step = { name: string; label: string; ok?: boolean; preview?: string };
type Item =
  | { kind: "user"; text: string }
  | { kind: "steps"; steps: Step[]; notes: string[] }
  | { kind: "answer"; text: string; facts?: RunFacts[] }
  | { kind: "plan"; summary: string; counts: PlanCounts; spec: Record<string, unknown>; status: "waiting" | "approved" | "changes" }
  | { kind: "confirm"; calls: { method?: string; path?: string; body?: unknown; text?: string }[]; status: "waiting" | "allowed" | "denied" }
  | { kind: "built"; domainId: number; problemId: number; scenarioId: number; versionId: number; domainCreated: boolean }
  | { kind: "error"; text: string }
  | { kind: "handover"; used?: boolean };

type Conversation = {
  items: Item[];
  /** Only for an old conversation the browser still carries; new ones live on the server. */
  messages: AgentMessage[];
  /** What is attached, as shown (names and counts; the server keeps the rows). */
  files?: AttachedFile[];
  /** Attached since the last message: sent once, in full, with the next one. */
  pending?: AttachedFile[];
  /** How big the server's copy is. */
  stored?: { messages: number; tokens: number };
  id?: string;
};
const EMPTY: Conversation = { items: [], messages: [], files: [] };

/** Chat commands: typed as the whole message. /compact is answered by the server; the rest here. */
const RESETS = ["/reset", "/new", "/clear"];
const HELP = [
  "**Commands** (type one as the whole message):",
  "- `/reset` — start a new conversation (also `/new`, `/clear`).",
  "- `/compact` — summarize the conversation so far, to free the model's memory (also `/summarize`). Long chats are also summarized on their own when needed.",
  "- `/help` — show these commands.",
].join("\n");

/** Roughly how many tokens a conversation takes (as sent: about two characters a token). */
function tokensOf(messages: unknown[]): number {
  return Math.round(JSON.stringify(messages).length / 2);
}

/** A file as the browser keeps it: its sheets' names and counts, not their rows. */
function light(file: AttachedFile): AttachedFile {
  return { ...file, sheets: file.sheets.map((sheet) => ({ ...sheet, rows: [] })) };
}

function shortCount(n: number): string {
  return n >= 1000 ? `${Math.round(n / 1000)}k` : String(n);
}

function elapsedLabel(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${String(seconds % 60).padStart(2, "0")}s`;
}

function newId(): string {
  try {
    return crypto.randomUUID().replace(/-/g, "");
  } catch {
    return Math.random().toString(36).slice(2) + Date.now().toString(36);
  }
}
const STORAGE = (mode: AgentMode) => `solver_assistant_${mode}`;

function AssistantWorkStatus({ phase, startedAt, lastPingAt }: {
  phase: string;
  startedAt: number;
  lastPingAt: { current: number };
}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  const elapsed = Math.max(0, Math.floor((now - startedAt) / 1000));

  return (
    <p role="status" aria-live="polite" data-testid="assistant-working-status"
      className="flex items-start gap-2 rounded-md bg-slate-50 px-2.5 py-2 text-xs text-slate-600">
      <Loader2 className="mt-0.5 h-3.5 w-3.5 shrink-0 animate-spin" aria-hidden />
      <span>
        <span className="font-medium text-slate-700">{phase || "Waiting for the assistant"}</span>
        {` · ${elapsedLabel(elapsed)}`}
        {elapsed >= 45 && (
          <span className="block pt-0.5">
            {now - lastPingAt.current <= 25_000
              ? "The connection is active; this step is taking longer than usual."
              : "There has been no recent update. The request may have timed out."}
            {" Use Stop to end your wait."}
          </span>
        )}
      </span>
    </p>
  );
}

// What the panel shows is kept in localStorage, so closing the tab or the browser pane mid-turn does not lose
// it: on return the panel finds its conversation id and picks the running turn up again (the field tests,
// October 2026: a closed pane came back empty while the server finished the turn). Signing out clears it.
function load(mode: AgentMode): Conversation {
  try {
    const raw = localStorage.getItem(STORAGE(mode)) ?? sessionStorage.getItem(STORAGE(mode));
    return raw ? (JSON.parse(raw) as Conversation) : EMPTY;
  } catch {
    return EMPTY;
  }
}

function save(mode: AgentMode, conversation: Conversation) {
  try {
    localStorage.setItem(STORAGE(mode), JSON.stringify(conversation));
    sessionStorage.removeItem(STORAGE(mode));
  } catch {
    // too large or unavailable: the conversation lasts as long as the page
  }
}

/** A tool call, said the way a person would. */
export function describeStep(name: string, args: Record<string, unknown>): string {
  const s = (v: unknown) => (typeof v === "string" ? v : JSON.stringify(v ?? ""));
  switch (name) {
    case "call_api":
      return `${s(args.method)} ${s(args.path)}`;
    case "search_endpoints":
      return `Looked for “${s(args.query)}”`;
    case "describe_endpoint":
      return `Read how ${s(args.method)} ${s(args.path)} works`;
    case "describe_schema":
      return `Read the shape of ${s(args.name)}`;
    case "read_doc":
      return `Read ${s(args.path) || "the documentation"}`;
    case "wait":
      return `Waited ${s(args.seconds)} s`;
    case "make_layout":
      return "Building a layout from the drawing";
    case "run_python":
      return "Running your data analysis";
    case "query_file":
      return `Checking ${s(args.file)}`;
    case "read_file":
      return `Reading ${s(args.file)}`;
    case "propose_plan":
      return "Checked the plan builds";
    default:
      return name;
  }
}

function countsLine(counts: PlanCounts): string {
  const parts: [number | undefined, string, string][] = [
    [counts.entity_types, "kind of record", "kinds of record"],
    [counts.entities, "record", "records"],
    [counts.parameters, "parameter", "parameters"],
    [counts.variables, "decision", "decisions"],
    [counts.constraints, "rule", "rules"],
    [counts.objective_terms, "goal", "goals"],
  ];
  return parts.filter(([n]) => n).map(([n, one, many]) => `${n} ${n === 1 ? one : many}`).join(" · ");
}

const EXAMPLES: Record<AgentMode, string[]> = {
  assistant: [
    "What problems and scenarios do I have?",
    "Solve the Base scenario of this problem and explain the result.",
    "Why was my last run infeasible? Which rules were fighting?",
  ],
  model: [
    "We have 12 nurses and must cover a morning, evening and night shift every day next week. Nobody works two shifts in a row.",
    "I want to choose which of 8 warehouse sites to open so all 20 shops are supplied at the lowest total cost.",
    "Pick which city projects to fund with a 500k budget to get the most benefit.",
  ],
};

export default function AssistantPanel({ open, onClose, context }: { open: boolean; onClose: () => void; context: AgentContext }) {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<AgentMode>(() => {
    try {
      return (localStorage.getItem("solver_assistant_mode") as AgentMode) === "model" ? "model" : "assistant";
    } catch {
      return "assistant";
    }
  });
  const [conversations, setConversations] = useState<Record<AgentMode, Conversation>>(() => ({
    assistant: load("assistant"),
    model: load("model"),
  }));
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [thinking, setThinking] = useState(false);
  const [workPhase, setWorkPhase] = useState("");
  const [workStartedAt, setWorkStartedAt] = useState<number | null>(null);
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  // A turn the server carried on with while this page was away (or reloaded): followed by polling.
  const resumingRef = useRef(false);
  const stoppedRef = useRef(false);
  const lastPingAt = useRef(0);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const status = useAgentStatus(open);

  const conversation = conversations[mode];
  const waiting = [...conversation.items].reverse().find((i) => (i.kind === "plan" || i.kind === "confirm") && i.status === "waiting");
  const lastItem = conversation.items[conversation.items.length - 1];
  // A plan on the table that is not yet approved: what the person types is their change to it.
  const revising = lastItem?.kind === "plan" && lastItem.status !== "approved";

  useEffect(() => {
    save("assistant", conversations.assistant);
    save("model", conversations.model);
  }, [conversations]);

  // To the newest item once it has laid out (a plan's table is taller than its first paint).
  useEffect(() => {
    const box = scrollRef.current;
    if (!box) return;
    const frame = requestAnimationFrame(() => {
      box.scrollTop = box.scrollHeight;
    });
    return () => cancelAnimationFrame(frame);
  }, [conversation.items, busy]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open, mode]);

  // Back on the page during a turn (the blend test: a page change lost a turn minutes into writing the model):
  // the server ran on with it; its events are shown again from the turn's start, and followed until it ends.
  useEffect(() => {
    const target = mode;
    const c = conversations[target];
    const tail = c.items[c.items.length - 1];
    if (!open || busy || abortRef.current || resumingRef.current || !c.id || !tail || (tail.kind !== "user" && tail.kind !== "steps")) return;
    const id = c.id;
    let cancelled = false;
    resumingRef.current = true;
    stoppedRef.current = false;
    (async () => {
      let first = await getTurn(id, 0).catch(() => null);
      if (cancelled || !first?.known) return;
      update(target, (conv) => {
        const at = conv.items.map((i) => i.kind).lastIndexOf("user");
        return { ...conv, items: at >= 0 ? conv.items.slice(0, at + 1) : conv.items };
      });
      let seen: number;
      setBusy(first.running);
      if (first.running) {
        setWorkStartedAt(Date.now());
        setWorkPhase("Still working on your last message");
      }
      let ended = false;
      for (;;) {
        for (const event of first.events) {
          apply(target, event);
          if (["answer", "plan", "confirm", "built", "error"].includes(event.type)) ended = true;
        }
        seen = first.count;
        if (!first.running || cancelled || stoppedRef.current) break;
        await new Promise((r) => setTimeout(r, 3000));
        const next = await getTurn(id, seen).catch(() => null);
        if (!next || cancelled) break;
        lastPingAt.current = Date.now(); // the server answered: the turn is alive, not timed out
        first = next;
      }
      if (!ended && !first.running && !cancelled) {
        // Nothing to show for it (stopped, or the server restarted): say so rather than leave a silent gap.
        update(target, (conv) => ({ ...conv, items: [...conv.items, { kind: "error",
          text: "That message's turn ended without an answer (it was stopped, or the server restarted). Say \"continue\" to pick it up." }] }));
      }
    })().finally(() => {
      resumingRef.current = false;
      if (!cancelled) {
        setBusy(false);
        setThinking(false);
        setWorkStartedAt(null);
        setWorkPhase("");
      }
    });
    return () => {
      cancelled = true;
    };
    // Once per opening and conversation; apply/update are stable enough for this follow-up.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, mode, conversations[mode].id]);

  function chooseMode(next: AgentMode) {
    setMode(next);
    try {
      localStorage.setItem("solver_assistant_mode", next);
    } catch {
      // not remembered
    }
  }

  function update(target: AgentMode, change: (c: Conversation) => Conversation) {
    setConversations((all) => ({ ...all, [target]: change(all[target]) }));
  }

  function apply(target: AgentMode, event: AgentEvent) {
    lastPingAt.current = Date.now(); // Every received event proves the connection is alive.
    if (event.type === "thinking") {
      setThinking(true);
      setWorkPhase("Thinking through your request");
      return;
    }
    if (event.type === "ping") {
      lastPingAt.current = Date.now();
      return;
    }
    setThinking(false);
    if (event.type === "tool") setWorkPhase(`Working on: ${describeStep(event.name, event.args)}`);
    else if (event.type === "result") setWorkPhase("Reviewing the result");
    else if (event.type === "note") setWorkPhase("Working through the next step");
    else if (event.type === "state") setWorkPhase("Saving the conversation");
    else if (event.type === "answer" || event.type === "error") setWorkPhase("Finishing your reply");
    update(target, (c) => {
      const items = [...c.items];
      const last = items[items.length - 1];
      const steps = () => {
        if (last?.kind === "steps") {
          const copy = { ...last, steps: [...last.steps], notes: [...last.notes] };
          items[items.length - 1] = copy;
          return copy;
        }
        const fresh: Extract<Item, { kind: "steps" }> = { kind: "steps", steps: [], notes: [] };
        items.push(fresh);
        return fresh;
      };
      switch (event.type) {
        case "tool":
          steps().steps.push({ name: event.name, label: describeStep(event.name, event.args) });
          break;
        case "result": {
          const s = steps();
          const step = s.steps[s.steps.length - 1];
          if (step) s.steps[s.steps.length - 1] = {
            ...step,
            ok: event.ok,
            ...(event.ok || !event.preview ? {} : { preview: event.preview }),
          };
          if (event.name === "propose_plan" && !event.ok) s.notes.push("The plan needed fixing; correcting it.");
          break;
        }
        case "note":
          steps().notes.push(event.text);
          break;
        case "plan":
          items.push({ kind: "plan", summary: event.summary, counts: event.counts, spec: event.spec, status: "waiting" });
          break;
        case "confirm":
          items.push({ kind: "confirm", calls: event.calls, status: "waiting" });
          break;
        case "built":
          items.push({ kind: "built", domainId: event.domain_id, problemId: event.problem_id, scenarioId: event.scenario_id,
                       versionId: event.model_version_id, domainCreated: event.domain_created });
          break;
        case "answer":
          if (event.text) items.push({ kind: "answer", text: event.text, ...(event.facts?.length ? { facts: event.facts } : {}) });
          break;
        case "error":
          items.push({ kind: "error", text: event.text });
          break;
        case "handover":
          items.push({ kind: "handover" });
          break;
        case "file": {
          // A map file placed in the coordinate system named, or a file the workbench (run_python) wrote:
          // the new one replaces any of the same name, or joins the attachments.
          const others = (c.files ?? []).filter((f) => f.name !== event.file.name);
          const at = (c.files ?? []).findIndex((f) => f.name === event.file.name);
          const files = at >= 0 ? (c.files ?? []).map((f, n) => (n === at ? event.file : f)) : [...others, event.file];
          return { ...c, items, files };
        }
        case "state":
          return { ...c, items, messages: event.stored ? [] : event.messages, stored: event.stored ?? c.stored };
      }
      return { ...c, items };
    });
    if (event.type === "state" && event.wrote) {
      // Something changed: every page showing data reads it again.
      void queryClient.invalidateQueries();
    }
  }

  async function send(body: { text?: string; confirm?: { allow: boolean } }) {
    if (busy) return;
    const target = mode;
    const messages = conversations[target].messages;
    const files = conversations[target].files ?? [];
    const pending = conversations[target].pending ?? [];
    // An old conversation the browser still carries goes up once more; from then on the server keeps it.
    const carried = messages.length > 0 && !conversations[target].stored;
    let conversationId = conversations[target].id;
    if (!conversationId) {
      conversationId = newId();
      const id = conversationId;
      update(target, (c) => ({ ...c, id }));
    }
    if (body.text) {
      update(target, (c) => ({
        ...c,
        items: [
          ...c.items.map((i) => ((i.kind === "plan" || i.kind === "confirm") && i.status === "waiting"
            ? (i.kind === "plan" ? { ...i, status: "changes" as const } : { ...i, status: "denied" as const })
            : i)),
          { kind: "user", text: body.text! },
        ],
      }));
    }
    const controller = new AbortController();
    abortRef.current = controller;
    setBusy(true);
    setThinking(true);
    setWorkStartedAt(Date.now());
    lastPingAt.current = Date.now();
    setWorkPhase("Connecting to the assistant");
    try {
      // A file attached since the last message goes up in full once; the chips keep only names and counts.
      const full = (f: AttachedFile) => pending.find((p) => p.name === f.name) ?? f;
      await streamChat({
        messages: carried ? messages : [], ...body, context, mode: target, conversation_id: conversationId,
        server_history: !carried, files: carried ? files.map(full) : pending, keep_files: files.map((f) => f.name),
      }, (event) => apply(target, event), controller.signal);
      // Sent: the server has them now. Only those sent: a file attached meanwhile still goes with the next one.
      const sent = new Set(pending.map((f) => f.name));
      update(target, (c) => ({ ...c, pending: (c.pending ?? []).filter((f) => !sent.has(f.name)) }));
    } catch (error) {
      if ((error as Error)?.name !== "AbortError") {
        update(target, (c) => ({ ...c, items: [...c.items, { kind: "error", text: (error as Error).message || "The assistant could not be reached." }] }));
      }
    } finally {
      setBusy(false);
      setThinking(false);
      setWorkStartedAt(null);
      setWorkPhase("");
      abortRef.current = null;
    }
  }

  // "Continue in Describe a problem": the Ask conversation's message and files, carried over and sent there.
  const handoverText = useRef<string | null>(null);
  async function continueInDescribe() {
    const from = conversations.assistant.id;
    if (!from) return;
    try {
      const moved = await handOver(from);
      update("assistant", (c) => ({ ...c, items: c.items.map((i) => (i.kind === "handover" ? { ...i, used: true } : i)) }));
      update("model", () => ({ ...EMPTY, id: moved.conversation_id, files: moved.files, stored: { messages: 0, tokens: 0 } }));
      handoverText.current = moved.text || "Please help me model and solve this problem.";
      chooseMode("model");
    } catch (error) {
      update("assistant", (c) => ({ ...c, items: [...c.items, { kind: "error", text: (error as Error).message || "Could not carry it over." }] }));
    }
  }
  useEffect(() => {
    if (mode === "model" && handoverText.current && !busy) {
      const text = handoverText.current;
      handoverText.current = null;
      void send({ text });
    }
    // Sent once, when the Describe conversation it was carried into is in place.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, conversations.model.id, busy]);

  function stop() {
    const id = conversations[mode].id;
    // Leaving the page no longer stops a turn (it runs on, and is shown again on return): Stop says so.
    if (id) void stopTurn(id).catch(() => undefined);
    stoppedRef.current = true;
    if (!abortRef.current && !resumingRef.current) return;
    abortRef.current?.abort();
    update(mode, (c) => ({
      ...c,
      items: [...c.items, { kind: "error", text: "Stop requested. The assistant will start no further actions after the server receives it. An API call or solver run already submitted may still finish." }],
    }));
  }

  function submit(event?: FormEvent) {
    event?.preventDefault();
    const text = draft.trim();
    if (!text || busy) return;
    setDraft("");
    const command = text.toLowerCase();
    if (RESETS.includes(command)) {
      restart();
      return;
    }
    if (command === "/help" || command === "/?") {
      update(mode, (c) => ({ ...c, items: [...c.items, { kind: "user", text }, { kind: "answer", text: HELP }] }));
      return;
    }
    void send({ text });
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
    if (event.key === "Escape") onClose();
  }

  function decide(allow: boolean) {
    update(mode, (c) => ({
      ...c,
      items: c.items.map((i) => (i === waiting
        ? (i.kind === "plan" ? { ...i, status: allow ? "approved" as const : "changes" as const }
          : { ...i, status: allow ? "allowed" as const : "denied" as const })
        : i)),
    }));
    if (allow || waiting?.kind === "confirm") void send({ confirm: { allow } });
    else inputRef.current?.focus();
  }

  async function attach(list: FileList | null) {
    if (!list?.length) return;
    const target = mode;
    setUploading(true);
    try {
      for (const file of Array.from(list)) {
        try {
          const parsed = await uploadAgentFile(file, context.domain_id);
          update(target, (c) => ({
            ...c,
            files: [...(c.files ?? []).filter((f) => f.name !== parsed.name), light(parsed)],
            pending: [...(c.pending ?? []).filter((f) => f.name !== parsed.name), parsed],
          }));
        } catch (error) {
          const text = (error as Error).message || "";
          let detail = text;
          try {
            detail = JSON.parse(text).detail ?? text;
          } catch {
            // plain text
          }
          update(target, (c) => ({ ...c, items: [...c.items, { kind: "error", text: `${file.name}: ${detail}` }] }));
        }
      }
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  function detach(name: string) {
    update(mode, (c) => ({
      ...c,
      files: (c.files ?? []).filter((f) => f.name !== name),
      pending: (c.pending ?? []).filter((f) => f.name !== name),
    }));
  }

  function restart() {
    abortRef.current?.abort();
    const old = conversations[mode].id;
    if (old) void apiFetch(`/api/v1/agent/conversations/${old}`, { method: "DELETE" }).catch(() => undefined);
    update(mode, () => EMPTY);
  }

  if (!open) return null;

  const off = status.data && !status.data.enabled;
  const unreachable = status.data?.enabled && status.data.reachable === false;

  return (
    <aside
      aria-label="Assistant"
      onDragOver={(e) => {
        if (Array.from(e.dataTransfer?.types ?? []).includes("Files")) {
          e.preventDefault();
          setDragging(true);
        }
      }}
      onDragLeave={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragging(false);
      }}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        void attach(e.dataTransfer?.files ?? null);
      }}
      className="fixed inset-0 z-50 flex flex-col bg-white shadow-panel lg:relative lg:inset-auto lg:z-auto lg:h-screen lg:w-[27rem] lg:shrink-0 lg:border-s lg:border-slate-200/80"
    >
      {dragging && (
        <div aria-hidden className="pointer-events-none absolute inset-2 z-10 grid place-items-center rounded-lg border-2 border-dashed border-blue-400 bg-blue-50/95 p-6 text-center text-sm font-medium text-blue-900">
          Drop data or map files here: CSV, Excel, JSON, CAD drawings (DXF), GeoJSON, KML/KMZ, GPX, Shapefile (.zip), GeoPackage
        </div>
      )}
      <div className="flex h-14 shrink-0 items-center gap-2 border-b border-slate-200/80 px-3">
        <span aria-hidden className="grid h-7 w-7 place-items-center rounded-md bg-blue-600 text-white"><Sparkles className="h-4 w-4" /></span>
        <h2 className="flex-1 text-sm font-semibold text-slate-900">Assistant</h2>
        <button type="button" onClick={restart} title="New conversation" aria-label="New conversation"
          className="rounded-md p-2 text-slate-500 hover:bg-slate-100 hover:text-slate-900">
          <RotateCcw className="h-4 w-4" aria-hidden />
        </button>
        <button type="button" onClick={onClose} aria-label="Close the assistant"
          className="rounded-md p-2 text-slate-500 hover:bg-slate-100 hover:text-slate-900">
          <X className="h-4 w-4" aria-hidden />
        </button>
      </div>

      <div role="tablist" aria-label="What to do" className="flex shrink-0 gap-1 border-b border-slate-200/80 px-3 py-2">
        {([["assistant", "Ask", MessageSquare], ["model", "Describe a problem", Workflow]] as const).map(([value, label, Icon]) => (
          <button key={value} type="button" role="tab" aria-selected={mode === value} onClick={() => chooseMode(value)} disabled={busy}
            className={`inline-flex flex-1 items-center justify-center gap-1.5 rounded-md px-2 py-1.5 text-sm ${
              mode === value ? "bg-blue-50 font-semibold text-blue-800" : "text-slate-600 hover:bg-slate-100"}`}>
            <Icon className="h-4 w-4" aria-hidden /> {label}
          </button>
        ))}
      </div>

      {(off || unreachable) && (
        <p role="status" className="mx-3 mt-3 flex gap-2 rounded-md border border-amber-200 bg-amber-50 p-2 text-xs text-amber-900">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          {off ? "The assistant is turned off on this installation (AGENT_ENABLED=0)."
            : `The language model (${status.data?.model}) cannot be reached: ${status.data?.error ?? "no answer"}.`}
        </p>
      )}

      <div ref={scrollRef} className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-3" aria-live="polite">
        {conversation.items.length === 0 && <Welcome mode={mode} onPick={(text) => { setDraft(text); inputRef.current?.focus(); }} />}
        {conversation.items.map((item, n) => (
          <ItemView key={n} item={item} live={item === waiting && !busy} onDecide={decide} onHandover={continueInDescribe} />
        ))}
        {busy && workStartedAt !== null && <AssistantWorkStatus phase={workPhase || (thinking ? "Working…" : "Waiting for the assistant")}
          startedAt={workStartedAt} lastPingAt={lastPingAt} />}
      </div>

      <form onSubmit={submit} className="shrink-0 border-t border-slate-200/80 p-3">
        {(conversation.files ?? []).length > 0 && (
          <ul aria-label="Attached files" className="mb-2 flex flex-wrap gap-1.5">
            {(conversation.files ?? []).map((f) => (
              <li key={f.name} className={`inline-flex items-center gap-1 rounded-md border py-0.5 ps-2 pe-1 text-xs ${
                f.spatial && !f.spatial.placed ? "border-amber-300 bg-amber-50 text-amber-900" : "border-slate-200 bg-slate-50 text-slate-700"}`}>
                {f.spatial ? <MapIcon className="h-3.5 w-3.5 shrink-0" aria-hidden /> : <FileSpreadsheet className="h-3.5 w-3.5 text-slate-500" aria-hidden />}
                <span className="max-w-[10rem] truncate" title={f.name}>{f.name}</span>
                <span className="opacity-80">
                  {f.spatial
                    ? `· ${f.spatial.format} · ${f.spatial.layers} layer${f.spatial.layers === 1 ? "" : "s"} · ${
                      f.spatial.placed
                        ? (f.spatial.placement?.code ? `EPSG:${f.spatial.placement.code}` : "local metres")
                        : "coordinate system to confirm"}`
                    : `· ${f.sheets.reduce((n, s) => n + s.total_rows, 0)} rows`}
                </span>
                <button type="button" onClick={() => detach(f.name)} aria-label={`Remove ${f.name}`}
                  className="rounded p-0.5 text-slate-500 hover:bg-slate-200 hover:text-slate-900">
                  <X className="h-3 w-3" aria-hidden />
                </button>
              </li>
            ))}
          </ul>
        )}
        <label htmlFor="assistant-input" className="sr-only">Message to the assistant</label>
        <input ref={fileRef} type="file" accept={ATTACHABLE} multiple className="hidden" data-testid="assistant-file"
          onChange={(e) => void attach(e.target.files)} />
        <div className="flex items-end gap-2">
          <button type="button" onClick={() => fileRef.current?.click()} disabled={uploading}
            aria-label="Attach files: data (CSV, Excel, JSON) or maps (DXF, GeoJSON, KML/KMZ, GPX, Shapefile .zip, GeoPackage)"
            title="Attach files: data (CSV, Excel, JSON) or maps (DXF, GeoJSON, KML/KMZ, GPX, Shapefile .zip, GeoPackage). You can also drop them here."
            className="rounded-md border border-slate-300 p-2.5 text-slate-600 hover:bg-slate-100 disabled:opacity-50">
            {uploading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Paperclip className="h-4 w-4" aria-hidden />}
          </button>
          <textarea
            id="assistant-input"
            ref={inputRef}
            rows={2}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder={revising ? "What should change in the plan?"
              : mode === "model" ? "Describe your problem in your own words… (/help for commands)" : "Ask or tell me what to do… (/help for commands)"}
            className="max-h-40 min-h-[2.75rem] flex-1 resize-y rounded-shell border border-slate-300 bg-white px-2.5 py-2 text-sm shadow-sm"
          />
          {busy ? (
            <button type="button" onClick={stop} aria-label="Stop"
              className="rounded-md border border-slate-300 p-2.5 text-slate-700 hover:bg-slate-100">
              <Square className="h-4 w-4" aria-hidden />
            </button>
          ) : (
            <button type="submit" disabled={!draft.trim()} aria-label="Send"
              className="rounded-md bg-blue-600 p-2.5 text-white hover:bg-blue-700 disabled:opacity-40">
              <Send className="h-4 w-4" aria-hidden />
            </button>
          )}
        </div>
        <p className="mt-1.5 text-[11px] text-slate-500">
          Acts as you, with your permissions{status.data?.model ? ` · ${status.data.model}` : ""}
          {status.data?.context ? (
            <span title="How much of the model's memory this conversation uses. Past about 60% the older part is summarized.">
              {` · ~${shortCount(conversation.stored?.tokens ?? tokensOf(conversation.messages))} of ${shortCount(status.data.context)} tokens`}
            </span>
          ) : null}. Enter to send, Shift+Enter for a new line.
          {(conversation.stored?.messages ?? conversation.messages.length) >= 6 && !busy && (
            <>
              {" "}
              <button type="button" onClick={() => void send({ text: "/compact" })}
                title="Summarize the conversation so far, so a long chat stays within the model's memory. Long chats are also summarized on their own when needed."
                className="underline decoration-dotted hover:text-slate-800">Summarize chat</button>
            </>
          )}
        </p>
      </form>
    </aside>
  );
}

function Welcome({ mode, onPick }: { mode: AgentMode; onPick: (text: string) => void }) {
  return (
    <div className="space-y-3 pt-2">
      <p className="text-sm text-slate-700">
        {mode === "model"
          ? "Describe the problem you want solved, in your own words, and attach your data: spreadsheets (CSV, Excel) or maps and drawings (DXF, GeoJSON, KML, Shapefile...). I'll ask questions until I understand it, show you the model I would build (sets, parameters, variables, rules, goals), build it when you approve, then solve it and explain the results."
          : "Ask me anything about your data, or tell me what to do: create, change, solve, explain. I work through the platform as you."}
      </p>
      <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">For example</p>
      <ul className="space-y-2">
        {EXAMPLES[mode].map((text) => (
          <li key={text}>
            <button type="button" onClick={() => onPick(text)}
              className="w-full rounded-md border border-slate-200 px-3 py-2 text-start text-sm text-slate-700 hover:border-blue-300 hover:bg-blue-50">
              {text}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

const number = (x: number | null | undefined) =>
  x === null || x === undefined ? "–" : Number.isInteger(x) ? x.toLocaleString("en-US") : x.toLocaleString("en-US", { maximumFractionDigits: 2 });

/** A run's facts, rendered by the platform from the result: the Assistant's text explains them, it does not type them. */
export function FactsCard({ facts }: { facts: RunFacts }) {
  const tone = facts.status === "optimal" ? "border-emerald-200 bg-emerald-50" : facts.status === "feasible"
    ? "border-sky-200 bg-sky-50" : "border-amber-300 bg-amber-50";
  return (
    <section aria-label={`Facts of run ${facts.run_id}`} className={`rounded-lg border px-3 py-2 text-sm ${tone}`}>
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
        From the result of run {facts.run_id} · written by the platform
      </p>
      <p className="mt-1 font-semibold text-slate-900">{facts.status_words}</p>
      {facts.goal !== null && (
        <p className="text-slate-800">
          Goal ({facts.sense}): <strong>{number(facts.goal)}</strong>
          {facts.bound !== null && <> · best possible {facts.sense === "maximize" ? "at most" : "at least"} {number(facts.bound)}</>}
        </p>
      )}
      {facts.parts && facts.parts.length > 0 && (
        <p className="text-slate-700">Made of: {facts.parts.map((p) => `${p.id} ${number(p.value)}`).join(" · ")}</p>
      )}
      {facts.decisions.map((d) => (
        <div key={d.var} className="mt-2">
          <p className="text-slate-700">{d.var}: {d.count.toLocaleString("en-US")} {d.chosen ? "chosen" : "non-zero"}{d.count > d.rows.length ? ` (first ${d.rows.length} shown)` : ""}</p>
          {d.rows.length > 0 && (
            <div className="overflow-x-auto">
              <table className="mt-1 min-w-full text-xs">
                <thead><tr>{d.header.map((h) => <th key={h} className="pe-3 text-start font-medium text-slate-500">{h}</th>)}</tr></thead>
                <tbody>{d.rows.map((r, n) => <tr key={n}>{r.map((c, m) => <td key={m} className="pe-3 text-slate-800">{c}</td>)}</tr>)}</tbody>
              </table>
            </div>
          )}
        </div>
      ))}
      {facts.rules.length > 0 && (
        <p className="mt-2 text-slate-700">
          {facts.rules.map((r) => r.state === "broken" ? `${r.id} broken${r.short_by ? ` (short by ${number(r.short_by)})` : ""}` : `${r.id} tight`).join(" · ")}
        </p>
      )}
      {(facts.map || (facts.files && facts.files.length > 0)) && (
        <p className="mt-2 text-xs text-slate-600">
          {facts.map && <><Link className="font-medium text-sky-700 underline" to={facts.map}>On the map</Link>{facts.files?.length ? " · " : ""}</>}
          {facts.files?.map((f, i) => (
            <span key={f.url}>
              {i > 0 && " · "}
              <button type="button" className="font-medium text-sky-700 underline" title={f.holds}
                      onClick={() => { void downloadFrom(f.url); }}>{f.name}</button>
              <span className="text-slate-500"> ({f.holds})</span>
            </span>
          ))}
        </p>
      )}
    </section>
  );
}

function ItemView({ item, live, onDecide, onHandover }: {
  item: Item; live: boolean; onDecide: (allow: boolean) => void; onHandover?: () => void;
}) {
  switch (item.kind) {
    case "handover":
      return item.used ? (
        <p className="text-xs text-slate-500">Carried over to Describe a problem.</p>
      ) : (
        <button type="button" onClick={onHandover}
          className="inline-flex items-center gap-2 rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700">
          <PencilLine className="h-4 w-4" aria-hidden /> Continue in Describe a problem
        </button>
      );
    case "user":
      return <p className="ms-8 whitespace-pre-wrap rounded-lg bg-blue-600 px-3 py-2 text-sm text-white">{item.text}</p>;
    case "answer":
      return (
        <div className="space-y-2">
          {item.facts?.map((f) => <FactsCard key={f.run_id} facts={f} />)}
          <div className="rounded-lg border border-slate-200 bg-white px-3 py-2"><Markdown text={item.text} /></div>
        </div>
      );
    case "steps":
      return <Steps steps={item.steps} notes={item.notes} />;
    case "error": {
      const interrupted = /^(network error|failed to fetch|load failed|the platform API could not be reached\.)$/i.test(item.text.trim());
      return (
        <p role="alert" className="flex gap-2 rounded-md border border-red-200 bg-red-50 p-2 text-sm text-red-800">
          <XCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          {interrupted
            ? "The connection ended before the assistant finished. Any changes made before the interruption may still be saved; check the workspace before retrying. You can continue by sending a new message."
            : item.text}
        </p>
      );
    }
    case "confirm":
      return (
        <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm">
          <p className="font-semibold text-amber-900">Allow this?</p>
          <ul className="mt-1 space-y-1 font-mono text-xs text-amber-900">
            {item.calls.map((c, n) => <li key={n}>{c.text ?? `${c.method ?? ""} ${c.path ?? ""}`}</li>)}
          </ul>
          {live ? (
            <div className="mt-2 flex gap-2">
              <button type="button" onClick={() => onDecide(true)} className="rounded-md bg-amber-600 px-3 py-1.5 text-white hover:bg-amber-700">Allow</button>
              <button type="button" onClick={() => onDecide(false)} className="rounded-md border border-amber-300 px-3 py-1.5 text-amber-900 hover:bg-amber-100">Deny</button>
            </div>
          ) : (
            <p className="mt-1 text-xs text-amber-800">{item.status === "allowed" ? "Allowed" : item.status === "denied" ? "Not allowed" : ""}</p>
          )}
        </div>
      );
    case "plan":
      return (
        <section aria-label="Proposed model" className="rounded-lg border border-blue-200 bg-blue-50/60 p-3">
          <p className="flex items-center gap-2 text-sm font-semibold text-blue-900">
            <Workflow className="h-4 w-4" aria-hidden /> Proposed model
          </p>
          {countsLine(item.counts) && <p className="mb-2 ms-6 text-xs text-blue-800">{countsLine(item.counts)}</p>}
          <div className="rounded-md bg-white p-2"><Markdown text={item.summary} /></div>
          <details className="mt-2 text-xs text-slate-600">
            <summary className="cursor-pointer select-none">Technical details (the exact model)</summary>
            <pre className="mt-1 max-h-64 overflow-auto rounded bg-white p-2 font-mono text-[11px]">{JSON.stringify(item.spec, null, 2)}</pre>
          </details>
          {live ? (
            <div className="mt-3 flex flex-wrap gap-2">
              <button type="button" onClick={() => onDecide(true)}
                className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700">
                <Check className="h-4 w-4" aria-hidden /> Approve and build
              </button>
              <button type="button" onClick={() => onDecide(false)}
                className="inline-flex items-center gap-1.5 rounded-md border border-blue-300 px-3 py-1.5 text-sm text-blue-900 hover:bg-blue-100">
                <PencilLine className="h-4 w-4" aria-hidden /> Request changes
              </button>
            </div>
          ) : (
            <p className="mt-2 text-xs text-blue-800">
              {item.status === "approved" ? "Approved" : item.status === "changes" ? "Changes requested" : ""}
            </p>
          )}
        </section>
      );
    case "built": {
      const base = `/domains/${item.domainId}/problems/${item.problemId}`;
      return (
        <div className="rounded-lg border border-green-200 bg-green-50 p-3 text-sm">
          <p className="flex items-center gap-2 font-semibold text-green-900"><CircleCheck className="h-4 w-4" aria-hidden /> Built</p>
          <p className="mt-1 text-green-900">
            {item.domainCreated ? "A new domain, " : ""}the problem, its first model version and a Base scenario.
          </p>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
            <Link className="font-medium text-blue-700 underline underline-offset-2" to={base}>Open the problem</Link>
            <Link className="font-medium text-blue-700 underline underline-offset-2" to={`${base}/model`}>See the model</Link>
            <Link className="font-medium text-blue-700 underline underline-offset-2" to={`${base}/scenarios/${item.scenarioId}`}>Base scenario</Link>
          </div>
        </div>
      );
    }
  }
}

function Steps({ steps, notes }: { steps: Step[]; notes: string[] }) {
  const [open, setOpen] = useState(false);
  // A step the platform sent back is the Assistant correcting itself, not a failure of the person's request:
  // it stays folded, and reads as a correction when opened. What could not be done is the turn's own error.
  const failed = steps.filter((s) => s.ok === false).length;
  if (steps.length === 0 && notes.length === 0) return null;
  return (
    <div className="text-xs text-slate-600">
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open}
        className="inline-flex items-center gap-1 rounded px-1 py-0.5 hover:bg-slate-100">
        {open ? <ChevronDown className="h-3.5 w-3.5 rtl:rotate-0" aria-hidden /> : <ChevronRight className="h-3.5 w-3.5 rtl:rotate-180" aria-hidden />}
        {steps.length} step{steps.length === 1 ? "" : "s"}{failed ? ` · ${failed} corrected automatically` : ""}
      </button>
      {open && (
        <ul className="ms-5 mt-1 space-y-0.5">
          {notes.map((n, i) => <li key={`n${i}`} className="italic text-slate-500">{n}</li>)}
          {steps.map((s, i) => (
            <li key={i} className="flex flex-wrap items-start gap-1.5 font-mono text-[11px]">
              {s.ok === false ? <RotateCcw className="mt-0.5 h-3 w-3 shrink-0 text-slate-500" aria-hidden />
                : <Check className="mt-0.5 h-3 w-3 shrink-0 text-green-600" aria-hidden />}
              <span className="break-all">{s.label}</span>
              {s.ok === false && s.preview && (
                <span className="basis-full whitespace-pre-wrap break-words rounded bg-slate-50 px-2 py-1 font-sans text-slate-600">
                  {s.preview}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
