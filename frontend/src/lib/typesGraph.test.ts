import { describe, expect, it } from "vitest";
import {
  CARDINALITY_LABEL,
  buildTypesView,
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
  attributes: [
    {
      id: 1,
      entity_type_id: 11,
      name: "grade",
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

  it("draws one node per entity type, labelled with the type's name", () => {
    expect(graph.nodes.map((node) => [node.id, node.label])).toEqual([
      ["type-11", "employee"],
      ["type-22", "unit"],
    ]);
  });

  it("gives a node its type's ROLE as `type`, which is what the filter groups by", () => {
    expect(graph.nodes.map((node) => node.type)).toEqual(["agent", "org"]);
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
    const CONTRACTOR: EntityType = { ...EMPLOYEE, id: 44, name: "contractor" };
    const { graph: mixed } = buildTypesView([TASK, EMPLOYEE, CONTRACTOR, UNIT], []);
    expect(mixed.entity_types.map((option) => option.name)).toEqual([
      "agent",
      "org",
      "task",
    ]);
    expect(mixed.entity_types.map((option) => option.id)).toEqual([
      "role-agent",
      "role-org",
      "role-task",
    ]);
    // Both agents still get their own node, coloured independently.
    expect(mixed.nodes.filter((node) => node.type === "agent")).toHaveLength(2);
  });

  it("nests nothing: the schema has no relationship rows to nest by", () => {
    expect(graph.nodes.every((node) => node.parent === null)).toBe(true);
    expect(graph.hierarchies).toEqual([]);
  });

  it("draws a self-referencing hierarchy as a loop and an ordinary type as a directed edge", () => {
    const bySource = graph.edges.map((edge) => [edge.type, edge.source, edge.target]);
    expect(bySource).toEqual([
      // The loop: both ends are the same node.
      ["reports_to", "type-22", "type-22"],
      // The ordinary edge, from_type -> to_type. A builder that swapped
      // the two would give ["works_for", "type-22", "type-11"] here, which
      // the loop above could never reveal.
      ["works_for", "type-11", "type-22"],
    ]);
  });

  it("labels an edge with its name, cardinality and whether it is a hierarchy", () => {
    expect(graph.edges.map((edge) => edge.label)).toEqual([
      "reports_to\n1 → n · hierarchy",
      "works_for\nn → 1",
    ]);
    expect(graph.edges.map((edge) => edge.attributes)).toEqual([
      { cardinality: "one_to_many", is_hierarchy: true },
      { cardinality: "many_to_one", is_hierarchy: false },
    ]);
  });

  it("colours a node from its type's colour, or a deterministic fallback", () => {
    expect(palette.nodeFill["type-11"]).toBe("#1f77b4");
    // `unit` has none, and the fallback is keyed on the entity type's own
    // id (22) -- not on the namespaced node id, and not on a list position.
    expect(palette.nodeFill["type-22"]).toBe(fallbackColour("22"));
  });

  it("colours an edge from its relationship type, with the same fallback rule", () => {
    expect(palette.edgeColour["reltype-5"]).toBe("#2ca02c");
    expect(palette.edgeColour["reltype-6"]).toBe(fallbackColour("6"));
  });

  it("gives every node a label colour that is readable on its own fill", () => {
    for (const node of graph.nodes) {
      expect(palette.nodeLabel[node.id]).toBe(labelForeground(palette.nodeFill[node.id]));
      expect([LABEL_DARK, LABEL_LIGHT]).toContain(palette.nodeLabel[node.id]);
    }
  });

  it("keeps each type's colour when the list is reordered or filtered", () => {
    // The determinism that matters in practice: the same type must not
    // change colour because another one was added or removed.
    const reordered = buildTypesView([UNIT, EMPLOYEE], [WORKS_FOR, REPORTS_TO]);
    expect(reordered.palette.nodeFill).toEqual(palette.nodeFill);
    expect(reordered.palette.edgeColour).toEqual(palette.edgeColour);

    const filtered = buildTypesView([UNIT], [REPORTS_TO]);
    expect(filtered.palette.nodeFill["type-22"]).toBe(palette.nodeFill["type-22"]);
    expect(filtered.palette.edgeColour["reltype-5"]).toBe(palette.edgeColour["reltype-5"]);
  });

  it("drops a relationship type whose endpoints are not among the given entity types", () => {
    // Cytoscape throws synchronously on an edge to a node it was not
    // given, which would abort the whole update.
    const partial = buildTypesView([EMPLOYEE], [WORKS_FOR, REPORTS_TO]);
    expect(partial.graph.edges).toEqual([]);
    expect(partial.graph.relationship_types).toEqual([]);
    expect(partial.palette.edgeColour).toEqual({});
  });

  it("is empty, not broken, for a domain with no types", () => {
    const empty = buildTypesView([], []);
    expect(empty.graph.nodes).toEqual([]);
    expect(empty.graph.edges).toEqual([]);
    expect(empty.graph.entity_types).toEqual([]);
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
