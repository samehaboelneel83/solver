import { useQuery } from "@tanstack/react-query";
import { ApiError, NetworkError, apiFetch, currentLocationParam, getToken, setToken } from "./client";

/** The assistant (backend app/api/agent.py): a conversation the client keeps, advanced one request at a time. */

export type AgentMode = "assistant" | "model";

export type AgentToolCall = { id: string; type: "function"; function: { name: string; arguments: string } };
export type AgentMessage = {
  role: "user" | "assistant" | "tool";
  content?: string | null;
  tool_calls?: AgentToolCall[];
  tool_call_id?: string;
  name?: string;
};

export type PlanCounts = Partial<Record<
  "entity_types" | "entities" | "relationships" | "parameters" | "parameter_values" | "variables" | "constraints" | "objective_terms",
  number
>>;

/** A run's facts as the platform renders them beside the Assistant's answer (never typed by the model). */
export type RunFacts = {
  run_id: number;
  status: string;
  status_words: string;
  sense: string;
  goal: number | null;
  bound: number | null;
  gap_pct: number | null;
  parts?: { id: string; value: number | null }[];
  decisions: { var: string; header: string[]; rows: string[][]; count: number; chosen: boolean }[];
  rules: { id: string; state: "broken" | "tight"; short_by: number | null; hard: boolean }[];
};

export type AgentEvent =
  | { type: "thinking" }
  | { type: "ping" }
  | { type: "note"; text: string }
  | { type: "tool"; name: string; args: Record<string, unknown> }
  | { type: "result"; name: string; ok: boolean; preview: string }
  | { type: "confirm"; calls: { method?: string; path?: string; body?: unknown; text?: string }[] }
  | { type: "plan"; summary: string; counts: PlanCounts; spec: Record<string, unknown> }
  | { type: "built"; domain_id: number; problem_id: number; model_version_id: number; scenario_id: number; domain_created: boolean; created: PlanCounts }
  | { type: "answer"; text: string; facts?: RunFacts[] }
  | { type: "error"; text: string }
  | { type: "handover"; mode: AgentMode; text: string }
  | { type: "file"; file: AttachedFile }
  | { type: "state"; messages: AgentMessage[]; wrote: boolean; stored?: { messages: number; tokens: number } };

/** An attached file, read into tables by the server (`POST /api/v1/agent/files`); sent with every turn. */
export type AttachedSheet = { name: string; columns: string[]; rows: unknown[][]; total_rows: number; truncated: boolean };
/** A map file (CAD drawing or GIS): read by the platform's own Map Import readers, kept a day as its uploads are. */
export type AttachedSpatial = {
  format: string;
  upload_id: string | null;
  placed: boolean;
  placement: { kind: string; code?: number; name?: string } | null;
  layers: number;
  candidates: { code: number; name: string; reason: string; lands_at: number[]; sure: boolean }[];
};
export type AttachedFile = { name: string; sheets: AttachedSheet[]; spatial?: AttachedSpatial };

/** What the attach button takes: data files, and every map file Map Import takes. */
export const ATTACHABLE = ".csv,.tsv,.txt,.xlsx,.xlsm,.json,.dxf,.geojson,.kml,.kmz,.gpx,.zip,.shp,.gpkg";

export function uploadAgentFile(file: File, domainId?: number | null): Promise<AttachedFile> {
  const form = new FormData();
  form.append("file", file);
  if (domainId) form.append("domain_id", String(domainId));
  return apiFetch<AttachedFile>("/api/v1/agent/files", { method: "POST", body: form });
}

export type AgentContext = { page?: string; domain_id?: number | null; problem_id?: number | null };

export type ChatBody = {
  messages: AgentMessage[];
  text?: string;
  confirm?: { allow: boolean };
  context?: AgentContext;
  mode: AgentMode;
  files?: AttachedFile[];
  /** Names the server's working folder for run_python; one per conversation. */
  conversation_id?: string;
  /** The server keeps the conversation: `messages` is empty, `files` only the newly attached. */
  server_history?: boolean;
  /** The attachments still wanted, by name. */
  keep_files?: string[];
};

export type AgentStatus = {
  enabled: boolean;
  model: string;
  confirm: string;
  reachable?: boolean;
  model_found?: boolean;
  run_python?: "off" | "on" | "unsafe";
  /** The model's context (vLLM's max_model_len), in tokens. */
  context?: number;
  error?: string;
};

export function useAgentStatus(enabled: boolean) {
  return useQuery({
    queryKey: ["agent", "status"],
    queryFn: () => apiFetch<AgentStatus>("/api/v1/agent/status"),
    enabled,
    staleTime: 60_000,
    retry: false,
  });
}

/** Sends one turn and calls `onEvent` for every line of the answer as it arrives. */
export async function streamChat(body: ChatBody, onEvent: (event: AgentEvent) => void, signal?: AbortSignal): Promise<void> {
  const token = getToken();
  let response: Response;
  try {
    response = await fetch("/api/v1/agent/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify(body),
      signal,
    });
  } catch (error) {
    if ((error as Error)?.name === "AbortError") throw error;
    throw new NetworkError();
  }
  if (response.status === 401) {
    setToken(null);
    const { pathname, search } = window.location;
    if (pathname !== "/login") window.location.href = `/login?reason=expired&next=${currentLocationParam(pathname, search)}`;
    throw new ApiError(401, "unauthorized");
  }
  if (!response.ok || !response.body) {
    throw new ApiError(response.status, (await response.text()) || response.statusText);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (value) buffer += decoder.decode(value, { stream: true });
    let newline = buffer.indexOf("\n");
    while (newline >= 0) {
      const line = buffer.slice(0, newline).trim();
      buffer = buffer.slice(newline + 1);
      if (line) {
        try {
          onEvent(JSON.parse(line) as AgentEvent);
        } catch {
          // a broken line is skipped; the next `state` still carries the conversation
        }
      }
      newline = buffer.indexOf("\n");
    }
    if (done) break;
  }
  const rest = buffer.trim();
  if (rest) {
    try {
      onEvent(JSON.parse(rest) as AgentEvent);
    } catch {
      // ignored, as above
    }
  }
}

/** A turn the server ran on while this page was away (or is still running): its events from `after` on. */
export type TurnState = { running: boolean; known: boolean; events: AgentEvent[]; count: number };

export function getTurn(conversationId: string, after = 0): Promise<TurnState> {
  return apiFetch<TurnState>(`/api/v1/agent/conversations/${conversationId}/turn?after=${after}`);
}

/** Stop: the server starts no further action in this conversation's running turn. */
export function stopTurn(conversationId: string): Promise<unknown> {
  return apiFetch(`/api/v1/agent/conversations/${conversationId}/stop`, { method: "POST" });
}

/** An Ask conversation's problem carried to Describe a problem: a new conversation with the same files. */
export function handOver(conversationId: string): Promise<{ conversation_id: string; text: string; files: AttachedFile[] }> {
  return apiFetch(`/api/v1/agent/conversations/${conversationId}/handover`, { method: "POST" });
}
