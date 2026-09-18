import { useSearchParams } from "react-router-dom";

const PARAM = "ids";

/**
 * B-1/E-4: a raw identifier -- a table's `id` column, or the `schema.table`
 * pair shown under a list/detail page's <h1> -- is real information a power
 * user occasionally needs (to copy a UUID, or map a page to its REST path),
 * but a planner using this app to model a domain should never see it by
 * default. Both are gated behind the same "?ids=1" URL flag, so DataTable's
 * existing "Show identifiers" toggle (E-4) also controls the schema.table
 * subtitle on list and detail pages (B-1) -- one mental model, one flag,
 * rather than a second control that happens to do something similar.
 */
export function useShowIdentifiers(): [boolean, () => void] {
  const [searchParams, setSearchParams] = useSearchParams();
  const show = searchParams.get(PARAM) === "1";

  function toggle() {
    const next = new URLSearchParams(searchParams);
    if (show) {
      next.delete(PARAM);
    } else {
      next.set(PARAM, "1");
    }
    setSearchParams(next);
  }

  return [show, toggle];
}
