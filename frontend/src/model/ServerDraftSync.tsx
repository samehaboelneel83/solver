/**
 * Saving the browser's draft to the server, and bringing a server-saved
 * draft into a browser that has none (plan §9.6, M2). The browser copy stays
 * the working copy; the server copy survives another browser or device.
 *
 * Every save names the server revision the browser last saw. When another
 * tab or browser saved in between, the server refuses, and this asks which
 * copy to keep -- it never overwrites either one silently.
 */
import { useCallback, useEffect, useState } from "react";
import { baseOfServerDraft, fetchServerDraft, saveServerDraft, type ServerDraft } from "../api/drafts";
import { isStaleRecordError, formatApiError } from "../api/errors";
import { readDraft, readServerLink, writeDraft, writeServerLink, type ModelDraft } from "./draftStore";

type Remote = { state: "loading" } | { state: "failed"; message: string } | { state: "ready"; draft: ServerDraft | null };

function time(iso: string): string {
  return new Date(iso).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" });
}

/** Save the local draft as the next server revision after `expected`. */
export async function saveToServer(draft: ModelDraft, expected: number | null): Promise<ServerDraft> {
  const saved = await saveServerDraft(draft.problemId, {
    ir: draft.ir,
    base_version_id: draft.base === "scratch" ? null : Number(draft.base.slice("version-".length)),
    expected_revision: expected,
  });
  writeServerLink(draft.problemId, { revision: saved.revision, savedEditedAt: draft.editedAt });
  return saved;
}

/** Make a server draft this browser's draft, linked to its revision. */
export function adoptServerDraft(problemId: number, remote: ServerDraft): ModelDraft {
  const local = writeDraft({ problemId, base: baseOfServerDraft(remote), baseVersion: remote.base_version, ir: remote.ir });
  writeServerLink(problemId, { revision: remote.revision, savedEditedAt: local.editedAt });
  return local;
}

export default function ServerDraftSync({ problemId, draft, disabled }: { problemId: number; draft: ModelDraft | null; disabled: boolean }) {
  const [remote, setRemote] = useState<Remote>({ state: "loading" });
  const [conflict, setConflict] = useState<ServerDraft | null | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const link = draft ? readServerLink(problemId) : null;

  const load = useCallback(async () => {
    setRemote({ state: "loading" });
    try {
      setRemote({ state: "ready", draft: await fetchServerDraft(problemId) });
    } catch (error) {
      setRemote({ state: "failed", message: formatApiError(error) });
    }
  }, [problemId]);
  // Check again whenever the local draft comes or goes: publishing or
  // discarding it removes the server copy too.
  const hasDraft = draft !== null;
  useEffect(() => { void load(); }, [load, hasDraft]);

  async function run(action: () => Promise<string>) {
    setBusy(true);
    setMessage("");
    try {
      setMessage(await action());
    } catch (error) {
      if (isStaleRecordError(error)) {
        const latest = await fetchServerDraft(problemId).catch(() => null);
        setConflict(latest);
        setMessage("");
      } else {
        setMessage(`Not saved to the server: ${formatApiError(error)}`);
      }
    } finally {
      setBusy(false);
    }
  }

  const save = () => run(async () => {
    const current = readDraft(problemId);
    if (!current) return "";
    const saved = await saveToServer(current, readServerLink(problemId)?.revision ?? null);
    setRemote({ state: "ready", draft: saved });
    return `Saved to the server as revision ${saved.revision}.`;
  });

  const overwrite = (latest: ServerDraft | null) => run(async () => {
    const current = readDraft(problemId);
    if (!current) return "";
    const saved = await saveToServer(current, latest?.revision ?? null);
    setConflict(undefined);
    setRemote({ state: "ready", draft: saved });
    return `This draft replaced the server copy (now revision ${saved.revision}).`;
  });

  const takeServerCopy = (latest: ServerDraft) => {
    adoptServerDraft(problemId, latest);
    setConflict(undefined);
    setRemote({ state: "ready", draft: latest });
    setMessage(`Opened the server copy (revision ${latest.revision}). You can undo this in the editor.`);
  };

  if (conflict !== undefined) {
    return (
      <div role="alert" className="w-full rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
        {conflict
          ? <p>The server copy was saved from another tab or browser (revision {conflict.revision}, {time(conflict.updated_at)}). Choose which copy to keep; the other is replaced.</p>
          : <p>The server copy was published or discarded from another tab or browser. You can save this draft as a new server copy.</p>}
        <div className="mt-2 flex flex-wrap gap-2">
          {conflict && <button type="button" disabled={busy || disabled} className="rounded border border-amber-400 px-3 py-2" onClick={() => takeServerCopy(conflict)}>Use the server copy</button>}
          <button type="button" disabled={busy || disabled} className="rounded bg-amber-600 px-3 py-2 text-white disabled:opacity-50" onClick={() => void overwrite(conflict)}>
            {conflict ? "Keep this draft and replace the server copy" : "Save this draft to the server"}
          </button>
        </div>
      </div>
    );
  }

  if (!draft) {
    if (remote.state !== "ready" || !remote.draft) return null;
    const found = remote.draft;
    return (
      <div role="status" className="w-full rounded border border-sky-300 bg-sky-50 p-3 text-sm text-sky-900">
        <p>You have a draft saved to the server (revision {found.revision}, {time(found.updated_at)}), started from {found.base_version === null ? "an empty model" : `version ${found.base_version}`}.</p>
        <button type="button" disabled={disabled} className="mt-2 rounded border border-sky-400 px-3 py-2" onClick={() => adoptServerDraft(problemId, found)}>
          Open the server draft
        </button>
      </div>
    );
  }

  const saved = link !== null && link.savedEditedAt === draft.editedAt;
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <span role="status" className={saved ? "text-green-800" : "text-slate-700"}>
        {saved ? `Saved to the server · revision ${link.revision}` : link ? "Changes not saved to the server" : "Saved on this device only"}
      </span>
      {!saved && (
        <button type="button" disabled={busy || disabled} className="rounded border px-3 py-2 disabled:opacity-50" onClick={() => void save()}>
          {busy ? "Saving…" : "Save to server"}
        </button>
      )}
      {remote.state === "failed" && !message && <span className="text-slate-500">The server copy could not be checked.</span>}
      {message && <span>{message}</span>}
    </div>
  );
}
