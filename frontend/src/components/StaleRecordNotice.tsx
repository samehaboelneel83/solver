/**
 * What an open form shows when its save was refused because the record
 * changed underneath it (Ruling 42).
 *
 * The refusal is the easy half. The hard half is what the person does
 * next, and the only acceptable answer is one that costs them nothing:
 * "Reload and keep my changes" re-reads the record, takes the other
 * client's values for every control this person has not touched, and
 * leaves the ones they have exactly as typed (`lib/staleRecord.ts`). So
 * the button is not an "are you sure you want to lose your work" prompt;
 * nothing is lost by pressing it.
 *
 * `role="alert"` rather than a toast: a toast disappears, and this state
 * persists until it is resolved. It sits inside the form, above the
 * controls, so it is in the same reading order as the error summary the
 * form already has for field problems.
 */
export default function StaleRecordNotice({
  message,
  onReload,
  reloading,
}: {
  /** The server's own words, shown verbatim -- the backend decides how to
   * name the record ("entity", "entity type", "relationship type"). */
  message: string;
  onReload: () => void;
  reloading: boolean;
}) {
  return (
    <div
      role="alert"
      data-testid="stale-record"
      className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900"
    >
      <p>{message}</p>
      <button
        type="button"
        onClick={onReload}
        disabled={reloading}
        className="mt-2 rounded-md border border-amber-400 bg-white px-3 py-1.5 text-sm font-medium text-amber-900 hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-60"
      >
        {reloading ? "Reloading…" : "Reload and keep my changes"}
      </button>
    </div>
  );
}
