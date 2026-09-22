import { describe, expect, it } from "vitest";
import {
  CARDINALITY_ENDS,
  CARDINALITY_LABEL,
  buildTypesView,
  erKind,
  underlined,
  withErDependents,
  entityTypeIdFromNodeId,
  objectsPalette,
  relationshipTypeIdFromEdgeId,
  relationshipTypeLabel,
  typeEdgeId,
  typeNodeId,
} from "./typesGraph";
import { LABEL_DARK, LABEL_LIGHT, fallbackColour, labelForeground } from "./colour";
import type { EntityType, RelationshipType } from "../api/v1";
import type { GraphResponse } from "../types/graph";

/**
 * The fixture is built so a wrong answer cannot look right.
 *
 * - `reports_to` is a **self-referencing hierarchy** (unit → unit), so it
 *   must come out as a loop on one node; `works_for` is an ordinary edge
 *   between two different types. With only the loop, a builder that
 *   swapped `from` and `to` would still look correct.
 * - `works_for` runs employee → unit, and employee and unit have different
 *   ids, names and roles, so a swap is visible in every field.
 * - The two entity types differ in role, which is what the types view's
 *   filter groups by.
 */
const EMPLOYEE: EntityType = {
  id: 11,
  domain_id: 1,
  name: "employee",
  role: "agent",
  colour: "#1f77b4",
  updated_at: "2026-09-20T09:00:00+00:00",
  attributes: [
    {
      id: 1,
      entity_type_id: 11,
      name: "grade",
      sort_order: 1,
      data_type: "integer",
      required: false,
      unit: null,
      enum_values: null,
      default_value: null,
    },
  ],
};

const UNIT: EntityType = {
  id: 22,
  domain_id: 1,
  name: "unit",
  role: "org",
  // No colour: this is the one that must get a deterministic fallback.
  colour: null,
  updated_at: "2026-09-20T09:00:00+00:00",
  attributes: [],
};

const REPORTS_TO: RelationshipType = {
  id: 5,
  domain_id: 1,
  name: "reports_to",
  from_type_id: 22,
  to_type_id: 22,
  cardinality: "one_to_many",
  is_hierarchy: true,
  colour: "#2ca02c",
  updated_at: "2026-09-20T09:00:00+00:00",
};

const WORKS_FOR: RelationshipType = {
  id: 6,
  domain_id: 1,
  name: "works_for",
  from_type_id: 11,
  to_type_id: 22,
  cardinality: "many_to_one",
  is_hierarchy: false,
  colour: null,
  updated_at: "2026-09-20T09:00:00+00:00",
};

describe("types-mode ids", () => {
  it("namespaces nodes and edges so an entity and an entity type cannot collide", () => {
    // Both the entity `3` and the entity type `3` exist; the canvas holds
    // one set of ids, and a mode switch has to look like remove + add, not
    // like an update of the same elements.
    expect(typeNodeId(3)).toBe("type-3");
    expect(typeEdgeId(3)).toBe("reltype-3");
    expect(typeNodeId(3)).not.toBe(typeEdgeId(3));
    expect(typeNodeId(3)).not.toBe("3");
  });

  it("reads the id back out, and refuses anything that is not one of ours", () => {
    expect(entityTypeIdFromNodeId("type-42")).toBe(42);
    expect(relationshipTypeIdFromEdgeId("reltype-42")).toBe(42);
    // An objects-mode id, the other kind's id, and junk.
    expect(entityTypeIdFromNodeId("42")).toBeNull();
    expect(entityTypeIdFromNodeId("reltype-42")).toBeNull();
    expect(relationshipTypeIdFromEdgeId("type-42")).toBeNull();
    expect(entityTypeIdFromNodeId("type-0")).toBeNull();
    expect(entityTypeIdFromNodeId("type-x")).toBeNull();
    expect(entityTypeIdFromNodeId("type-")).toBeNull();
  });
});

describe("relationshipTypeLabel", () => {
  it("names the type and shows its cardinality on a second line", () => {
    expect(relationshipTypeLabel(WORKS_FOR)).toBe(`works_for\n${CARDINALITY_LABEL.many_to_one}`);
  });

  it("marks a hierarchy", () => {
    expect(relationshipTypeLabel(REPORTS_TO)).toBe("reports_to\n1 → n · hierarchy");
  });

  it("gives each cardinality its own label", () => {
    expect(new Set(Object.values(CARDINALITY_LABEL)).size).toBe(4);
  });
});

describe("buildTypesView", () => {
  const { graph, palette } = buildTypesView([EMPLOYEE, UNIT], [REPORTS_TO, WORKS_FOR]);
  const ofKind = (kind: string) => graph.nodes.filter((node) => erKind(node) === kind);

  it("draws one rectangle per entity type, labelled with the type's name", () => {
    expect(ofKind("entity").map((node) => [node.id, node.label])).toEqual([
      ["type-11", "employee"],
      ["type-22", "unit"],
    ]);
    expect(palette.nodeData?.["type-11"]?.er).toBe("entity");
  });

  it("gives a rectangle its type's ROLE as `type`, which is what the filter groups by", () => {
    expect(ofKind("entity").map((node) => node.type)).toEqual(["agent", "org"]);
    // ... and offers exactly the roles present, not the whole role list.
    expect(graph.entity_types.map((option) => option.name)).toEqual(["agent", "org"]);
  });

  it("offers each role once, in a stable order, however the types are listed", () => {
    // The fixture above has one type per role, so it cannot tell a deduped
    // list from a raw one. Here two types share `agent` and the list is
    // given out of alphabetical order: a raw `map` would produce
    // ["task", "agent", "agent", "org"] -- three checkboxes for two roles,
    // two of them toggling the same thing, and the list jumping around as
    // types are added.
    const TASK: EntityType = { ...UNIT, id: 33, name: "job", role: "task" };
    const CONTRACTOR: EntityType = { ...EMPLOYEE, id: 44, name: "contractor", attributes: [] };
    const { graph: mixed } = buildTypesView([TASK, EMPLOYEE, CONTRACTOR, UNIT], []);
    expect(mixed.entity_types.map((option) => option.name)).toEqual(["agent", "org", "task"]);
    expect(mixed.entity_types.map((option) => option.id)).toEqual(["role-agent", "role-org", "role-task"]);
    // Both agents still get their own rectangle, coloured independently.
    expect(mixed.nodes.filter((node) => erKind(node) === "entity" && node.type === "agent")).toHaveLength(2);
  });

  it("nests nothing: the schema has no relationship rows to nest by", () => {
    expect(graph.nodes.every((node) => node.parent === null)).toBe(true);
    expect(graph.hierarchies).toEqual([]);
  });

  it("draws a relationship type as a diamond that keeps the relationship type's id", () => {
    // `reltype-<id>` is what the side panel resolves as a relationship type,
    // so the diamond can stand in for the edge it replaced.
    expect(ofKind("relationship").map((node) => [node.id, node.label])).toEqual([
      ["reltype-5", "reports_to"],
      ["reltype-6", "works_for"],
    ]);
    expect(palette.nodeData?.["reltype-5"]).toMatchObject({ selectKind: "edge", selectId: "reltype-5" });
  });

  it("runs each relationship from_type -> diamond -> to_type", () => {
    // That direction is what lets a layered layout set the diamond BETWEEN
    // the two types rather than below both.
    const lines = graph.edges
      .filter((edge) => palette.edgeData?.[edge.id]?.er === "connector")
      .map((edge) => [edge.id, edge.source, edge.target, palette.edgeData?.[edge.id]?.endAt]);
    expect(lines).toEqual([
      // The hierarchy: both lines on the one rectangle.
      ["rellink-5-from", "type-22", "reltype-5", "source"],
      ["rellink-5-to", "reltype-5", "type-22", "target"],
      // from_type -> to_type. A builder that swapped the two would put
      // employee on the `to` line, which the hierarchy could never reveal.
      ["rellink-6-from", "type-11", "reltype-6", "source"],
      ["rellink-6-to", "reltype-6", "type-22", "target"],
    ]);
  });

  it("writes each side's cardinality beside the type at that end", () => {
    // works_for is many-to-one: many employees work for one unit.
    expect(palette.edgeData?.["rellink-6-from"]?.end).toBe("n");
    expect(palette.edgeData?.["rellink-6-to"]?.end).toBe("1");
    expect(palette.edgeData?.["rellink-5-from"]?.end).toBe("1");
    expect(palette.edgeData?.["rellink-5-to"]?.end).toBe("n");
  });

  it("marks a hierarchy's diamond, and only that one", () => {
    expect(palette.nodeData?.["reltype-5"]?.hierarchy).toBe("yes");
    expect(palette.nodeData?.["reltype-6"]?.hierarchy).toBe("no");
  });

  it("draws each attribute as an ellipse joined to its owner, after the underlined key", () => {
    const ofEmployee = graph.nodes
      .filter((node) => erKind(node) === "attribute" && node.attributes?.owner === "type-11")
      .map((node) => [node.id, node.label, palette.nodeData?.[node.id]?.seq]);
    expect(ofEmployee).toEqual([
      ["typekey-11", underlined("key"), 0],
      ["attr-1", "grade", 1],
    ]);
    // A type with no attributes of its own still has its key.
    expect(graph.nodes.filter((node) => node.attributes?.owner === "type-22").map((node) => node.id)).toEqual([
      "typekey-22",
    ]);
    const link = graph.edges.find((edge) => edge.id === "attrlink-attr-1");
    expect([link?.source, link?.target]).toEqual(["type-11", "attr-1"]);
  });

  it("lays attributes out in their chosen order, not alphabetically (migration 0027)", () => {
    const attribute = (id: number, name: string, sort_order: number) => ({
      ...EMPLOYEE.attributes[0],
      id,
      name,
      sort_order,
    });
    const ordered: EntityType = {
      ...EMPLOYEE,
      // Given in neither order, to show the builder sorts by sort_order.
      attributes: [attribute(3, "alpha", 3), attribute(1, "zeta", 1), attribute(2, "mid", 2)],
    };
    const { graph: built, palette: drawn } = buildTypesView([ordered], []);
    const names = built.nodes
      .filter((node) => erKind(node) === "attribute")
      .sort((a, b) => (drawn.nodeData?.[a.id]?.seq ?? 0) - (drawn.nodeData?.[b.id]?.seq ?? 0))
      .map((node) => node.label);
    expect(names).toEqual([underlined("key"), "zeta", "mid", "alpha"]);
  });

  it("selects the owner when an ellipse or its line is tapped", () => {
    expect(palette.nodeData?.["attr-1"]).toMatchObject({ selectKind: "node", selectId: "type-11" });
    expect(palette.edgeData?.["attrlink-attr-1"]).toMatchObject({ selectKind: "node", selectId: "type-11" });
  });

  it("gives an ellipse the owner's role, so the role filter takes it along", () => {
    expect(graph.nodes.find((node) => node.id === "attr-1")?.type).toBe("agent");
  });

  it("draws relationship attributes round the diamond, selecting the relationship", () => {
    const withShare: RelationshipType = {
      ...WORKS_FOR,
      attributes: [{ ...EMPLOYEE.attributes[0], id: 9, entity_type_id: null, relationship_type_id: 6, name: "share" }],
    };
    const { graph: built, palette: drawn } = buildTypesView([EMPLOYEE, UNIT], [withShare]);
    expect(built.nodes.find((node) => node.id === "attr-9")?.attributes?.owner).toBe("reltype-6");
    expect(drawn.nodeData?.["attr-9"]).toMatchObject({ selectKind: "edge", selectId: "reltype-6" });
  });

  it("colours a rectangle from its type's colour, or a deterministic fallback", () => {
    expect(palette.nodeFill["type-11"]).toBe("#1f77b4");
    // `unit` has none, and the fallback is keyed on the entity type's own
    // id (22) -- not on the namespaced node id, and not on a list position.
    expect(palette.nodeFill["type-22"]).toBe(fallbackColour("22"));
  });

  it("colours a diamond from its relationship type, with the same fallback rule", () => {
    expect(palette.nodeFill["reltype-5"]).toBe("#2ca02c");
    expect(palette.nodeFill["reltype-6"]).toBe(fallbackColour("6"));
  });

  it("draws every ellipse white with dark text, whatever its owner's colour", () => {
    for (const node of graph.nodes.filter((candidate) => erKind(candidate) === "attribute")) {
      expect(palette.nodeFill[node.id]).toBe("#ffffff");
      expect(palette.nodeLabel[node.id]).toBe("#0f172a");
    }
  });

  it("gives every rectangle and diamond a label colour readable on its own fill", () => {
    for (const node of graph.nodes.filter((candidate) => erKind(candidate) !== "attribute")) {
      expect(palette.nodeLabel[node.id]).toBe(labelForeground(palette.nodeFill[node.id]));
      expect([LABEL_DARK, LABEL_LIGHT]).toContain(palette.nodeLabel[node.id]);
    }
  });

  it("keeps each type's colour when the list is reordered or filtered", () => {
    // The determinism that matters in practice: the same type must not
    // change colour because another one was added or removed.
    const reordered = buildTypesView([UNIT, EMPLOYEE], [WORKS_FOR, REPORTS_TO]);
    expect(reordered.palette.nodeFill).toEqual(palette.nodeFill);

    const filtered = buildTypesView([UNIT], [REPORTS_TO]);
    expect(filtered.palette.nodeFill["type-22"]).toBe(palette.nodeFill["type-22"]);
    expect(filtered.palette.nodeFill["reltype-5"]).toBe(palette.nodeFill["reltype-5"]);
  });

  it("drops a relationship type whose endpoints are not among the given entity types", () => {
    // Cytoscape throws synchronously on an edge to a node it was not
    // given, which would abort the whole update.
    const partial = buildTypesView([EMPLOYEE], [WORKS_FOR, REPORTS_TO]);
    expect(partial.graph.nodes.filter((node) => erKind(node) === "relationship")).toEqual([]);
    expect(partial.graph.edges.filter((edge) => edge.id.startsWith("rellink-"))).toEqual([]);
    expect(partial.graph.relationship_types).toEqual([]);
  });

  it("is empty, not broken, for a domain with no types", () => {
    const empty = buildTypesView([], []);
    expect(empty.graph.nodes).toEqual([]);
    expect(empty.graph.edges).toEqual([]);
    expect(empty.graph.entity_types).toEqual([]);
  });
});

describe("CARDINALITY_ENDS", () => {
  it("puts each side's number beside the type at that end", () => {
    expect(CARDINALITY_ENDS).toEqual({
      one_to_one: { from: "1", to: "1" },
      one_to_many: { from: "1", to: "n" },
      many_to_one: { from: "n", to: "1" },
      // Two independent "many"s, as the notation writes them.
      many_to_many: { from: "m", to: "n" },
    });
  });
});

describe("underlined", () => {
  it("puts a combining low line after every character", () => {
    expect(underlined("key")).toBe("k̲e̲y̲");
    expect(underlined("")).toBe("");
  });
});

describe("withErDependents", () => {
  const { graph } = buildTypesView([EMPLOYEE, UNIT], [REPORTS_TO, WORKS_FOR]);

  it("shows an ellipse exactly when its owner shows", () => {
    const shown = withErDependents(graph.nodes, (node) => node.id === "type-11");
    expect(shown.has("attr-1")).toBe(true);
    expect(shown.has("typekey-11")).toBe(true);
    expect(shown.has("typekey-22")).toBe(false);
  });

  it("shows a diamond only when both of its types show", () => {
    // Searching "employee" must not leave works_for pointing at a hidden unit.
    const employeeOnly = withErDependents(graph.nodes, (node) => node.id === "type-11");
    expect(employeeOnly.has("reltype-6")).toBe(false);
    const both = withErDependents(graph.nodes, (node) => node.id === "type-11" || node.id === "type-22");
    expect(both.has("reltype-6")).toBe(true);
    // The hierarchy needs only unit, which is both of its ends.
    const unitOnly = withErDependents(graph.nodes, (node) => node.id === "type-22");
    expect(unitOnly.has("reltype-5")).toBe(true);
  });

  it("never asks the filters about an ellipse or a diamond", () => {
    const asked: string[] = [];
    withErDependents(graph.nodes, (node) => {
      asked.push(node.id);
      return true;
    });
    expect(asked.sort()).toEqual(["type-11", "type-22"]);
  });

  it("passes an objects-view node straight through the filters", () => {
    const plain = [{ id: "1", attributes: {} }, { id: "2", attributes: {} }];
    expect([...withErDependents(plain, (node) => node.id === "2")]).toEqual(["2"]);
  });
});

describe("objectsPalette", () => {
  const graph: GraphResponse = {
    nodes: [
      { id: "1", type: "unit", label: "hq", parent: null, attributes: {} },
      { id: "2", type: "employee", label: "ahmed", parent: null, attributes: {} },
    ],
    edges: [
      { id: "10", source: "2", target: "1", type: "works_for", label: "works_for", attributes: {} },
      { id: "11", source: "1", target: "1", type: "reports_to", label: "reports_to", attributes: {} },
    ],
    entity_types: [
      { id: "11", code: "employee", name: "employee", is_abstract: false, colour: "#1f77b4" },
      { id: "22", code: "unit", name: "unit", is_abstract: false, colour: null },
    ],
    relationship_types: [
      {
        id: "5",
        code: "reports_to",
        name: "reports_to",
        is_directed: true,
        source_entity_type: "unit",
        target_entity_type: "unit",
        colour: "#2ca02c",
      },
      {
        id: "6",
        code: "works_for",
        name: "works_for",
        is_directed: true,
        source_entity_type: "employee",
        target_entity_type: "unit",
        colour: null,
      },
    ],
    hierarchies: [],
    attribute_definitions: [],
  };

  it("draws a node in its entity TYPE's colour, resolved through the node's type name", () => {
    const palette = objectsPalette(graph);
    // Node 2 is an employee, so it takes employee's colour -- not a colour
    // of its own, which entities do not have.
    expect(palette.nodeFill["2"]).toBe("#1f77b4");
    // Node 1 is a unit, which has none: the fallback is keyed on the
    // TYPE's id (22), so renaming the type would not change it and two
    // units always match each other.
    expect(palette.nodeFill["1"]).toBe(fallbackColour("22"));
  });

  it("draws an edge in its relationship type's colour", () => {
    const palette = objectsPalette(graph);
    expect(palette.edgeColour["11"]).toBe("#2ca02c");
    expect(palette.edgeColour["10"]).toBe(fallbackColour("6"));
  });

  it("gives every node a readable label colour", () => {
    const palette = objectsPalette(graph);
    for (const node of graph.nodes) {
      expect(palette.nodeLabel[node.id]).toBe(labelForeground(palette.nodeFill[node.id]));
    }
  });

  it("still colours a node whose type is missing from the options", () => {
    const orphan = objectsPalette({
      ...graph,
      nodes: [{ id: "9", type: "ghost", label: "g", parent: null, attributes: {} }],
    });
    expect(orphan.nodeFill["9"]).toBe(fallbackColour("ghost"));
    expect(orphan.nodeLabel["9"]).toBe(labelForeground(fallbackColour("ghost")));
  });
});
