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

  if (health.data && (health.data.postgres === "error" || health.data.clickhouse === "error")) {
    const parts = [
      health.data.postgres === "error" ? "database" : null,
      health.data.clickhouse === "error" ? "analytics store" : null,
    ].filter(Boolean);
    return (
      <div
        role="status"
        aria-live="polite"
        data-testid="degraded-notice"
        className="border-b border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-900"
      >
        The {parts.join(" and ")} reported an error. Planning may still work.{" "}
        <a className="underline" href="/health">See what to do</a>
      </div>
    );
  }

  return null;
}
