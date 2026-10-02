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
