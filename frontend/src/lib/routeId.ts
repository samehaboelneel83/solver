/**
 * A bigint primary key as it appears in a route or a query string: a plain
 * positive decimal integer, or nothing.
 *
 * Rejects "1.5", "1e3", " 4", "0", "-3" and anything beyond 2^53, none of
 * which an identity column produces -- so a mistyped URL shows "not found"
 * instead of issuing a request for `/api/v1/entities/NaN`. The same rule
 * `useDomain.parseId` applies to the stored domain id.
 */
export function parseRouteId(raw: string | undefined | null): number | null {
  if (!raw || !/^[1-9][0-9]*$/.test(raw)) return null;
  const id = Number(raw);
  return Number.isSafeInteger(id) ? id : null;
}
