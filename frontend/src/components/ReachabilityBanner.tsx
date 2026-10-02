import { useState } from "react";
import { useHealth } from "../api/health";
import { useCapabilities } from "../hooks/useCapability";
import OfflineNotice from "./OfflineNotice";

const HIDDEN_KEY = "solver_analytics_notice_hidden";

/** Hidden in this browser until the analytics store is back: it was on every page of every session for
 * every tester (benchmark re-test, October 2026), though planning works without it. */
function hiddenHere(): boolean {
  try {
    return localStorage.getItem(HIDDEN_KEY) === "1";
  } catch {
    return false;
  }
}

/**
 * Shell-level reachability (OAAS O02): browser offline vs API/DB unhealthy.
 * Renders nothing when health is ok or still loading for the first time.
 */
export default function ReachabilityBanner() {
  const health = useHealth();
  const { can } = useCapabilities();
  const [hidden, setHidden] = useState(hiddenHere);

  if (health.fetchStatus === "paused" && !health.data) {
    return (
      <div className="border-b border-amber-200 bg-amber-50 px-4 py-2">
        <OfflineNotice subject="The platform" reason="offline" />
      </div>
    );
  }

  if (health.isError && !health.data) {
    return (
      <div className="border-b border-amber-200 bg-amber-50 px-4 py-2">
        <OfflineNotice subject="The platform" reason="unreachable" />
      </div>
    );
  }

  const databaseDown = health.data?.postgres === "error";
  if (hidden && health.data && health.data.clickhouse !== "error") {
    // Back: the next outage is news again.
    try {
      localStorage.removeItem(HIDDEN_KEY);
    } catch {
      /* nothing kept */
    }
  }
  // The analytics store alone being down leaves planning working: it is news for whoever runs the
  // platform, not a banner on every page for everyone (user trial). They may hide it for the session.
  const analyticsDown = health.data?.clickhouse === "error" && can("settings.edit") && !hidden;
  if (health.data && (databaseDown || analyticsDown)) {
    const parts = [databaseDown ? "database" : null, health.data.clickhouse === "error" ? "analytics store" : null].filter(Boolean);
    return (
      <div
        role="status"
        aria-live="polite"
        data-testid="degraded-notice"
        className="border-b border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-900"
      >
        The {parts.join(" and ")} reported an error. Planning may still work.{" "}
        <a className="underline" href="/health">See what to do</a>
        {!databaseDown && (
          <button
            type="button"
            className="ml-3 underline"
            onClick={() => {
              try {
                localStorage.setItem(HIDDEN_KEY, "1");
              } catch {
                /* this page only */
              }
              setHidden(true);
            }}
          >
            Hide until it is back
          </button>
        )}
      </div>
    );
  }

  return null;
}
