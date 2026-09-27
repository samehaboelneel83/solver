import { useEffect } from "react";
import { Outlet, useParams } from "react-router-dom";
import { useDomainDetail } from "../api/v1";
import { ApiError } from "../api/client";
import { useDomain } from "../hooks/useDomain";
import { parseRouteId } from "../lib/routeId";
import ContextMismatch from "./ContextMismatch";

/**
 * Validates the canonical domain before mounting the nested page. Only a
 * validated selection is remembered for later visits to unscoped routes.
 */
export default function DomainScope() {
  const { domainId: raw } = useParams();
  const requested = parseRouteId(raw ?? null);
  const { setDomainId } = useDomain();
  const domains = useDomainDetail(requested);

  useEffect(() => {
    if (requested !== null && Number(domains.data?.id) === requested) setDomainId(requested);
  }, [requested, setDomainId, domains.data]);

  if (requested === null) {
    return (
      <ContextMismatch
        title="This domain link is not valid"
        detail="The URL does not name a domain id."
        parentHref="/public/domain"
        parentLabel="Open all domains"
      />
    );
  }

  if (domains.isLoading) return <p role="status">Loading domain…</p>;
  const unavailable = domains.error instanceof ApiError && [403, 404].includes(domains.error.status);
  if (!unavailable && (domains.isError || !domains.data)) return (
    <div role="alert">
      <p>The domain could not be loaded. Your selected domain has not changed.</p>
      <button type="button" onClick={() => void domains.refetch()}>Retry</button>
    </div>
  );
  if (unavailable || Number(domains.data?.id) !== requested) {
    return (
      <ContextMismatch
        title="This domain is not available"
        detail="The link asked for a domain that is missing or not in your organization. Nothing was substituted."
        parentHref="/public/domain"
        parentLabel="Open all domains"
      />
    );
  }

  return <Outlet />;
}
