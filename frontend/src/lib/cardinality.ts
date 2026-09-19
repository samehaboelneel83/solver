/**
 * The `relationship_type.cardinality` vocabulary, in one place.
 *
 * It was `CARDINALITY_LABEL` inside `typesGraph.ts` while the graph's edge
 * labels were its only reader. Task 14f's relationship-type form is the
 * third consumer (`typesGraph`, `PropertyPanel`, the form), which is the
 * point Ruling 22 draws the line at, so it moved here -- a module a plain
 * CRUD page can import without pulling the cytoscape-shaped graph helpers
 * in with it.
 *
 * The four labels are `backend/app/api/relationships.py`'s `Cardinality`
 * Literal, which is itself the table CHECK in migration 0006. Nothing
 * keeps the copies in step automatically; see the note carried forward
 * from Task 14b about `colour` living in three places.
 */

import type { Cardinality } from "../api/v1";

/** In words. A `Record<Cardinality, …>`, so the compiler refuses a copy
 * that has drifted from the API's union. */
export const CARDINALITY_NAME: Record<Cardinality, string> = {
  one_to_one: "One to one",
  one_to_many: "One to many",
  many_to_one: "Many to one",
  many_to_many: "Many to many",
};

/** How a cardinality reads on a graph edge label: short, because it is
 * drawn on a canvas beside the type's name. */
export const CARDINALITY_LABEL: Record<Cardinality, string> = {
  one_to_one: "1 → 1",
  one_to_many: "1 → n",
  many_to_one: "n → 1",
  many_to_many: "n → n",
};

/** The API's own declaration order, which is also the order that reads
 * naturally in a picker (the two strict ends first). */
export const CARDINALITY_ORDER: readonly Cardinality[] = [
  "one_to_one",
  "one_to_many",
  "many_to_one",
  "many_to_many",
];

/** Words plus the graph's short form, so the picker and the canvas can be
 * read against each other. */
export function cardinalityOptionLabel(value: Cardinality): string {
  return `${CARDINALITY_NAME[value]} (${CARDINALITY_LABEL[value]})`;
}

export const CARDINALITIES: { value: Cardinality; label: string }[] = CARDINALITY_ORDER.map((value) => ({
  value,
  label: cardinalityOptionLabel(value),
}));

/**
 * The only cardinality a hierarchy may have. Not a preference: migration
 * 0006 carries `CHECK (NOT is_hierarchy OR (from_type_id = to_type_id AND
 * cardinality = 'one_to_many'))`, because a hierarchy is read as
 * "from_entity is the parent of to_entity" and each child has at most one
 * parent.
 */
export const HIERARCHY_CARDINALITY: Cardinality = "one_to_many";
