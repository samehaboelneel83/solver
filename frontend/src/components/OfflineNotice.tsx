type OfflineNoticeProps = {
  /** What couldn't load, placed in the sentence so the message reads
   * naturally in each of the several places it's reused, e.g. "This list"
   * or "The graph". */
  subject?: string;
};

/**
 * D-7: React Query *pauses* a query (rather than failing it) when the
 * browser reports itself offline, so the normal loading/error branches
 * never run at all -- a genuinely offline fetch used to leave whatever
 * "Loading…" skeleton or spinner was already on screen up forever, with
 * nothing telling the user why. Callers render this instead whenever a
 * query's `fetchStatus` is `"paused"` and it has no data yet to fall back
 * on. `role="status"`/`aria-live="polite"` matches the rest of the app's
 * live-region convention (D-1) rather than the assertive one used for hard
 * errors -- this isn't a failure, it resolves itself once the connection
 * returns (React Query refetches automatically on the `online` event).
 */
export default function OfflineNotice({ subject = "This page" }: OfflineNoticeProps) {
  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="offline-notice"
      className="flex items-center gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-800"
    >
      <p>{subject} can&rsquo;t load right now &mdash; you appear to be offline. It will load automatically once your connection is back.</p>
    </div>
  );
}
