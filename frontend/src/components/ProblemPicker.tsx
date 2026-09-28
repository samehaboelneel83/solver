/**
 * Choosing a problem in a domain of any size (plan §4.2, M1 backlog 4). The
 * first page of problems comes from the page; when the domain has more than
 * that, a search box finds the rest through the list API's `q`, a page of
 * matches at a time. The chosen problem always stays among the options, so a
 * deep-linked problem that is on no page is never swapped for another.
 */
import { useEffect, useId, useState } from "react";
import { useEntityList } from "../api/entities";
import { INPUT_CLASS } from "./attrTypes";

type Row = Record<string, unknown>;

export const PROBLEM_PAGE = 50;

const label = (row: Row) => String(row.name ?? row.id);

export default function ProblemPicker({
  domainId,
  current,
  firstPage,
  total,
  onChoose,
}: {
  domainId: string | number;
  current: Row;
  /** The problems the page already loaded, in name order. */
  firstPage: Row[];
  /** How many problems the domain has. */
  total: number;
  onChoose: (id: string) => void;
}) {
  const selectId = useId();
  const searchId = useId();
  const [typed, setTyped] = useState("");
  const [term, setTerm] = useState("");
  useEffect(() => {
    const timer = setTimeout(() => setTerm(typed.trim()), 250);
    return () => clearTimeout(timer);
  }, [typed]);

  const searchable = total > firstPage.length;
  const found = useEntityList("public", "problem", {
    limit: PROBLEM_PAGE,
    offset: 0,
    q: term,
    orderBy: "name",
    order: "asc",
    filters: { domain_id: String(domainId) },
    enabled: searchable && term !== "",
  });
  const searching = searchable && term !== "";
  const matches = searching ? found.data?.items ?? [] : firstPage;
  const options = matches.some((row) => String(row.id) === String(current.id)) ? matches : [current, ...matches];

  let status = "";
  if (searching) {
    if (found.isError) status = "The search failed. Try again, or clear the search to see the first problems.";
    else if (!found.data || found.isPlaceholderData) status = "Searching…";
    else if (found.data.total === 0) status = `No problem matches “${term}”.`;
    else if (found.data.total > found.data.items.length) status = `Showing ${found.data.items.length} of ${found.data.total} matches. Type more to narrow them.`;
    else status = `${found.data.total} ${found.data.total === 1 ? "match" : "matches"}.`;
  } else if (searchable) {
    status = `Showing the first ${firstPage.length} of ${total} problems. Search to find the others.`;
  }

  return (
    <div className="mb-4 space-y-2">
      <div>
        <label htmlFor={selectId} className="block text-sm font-medium text-slate-700">
          Problem
        </label>
        <select
          id={selectId}
          className={`${INPUT_CLASS} max-w-sm`}
          value={String(current.id)}
          onChange={(event) => onChoose(event.target.value)}
        >
          {options.map((row) => (
            <option key={String(row.id)} value={String(row.id)}>
              {label(row)}
            </option>
          ))}
        </select>
      </div>
      {searchable && (
        <div>
          <label htmlFor={searchId} className="block text-sm font-medium text-slate-700">
            Find a problem
          </label>
          <input
            id={searchId}
            type="search"
            className={`${INPUT_CLASS} max-w-sm`}
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
            placeholder="Part of its name"
          />
        </div>
      )}
      {status && <p role="status" className="text-sm text-slate-600">{status}</p>}
    </div>
  );
}
