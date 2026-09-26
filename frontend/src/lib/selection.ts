/**
 * Resolve an optional URL id against a loaded list (OAAS §3.6 / N02).
 *
 * Defaults apply only when nothing was requested. An explicit id that is not
 * in the list is never replaced by another object.
 */
export function resolveById<T>(
  items: readonly T[],
  requestedId: number | null,
  idOf: (item: T) => number
): { item: T | null; missing: boolean } {
  if (requestedId === null) {
    return { item: items[0] ?? null, missing: false };
  }
  const item = items.find((row) => idOf(row) === requestedId) ?? null;
  return { item, missing: item === null };
}
