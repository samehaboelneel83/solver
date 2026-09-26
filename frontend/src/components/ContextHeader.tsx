import { useDomains } from "../api/v1";
import { useDomain } from "../hooks/useDomain";

/**
 * Visible domain context for the shell header (OAAS N03 §3.6).
 * Domain name stays visible even when the sidebar is collapsed.
 */
export default function ContextHeader() {
  const { domainId } = useDomain();
  const { data } = useDomains();
  const domains = Array.isArray(data?.items) ? data.items : [];
  const domain = domains.find((row) => row.id === domainId);

  if (!domain) {
    return (
      <p className="hidden truncate text-xs text-slate-500 lg:block" data-testid="context-header">
        No domain selected
      </p>
    );
  }

  return (
    <p className="hidden max-w-[12rem] truncate text-xs text-slate-600 lg:block" data-testid="context-header" title={domain.name}>
      Domain: <span className="font-medium text-slate-800">{domain.name}</span>
    </p>
  );
}
