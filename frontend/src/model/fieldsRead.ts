/**
 * Every record field a model reads -- `enrollment` of each section, `capacity`
 * of each room -- for the review before publishing (UX audit B-7: "The data
 * it reads" listed only parameters, and missed the fields the rules use).
 *
 * Walks each rule and goal term on its own, so an index letter means the set
 * its own bindings give it; a field read off a link (`of` a walk's `as`) is
 * named by the link.
 */
type Json = unknown;
export type FieldRead = { set: string; name: string; link?: boolean };

function bindings(node: Json, into: Map<string, { set: string; link?: boolean }>) {
  if (Array.isArray(node)) {
    node.forEach((item) => bindings(item, into));
    return;
  }
  if (!node || typeof node !== "object") return;
  const o = node as Record<string, Json>;
  if (typeof o.index === "string" && typeof o.set === "string") {
    into.set(o.index, { set: o.set });
    const via = o.via as { rel?: string; as?: string } | undefined;
    if (via?.as && via.rel) into.set(via.as, { set: via.rel, link: true });
  }
  Object.values(o).forEach((value) => bindings(value, into));
}

function reads(node: Json, scope: Map<string, { set: string; link?: boolean }>, out: Map<string, FieldRead>) {
  if (Array.isArray(node)) {
    node.forEach((item) => reads(item, scope, out));
    return;
  }
  if (!node || typeof node !== "object") return;
  const o = node as Record<string, Json>;
  const attr = o.attr as { of?: string; name?: string } | undefined;
  if (attr && typeof attr.name === "string") {
    const bound = scope.get(String(attr.of ?? ""));
    const set = bound?.set ?? "?";
    out.set(`${set}.${attr.name}`, { set, name: attr.name, ...(bound?.link ? { link: true } : {}) });
  }
  Object.values(o).forEach((value) => reads(value, scope, out));
}

export function fieldsRead(model: { constraints?: Json[]; objective?: { terms?: Json[] }; variables?: Record<string, Json> }): FieldRead[] {
  const out = new Map<string, FieldRead>();
  const pieces: Json[] = [...(model.constraints ?? []), ...(model.objective?.terms ?? []), ...Object.values(model.variables ?? {})];
  for (const piece of pieces) {
    const scope = new Map<string, { set: string; link?: boolean }>();
    bindings(piece, scope);
    reads(piece, scope, out);
  }
  return [...out.values()].sort((a, b) => a.set.localeCompare(b.set) || a.name.localeCompare(b.name));
}
