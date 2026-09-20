import { FormEvent, useEffect, useId, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ErrorSummary, FieldError, FieldLabel, INPUT_CLASS, describedBy, useFieldErrors, type FieldErrors } from "./attrTypes";
import { useToast } from "./ToastProvider";
import { formatApiError } from "../api/errors";
import {
  useCreateRelationship,
  useDeleteRelationship,
  type Entity,
  type Id,
  type Relationship,
  type RelationshipType,
} from "../api/v1";
import { CARDINALITY_NAME } from "../lib/cardinality";
import {
  RELATIONSHIP_FIELDS,
  confirmDeleteRelationship,
  connectionLabel,
  connectionOptions,
  deletedRelationshipMessage,
  endsFor,
  entityLabel,
  relationshipProblems,
  type ConnectionOption,
} from "../lib/relationships";

/**
 * The two controls every relationship screen is made of: a table of edges
 * that can be deleted, and a form that makes one.
 *
 * They exist because until now a relationship could only be seen or made
 * by dragging on the graph canvas, advertised by one line of grey helper
 * text -- so "who works where" and "which unit sits under which", the two
 * facts a workforce planner's model is actually about, existed only as
 * arrows on a crowded picture. Both are shared by `/relationships` (the
 * whole domain) and the Relationships section on an entity (one entity,
 * both directions), so those two cannot drift apart in wording or in what
 * they allow.
 */

/** One edge, already resolved to names. Resolving happens in the screen
 * that owns the data, so this component has no idea where entities come
 * from and can be rendered from a fixture. */
export type RelationshipRow = {
  id: Id;
  typeName: string;
  fromEntityId: Id;
  toEntityId: Id;
  fromLabel: string;
  toLabel: string;
};

export function relationshipRows(
  relationships: Relationship[],
  types: Map<Id, RelationshipType>,
  entities: Map<Id, Entity>
): RelationshipRow[] {
  return relationships.map((relationship) => ({
    id: relationship.id,
    typeName: types.get(relationship.relationship_type_id)?.name ?? `#${relationship.relationship_type_id}`,
    fromEntityId: relationship.from_entity_id,
    toEntityId: relationship.to_entity_id,
    fromLabel: entityLabel(entities, relationship.from_entity_id),
    toLabel: entityLabel(entities, relationship.to_entity_id),
  }));
}

const CELL = "px-3 py-2 text-slate-700";

/**
 * The table.
 *
 * Three columns in the row's own direction -- From, the relationship
 * type, To -- so a row reads as the sentence the relationship-type form
 * teaches ("Read as a sentence: from <name> to"). `subjectId` marks the
 * entity whose page this is, so on an entity's own section the other end
 * is the one that stands out, and an incoming row is visibly not an
 * outgoing one.
 */
export function RelationshipList({
  rows,
  caption,
  emptyNote,
  subjectId,
  entityHref,
  truncated,
}: {
  rows: RelationshipRow[];
  caption: string;
  emptyNote: string;
  subjectId?: Id;
  /** Where an endpoint's name links to, or nothing to render plain text. */
  entityHref?: (id: Id) => string;
  truncated?: boolean;
}) {
  const deleteRelationship = useDeleteRelationship();
  const toast = useToast();
  const [error, setError] = useState<string | null>(null);

  async function handleDelete(row: RelationshipRow) {
    setError(null);
    if (!window.confirm(confirmDeleteRelationship(row.typeName, row.fromLabel, row.toLabel))) return;
    try {
      await deleteRelationship.mutateAsync(row.id);
      toast.success(deletedRelationshipMessage(row.typeName, row.fromLabel, row.toLabel));
    } catch (err) {
      setError(formatApiError(err));
    }
  }

  function endCell(id: Id, label: string) {
    const isSubject = subjectId !== undefined && id === subjectId;
    if (isSubject) {
      return (
        <span className="text-slate-900">
          {label} <span className="text-xs text-slate-500">(this entity)</span>
        </span>
      );
    }
    return entityHref ? (
      <Link to={entityHref(id)} className="inline-block rounded py-1 text-blue-600 underline">
        {label}
      </Link>
    ) : (
      <span>{label}</span>
    );
  }

  if (rows.length === 0) {
    return (
      <>
        {error && <p className="mb-2 text-sm text-red-600">{error}</p>}
        <p data-testid="relationships-empty" className="mb-4 text-sm text-slate-600">
          {emptyNote}
        </p>
      </>
    );
  }

  return (
    <>
      {error && <p className="mb-2 whitespace-pre-line text-sm text-red-600">{error}</p>}
      {truncated && (
        <p data-testid="relationships-truncated" className="mb-2 text-xs text-amber-800">
          Showing the first 500 of each list. Narrow this down by relationship type to see the rest.
        </p>
      )}
      <div className="mb-4 overflow-x-auto rounded-md border border-slate-200 bg-white">
        <table className="w-full text-left text-sm" aria-label={caption}>
          <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-600">
            <tr>
              <th scope="col" className="px-3 py-2 font-semibold">
                From
              </th>
              <th scope="col" className="px-3 py-2 font-semibold">
                Relationship
              </th>
              <th scope="col" className="px-3 py-2 font-semibold">
                To
              </th>
              <th scope="col" className="px-3 py-2 font-semibold">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id} className="border-b border-slate-100 last:border-0" data-testid={`relationship-${row.id}`}>
                <td className={CELL}>{endCell(row.fromEntityId, row.fromLabel)}</td>
                <td className={`${CELL} font-mono text-xs`}>{row.typeName}</td>
                <td className={CELL}>{endCell(row.toEntityId, row.toLabel)}</td>
                <td className="px-3 py-2">
                  <button
                    type="button"
                    onClick={() => handleDelete(row)}
                    disabled={deleteRelationship.isPending}
                    className="rounded-md border border-red-300 px-2 py-1 text-xs font-medium text-red-700 hover:bg-red-50 disabled:opacity-60"
                  >
                    Delete
                    <span className="sr-only">
                      {" "}
                      the {row.typeName} relationship from {row.fromLabel} to {row.toLabel}
                    </span>
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

// --- the create form --------------------------------------------------------

/** What the form needs to know about the entity it is anchored to, when
 * it is anchored to one. */
export type Subject = { id: Id; entityTypeId: Id; label: string };

function entityOptionLabel(entity: Entity): string {
  return entity.label && entity.label.trim() !== "" ? entity.label : entity.key;
}

/**
 * "Add a relationship".
 *
 * Anchored to an entity (`subject`), it asks one question -- which
 * connection, then which other entity -- because the entity is already
 * one end; a hierarchy therefore offers both "this unit is the parent"
 * and "this unit is the child", which is the half of a hierarchy that
 * dragging on a canvas makes hardest to get right.
 *
 * Unanchored (the relationships page), it asks for the type and then both
 * ends. In both shapes the entity pickers only ever offer entities of the
 * type that end requires, so the one trigger rule the UI can prevent --
 * `type_mismatch` -- cannot normally be reached from here. The other two
 * (cardinality, cycle) genuinely cannot be checked client-side: they are
 * a recursive walk and a uniqueness question under concurrency, which is
 * why the server refuses them and why those refusals land on the control
 * they are about instead of being guessed at in advance.
 */
export function NewRelationshipForm({
  types,
  entitiesByType,
  entityTypeNames,
  subject,
  heading,
}: {
  /** The domain's relationship types. */
  types: RelationshipType[];
  /** Entities to offer, keyed by entity type id. */
  entitiesByType: Map<Id, Entity[]>;
  entityTypeNames: Map<Id, string>;
  subject?: Subject;
  heading: string;
}) {
  const baseId = useId();
  const id = (field: string) => `${baseId}-${field}`;
  const errorId = (field: string) => `${baseId}-${field}-error`;
  const [serverErrors, setServerErrors] = useState<FieldErrors | null>(null);
  const [general, setGeneral] = useState<string | null>(null);
  const { errors, replace, summaryRef } = useFieldErrors(serverErrors);
  const createRelationship = useCreateRelationship();
  const toast = useToast();

  const options: ConnectionOption[] = useMemo(
    () =>
      subject
        ? connectionOptions(types, subject.entityTypeId)
        : types.map((type) => ({
            key: `${type.id}:from`,
            type,
            role: "from" as const,
            otherTypeId: type.to_type_id,
          })),
    [types, subject]
  );

  const [optionKey, setOptionKey] = useState<string>(() => options[0]?.key ?? "");
  // Re-seed when the offered set changes underneath (a domain switch, or a
  // relationship type created in another tab): a select holding a value
  // that is no longer an option renders blank and submits nothing.
  useEffect(() => {
    if (options.length > 0 && !options.some((option) => option.key === optionKey)) {
      setOptionKey(options[0].key);
    }
  }, [options, optionKey]);

  const option = options.find((candidate) => candidate.key === optionKey) ?? options[0];
  const [otherId, setOtherId] = useState<string>("");
  const [fromId, setFromId] = useState<string>("");
  const [toId, setToId] = useState<string>("");

  // The ends reset with the type, because an entity valid for one type's
  // end is usually not of the type the next one needs.
  useEffect(() => {
    setOtherId("");
    setFromId("");
    setToId("");
  }, [optionKey]);

  const typeName = (typeId: Id) => entityTypeNames.get(typeId) ?? `#${typeId}`;
  const choicesFor = (typeId: Id) => entitiesByType.get(typeId) ?? [];

  if (options.length === 0) {
    return (
      <section aria-labelledby={id("heading")} className="rounded-md border border-slate-200 bg-white p-4">
        <h2 id={id("heading")} className="mb-2 text-base font-semibold text-slate-900">
          {heading}
        </h2>
        <p className="text-sm text-slate-600">
          {subject
            ? `No relationship type joins ${typeName(subject.entityTypeId)} to anything yet, so this entity cannot be connected to one.`
            : "This domain has no relationship types yet, so there is nothing a relationship could be."}{" "}
          <Link to="/relationship-types" className="inline-block rounded py-1 text-blue-600 underline">
            Define one on the relationship types page
          </Link>
          .
        </p>
      </section>
    );
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setGeneral(null);
    if (!option) return;
    const problems: FieldErrors = {};
    let ends: { from_entity_id: Id; to_entity_id: Id } | null = null;
    if (subject) {
      if (otherId === "") {
        problems.to_entity_id = `Choose the ${typeName(option.otherTypeId)} to connect.`;
      } else {
        ends = endsFor(option, subject.id, Number(otherId));
      }
    } else {
      if (fromId === "") problems.from_entity_id = "From: choose an entity.";
      if (toId === "") problems.to_entity_id = "To: choose an entity.";
      if (fromId !== "" && toId !== "") {
        ends = { from_entity_id: Number(fromId), to_entity_id: Number(toId) };
      }
    }
    replace(problems);
    if (!ends) return;
    try {
      await createRelationship.mutateAsync({ relationship_type_id: option.type.id, ...ends });
      toast.success(`"${option.type.name}" relationship created`);
      setOtherId("");
      setFromId("");
      setToId("");
      replace({});
      setServerErrors(null);
    } catch (err) {
      const result = relationshipProblems(err);
      setServerErrors(result.fields);
      setGeneral(result.general);
    }
  }

  return (
    <section aria-labelledby={id("heading")} className="rounded-md border border-slate-200 bg-white p-4">
      <h2 id={id("heading")} className="mb-3 text-base font-semibold text-slate-900">
        {heading}
      </h2>
      <form aria-label={heading} onSubmit={handleSubmit} noValidate className="space-y-4">
        <ErrorSummary errors={errors} order={RELATIONSHIP_FIELDS} summaryRef={summaryRef} />
        {general && (
          <p data-testid="relationship-general-error" className="whitespace-pre-line text-sm text-red-600">
            {general}
          </p>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          <div className={subject ? "sm:col-span-2" : ""}>
            <FieldLabel htmlFor={id("type")} required>
              Relationship type
            </FieldLabel>
            <select
              id={id("type")}
              className={INPUT_CLASS}
              value={optionKey}
              aria-invalid={errors.relationship_type_id ? "true" : undefined}
              aria-describedby={describedBy(id("type-hint"), errors.relationship_type_id && errorId("relationship_type_id"))}
              onChange={(event) => setOptionKey(event.target.value)}
              data-testid="relationship-type-select"
            >
              {options.map((candidate) => (
                <option key={candidate.key} value={candidate.key}>
                  {subject
                    ? connectionLabel(candidate, subject.label, typeName(candidate.otherTypeId))
                    : `${candidate.type.name}: ${typeName(candidate.type.from_type_id)} → ${typeName(candidate.type.to_type_id)}`}
                </option>
              ))}
            </select>
            <p id={id("type-hint")} className="mt-1 text-xs text-slate-500">
              {option
                ? `${CARDINALITY_NAME[option.type.cardinality]}${option.type.is_hierarchy ? ", and a hierarchy: the From end is the parent" : ""}. The database enforces this on every relationship.`
                : ""}
            </p>
            <FieldError id={errorId("relationship_type_id")} message={errors.relationship_type_id} />
          </div>

          {subject ? (
            <div className="sm:col-span-2">
              <FieldLabel htmlFor={id("other")} required>
                {option?.role === "from" ? "To entity" : "From entity"}
              </FieldLabel>
              <select
                id={id("other")}
                className={INPUT_CLASS}
                value={otherId}
                aria-invalid={errors.to_entity_id || errors.from_entity_id ? "true" : undefined}
                aria-describedby={describedBy(
                  id("other-hint"),
                  (errors.to_entity_id || errors.from_entity_id) && errorId("other")
                )}
                onChange={(event) => setOtherId(event.target.value)}
                data-testid="relationship-other-select"
              >
                <option value="">Choose a {option ? typeName(option.otherTypeId) : "entity"}…</option>
                {(option ? choicesFor(option.otherTypeId) : [])
                  // The subject cannot be its own other end: a hierarchy
                  // refuses `from = to` outright, and for anything else it
                  // is never what was meant.
                  .filter((entity) => entity.id !== subject.id)
                  .map((entity) => (
                    <option key={entity.id} value={entity.id}>
                      {entityOptionLabel(entity)}
                    </option>
                  ))}
              </select>
              <p id={id("other-hint")} className="mt-1 text-xs text-slate-500">
                Only {option ? typeName(option.otherTypeId) : "entity"} records are offered — this relationship type
                accepts nothing else at that end.
              </p>
              <FieldError
                id={errorId("other")}
                message={option?.role === "from" ? errors.to_entity_id ?? errors.from_entity_id : errors.from_entity_id ?? errors.to_entity_id}
              />
            </div>
          ) : (
            <>
              <div>
                <FieldLabel htmlFor={id("from")} required>
                  From entity
                </FieldLabel>
                <select
                  id={id("from")}
                  className={INPUT_CLASS}
                  value={fromId}
                  aria-invalid={errors.from_entity_id ? "true" : undefined}
                  aria-describedby={describedBy(id("from-hint"), errors.from_entity_id && errorId("from_entity_id"))}
                  onChange={(event) => setFromId(event.target.value)}
                  data-testid="relationship-from-select"
                >
                  <option value="">Choose a {option ? typeName(option.type.from_type_id) : "entity"}…</option>
                  {(option ? choicesFor(option.type.from_type_id) : []).map((entity) => (
                    <option key={entity.id} value={entity.id}>
                      {entityOptionLabel(entity)}
                    </option>
                  ))}
                </select>
                <p id={id("from-hint")} className="mt-1 text-xs text-slate-500">
                  {option?.type.is_hierarchy ? "The parent." : "The end the type's name reads from."}
                </p>
                <FieldError id={errorId("from_entity_id")} message={errors.from_entity_id} />
              </div>
              <div>
                <FieldLabel htmlFor={id("to")} required>
                  To entity
                </FieldLabel>
                <select
                  id={id("to")}
                  className={INPUT_CLASS}
                  value={toId}
                  aria-invalid={errors.to_entity_id ? "true" : undefined}
                  aria-describedby={describedBy(id("to-hint"), errors.to_entity_id && errorId("to_entity_id"))}
                  onChange={(event) => setToId(event.target.value)}
                  data-testid="relationship-to-select"
                >
                  <option value="">Choose a {option ? typeName(option.type.to_type_id) : "entity"}…</option>
                  {(option ? choicesFor(option.type.to_type_id) : []).map((entity) => (
                    <option key={entity.id} value={entity.id}>
                      {entityOptionLabel(entity)}
                    </option>
                  ))}
                </select>
                <p id={id("to-hint")} className="mt-1 text-xs text-slate-500">
                  {option?.type.is_hierarchy ? "The child." : "The end the type's name reads to."}
                </p>
                <FieldError id={errorId("to_entity_id")} message={errors.to_entity_id} />
              </div>
            </>
          )}
        </div>
        <button
          type="submit"
          disabled={createRelationship.isPending}
          className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {createRelationship.isPending ? "Saving…" : "Add relationship"}
        </button>
      </form>
    </section>
  );
}
