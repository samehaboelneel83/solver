import { useEffect } from "react";
import { Outlet, useParams } from "react-router-dom";
import { useDomains } from "../api/v1";
import { useDomain } from "../hooks/useDomain";
import { parseRouteId } from "../lib/routeId";
import ContextMismatch from "./ContextMismatch";

/**
 * Syncs `:domainId` from the canonical OAAS path into the domain store,
 * then renders the nested page. Explicit missing domains are not substituted.
 */
export default function DomainScope() {
  const { domainId: raw } = useParams();
  const requested = parseRouteId(raw ?? null);
  const { setDomainId } = useDomain();
  const domains = useDomains();

  useEffect(() => {
    if (requested !== null) setDomainId(requested);
  }, [requested, setDomainId]);

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

  const items = domains.data?.items ?? [];
  const known = items.some((row) => Number(row.id) === requested);
  if (!domains.isLoading && domains.data && !known) {
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
