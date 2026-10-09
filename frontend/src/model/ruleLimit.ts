export type RuleSides = { id: string; note?: string; severity?: string; left?: unknown; right?: unknown };

/** The number on the side of a rule that is one number -- what a scenario may change -- or null. */
export function ruleLimit(rule: RuleSides): number | null {
  for (const side of [rule.right, rule.left]) {
    if (side && typeof side === "object" && Object.keys(side).length === 1 && typeof (side as { const?: unknown }).const === "number") {
      return (side as { const: number }).const;
    }
  }
  return null;
}

/** A rule whose limit is one data value (`demand[m]`): the parameter, and for each of its indices either the rule's
 * own index (then which record, `set`) or a fixed key -- so a what-if changes that value for the instance chosen,
 * as the Assistant does (`limit_as_param`). Null when the limit is a number or anything more than one value. */
export function ruleLimitParam(rule: RuleSides & { forall?: { index: string; set: string }[] }):
  { param: string; at: ({ index: string; set: string } | { key: string })[] } | null {
  for (const side of [rule.right, rule.left]) {
    if (!side || typeof side !== "object") continue;
    const keys = Object.keys(side);
    const term = side as { par?: unknown; index?: unknown[] };
    if (typeof term.par !== "string" || keys.some((k) => k !== "par" && k !== "index")) continue;
    const forall = rule.forall ?? [];
    return {
      param: term.par,
      at: (term.index ?? []).map((i) => {
        const bound = forall.find((f) => f.index === String(i));
        return bound ? { index: bound.index, set: bound.set } : { key: String(i) };
      }),
    };
  }
  return null;
}
