/**
 * Members in an order a person reads: "c2" before "c10" (UX audit C-4 --
 * result grids read Customer 1, 10, 11 ... 2). A run lists each set in the
 * order its records were given (their sort order, then their key); when that
 * is just the keys as text, nobody chose it, and numbers are put in number
 * order. An order someone did choose is kept as it is.
 */
const NATURAL = new Intl.Collator("en", { numeric: true, sensitivity: "base" });

export function naturalOrder(keys: string[]): string[] {
  const textual = [...keys].sort();
  if (keys.some((key, i) => key !== textual[i])) return keys;
  return [...keys].sort(NATURAL.compare);
}

export function naturalOrders(order: Record<string, string[]>): Record<string, string[]> {
  return Object.fromEntries(Object.entries(order).map(([set, keys]) => [set, naturalOrder(keys)]));
}
