/** A walk along a relationship, in words. */
import type { Steps, Via } from "./terms";
import { entryWords } from "./whereWords";

export const DEPTH_WORDS: Record<string, string> = {
  one: "in 1 step",
  any: "in 1 or more steps",
  any_or_self: "in 0 or more steps (itself too)",
};

/** How far, in words: "in 2 to 3 steps", "in 2 or more steps", "in exactly 2 steps". */
export function stepsWords(steps: Steps): string {
  const self = steps.min === 0 ? " (itself too)" : "";
  if (steps.max === undefined) return `in ${steps.min} or more steps${self}`;
  if (steps.max === steps.min) return steps.min === 1 ? "in 1 step" : `in exactly ${steps.min} steps`;
  return `in ${steps.min} to ${steps.max} steps${self}`;
}

/**
 * A walk in words: "below m by manages in 1 or more steps (each link called r)",
 * "linked to u by belongs_to", "linked either way to c by adjacent in 2 steps",
 * with "through links whose share is above 0" and "on 2026-10-01" when it has them.
 */
export function walkWords(via: Via, hierarchy = false): string {
  const end = via.from !== undefined ? "from" : via.both !== undefined ? "both" : "to";
  const anchor = (via.from ?? via.both ?? via.to) as string;
  const depth = via.steps
    ? ` ${stepsWords(via.steps)}`
    : via.depth && via.depth !== "one" ? ` ${DEPTH_WORDS[via.depth] ?? via.depth}` : "";
  const through = via.where?.length ? ` through links whose ${via.where.map((entry) => entryWords(entry)).join(" and ")}` : "";
  const on = via.on ? ` on ${via.on}` : "";
  const edge = via.as ? ` (each link called ${via.as})` : "";
  // A hierarchy runs from parent to child, so from its parent end is "below" and back is "above".
  const lead = end === "both"
    ? "linked either way to"
    : hierarchy ? (end === "from" ? "below" : "above") : `linked ${end}`;
  return `${lead} ${anchor} by ${via.rel}${depth}${through}${on}${edge}`;
}
