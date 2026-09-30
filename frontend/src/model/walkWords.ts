/** A walk along a relationship, in words. */
import type { Via } from "./terms";

export const DEPTH_WORDS: Record<string, string> = {
  one: "in 1 step",
  any: "in 1 or more steps",
  any_or_self: "in 0 or more steps (itself too)",
};

/** A walk in words: "linked from m by manages in 1 or more steps (each link called r)". */
export function walkWords(via: Via): string {
  const from = via.from !== undefined;
  const anchor = (via.from ?? via.to) as string;
  const depth = via.depth && via.depth !== "one" ? ` ${DEPTH_WORDS[via.depth] ?? via.depth}` : "";
  const edge = via.as ? ` (each link called ${via.as})` : "";
  return `linked ${from ? "from" : "to"} ${anchor} by ${via.rel}${depth}${edge}`;
}
