import { useEffect, useId } from "react";
import { useNavigate } from "react-router-dom";
import { useDomains, useDomainDetail } from "../api/v1";
import { resolveDomainId, useDomain, useHasRouteDomain } from "../hooks/useDomain";
import { useConfirmLeave } from "../hooks/useUnsavedChangesGuard";
import OfflineNotice from "./OfflineNotice";

/**
 * The sidebar's domain picker. Everything domain-scoped reads the choice
 * through `useDomain()`; this component is what keeps that choice valid.
 *
 * On every change to the domain list it reconciles the stored id with the
 * domains that exist: a stored domain that has been deleted (here, in
 * another tab, or by someone else) falls back to the first domain listed,
 * and that fallback is written back so every other consumer sees it too.
 * It deliberately does nothing while the list is loading, paused or
 * failed -- a stored choice must not be thrown away because one request
 * didn't come back.
 */
export default function DomainSelector() {
  const selectId = useId();
  const navigate = useNavigate();
  const confirmLeave = useConfirmLeave();
  const routeScoped = useHasRouteDomain();
  const { domainId, setDomainId } = useDomain();
  const { data, isLoading, error, fetchStatus } = useDomains();
  // Guard against a body that isn't the `{items, total}` page it should be.
  const domains = Array.isArray(data?.items) ? data.items : undefined;
  const detail = useDomainDetail(routeScoped && domains && !domains.some((row) => row.id === domainId) ? domainId : null);
  const resolved = routeScoped ? domainId : domains ? resolveDomainId(domainId, domains) : domainId;

  useEffect(() => {
    if (!routeScoped && domains && resolved !== domainId) setDomainId(resolved);
  }, [routeScoped, domains, resolved, domainId, setDomainId]);

  const paused = fetchStatus === "paused" && !data;

  let body: React.ReactNode;
  if (paused) {
    body = <OfflineNotice subject="The domain list" />;
  } else if (isLoading) {
    body = <p className="text-sm text-slate-500">Loading domains…</p>;
  } else if (error && !domains) {
    body = <p className="text-sm text-red-600">Failed to load domains</p>;
  } else if (!domains || domains.length === 0) {
    body = <p className="text-sm text-slate-500">No domains yet</p>;
  } else {
    body = (
      <select
        id={selectId}
        value={resolved === null ? "" : String(resolved)}
        onChange={(event) => {
          const next = Number(event.target.value);
          if (next === domainId || !confirmLeave()) return;
          setDomainId(next);
          // A different domain cannot retain the previous problem or record id.
          navigate(`/domains/${next}/problems`);
        }}
        className="w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm text-slate-900"
      >
        {routeScoped && !domains.some((domain) => domain.id === resolved) && (
          <option value={resolved ?? ""} disabled>{detail.data?.id === resolved ? detail.data.name : detail.isLoading ? "Loading selected domain…" : "Domain unavailable"}</option>
        )}
        {domains.map((domain) => (
          <option key={domain.id} value={String(domain.id)}>
            {domain.name}
          </option>
        ))}
      </select>
    );
  }

  // The label is only associated when there is a <select> to label; the
  // loading/empty/error lines sit under the same visible heading.
  const hasSelect = !paused && !isLoading && domains !== undefined && domains.length > 0;
  return (
    <div className="mb-4" data-testid="domain-selector">
      {hasSelect ? (
        <label htmlFor={selectId} className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">
          Domain
        </label>
      ) : (
        <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Domain</p>
      )}
      {body}
    </div>
  );
}
