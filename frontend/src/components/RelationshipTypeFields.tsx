import { useId, useRef } from "react";
import ColourField from "./ColourField";
import { FieldError, FieldLabel, INPUT_CLASS, describedBy, type FieldErrors } from "./attrTypes";
import type { Cardinality, EntityType, Id, RelationshipType } from "../api/v1";
import { CARDINALITIES, HIERARCHY_CARDINALITY } from "../lib/cardinality";

/** The order the error summary lists problems in, which is also the order
 * the controls appear in. */
export const RELATIONSHIP_TYPE_FIELDS = [
  "name",
  "from_type_id",
  "to_type_id",
  "cardinality",
  "is_hierarchy",
  "colour",
];

/** What the form holds while it is being filled in. The two ends are
 * nullable because a brand-new form has not chosen them yet; the submit
 * handler turns that into a field error rather than a request. */
export type RelationshipTypeDraft = {
  name: string;
  from_type_id: Id | null;
  to_type_id: Id | null;
  cardinality: Cardinality;
  is_hierarchy: boolean;
  colour: string | null;
};

export function draftFromType(type: RelationshipType): RelationshipTypeDraft {
  return {
    name: type.name,
    from_type_id: type.from_type_id,
    to_type_id: type.to_type_id,
    cardinality: type.cardinality,
    is_hierarchy: type.is_hierarchy,
    colour: type.colour,
  };
}

/**
 * The table CHECK, as an invariant over the draft:
 *
 * ```sql
 * CHECK (NOT is_hierarchy OR (from_type_id = to_type_id AND cardinality = 'one_to_many'))
 * ```
 *
 * Applied after **every** change, not only when the checkbox moves, so
 * there is no ordering of clicks that leaves the draft holding a
 * combination the database would refuse. That is the point: a form that
 * lets the invalid row be expressed and then reports the refusal has
 * already failed the user, and `relationship_type` carries no validation
 * trigger, so the refusal arrives as a bare 409 naming a constraint (or,
 * because `relationships.py` shadows this CHECK, a 422 on `to_type_id` or
 * `cardinality` -- see the note in the task report).
 *
 * `from_type_id` is copied onto `to_type_id`, never the other way round,
 * and a null stays null: the function constrains a choice, it does not
 * invent one.
 */
export function constrainDraft(draft: RelationshipTypeDraft): RelationshipTypeDraft {
  if (!draft.is_hierarchy) return draft;
  return { ...draft, to_type_id: draft.from_type_id, cardinality: HIERARCHY_CARDINALITY };
}

/** What the second end and the cardinality were before the hierarchy box
 * took them over, so unticking gives the user their own choice back rather
 * than a default. */
type FreeChoice = { to_type_id: Id | null; cardinality: Cardinality };

function selectValue(id: Id | null): string {
  return id === null ? "" : String(id);
}

/**
 * The options for one end: the domain's entity types, plus the id the
 * draft already holds if that is not among them.
 *
 * Without the second part a stored row would show a **blank** end for as
 * long as the entity-type list is in flight, and permanently if the type
 * it names was deleted underneath -- in both cases claiming a choice the
 * row has not lost. `#id` is the same "an id with no type" spelling the
 * list page uses.
 */
function endOptions(entityTypes: EntityType[], selected: Id | null): { value: Id; label: string }[] {
  const options = entityTypes.map((type) => ({ value: type.id, label: type.name }));
  if (selected !== null && !options.some((option) => option.value === selected)) {
    options.push({ value: selected, label: `#${selected}` });
  }
  return options;
}

function parseSelected(raw: string): Id | null {
  return raw === "" ? null : Number(raw);
}

/**
 * The name + ends + cardinality + hierarchy + colour form, shared by "new
 * relationship type" and the type's editor -- the same arrangement
 * `EntityTypeFields` has for entity types.
 *
 * `entityTypes` is the **selected domain's** types and nothing else.
 * Migration 0009 rule 3 requires both ends to live in the relationship
 * type's own domain, so offering anything else would only let the user
 * express a refusal.
 */
export default function RelationshipTypeFields({
  draft,
  onChange,
  onColourProblem,
  entityTypes,
  errors,
  fallbackKey,
}: {
  draft: RelationshipTypeDraft;
  onChange: (next: RelationshipTypeDraft) => void;
  /** What the colour box cannot commit, so the form can refuse the save.
   * It is not part of the draft: a problem is the absence of a value, and
   * `RelationshipTypeDraft` holds only values that can be sent. */
  onColourProblem: (problem: string | null) => void;
  entityTypes: EntityType[];
  errors: FieldErrors;
  /** The id the graph hashes for the fallback colour; a type being created
   * has none, so its name stands in, exactly as `EntityTypeFields` does. */
  fallbackKey: string;
}) {
  const baseId = useId();
  const id = (field: string) => `${baseId}-${field}`;
  const errorId = (field: string) => `${baseId}-${field}-error`;
  const constraintId = `${baseId}-hierarchy-constraint`;
  const remembered = useRef<FreeChoice | null>(null);

  function update(patch: Partial<RelationshipTypeDraft>) {
    onChange(constrainDraft({ ...draft, ...patch }));
  }

  function toggleHierarchy(on: boolean) {
    if (on) {
      remembered.current = { to_type_id: draft.to_type_id, cardinality: draft.cardinality };
      update({ is_hierarchy: true });
      return;
    }
    const restore = remembered.current;
    remembered.current = null;
    onChange({ ...draft, is_hierarchy: false, ...(restore ?? {}) });
  }

  const locked = draft.is_hierarchy;

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <div className="sm:col-span-2">
        <FieldLabel htmlFor={id("name")} required>
          Name
        </FieldLabel>
        <input
          id={id("name")}
          type="text"
          autoComplete="off"
          spellCheck={false}
          className={`${INPUT_CLASS} font-mono`}
          value={draft.name}
          aria-invalid={errors.name ? "true" : undefined}
          aria-describedby={describedBy(id("name-hint"), errors.name && errorId("name"))}
          onChange={(e) => update({ name: e.target.value })}
        />
        <p id={id("name-hint")} className="mt-1 text-xs text-slate-500">
          Lowercase, e.g. <code>reports_to</code>. Read as a sentence: <em>from</em> reports_to <em>to</em>.
        </p>
        <FieldError id={errorId("name")} message={errors.name} />
      </div>

      <div>
        <FieldLabel htmlFor={id("from_type_id")} required>
          From entity type
        </FieldLabel>
        <select
          id={id("from_type_id")}
          className={INPUT_CLASS}
          value={selectValue(draft.from_type_id)}
          aria-invalid={errors.from_type_id ? "true" : undefined}
          aria-describedby={describedBy(id("from-hint"), errors.from_type_id && errorId("from_type_id"))}
          onChange={(e) => update({ from_type_id: parseSelected(e.target.value) })}
        >
          <option value="">Choose an entity type…</option>
          {endOptions(entityTypes, draft.from_type_id).map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <p id={id("from-hint")} className="mt-1 text-xs text-slate-500">
          In a hierarchy, this end is the parent.
        </p>
        <FieldError id={errorId("from_type_id")} message={errors.from_type_id} />
      </div>

      <div>
        <FieldLabel htmlFor={id("to_type_id")} required>
          To entity type
        </FieldLabel>
        <select
          id={id("to_type_id")}
          className={INPUT_CLASS}
          value={selectValue(draft.to_type_id)}
          disabled={locked}
          aria-invalid={errors.to_type_id ? "true" : undefined}
          aria-describedby={describedBy(
            locked ? constraintId : id("to-hint"),
            errors.to_type_id && errorId("to_type_id")
          )}
          onChange={(e) => update({ to_type_id: parseSelected(e.target.value) })}
        >
          <option value="">Choose an entity type…</option>
          {endOptions(entityTypes, draft.to_type_id).map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <p id={id("to-hint")} className="mt-1 text-xs text-slate-500">
          In a hierarchy, this end is the child.
        </p>
        <FieldError id={errorId("to_type_id")} message={errors.to_type_id} />
      </div>

      <div>
        <FieldLabel htmlFor={id("cardinality")} required>
          Cardinality
        </FieldLabel>
        <select
          id={id("cardinality")}
          className={INPUT_CLASS}
          value={draft.cardinality}
          disabled={locked}
          aria-invalid={errors.cardinality ? "true" : undefined}
          aria-describedby={describedBy(
            locked ? constraintId : id("cardinality-hint"),
            errors.cardinality && errorId("cardinality")
          )}
          onChange={(e) => update({ cardinality: e.target.value as Cardinality })}
        >
          {CARDINALITIES.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <p id={id("cardinality-hint")} className="mt-1 text-xs text-slate-500">
          How many of each end an edge may join. Enforced on every relationship, not just described.
        </p>
        <FieldError id={errorId("cardinality")} message={errors.cardinality} />
      </div>

      <div className="sm:col-span-2">
        <div className="flex items-start gap-2">
          <input
            id={id("is_hierarchy")}
            type="checkbox"
            className="mt-1 h-4 w-4 rounded border-slate-300"
            checked={draft.is_hierarchy}
            aria-describedby={describedBy(id("hierarchy-hint"), locked && constraintId)}
            onChange={(e) => toggleHierarchy(e.target.checked)}
          />
          <div>
            <label htmlFor={id("is_hierarchy")} className="block text-sm font-medium text-slate-700">
              This relationship type is a hierarchy
            </label>
            <p id={id("hierarchy-hint")} className="mt-1 text-xs text-slate-500">
              A hierarchy nests entities of one type inside each other — a reporting line, a bill of materials — and
              the graph can be arranged by it.
            </p>
          </div>
        </div>
        {locked && (
          <p
            id={constraintId}
            data-testid="hierarchy-constraint"
            className="mt-2 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-700"
          >
            Because this is a hierarchy, both ends are the same entity type — a hierarchy nests a type inside itself —
            and the cardinality is one to many, so that each child has at most one parent. Both are set for you and
            cannot be changed here. Clear the checkbox to choose them freely again.
          </p>
        )}
        <FieldError id={errorId("is_hierarchy")} message={errors.is_hierarchy} />
      </div>

      <div className="sm:col-span-2">
        <ColourField
          value={draft.colour}
          onChange={(colour) => update({ colour })}
          onProblemChange={onColourProblem}
          error={errors.colour}
          fallbackKey={fallbackKey}
          sampleText={draft.name.trim() === "" ? "reports_to" : draft.name}
        />
      </div>
    </div>
  );
}
