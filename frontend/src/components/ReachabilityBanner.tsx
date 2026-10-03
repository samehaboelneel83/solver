import { useHealth } from "../api/health";
import OfflineNotice from "./OfflineNotice";

/**
 * Shell-level reachability (OAAS O02): browser offline vs API/DB unhealthy.
 * Renders nothing when health is ok or still loading for the first time.
 */
export default function ReachabilityBanner() {
  const health = useHealth();

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

  // Only the database being down is news on every page. The analytics store alone leaves planning
  // working: the Health page says so, not a banner on every page (benchmark round 3: four of five
  // testers, signed in as administrators, saw it all session).
  if (health.data?.postgres === "error") {
    return (
      <div
        role="status"
        aria-live="polite"
        data-testid="degraded-notice"
        className="border-b border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-900"
      >
        The database reported an error. Planning may not work until it is back.{" "}
        <a className="underline" href="/health">See what to do</a>
      </div>
    );
  }

  return null;
}
