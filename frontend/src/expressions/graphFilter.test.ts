import { describe, expect, it } from "vitest";
import type { GraphResponse } from "../types/graph";
import { EXPRESSION_VERSION, type ExpressionDocument } from "./document";
import { encodeFieldId } from "./fields";
import { degreeKey } from "./evaluate";
import { graphCatalogue, graphTargets, matchingNodeIds } from "./graphFilter";
import { ENTITY_TYPES, RELATIONSHIP_TYPES } from "./testFixtures";

/**
 * The graph's own adapter: what the loaded `GraphResponse` can honestly
 * answer, and nothing else.
 *
 * The payload carries `entity.attrs` verbatim and the relationships, but
 * NOT the entity's own columns -- `key`, `sort_order` and `active` are not
 * on the wire at all, and `label` is `entity.label OR entity.key`
 * (`graph/service.py:_node_label`), which is not the column. So the
 * catalogue built here deliberately offers no columns: a rule that meant
 * one thing on this canvas and another in Task 14d's SQL would be worse
 * than a rule that cannot be written.
 */

const GRAPH: GraphResponse = {
  nodes: [
    { id: "n1", type: "unit", label: "HQ", parent: null, attributes: { capacity: 10, code: "AB", band: "high" } },
    { id: "n2", type: "unit", label: "Ops", parent: null, attributes: { capacity: 2, code: "CD", band: "low" } },
    { id: "n3", type: "shift", label: "Morning", parent: null, attributes: { capacity: 10.5 } },
    { id: "n4", type: "ghost", label: "Unknown", parent: null, attributes: { capacity: 10 } },
  ],
  edges: [
    { id: "e1", source: "n3", target: "n1", type: "works_for", label: "works_for", attributes: {} },
    { id: "e2", source: "n3", target: "n2", type: "works_for", label: "works_for", attributes: {} },
    { id: "e3", source: "n1", target: "n1", type: "reports_to", label: "reports_to", attributes: {} },
  ],
  entity_types: [
    { id: "1", code: "unit", name: "unit", is_abstract: false, colour: null },
    { id: "2", code: "shift", name: "shift", is_abstract: false, colour: null },
  ],
  relationship_types: [
    { id: "10", code: "works_for", name: "works_for", is_directed: true, source_entity_type: "shift", target_entity_type: "unit", colour: null },
    { id: "11", code: "reports_to", name: "reports_to", is_directed: true, source_entity_type: "unit", target_entity_type: "unit", colour: null },
  ],
  hierarchies: [],
  attribute_definitions: [],
};

const catalogue = graphCatalogue(ENTITY_TYPES, RELATIONSHIP_TYPES);
const UNIT_CAPACITY = encodeFieldId({ kind: "attribute", entityTypeId: "1", attribute: "capacity" });
const SHIFT_CAPACITY = encodeFieldId({ kind: "attribute", entityTypeId: "2", attribute: "capacity" });

function expr(...rules: unknown[]): ExpressionDocument {
  return { version: EXPRESSION_VERSION, query: { combinator: "and", rules } } as ExpressionDocument;
}

describe("graphCatalogue", () => {
  it("offers attributes and relationship counts", () => {
    expect(catalogue.get(UNIT_CAPACITY)).toBeDefined();
    expect(
      catalogue.get(
        encodeFieldId({
          kind: "function",
          fn: "count",
          argument: { kind: "relationship", relationshipTypeId: "10", direction: "any" },
        })
      )
    ).toBeDefined();
  });

  it("offers none of the entity's own columns, because the graph payload does not carry them", () => {
    for (const column of ["key", "label", "sort_order", "active"] as const) {
      expect(catalogue.get(encodeFieldId({ kind: "column", column })), column).toBeUndefined();
    }
  });
});

describe("graphTargets", () => {
  it("keys the entity type by the id the catalogue uses, resolved through the node's type NAME", () => {
    const targets = graphTargets(GRAPH);
    expect(targets.get("n1")?.entityTypeId).toBe("1");
    expect(targets.get("n3")?.entityTypeId).toBe("2");
  });

  it("carries the node's attributes through unchanged", () => {
    expect(graphTargets(GRAPH).get("n1")?.attrs).toEqual({ capacity: 10, code: "AB", band: "high" });
  });

  it("counts each node's relationships by type and direction", () => {
    const targets = graphTargets(GRAPH);
    const shift = targets.get("n3")!;
    expect(shift.degrees.get(degreeKey("10", "outgoing"))).toBe(2);
    expect(shift.degrees.get(degreeKey("10", "incoming"))).toBeUndefined();
    const hq = targets.get("n1")!;
    expect(hq.degrees.get(degreeKey("10", "incoming"))).toBe(1);
    expect(hq.degrees.get(degreeKey("10", "outgoing"))).toBeUndefined();
  });

  it("counts a self-loop once in `any`, and in both directions separately", () => {
    // `reports_to` runs n1 -> n1. Counted as two rows in `any` it would
    // report 2 where the database holds 1 relationship row.
    const hq = graphTargets(GRAPH).get("n1")!;
    expect(hq.degrees.get(degreeKey("11", "outgoing"))).toBe(1);
    expect(hq.degrees.get(degreeKey("11", "incoming"))).toBe(1);
    expect(hq.degrees.get(degreeKey("11", "any"))).toBe(1);
    // ...while two distinct edges on the same node do count twice.
    expect(graphTargets(GRAPH).get("n3")!.degrees.get(degreeKey("10", "any"))).toBe(2);
  });

  it("skips a node whose entity type is not in the payload rather than guessing one", () => {
    expect(graphTargets(GRAPH).has("n4")).toBe(false);
  });
});

describe("matchingNodeIds", () => {
  it("returns the nodes that match and leaves out the ones that do not", () => {
    const ids = matchingNodeIds(GRAPH, catalogue, expr({ field: UNIT_CAPACITY, operator: ">", value: 5 }));
    expect(ids.has("n1")).toBe(true);
    expect(ids.has("n2")).toBe(false);
  });

  it("keeps every other type on the canvas when a rule names one type's attribute", () => {
    // HQ matches `unit.capacity > 5`; Ops does not. Morning is a shift, so
    // a unit rule is not a reason to hide it -- that used to empty the
    // rest of the canvas. A node we cannot type still does not sneak through.
    const ids = matchingNodeIds(GRAPH, catalogue, expr({ field: UNIT_CAPACITY, operator: ">", value: 5 }));
    expect([...ids].sort()).toEqual(["n1", "n3"]);
    expect(ids.has("n4")).toBe(false);
  });

  it("distinguishes the two entity types' same-named attributes", () => {
    // Threshold above both capacities, so a match-by-name would hide
    // everyone. Keeping the *other* type is what proves the field still
    // carries its owner, not that we matched the wrong `capacity`.
    expect([...matchingNodeIds(GRAPH, catalogue, expr({ field: SHIFT_CAPACITY, operator: ">", value: 20 }))].sort()).toEqual(
      ["n1", "n2"]
    );
    expect([...matchingNodeIds(GRAPH, catalogue, expr({ field: UNIT_CAPACITY, operator: ">", value: 20 }))]).toEqual([
      "n3",
    ]);
  });

  it("filters each type independently when the document names two types under and", () => {
    const ids = matchingNodeIds(
      GRAPH,
      catalogue,
      expr(
        { field: UNIT_CAPACITY, operator: ">", value: 5 },
        { field: SHIFT_CAPACITY, operator: ">", value: 5 }
      )
    );
    expect([...ids].sort()).toEqual(["n1", "n3"]);
  });

  it("a negated rule about one type does not hide the others", () => {
    const ids = matchingNodeIds(GRAPH, catalogue, {
      version: EXPRESSION_VERSION,
      query: {
        combinator: "and",
        not: true,
        rules: [{ field: UNIT_CAPACITY, operator: ">", value: 5 }],
      },
    } as ExpressionDocument);
    expect([...ids].sort()).toEqual(["n2", "n3"]);
  });

  it("returns every node for an empty expression, so it filters nothing", () => {
    const ids = matchingNodeIds(GRAPH, catalogue, {
      version: EXPRESSION_VERSION,
      query: { combinator: "and", rules: [] },
    } as ExpressionDocument);
    expect(ids.size).toBe(GRAPH.nodes.length);
    expect(ids.has("n4")).toBe(true);
  });

  it("matches on a relationship count", () => {
    const outgoing = encodeFieldId({
      kind: "function",
      fn: "count",
      argument: { kind: "relationship", relationshipTypeId: "10", direction: "outgoing" },
    });
    expect([...matchingNodeIds(GRAPH, catalogue, expr({ field: outgoing, operator: ">=", value: 2 }))]).toEqual(["n3"]);
    expect([...matchingNodeIds(GRAPH, catalogue, expr({ field: outgoing, operator: "=", value: 0 }))].sort()).toEqual([
      "n1",
      "n2",
    ]);
  });

  it("leaves a node it cannot type out of the result rather than passing it through", () => {
    const ids = matchingNodeIds(GRAPH, catalogue, expr({ field: UNIT_CAPACITY, operator: ">", value: 0 }));
    expect(ids.has("n4")).toBe(false);
    expect(ids.has("n1")).toBe(true);
  });
});
