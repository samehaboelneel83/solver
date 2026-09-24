/**
 * What every page that edits the shared draft shows beside it (Blockly edit
 * mode spec §2): whether there are unpublished changes and when they were
 * last made, Publish, and Discard -- which asks first, on the page beside
 * what it would throw away, rather than in a browser dialog.
 */
import { useState } from "react";
import type { ModelDraft } from "./draftStore";

/** "14:02": a 24-hour clock in Latin digits, since it sits inside an English
 * sentence -- the browser's own locale may write it in another script. */
function editedAt(draft: ModelDraft): string {
  return new Date(draft.editedAt).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false });
}

export default function DraftBar({
  draft,
  publishing,
  blocked,
  onPublish,
  onDiscard,
}: {
  draft: ModelDraft | null;
  publishing: boolean;
  /** Why Publish is refused, or null when it may go. */
  blocked: string | null;
  onPublish: () => void;
  onDiscard: () => void;
}) {
  const [asking, setAsking] = useState(false);
  return (
    <div className="flex flex-wrap items-center gap-3">
      <button
        type="button"
        onClick={onPublish}
        disabled={publishing || blocked !== null}
        title={blocked ?? undefined}
        className="rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
      >
        {publishing ? "Publishing…" : "Publish a new version"}
      </button>
      {draft && (
        <>
          <span role="status" className="text-sm text-amber-800">
            {`Unpublished changes · edited ${editedAt(draft)}`}
            {!draft.persisted && " — not saved in this browser: they are lost on reload"}
          </span>
          {asking ? (
            <span className="text-sm text-slate-700">
              Discard the unpublished changes?{" "}
              <button
                type="button"
                className="rounded px-2 py-1 text-red-700 underline"
                onClick={() => {
                  setAsking(false);
                  onDiscard();
                }}
              >
                Discard them
              </button>
              <button type="button" className="rounded px-2 py-1 underline" onClick={() => setAsking(false)}>
                Keep editing
              </button>
            </span>
          ) : (
            <button type="button" className="rounded px-2 py-1 text-sm text-slate-700 underline" onClick={() => setAsking(true)}>
              Discard
            </button>
          )}
        </>
      )}
      {!draft && (
        <span className="text-sm text-slate-500">
          The version you started from is untouched, and any run of it keeps its answer.
        </span>
      )}
    </div>
  );
}

/** A draft started from another version than the one on screen: never swapped silently. */
export function DraftConflict({
  draft,
  shownVersion,
  onContinue,
  onStartAgain,
}: {
  draft: ModelDraft;
  shownVersion: number | null;
  onContinue: () => void;
  onStartAgain: () => void;
}) {
  const from = draft.base === "scratch" ? "an empty model" : `version ${draft.baseVersion ?? "?"}`;
  return (
    <div role="alert" className="mb-4 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
      <p>
        You have unpublished changes started from {from}, edited {editedAt(draft)}.
      </p>
      <div className="mt-2 flex flex-wrap gap-2">
        <button type="button" className="rounded-md bg-amber-600 px-3 py-1.5 text-white" onClick={onContinue}>
          Continue the draft
        </button>
        <button type="button" className="rounded-md border border-amber-400 px-3 py-1.5" onClick={onStartAgain}>
          {shownVersion === null ? "Start again" : `Start again from version ${shownVersion}`}
        </button>
      </div>
    </div>
  );
}
