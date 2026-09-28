/**
 * Where a person put the cards of a problem's Visual Graph (plan §7.3, M4).
 * Presentation only: kept apart from the draft and never in the IR, so
 * arranging cards cannot change the model, its hash, or its undo history.
 * Stored per account and problem in this browser, keyed by the cards'
 * stable ids, so it survives reloads, view changes and model edits.
 */
import { accountNamespace } from "./draftStore";

export type Positions = Record<string, { x: number; y: number }>;

const PREFIX = "solver_graph_layout_v1:";
/** More cards than any model the editor draws; a guard against runaway storage. */
const MAX_CARDS = 2000;

const keyOf = (layoutKey: string) => `${PREFIX}${accountNamespace()}:${layoutKey}`;

function isPositions(value: unknown): value is Positions {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  return Object.values(value).every((p) => {
    const point = p as { x?: unknown; y?: unknown } | null;
    return !!point && Number.isFinite(point.x) && Number.isFinite(point.y);
  });
}

export function readLayout(layoutKey: string): Positions {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(keyOf(layoutKey)) ?? "{}");
    return isPositions(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

/** False when storage refused it: the layout then lasts only for this page. */
export function writeLayout(layoutKey: string, positions: Positions): boolean {
  try {
    const ids = Object.keys(positions);
    if (ids.length === 0) localStorage.removeItem(keyOf(layoutKey));
    else localStorage.setItem(keyOf(layoutKey), JSON.stringify(ids.length > MAX_CARDS
      ? Object.fromEntries(ids.slice(-MAX_CARDS).map((id) => [id, positions[id]])) : positions));
    return true;
  } catch {
    return false;
  }
}
