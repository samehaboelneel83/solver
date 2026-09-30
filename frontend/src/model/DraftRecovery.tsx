import { useState } from "react";
import { readDraft, writeDraft, type ModelDraft } from "./draftStore";

export function parseDraftBackup(text: string, current: ModelDraft): ModelDraft {
  const parsed = JSON.parse(text) as { format?: unknown; draft?: Partial<ModelDraft> };
  const draft = parsed?.draft;
  if (parsed?.format !== "oaas-draft-backup-v1" || !draft || draft.problemId !== current.problemId || draft.base !== current.base) {
    throw new Error("Choose a backup for this problem and the same starting version.");
  }
  if (!draft.ir || typeof draft.ir !== "object" || Array.isArray(draft.ir) || typeof draft.editedAt !== "string" || !Number.isFinite(Date.parse(draft.editedAt))) {
    throw new Error("This file does not contain a valid draft backup.");
  }
  return { ...current, ir: draft.ir, editedAt: draft.editedAt };
}

export default function DraftRecovery({ draft, disabled }: { draft: ModelDraft; disabled: boolean }) {
  const [pending, setPending] = useState<{ backup: ModelDraft; original: string } | null>(null);
  const [message, setMessage] = useState("");
  return <div className="w-full space-y-2 text-sm">
    <label className="inline-flex cursor-pointer flex-wrap items-center gap-2 rounded border px-3 py-2">
      Restore draft backup
      <input type="file" accept=".json,application/json" disabled={disabled} className="max-w-64 text-sm" onChange={async event => {
        const file = event.currentTarget.files?.[0];
        event.currentTarget.value = "";
        setPending(null);
        setMessage("");
        if (!file) return;
        const original = JSON.stringify(readDraft(draft.problemId));
        try {
          if (file.size > 5 * 1024 * 1024) throw new Error("Choose a backup smaller than 5 MB.");
          const backup = parseDraftBackup(await file.text(), draft);
          setPending({ backup, original });
        } catch (error) { setMessage(error instanceof Error ? error.message : "The backup could not be read."); }
      }} />
    </label>
    {pending && <div className="rounded border border-amber-300 bg-amber-50 p-3 text-amber-900">
      <p>Restore the backup edited {new Date(pending.backup.editedAt).toLocaleString()}? This replaces this problem’s unpublished draft. You can undo the restoration. Publishing still requires model validation.</p>
      <button type="button" disabled={disabled} className="mt-2 rounded border px-3 py-2" onClick={() => {
        if (JSON.stringify(readDraft(draft.problemId)) !== pending.original) {
          setMessage("The draft changed after you selected the backup. Select the file again to review it against the current draft.");
          setPending(null);
          return;
        }
        writeDraft({ problemId: draft.problemId, base: draft.base, baseVersion: draft.baseVersion, ir: pending.backup.ir });
        setPending(null);
        setMessage("Backup restored as an unpublished draft.");
      }}>Restore this backup</button>
      <button type="button" className="ml-2 rounded px-3 py-2 underline" onClick={() => setPending(null)}>Cancel restoration</button>
    </div>}
    {message && <p role="status">{message}</p>}
    <p className="text-xs text-slate-500">Undo history keeps the last 30 edits in this tab. The draft saves itself to the server as you edit; a backup file is a copy you keep yourself.</p>
  </div>;
}
