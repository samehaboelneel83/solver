/**
 * The vocabulary the relationship screens share: which relationship types
 * an entity can take part in, which way round, and where a refused write
 * belongs on the form.
 *
 * Pure, and in `lib/` rather than inside either screen, because the two
 * surfaces that need it -- the `/relationships` page and the Relationships
 * section on an entity -- ask the same questions from opposite sides, and
 * the answers are the database's rules rather than either screen's layout.
 */
import { ApiError } from "../api/client";
import { formatApiError } from "../api/errors";
import { rewordTriggerMessage } from "../api/graph";
import { validationErrors, type Entity, type Id, type RelationshipType } from "../api/v1";

/** Which end of an edge an entity is on. `from` is the parent end of a
 * hierarchy; the forms call the two ends From and To throughout. */
export type EndRole = "from" | "to";

/**
 * One way a given entity can take part in a given relationship type.
 *
 * A type whose two ends are DIFFERENT entity types yields at most one
 * option for any entity. A hierarchy -- whose ends are the same type by
 * the table CHECK -- yields two, because a unit needs to be able to gain a
 * parent and to gain a child, and those are the same row read from
 * opposite ends. Offering only one of them would make half the hierarchy
 * unbuildable outside the graph, which is the whole complaint.
 */
export type ConnectionOption = {
  /** Stable `<select>` value: the type and the end, which is exactly what
   * distinguishes a hierarchy's two options from each other. */
  key: string;
  type: RelationshipType;
  /** The end the KNOWN entity takes. */
  role: EndRole;
  /** The entity type at the other end, which is what the picker offers. */
  otherTypeId: Id;
};

export function connectionKey(typeId: Id, role: EndRole): string {
  return `${typeId}:${role}`;
}

/**
 * Every way an entity of `entityTypeId` can be connected, in the order the
 * types arrive (the API orders them by name), with the From reading before
 * the To for a hierarchy -- "this unit is the parent" before "this unit is
 * the child", which is the direction the type's name is written in.
 */
export function connectionOptions(types: RelationshipType[], entityTypeId: Id): ConnectionOption[] {
  const options: ConnectionOption[] = [];
  for (const type of types) {
    if (type.from_type_id === entityTypeId) {
      options.push({
        key: connectionKey(type.id, "from"),
        type,
        role: "from",
        otherTypeId: type.to_type_id,
      });
    }
    if (type.to_type_id === entityTypeId) {
      options.push({
        key: connectionKey(type.id, "to"),
        type,
        role: "to",
        otherTypeId: type.from_type_id,
      });
    }
  }
  return options;
}

/**
 * How an option reads in the picker.
 *
 * As a sentence in the type's own direction, with the fixed entity named
 * and the other end described by its type: "Ahmed Salah works_in a unit",
 * "a unit reports_to North Region". That is the same reading the
 * relationship-type form teaches ("Read as a sentence: from <name> to"),
 * so the two screens cannot disagree about which end is which.
 */
export function connectionLabel(
  option: ConnectionOption,
  subject: string,
  otherTypeName: string
): string {
  return option.role === "from"
    ? `${subject} ${option.type.name} a ${otherTypeName}`
    : `a ${otherTypeName} ${option.type.name} ${subject}`;
}

/** The ids a create needs, given which end the known entity is on. */
export function endsFor(option: ConnectionOption, subjectId: Id, otherId: Id): {
  from_entity_id: Id;
  to_entity_id: Id;
} {
  return option.role === "from"
    ? { from_entity_id: subjectId, to_entity_id: otherId }
    : { from_entity_id: otherId, to_entity_id: subjectId };
}

/** What an entity is called on screen: its label, or its key when it has
 * none (the same fallback the graph read applies), or `#id` when the row
 * is not among the ones this screen loaded. */
export function entityLabel(entities: Map<Id, Entity>, id: Id): string {
  const entity = entities.get(id);
  if (!entity) return `#${id}`;
  return entity.label && entity.label.trim() !== "" ? entity.label : entity.key;
}

/**
 * What a delete asks before it happens, and what the toast says after.
 *
 * One wording, in one place, for all three screens that can now remove a
 * relationship -- the graph's edge panel, the relationships page and an
 * entity's own section. Each names the relationship type AND both
 * endpoints, and volunteers what is NOT deleted, which is the quality the
 * tester singled out in Task 11's confirmations.
 */
export function confirmDeleteRelationship(typeName: string, fromLabel: string, toLabel: string): string {
  return (
    `Delete the "${typeName}" relationship from "${fromLabel}" to "${toLabel}"? ` +
    `The entities at either end are not deleted. This cannot be undone.`
  );
}

export function deletedRelationshipMessage(typeName: string, fromLabel: string, toLabel: string): string {
  return `"${typeName}" from "${fromLabel}" to "${toLabel}" deleted`;
}

// --- refusals ---------------------------------------------------------------

/** The fields a relationship write actually carries. Anything else in a
 * 422's `loc` is not a field of the request -- see `api/graph.ts`, which
 * makes the same distinction for the canvas. */
const BODY_FIELDS = ["relationship_type_id", "from_entity_id", "to_entity_id", "valid_from", "valid_to", "attrs"];

/** The order the error summary lists problems in. */
export const RELATIONSHIP_FIELDS = ["relationship_type_id", "from_entity_id", "to_entity_id"];

/**
 * Which control a trigger refusal belongs to.
 *
 * `relationship_validate` names the relationship TYPE in `field`, not a
 * column, so every one of its refusals arrives at the same `loc` and
 * `loc` alone cannot place them (Ruling 30 decides whether an entry is
 * about a body field at all -- it is the trigger's sentence that then
 * says which END is at fault, because the two cardinality rules are
 * mirror images and carry the same `kind`).
 *
 * Only the two rules that are ABOUT one end are placed. A cycle is about
 * the pair, and a type mismatch is about the type against both ends, so
 * both stay form-level rather than being guessed onto a control -- and so
 * does any rule added to the trigger later.
 */
function endFieldForTrigger(message: string): string | null {
  if (/: source already has a target$/.test(message)) return "from_entity_id";
  if (/: target already has a source$/.test(message)) return "to_entity_id";
  return null;
}

export type RelationshipProblems = { fields: Record<string, string>; general: string | null };

/**
 * Splits a refused relationship write into messages for the controls on
 * screen and one for the form as a whole.
 *
 * - A list-shaped 422 whose `loc[1]` names a body field goes to that
 *   control (Ruling 30: `loc` says what was wrong).
 * - A trigger entry -- `loc[1]` is the relationship type's name -- is
 *   reworded (`rewordTriggerMessage`) and placed on the end it is about,
 *   or left form-level when it is about the pair.
 * - A 409 whose string `detail` says "already exists" is
 *   `UNIQUE (relationship_type_id, from_entity_id, to_entity_id)`: these
 *   two are already connected by this type.
 * - Anything else is `formatApiError`'s text.
 */
export function relationshipProblems(err: unknown): RelationshipProblems {
  const items = validationErrors(err);
  if (items.length > 0) {
    const fields: Record<string, string> = {};
    const rest: string[] = [];
    for (const item of items) {
      const loc = item.loc?.[1];
      if (typeof loc === "string" && BODY_FIELDS.includes(loc)) {
        if (!(loc in fields)) fields[loc] = `${loc}: ${item.msg}`;
        continue;
      }
      const reworded = rewordTriggerMessage(item.msg);
      const field = endFieldForTrigger(item.msg);
      if (field && !(field in fields)) {
        fields[field] = reworded;
        continue;
      }
      rest.push(reworded);
    }
    return { fields, general: rest.length > 0 ? rest.join("\n") : null };
  }
  const message = formatApiError(err);
  if (err instanceof ApiError && err.status === 409 && /already exists/.test(message)) {
    return {
      fields: {},
      general: "These two entities are already connected by this relationship type.",
    };
  }
  return { fields: {}, general: message };
}
