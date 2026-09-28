/**
 * The notice for a draft saved before drafts were kept per account, and the
 * one explicit way to recover it. The browser never recorded its author, so
 * its contents are not shown until a signed-in account attests that it wrote
 * the draft and claims it; the original stays in this browser as the source.
 */
import { useState } from "react";
import { claimLegacyDraft, legacyDraftStatus } from "./draftStore";

const NOTICE = "rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900";

export default function LegacyDraftRecovery({ problemId }: { problemId: number }) {
  const [, rerender] = useState(0);
  const [confirming, setConfirming] = useState(false);
  const [attested, setAttested] = useState(false);
  const [message, setMessage] = useState("");
  const status = legacyDraftStatus(problemId);
  if (status === "none") return null;

  function recover() {
    try {
      const saved = claimLegacyDraft(problemId);
      setMessage(saved.persisted
        ? "Recovered as your unpublished draft. The original browser copy is kept unchanged."
        : "Recovered for this page only: this browser's storage is full, so download a draft backup before reloading.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "The older draft could not be recovered.");
    }
    setConfirming(false);
    setAttested(false);
    rerender((n) => n + 1);
  }

  return (
    <div role="status" className={`mb-4 space-y-2 ${NOTICE}`}>
      {status === "claimed-by-you" && <p>You recovered the older browser draft for this problem into your account. The original browser copy is kept unchanged.</p>}
      {status === "claimed-by-other" && <p>An older browser draft for this problem was recovered by another account in this browser. It has not been assigned to this account.</p>}
      {status !== "claimed-by-you" && status !== "claimed-by-other" && <p>
        An older browser draft is preserved for this problem, but its owner was not recorded. It has not been assigned to this account. Keep this browser’s data until the original author’s draft has been recovered.
      </p>}
      {status === "signed-out" && <p>Sign in with the account that wrote it to recover it.</p>}
      {status === "unreadable" && <p>The older draft could not be read, so it cannot be recovered here. It remains preserved in this browser.</p>}
      {status === "available" && !confirming && (
        <button type="button" className="rounded border border-amber-400 px-3 py-2" onClick={() => { setMessage(""); setConfirming(true); }}>
          Recover the older draft into my account
        </button>
      )}
      {status === "available" && confirming && (
        <div className="space-y-2">
          <p>
            Recover it only if you wrote it. It becomes your unpublished draft and must pass normal validation before publishing.
            Once recovered, no other account in this browser can recover it. The original browser copy is not changed or removed.
          </p>
          <label className="flex items-start gap-2">
            <input type="checkbox" checked={attested} onChange={(event) => setAttested(event.currentTarget.checked)} />
            I wrote this draft in this browser.
          </label>
          <div className="flex flex-wrap gap-2">
            <button type="button" disabled={!attested} className="rounded bg-amber-600 px-3 py-2 text-white disabled:opacity-50" onClick={recover}>
              Recover this draft
            </button>
            <button type="button" className="rounded px-3 py-2 underline" onClick={() => { setConfirming(false); setAttested(false); }}>
              Cancel recovery
            </button>
          </div>
        </div>
      )}
      {message && <p>{message}</p>}
    </div>
  );
}
