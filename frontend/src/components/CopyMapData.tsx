import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../api/client";
import { formatApiError } from "../api/errors";
import { useDomains } from "../api/v1";

/** Map data copied into another workspace, as it is: how one drawing serves two problems' domains. */
export function CopyMapData({ datasetId, fromDomain, name }: { datasetId: number; fromDomain: number; name: string }) {
  const domains = useDomains();
  const [to, setTo] = useState("");
  const others = (domains.data?.items ?? []).filter((d) => d.id !== fromDomain);
  const copy = useMutation({
    mutationFn: () => apiFetch<{ id: number; domain_id: number }>(`/api/v1/gis/datasets/${datasetId}/copy`, {
      method: "POST", body: JSON.stringify({ domain_id: Number(to), name }),
    }),
  });
  if (!others.length) return null;
  return <span className="inline-flex flex-wrap items-center gap-1">
    <select aria-label="Copy into workspace" className="rounded border border-slate-300 bg-white px-1 py-1" value={to}
      onChange={(e) => setTo(e.target.value)}>
      <option value="">Copy into…</option>
      {others.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
    </select>
    <button type="button" className="rounded border border-slate-300 bg-white px-2 py-1 disabled:opacity-50"
      disabled={!to || copy.isPending} onClick={() => copy.mutate()}>Copy</button>
    {copy.isError && <span role="alert" className="text-red-700">{formatApiError(copy.error)}</span>}
    {copy.data && <Link className="text-blue-700 underline" to={`/domains/${copy.data.domain_id}/map-data/${copy.data.id}`}>Copied: open it</Link>}
  </span>;
}
