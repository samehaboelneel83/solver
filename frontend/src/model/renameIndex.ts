/**
 * Renaming an item a rule or a total runs over ("for each v" -> "c"), and every place it is read
 * following the new name.
 */
import type { Binding } from "./terms";

/**
 * `value` with the item name `from` read as `to`: in the cells of decisions and data, the owner of
 * a field, and where a link is followed from -- except below a total that names its own `from`.
 * Benchmark, October 2026: renaming "for each v" to "c" left every "which" still on v.
 */
export function renameIndex<T>(value: T, from: string, to: string): T {
  if (from === to) return value;
  if (Array.isArray(value)) return value.map((item) => renameIndex(item, from, to)) as T;
  if (!value || typeof value !== "object") return value;
  const node = value as Record<string, unknown>;
  if (Array.isArray(node.over) && (node.over as Binding[]).some((b) => b.index === from)) return value;
  return Object.fromEntries(Object.entries(node).map(([key, inner]) => {
    if (key === "index" && Array.isArray(inner)) return [key, inner.map((cell) => (cell === from ? to : renameIndex(cell, from, to)))];
    if ((key === "of" || key === "from") && inner === from) return [key, to];
    return [key, renameIndex(inner, from, to)];
  })) as T;
}

/** The names changed in place between two lists of bindings, as [from, to]. */
function renamedBindings(before: Binding[], after: Binding[]): [string, string][] {
  if (before.length !== after.length) return [];
  return before.flatMap((b, i) => (b.index !== after[i].index && b.set === after[i].set ? [[b.index, after[i].index] as [string, string]] : []));
}

/** `body` and the bindings after the one renamed, following the names `next` changed. */
export function following<T>(before: Binding[], next: Binding[], body: T): { bindings: Binding[]; body: T } {
  let bindings = next;
  let out = body;
  for (const [from, to] of renamedBindings(before, next)) {
    const at = bindings.findIndex((b) => b.index === to);
    bindings = bindings.map((b, j) => (j > at ? renameIndex(b, from, to) : b));
    out = renameIndex(out, from, to);
  }
  return { bindings, body: out };
}
