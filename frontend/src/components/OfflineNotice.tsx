type OfflineNoticeProps = {
  /** What couldn't load, placed in the sentence so the message reads
   * naturally in each of the several places it's reused, e.g. "This list"
   * or "The graph". */
  subject?: string;
  /**
   * `offline` — browser reports no network (React Query paused).
   * `unreachable` — browser is online but the platform API did not answer (OAAS O02).
   */
  reason?: "offline" | "unreachable";
};

/**
 * D-7 / OAAS O02: distinguish browser offline from an unreachable API so
 * air-gapped operators are not told they "appear to be offline" when the
 * LAN is fine and only the compose stack is down.
 */
export default function OfflineNotice({
  subject = "This page",
  reason = "offline",
}: OfflineNoticeProps) {
  const detail =
    reason === "unreachable"
      ? `${subject} can\u2019t reach the platform API. Check that the API and database are running; this page will retry automatically.`
      : `${subject} can\u2019t load right now \u2014 you appear to be offline. It will load automatically once your connection is back.`;

  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="offline-notice"
      data-reason={reason}
      className="flex items-center gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-800"
    >
      <p>{detail}</p>
    </div>
  );
}
