import { describe, expect, it } from "vitest";
import { ApiError } from "../api/client";
import type { Entity, RelationshipType } from "../api/v1";
import {
  connectionKey,
  connectionLabel,
  connectionOptions,
  endsFor,
  entityLabel,
  relationshipProblems,
} from "./relationships";

function relType(over: Partial<RelationshipType> & { id: number; name: string }): RelationshipType {
  return {
    domain_id: 7,
    from_type_id: 1,
    to_type_id: 2,
    cardinality: "many_to_many",
    is_hierarchy: false,
    colour: null,
    updated_at: "2026-09-20T09:00:00+00:00",
    ...over,
  };
}

// employee(1) -> unit(2), and unit(2) -> unit(2) as a hierarchy.
const WORKS_IN = relType({ id: 5, name: "works_in", from_type_id: 1, to_type_id: 2, cardinality: "many_to_one" });
const REPORTS_TO = relType({
  id: 6,
  name: "reports_to",
  from_type_id: 2,
  to_type_id: 2,
  cardinality: "one_to_many",
  is_hierarchy: true,
});
const TYPES = [REPORTS_TO, WORKS_IN];

function error422(detail: unknown[]): ApiError {
  return new ApiError(422, JSON.stringify({ detail }));
}

describe("connectionOptions", () => {
  it("offers the one direction a cross-type relationship can go for an employee", () => {
    const options = connectionOptions(TYPES, 1);
    expect(options).toHaveLength(1);
    expect(options[0]).toMatchObject({ role: "from", otherTypeId: 2 });
    expect(options[0].type.name).toBe("works_in");
  });

  it("offers a unit BOTH ends of a hierarchy, which is the half the graph hid", () => {
    // A unit needs to be able to gain a parent and to gain a child. Those
    // are the same row read from opposite ends, so a screen that offered
    // one of them would leave half the hierarchy unbuildable.
    const options = connectionOptions(TYPES, 2).filter((o) => o.type.name === "reports_to");
    expect(options.map((o) => o.role)).toEqual(["from", "to"]);
    expect(options.map((o) => o.key)).toEqual([connectionKey(6, "from"), connectionKey(6, "to")]);
    // Both ends of a hierarchy are the same entity type, by the table CHECK.
    expect(options.every((o) => o.otherTypeId === 2)).toBe(true);
  });

  it("offers a unit the far end of works_in as well, as the To end", () => {
    const options = connectionOptions(TYPES, 2);
    const worksIn = options.filter((o) => o.type.name === "works_in");
    expect(worksIn).toHaveLength(1);
    expect(worksIn[0]).toMatchObject({ role: "to", otherTypeId: 1 });
  });

  it("offers nothing for an entity type no relationship type mentions", () => {
    expect(connectionOptions(TYPES, 99)).toEqual([]);
  });
});

describe("connectionLabel", () => {
  it("reads in the type's own direction, so the two ends cannot be confused", () => {
    const [outgoing] = connectionOptions(TYPES, 1);
    expect(connectionLabel(outgoing, "Ahmed Salah", "unit")).toBe("Ahmed Salah works_in a unit");
  });

  it("puts the other end first when the known entity is the To end", () => {
    const incoming = connectionOptions(TYPES, 2).find((o) => o.type.name === "works_in")!;
    expect(connectionLabel(incoming, "North Depot", "employee")).toBe("a employee works_in North Depot");
  });

  it("gives a hierarchy's two options different sentences", () => {
    const [asParent, asChild] = connectionOptions(TYPES, 2).filter((o) => o.type.name === "reports_to");
    expect(connectionLabel(asParent, "Head Office", "unit")).toBe("Head Office reports_to a unit");
    expect(connectionLabel(asChild, "Head Office", "unit")).toBe("a unit reports_to Head Office");
  });
});

describe("endsFor", () => {
  it("puts the known entity on the end its option names, and the chosen one on the other", () => {
    const [outgoing] = connectionOptions(TYPES, 1);
    expect(endsFor(outgoing, 17, 4)).toEqual({ from_entity_id: 17, to_entity_id: 4 });

    const incoming = connectionOptions(TYPES, 2).find((o) => o.type.name === "works_in")!;
    expect(endsFor(incoming, 4, 17)).toEqual({ from_entity_id: 17, to_entity_id: 4 });
  });
});

describe("entityLabel", () => {
  const entity = (over: Partial<Entity> & { id: number; key: string }): Entity => ({
    entity_type_id: 1,
    label: null,
    sort_order: 0,
    active: true,
    attrs: {},
    updated_at: "2026-09-20T09:00:00+00:00",
    ...over,
  });
  const map = new Map<number, Entity>([
    [1, entity({ id: 1, key: "ahmed", label: "Ahmed Salah" })],
    [2, entity({ id: 2, key: "bilal", label: null })],
    [3, entity({ id: 3, key: "carla", label: "   " })],
  ]);

  it("prefers the label", () => {
    expect(entityLabel(map, 1)).toBe("Ahmed Salah");
  });

  it("falls back to the key, like the graph read does, rather than showing nothing", () => {
    expect(entityLabel(map, 2)).toBe("bilal");
    expect(entityLabel(map, 3)).toBe("carla");
  });

  it("admits an id it has not loaded rather than rendering a blank cell", () => {
    expect(entityLabel(map, 404)).toBe("#404");
  });
});

describe("relationshipProblems", () => {
  it("puts a body-field 422 on that control (Ruling 30: loc says what was wrong)", () => {
    const { fields, general } = relationshipProblems(
      error422([{ loc: ["body", "to_entity_id"], msg: "Input should be a valid integer" }])
    );
    expect(fields.to_entity_id).toBe("to_entity_id: Input should be a valid integer");
    expect(general).toBeNull();
  });

  it("puts the From-end cardinality refusal on the From control, reworded", () => {
    const { fields, general } = relationshipProblems(
      error422([
        {
          loc: ["body", "works_in"],
          msg: 'relationship "works_in": source already has a target',
          kind: "cardinality",
        },
      ])
    );
    expect(fields.from_entity_id).toMatch(/allows each From entity at most one To entity/);
    expect(fields.from_entity_id).not.toMatch(/source|target/);
    expect(fields.to_entity_id).toBeUndefined();
    expect(general).toBeNull();
  });

  it("puts the To-end one on the To control, which is the other half of the same rule", () => {
    const { fields } = relationshipProblems(
      error422([
        {
          loc: ["body", "reports_to"],
          msg: 'relationship "reports_to": target already has a source',
          kind: "cardinality",
        },
      ])
    );
    expect(fields.to_entity_id).toMatch(/allows each To entity at most one From entity/);
    expect(fields.from_entity_id).toBeUndefined();
  });

  it("leaves a cycle at form level, because it is about the pair and not about one end", () => {
    const { fields, general } = relationshipProblems(
      error422([
        {
          loc: ["body", "reports_to"],
          msg: 'relationship "reports_to": would create a cycle',
          kind: "cycle",
        },
      ])
    );
    expect(fields).toEqual({});
    expect(general).toBe('relationship "reports_to": would create a cycle');
  });

  it("leaves a type mismatch at form level too, since it judges the type against both ends", () => {
    const { fields, general } = relationshipProblems(
      error422([
        {
          loc: ["body", "works_in"],
          msg: 'relationship "works_in": entity types do not match',
          kind: "type_mismatch",
        },
      ])
    );
    expect(fields).toEqual({});
    expect(general).toMatch(/entity types do not match/);
  });

  it("does not guess a control for a trigger rule it has never seen", () => {
    // A rule added to `relationship_validate` later arrives with the same
    // `loc` and, quite possibly, `kind: "cardinality"`. Placing it by kind
    // would pin it to a control it may have nothing to do with.
    const { fields, general } = relationshipProblems(
      error422([
        {
          loc: ["body", "works_in"],
          msg: 'relationship "works_in": some rule from a later migration',
          kind: "cardinality",
        },
      ])
    );
    expect(fields).toEqual({});
    expect(general).toBe('relationship "works_in": some rule from a later migration');
  });

  it("names the unique constraint for what it is", () => {
    const { fields, general } = relationshipProblems(
      new ApiError(
        409,
        JSON.stringify({
          detail: "a relationship row with the same relationship_type_id_from_entity_id_to_entity_id already exists",
        })
      )
    );
    expect(fields).toEqual({});
    expect(general).toBe("These two entities are already connected by this relationship type.");
  });

  it("keeps several entries apart, placing each by its own rule", () => {
    const { fields, general } = relationshipProblems(
      error422([
        { loc: ["body", "works_in"], msg: 'relationship "works_in": source already has a target' },
        { loc: ["body", "to_entity_id"], msg: "entity 42 does not exist" },
        { loc: ["body", "works_in"], msg: 'relationship "works_in": would create a cycle' },
      ])
    );
    expect(fields.from_entity_id).toMatch(/at most one To entity/);
    expect(fields.to_entity_id).toBe("to_entity_id: entity 42 does not exist");
    expect(general).toBe('relationship "works_in": would create a cycle');
  });

  it("falls back to the shared formatter for anything else", () => {
    expect(relationshipProblems(new ApiError(500, "boom")).general).toMatch(/Server error \(500\)/);
  });
});
