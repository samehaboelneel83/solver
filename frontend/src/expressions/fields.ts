import type { AttrType, EntityType, Id } from "../api/v1";
import { EXPRESSION_FUNCTIONS, functionReturnType } from "./functions";
import { OPERATORS_BY_TYPE } from "./operators";

/**
 * What an expression may name, and how a name travels.
 *
 * A rule stores its field as ONE string, because that is what
 * react-querybuilder's `RuleType.field` is and this format is a documented
 * subset of its own (see `document.ts`). That string has to be an
 * unambiguous IDENTITY rather than a bare name, for two reasons this
 * schema actually produces:
 *
 * - an entity type may legally declare an attribute called `key`, `label`,
 *   `sort_order` or `active` -- the same names as the entity's own columns
 *   (Task 12 found this);
 * - two entity types may each declare `capacity`, with different data
 *   types. A catalogue keyed by name would type-check one rule against the
 *   other's definition.
 *
 * So the id names the source as well as the name, and this module owns
 * both directions of that encoding. Task 14d reads the same strings.
 *
 *   col:<column>                      an entity column
 *   attr:<entityTypeId>:<name>        an attribute of one entity type
 *   fn:<function>:<argument>          a call, one level deep
 *   rel:<relTypeId>:<direction>       only ever a call's argument
 *
 * `:` cannot occur inside any part: attribute names match
 * `^[a-z][a-z0-9_]*$` (the server's rule), ids are digits, and the
 * function and direction vocabularies are closed.
 */

export type RelationshipDirection = "outgoing" | "incoming" | "any";
export const RELATIONSHIP_DIRECTIONS: readonly RelationshipDirection[] = ["outgoing", "incoming", "any"];

export type EntityColumnName = "key" | "label" | "sort_order" | "active";

export type ColumnRef = { kind: "column"; column: EntityColumnName };
export type AttributeRef = { kind: "attribute"; entityTypeId: string; attribute: string };
export type RelationshipRef = {
  kind: "relationship";
  relationshipTypeId: string;
  direction: RelationshipDirection;
};
export type BaseRef = ColumnRef | AttributeRef;
export type FunctionRef = { kind: "function"; fn: string; argument: BaseRef | RelationshipRef };
export type FieldRef = BaseRef | FunctionRef;

/**
 * The entity's own columns, as expression fields.
 *
 * `entity` has exactly these four beyond `id`, `entity_type_id` and
 * `attrs`. They are part of the SHARED catalogue because Task 14d has them
 * all as real columns; a consumer that cannot answer for one (the graph
 * payload carries none of them faithfully) narrows the list with
 * `columns`.
 */
export const ENTITY_COLUMNS: readonly {
  column: EntityColumnName;
  label: string;
  dataType: AttrType;
  nullable: boolean;
}[] = [
  { column: "key", label: "key", dataType: "text", nullable: false },
  // The only nullable one: `label` is optional on every entity.
  { column: "label", label: "label", dataType: "text", nullable: true },
  { column: "sort_order", label: "sort order", dataType: "integer", nullable: false },
  { column: "active", label: "active", dataType: "boolean", nullable: false },
];

const COLUMN_NAMES = new Set<string>(ENTITY_COLUMNS.map((c) => c.column));
const ID_RE = /^\d+$/;

export function encodeFieldId(ref: FieldRef | RelationshipRef): string {
  switch (ref.kind) {
    case "column":
      return `col:${ref.column}`;
    case "attribute":
      return `attr:${ref.entityTypeId}:${ref.attribute}`;
    case "relationship":
      return `rel:${ref.relationshipTypeId}:${ref.direction}`;
    case "function":
      return `fn:${ref.fn}:${encodeFieldId(ref.argument)}`;
  }
}

function decodeArgument(id: string): BaseRef | RelationshipRef | null {
  const parts = id.split(":");
  if (parts[0] === "col") {
    return parts.length === 2 && COLUMN_NAMES.has(parts[1])
      ? { kind: "column", column: parts[1] as EntityColumnName }
      : null;
  }
  if (parts[0] === "attr") {
    return parts.length === 3 && ID_RE.test(parts[1]) && parts[2] !== ""
      ? { kind: "attribute", entityTypeId: parts[1], attribute: parts[2] }
      : null;
  }
  if (parts[0] === "rel") {
    return parts.length === 3 &&
      ID_RE.test(parts[1]) &&
      (RELATIONSHIP_DIRECTIONS as readonly string[]).includes(parts[2])
      ? {
          kind: "relationship",
          relationshipTypeId: parts[1],
          direction: parts[2] as RelationshipDirection,
        }
      : null;
  }
  return null;
}

/**
 * The reference an id names, or null when the id is not one this version
 * expresses.
 *
 * A bare `rel:...` is null: a relationship is only ever `count`'s
 * argument, never a field in its own right. A nested call is null too --
 * version 1 is one level deep, and reading `fn:abs:fn:year:x` as
 * `abs(fn)` would quietly drop a level.
 */
export function decodeFieldId(id: string): FieldRef | null {
  if (!id) return null;
  const parts = id.split(":");
  if (parts[0] !== "fn") {
    const base = decodeArgument(id);
    return base && base.kind !== "relationship" ? base : null;
  }
  if (parts.length < 3) return null;
  const fn = parts[1];
  const argumentId = parts.slice(2).join(":");
  if (argumentId.startsWith("fn:")) return null;
  const argument = decodeArgument(argumentId);
  if (!argument) return null;
  return { kind: "function", fn, argument };
}

/** One thing an expression may name, ready for the builder and the
 * validator. */
export type ExpressionField = {
  /** What the document stores. */
  id: string;
  /** What the builder shows. */
  label: string;
  /** The option group the builder lists it under. */
  group: string;
  /** The type of the VALUE this field yields -- a call's return type, not
   * its argument's. */
  dataType: AttrType;
  /** Whether the value can be absent, which is what the null operators are
   * for. */
  nullable: boolean;
  /** An enum attribute's own allowed values, or null. */
  enumValues: string[] | null;
  ref: FieldRef;
};

export type FieldCatalogue = {
  fields: ExpressionField[];
  get(id: string): ExpressionField | undefined;
};

export const COLUMN_GROUP = "Every entity";
export const RELATIONSHIP_GROUP = "Relationships";

export type RelationshipTypeRef = { id: Id | string; name: string };

export type FieldCatalogueInput = {
  entityTypes: readonly EntityType[];
  /** Given, `count(...)` is offered over each of them. Only the id and the
   * name are used, so either `RelationshipType` (the v1 API) or the graph
   * payload's `RelationshipTypeOption` fits -- the graph already lists
   * them, which is what keeps the builder free of an extra request. */
  relationshipTypes?: readonly RelationshipTypeRef[];
  /** Which of the entity's own columns this consumer can actually answer
   * for. Defaults to all four. */
  columns?: readonly EntityColumnName[];
};

/**
 * Every field the given domain can be asked about: its columns, its
 * attributes, and each function of the catalogue applied to the arguments
 * whose type it accepts.
 *
 * The function fields are generated rather than chosen, which is what
 * keeps `functions.ts` a table instead of a set of special cases: a
 * function is offered exactly where its declared `argumentTypes` allow it,
 * and it carries its own return type from there.
 */
export function buildFieldCatalogue(input: FieldCatalogueInput): FieldCatalogue {
  const columns = input.columns ?? ENTITY_COLUMNS.map((c) => c.column);
  const wanted = new Set<string>(columns);
  const fields: ExpressionField[] = [];

  const addWithFunctions = (base: ExpressionField) => {
    fields.push(base);
    if (base.ref.kind === "function") return;
    for (const def of Object.values(EXPRESSION_FUNCTIONS)) {
      if (def.argument !== "field") continue;
      if (!def.argumentTypes.includes(base.dataType)) continue;
      fields.push({
        id: encodeFieldId({ kind: "function", fn: def.name, argument: base.ref as BaseRef }),
        label: `${def.name}(${base.label})`,
        group: base.group,
        dataType: functionReturnType(def, base.dataType),
        // A function of an absent value is absent, and SQL says the same;
        // but `is empty` on a call is confusing UI, so calls are compared
        // rather than tested for emptiness.
        nullable: false,
        enumValues: null,
        ref: { kind: "function", fn: def.name, argument: base.ref as BaseRef },
      });
    }
  };

  for (const column of ENTITY_COLUMNS) {
    if (!wanted.has(column.column)) continue;
    addWithFunctions({
      id: encodeFieldId({ kind: "column", column: column.column }),
      label: column.label,
      group: COLUMN_GROUP,
      dataType: column.dataType,
      nullable: column.nullable,
      enumValues: null,
      ref: { kind: "column", column: column.column },
    });
  }

  for (const type of input.entityTypes) {
    const entityTypeId = String(type.id);
    for (const attribute of type.attributes ?? []) {
      // A shape is drawn, never compared: it offers no operator, so it is
      // not a field a filter could name.
      if ((OPERATORS_BY_TYPE[attribute.data_type] ?? []).length === 0) continue;
      const ref: AttributeRef = { kind: "attribute", entityTypeId, attribute: attribute.name };
      addWithFunctions({
        id: encodeFieldId(ref),
        // An attribute that shadows one of the entity's own columns says
        // so: the group tells a careful reader which is which, but a
        // scanned list of labels would not.
        label: COLUMN_NAMES.has(attribute.name) ? `${attribute.name} (attribute)` : attribute.name,
        group: type.name,
        dataType: attribute.data_type,
        nullable: !attribute.required,
        enumValues: attribute.enum_values ?? null,
        ref,
      });
    }
  }

  for (const type of input.relationshipTypes ?? []) {
    for (const direction of RELATIONSHIP_DIRECTIONS) {
      const argument: RelationshipRef = {
        kind: "relationship",
        relationshipTypeId: String(type.id),
        direction,
      };
      const ref: FunctionRef = { kind: "function", fn: "count", argument };
      fields.push({
        id: encodeFieldId(ref),
        label: `count(${type.name}, ${direction})`,
        group: RELATIONSHIP_GROUP,
        dataType: "integer",
        // No relationships is zero, not absent.
        nullable: false,
        enumValues: null,
        ref,
      });
    }
  }

  fields.sort((a, b) => a.group.localeCompare(b.group) || a.label.localeCompare(b.label));
  const byId = new Map(fields.map((f) => [f.id, f]));
  return { fields, get: (id: string) => byId.get(id) };
}

/** The groups in `fields` order, for a grouped `<select>`. */
export function groupFields(catalogue: FieldCatalogue): { group: string; fields: ExpressionField[] }[] {
  const out: { group: string; fields: ExpressionField[] }[] = [];
  for (const field of catalogue.fields) {
    const last = out[out.length - 1];
    if (last && last.group === field.group) last.fields.push(field);
    else out.push({ group: field.group, fields: [field] });
  }
  return out;
}
