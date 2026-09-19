/**
 * Fixtures for the expression core's tests. Test-only: nothing in the app
 * imports this, so it is tree-shaken out of the bundle.
 *
 * Shaped to exercise the three things that make this catalogue hard:
 *
 * - the SAME attribute name on two entity types with DIFFERENT data types
 *   (`capacity` is an integer on `unit` and a number on `shift`), so a
 *   catalogue keyed by bare name would type-check the wrong one;
 * - attribute names that COLLIDE with the entity's own columns (`key`,
 *   `active`, `label` -- Task 12 found this is legal), so a field identity
 *   that is a bare name is ambiguous;
 * - one attribute of every v1 data type, so the operator table and the
 *   value editors can be swept rather than sampled.
 */
import type { AttributeDef, EntityType, RelationshipType } from "../api/v1";

let nextId = 1000;

function attr(
  entityTypeId: number,
  name: string,
  data_type: AttributeDef["data_type"],
  extra: Partial<AttributeDef> = {}
): AttributeDef {
  nextId += 1;
  return {
    id: nextId,
    entity_type_id: entityTypeId,
    name,
    data_type,
    required: false,
    unit: null,
    enum_values: null,
    default_value: null,
    ...extra,
  };
}

export const UNIT_TYPE: EntityType = {
  id: 1,
  domain_id: 9,
  name: "unit",
  role: "resource",
  colour: "#1f77b4",
  attributes: [
    attr(1, "active", "boolean"),
    attr(1, "band", "enum", { enum_values: ["low", "high"] }),
    attr(1, "capacity", "integer", { required: true }),
    attr(1, "code", "text"),
    attr(1, "grade", "number"),
    attr(1, "key", "text"),
    attr(1, "opened", "date"),
    attr(1, "starts", "time"),
  ],
};

export const SHIFT_TYPE: EntityType = {
  id: 2,
  domain_id: 9,
  name: "shift",
  role: "time",
  colour: null,
  attributes: [
    // Same NAME as unit's, different DATA TYPE -- on purpose.
    attr(2, "capacity", "number"),
    attr(2, "label", "text"),
  ],
};

export const ENTITY_TYPES: EntityType[] = [UNIT_TYPE, SHIFT_TYPE];

export const WORKS_FOR: RelationshipType = {
  id: 10,
  domain_id: 9,
  name: "works_for",
  from_type_id: 2,
  to_type_id: 1,
  cardinality: "many_to_one",
  is_hierarchy: false,
  colour: null,
};

export const REPORTS_TO: RelationshipType = {
  id: 11,
  domain_id: 9,
  name: "reports_to",
  from_type_id: 1,
  to_type_id: 1,
  cardinality: "many_to_one",
  is_hierarchy: true,
  colour: null,
};

export const RELATIONSHIP_TYPES: RelationshipType[] = [WORKS_FOR, REPORTS_TO];
