import LoadFailure from "../components/LoadFailure";
import { FormEvent, useId, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import AttrsForm, { attrField, buildAttrs, draftsFromAttrs, staleAttrKeys, type AttrDrafts } from "../components/AttrsForm";
import EntityRelationships from "../components/EntityRelationships";
import RecordTrees from "../components/RecordTrees";
import OfflineNotice from "../components/OfflineNotice";
import StaleRecordNotice from "../components/StaleRecordNotice";
import { useToast } from "../components/ToastProvider";
import {
  ErrorSummary,
  FieldError,
  FieldLabel,
  INPUT_CLASS,
  describedBy,
  parseAttrValue,
  useFieldErrors,
  type FieldErrors,
} from "../components/attrTypes";
import { ApiError } from "../api/client";
import { formatApiError, isStaleRecordError } from "../api/errors";
import {
  useCreateEntity,
  useDeleteEntity,
  useEntityRecord,
  useEntityType,
  useEntityReferrers,
  useEntityTrees,
  useUpdateEntity,
  validationErrors,
  type AttributeDef,
  type Entity,
  type EntityType,
  type ReferrerField,
} from "../api/v1";
import { useCapabilities } from "../hooks/useCapability";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { parseRouteId } from "../lib/routeId";
import { mergeReload, reloadedKeys } from "../lib/staleRecord";

/**
 * One entity: its four columns (`key`, `label`, `sort_order`, `active`)
 * and a control per attribute of its type, generated from `attribute_def`
 * rather than from table metadata -- the shape the spec calls for and the
 * reason `attrs` is a free-form JSONB column on the server.
 *
 * `entity_type_id` is chosen once, on the new-entity route, and never
 * shown as an editable field: the API does not accept it in a PATCH, and
 * changing it would invalidate every attribute value at once.
 */

const BACK_LINK = "inline-block rounded py-1 text-sm text-blue-600 underline";

const COLUMN_FIELDS = ["key", "label", "sort_order", "active"];

/** The trigger kinds that name an attribute the form has a control for.
 * `unknown_attribute` also carries an attribute name, but by definition it
 * is one with no definition and so no control -- it becomes a general
 * message instead of being attached to nothing. */
const ATTRIBUTE_KINDS = new Set(["required_attribute", "attribute_type"]);

/**
 * Splits a refused save into per-control messages and a general one.
 *
 * The wire gives one 422 shape (Ruling 19) for two different sources, and
 * `kind` is the only thing that tells them apart: `["body", "key"]` with no
 * `kind` is the *column* `key`, while the same `loc` with
 * `kind="attribute_type"` is an *attribute* named `key` -- which is legal,
 * since `attribute_def.name` only forbids `id`. That is why attribute
 * errors are namespaced with `attrField()` rather than sharing the column
 * namespace.
 *
 * A 409 here is the one unique constraint the table has,
 * `UNIQUE (entity_type_id, key)`; `conflict_detail` words it after the
 * constraint name, so it is reworded and pointed at the key field. The
 * OTHER 409 a save can get -- the record changed underneath the form
 * (Ruling 42) -- never reaches here: `handleSubmit` recognises it first,
 * because it is not a field problem and its remedy is not an edit.
 */
export function entityServerErrors(
  err: unknown,
  attributeNames: string[]
): { fields: FieldErrors; general: string | null } {
  const items = validationErrors(err);
  if (items.length > 0) {
    const fields: FieldErrors = {};
    const rest: string[] = [];
    for (const item of items) {
      const field = item.loc?.[1];
      if (typeof field === "string") {
        if (item.kind && ATTRIBUTE_KINDS.has(item.kind) && attributeNames.includes(field)) {
          if (!(attrField(field) in fields)) fields[attrField(field)] = item.msg;
          continue;
        }
        if (!item.kind && COLUMN_FIELDS.includes(field) && !(field in fields)) {
          fields[field] = item.msg;
          continue;
        }
      }
      rest.push(item.msg);
    }
    return { fields, general: rest.length > 0 ? rest.join("\n") : null };
  }
  const message = formatApiError(err);
  if (err instanceof ApiError && err.status === 409 && /already exists/.test(message)) {
    return {
      fields: { key: "Key: another entity of this type already has this key." },
      general: null,
    };
  }
  return { fields: {}, general: message };
}

export default function EntityRecord() {
  const { id: rawId } = useParams();
  const [searchParams] = useSearchParams();
  const isNew = rawId === undefined;
  const entityId = isNew ? null : parseRouteId(rawId);
  const queryTypeId = parseRouteId(searchParams.get("type"));

  const entityQuery = useEntityRecord(entityId);
  const entity = entityQuery.data ?? null;
  const typeId = isNew ? queryTypeId : (entity?.entity_type_id ?? null);
  const typeQuery = useEntityType(typeId);

  useDocumentTitle(isNew ? "New entity" : entity ? `Entity ${entity.key}` : "Entity");

  if (isNew && queryTypeId === null) {
    return (
      <div>
        {/* Reachable by typing or bookmarking /entities/new. Same rule. */}
        <h1 className="mb-2 text-lg font-semibold text-slate-900">New entity</h1>
        <p className="text-sm text-slate-600">
          Choose an entity type first: a new entity belongs to exactly one, and its type is what says which
          attributes it has.
        </p>
        <Link to="/entities" className={BACK_LINK}>
          Back to entities
        </Link>
      </div>
    );
  }

  const notFound =
    (!isNew && entityId === null) ||
    (entityQuery.isError && entityQuery.error instanceof ApiError && entityQuery.error.status === 404) ||
    (typeQuery.isError && typeQuery.error instanceof ApiError && typeQuery.error.status === 404);
  if (notFound) {
    return (
      <div>
        {/* See EntityTypeDetail: a page with no <h1> is an axe
            `page-has-heading-one` violation. */}
        <h1 className="mb-2 text-lg font-semibold text-slate-900">Entity not found.</h1>
        <Link to="/entities" className={BACK_LINK}>
          Back to entities
        </Link>
      </div>
    );
  }

  const paused = entityQuery.fetchStatus === "paused" || typeQuery.fetchStatus === "paused";
  if (paused && !typeQuery.data) return <OfflineNotice subject="This entity" />;

  const failed = (entityQuery.isError && !entity) || (typeQuery.isError && !typeQuery.data);
  if (failed) {
    return (
      <div>
        <LoadFailure subject="This entity" error={entityQuery.error ?? typeQuery.error}
          retry={() => { void entityQuery.refetch(); void typeQuery.refetch(); }} />
        <Link to="/entities" className={BACK_LINK}>
          Back to entities
        </Link>
      </div>
    );
  }

  if (!typeQuery.data || (!isNew && !entity)) return <p className="text-sm text-slate-500">Loading…</p>;

  return (
    <RecordForm
      key={entity?.id ?? "new"}
      type={typeQuery.data}
      entity={entity}
      // Ruling 42: what "Reload and keep my changes" reads. It goes through
      // the page's own query, so the reload also refreshes everything else
      // rendered from that entity rather than holding a second copy.
      reload={async () => (await entityQuery.refetch()).data ?? null}
    />
  );
}

function sortedFieldOrder(attributes: AttributeDef[]): string[] {
  return [...COLUMN_FIELDS, ...attributes.map((attribute) => attrField(attribute.name))];
}

/** The four column controls, exactly as they hold their values, so the
 * reload merge compares what the person sees rather than a re-derived
 * version of it. */
type ColumnDrafts = { key: string; label: string; sortOrder: string; active: boolean };

function columnDraftsOf(entity: Entity): ColumnDrafts {
  return {
    key: entity.key,
    label: entity.label ?? "",
    sortOrder: String(entity.sort_order),
    active: entity.active,
  };
}

function RecordForm({
  type,
  entity,
  reload,
}: {
  type: EntityType;
  entity: Entity | null;
  reload: () => Promise<Entity | null>;
}) {
  const { can } = useCapabilities();
  const canEdit = can("domain.edit");
  const attributes = type.attributes;
  const [key, setKey] = useState(entity?.key ?? "");
  const [label, setLabel] = useState(entity?.label ?? "");
  const [sortOrder, setSortOrder] = useState(String(entity?.sort_order ?? 0));
  const [active, setActive] = useState(entity?.active ?? true);
  const [drafts, setDrafts] = useState<AttrDrafts>(() => draftsFromAttrs(attributes, entity?.attrs ?? {}));
  const [stored, setStored] = useState<Record<string, unknown>>(entity?.attrs ?? {});
  const [serverErrors, setServerErrors] = useState<FieldErrors | null>(null);
  const [general, setGeneral] = useState<string | null>(null);
  const { errors, replace, summaryRef } = useFieldErrors(serverErrors);
  // Ruling 42. What this form read; it goes back with every save, and the
  // server refuses a save built on a read another client has superseded.
  const [updatedAt, setUpdatedAt] = useState<string | null>(entity?.updated_at ?? null);
  const [stale, setStale] = useState<string | null>(null);
  const [reloading, setReloading] = useState(false);
  // What the controls were SEEDED with -- the third input the reload merge
  // needs to tell "the person typed this" from "the person left it alone".
  // A ref, not state: nothing renders from it, and the handler that reads
  // it is the same one that replaces it.
  const seeded = useRef({
    columns: entity ? columnDraftsOf(entity) : { key: "", label: "", sortOrder: "0", active: true },
    drafts: draftsFromAttrs(attributes, entity?.attrs ?? {}),
  });

  const createEntity = useCreateEntity();
  const updateEntity = useUpdateEntity();
  const deleteEntity = useDeleteEntity();
  // A reference that nests this kind in itself may not name this record or anything below it.
  const trees = useEntityTrees(entity?.id);
  const referrers = useEntityReferrers(entity?.id);
  const clears = (referrers.data?.fields ?? []).filter((f) => !f.required);
  const refuses = (referrers.data?.fields ?? []).filter((f) => f.required);
  const loopBlocked = (attributeName: string): ReadonlyMap<string, string> | undefined => {
    const tree = trees.data?.trees.find((t) => t.via_attribute === attributeName);
    return tree ? new Map(tree.blocked.map((key) => [key, key === entity?.key ? "this record" : "below this one: a loop"])) : undefined;
  };
  const toast = useToast();
  const navigate = useNavigate();

  const baseId = useId();
  const id = (field: string) => `${baseId}-${field}`;
  const errorId = (field: string) => `${baseId}-${field}-error`;
  const isSubmitting = createEntity.isPending || updateEntity.isPending;
  const staleKeys = staleAttrKeys(attributes, stored);

  function clearError(field: string) {
    if (errors[field]) {
      const next = { ...errors };
      delete next[field];
      replace(next);
    }
  }

  /** Re-seed from what the server stored, which is not what was sent: the
   * `entity_validate` trigger materialises defaults into `attrs` on write,
   * so an attribute left empty comes back populated. */
  function resetFrom(saved: Entity) {
    setKey(saved.key);
    setLabel(saved.label ?? "");
    setSortOrder(String(saved.sort_order));
    setActive(saved.active);
    const savedDrafts = draftsFromAttrs(attributes, saved.attrs);
    setDrafts(savedDrafts);
    setStored(saved.attrs);
    setUpdatedAt(saved.updated_at);
    setStale(null);
    seeded.current = { columns: columnDraftsOf(saved), drafts: savedDrafts };
  }

  /**
   * Ruling 42: re-read the record and take the other client's value for
   * every control this person has not touched, leaving the ones they have
   * exactly as typed. Nothing they wrote is lost, which is what makes the
   * offer safe to accept without weighing it up.
   *
   * The save that follows still sends the whole `attrs` object: the merge
   * decides what the CONTROLS hold, not what the payload carries, so Tasks
   * 11/12's stale-key clearing is untouched.
   */
  async function handleReload() {
    setReloading(true);
    try {
      const fresh = await reload();
      if (!fresh) return;
      const freshColumns = columnDraftsOf(fresh);
      const current: ColumnDrafts = { key, label, sortOrder, active };
      const mergedColumns = mergeReload(seeded.current.columns, current, freshColumns);
      setKey(mergedColumns.key);
      setLabel(mergedColumns.label);
      setSortOrder(mergedColumns.sortOrder);
      setActive(mergedColumns.active);

      const freshDrafts = draftsFromAttrs(attributes, fresh.attrs);
      setDrafts(mergeReload(seeded.current.drafts, drafts, freshDrafts));

      // Named rather than left to be spotted: the whole complaint was that
      // a concurrent change was invisible.
      const brought = [
        ...reloadedKeys(seeded.current.columns, current, freshColumns),
        ...reloadedKeys(seeded.current.drafts, drafts, freshDrafts),
      ];
      setStored(fresh.attrs);
      setUpdatedAt(fresh.updated_at);
      setStale(null);
      seeded.current = { columns: freshColumns, drafts: freshDrafts };
      toast.success(
        brought.length > 0
          ? `Reloaded, keeping your edits. Updated from the other change: ${brought.join(", ")}.`
          : "Reloaded, keeping your edits."
      );
    } finally {
      setReloading(false);
    }
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setGeneral(null);
    const next: FieldErrors = {};

    // Client-side copy of 0009's `entity_key_not_blank` CHECK -- the API
    // maps that constraint to a 422 on `key`; this keeps the same sentence
    // on the field before a round-trip. The key feeds IR expressions and
    // `snapshot_dataset()`, where an empty one would be unaddressable.
    const trimmedKey = key.trim();
    if (trimmedKey === "") next.key = "Key: a key is required -- it is how model expressions refer to this entity.";

    const order =
      sortOrder.trim() === ""
        ? ({ ok: true, value: 0 } as const)
        : parseAttrValue("integer", sortOrder, [], "Sort order");
    if (!order.ok) next.sort_order = order.message;

    const built = buildAttrs(attributes, drafts);
    if (!built.ok) Object.assign(next, built.errors);

    replace(next);
    if (Object.keys(next).length > 0) return;

    const body = {
      key: trimmedKey,
      label: label.trim() === "" ? null : label,
      sort_order: order.ok ? (order.value as number) : 0,
      active,
      attrs: built.ok ? built.attrs : {},
    };

    try {
      if (entity) {
        const saved = await updateEntity.mutateAsync({
          id: entity.id,
          // Ruling 42. Sent to be compared, never to be stored: a save
          // built on a superseded read is refused rather than silently
          // reverting whatever the other client wrote.
          body: updatedAt === null ? body : { ...body, updated_at: updatedAt },
        });
        resetFrom(saved);
        toast.success(`Entity "${saved.key}" saved`);
      } else {
        const created = await createEntity.mutateAsync({ entity_type_id: type.id, ...body });
        toast.success(`Entity "${created.key}" created`);
        navigate(`/entities/${created.id}`);
      }
    } catch (err) {
      // Ruling 42: not a field problem, and re-sending the same payload
      // would be refused again -- so it gets its own state and its own
      // remedy rather than a red line under a control.
      if (isStaleRecordError(err)) {
        setServerErrors(null);
        setGeneral(null);
        setStale(formatApiError(err));
        return;
      }
      const result = entityServerErrors(err, attributes.map((attribute) => attribute.name));
      setServerErrors(result.fields);
      setGeneral(result.general);
    }
  }

  async function handleDelete() {
    if (!entity) return;
    const cleared = clears.map((f) => `${f.kind}.${f.attribute} on ${f.count} record${f.count === 1 ? "" : "s"}`);
    const confirmed = window.confirm(
      `Delete entity "${entity.key}"? This also deletes every relationship it takes part in and every parameter ` +
        `value indexed by it.${cleared.length ? ` It also empties ${cleared.join(", ")}.` : ""} This cannot be undone.`
    );
    if (!confirmed) return;
    try {
      await deleteEntity.mutateAsync(entity.id);
      toast.success(`Entity "${entity.key}" deleted`);
      navigate("/entities");
    } catch (err) {
      toast.error(formatApiError(err));
    }
  }

  return (
    <div className="max-w-4xl space-y-6">
      <div>
        <nav aria-label="Breadcrumb" className="mb-2 text-sm">
          <Link to={`/entities?type=${type.id}`} className={BACK_LINK}>
            Entities
          </Link>
        </nav>
        <h1 className="text-lg font-semibold text-slate-900">
          {entity ? (
            <>
              <span className="sr-only">Entity </span>
              <span className="font-mono">{entity.key}</span>
            </>
          ) : (
            "New entity"
          )}
        </h1>
        <p className="mt-1 text-sm text-slate-600">
          Type <span className="font-mono">{type.name}</span>
        </p>
        {entity && (
          // B-3: restored for v1 (the v0 link lived on the generic
          // EntityDetail page and carried `&org=`). `domain` comes from the
          // entity's type -- entities have no domain of their own -- and the
          // graph switches to it before resolving `focus`, since the node is
          // only looked for in the loaded domain's graph.
          <p className="mt-1 text-sm">
            <Link
              to={`/graph?domain=${type.domain_id}&focus=${entity.id}`}
              className="inline-block rounded py-1 text-blue-600 underline hover:text-blue-800"
            >
              Open in graph
            </Link>
          </p>
        )}
      </div>

      <section aria-labelledby="entity-heading" className="rounded-md border border-slate-200 bg-white p-4">
        <h2 id="entity-heading" className="mb-3 text-base font-semibold text-slate-900">
          Record
        </h2>
        <form
          aria-label={entity ? `Entity ${entity.key}` : "New entity"}
          onSubmit={handleSubmit}
          noValidate
          className="space-y-4"
        >
          <ErrorSummary errors={errors} order={sortedFieldOrder(attributes)} summaryRef={summaryRef} />
          {stale && <StaleRecordNotice message={stale} onReload={handleReload} reloading={reloading} />}
          {general && <p className="whitespace-pre-line text-sm text-red-600">{general}</p>}

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <FieldLabel htmlFor={id("key")} required>
                Key
              </FieldLabel>
              <input
                id={id("key")}
                type="text"
                autoComplete="off"
                spellCheck={false}
                className={`${INPUT_CLASS} font-mono`}
                value={key}
                aria-invalid={errors.key ? "true" : undefined}
                aria-describedby={describedBy(id("key-hint"), errors.key && errorId("key"))}
                onChange={(e) => {
                  setKey(e.target.value);
                  clearError("key");
                }}
              />
              <p id={id("key-hint")} className="mt-1 text-xs text-slate-500">
                How model expressions refer to this entity, e.g. <code>ahmed</code> or <code>mon</code>. Unique
                within the type.
              </p>
              <FieldError id={errorId("key")} message={errors.key} />
            </div>

            <div>
              <FieldLabel htmlFor={id("label")}>Label</FieldLabel>
              <input
                id={id("label")}
                type="text"
                autoComplete="off"
                className={INPUT_CLASS}
                value={label}
                aria-invalid={errors.label ? "true" : undefined}
                aria-describedby={describedBy(id("label-hint"), errors.label && errorId("label"))}
                onChange={(e) => {
                  setLabel(e.target.value);
                  clearError("label");
                }}
              />
              <p id={id("label-hint")} className="mt-1 text-xs text-slate-500">
                Shown on screens instead of the key. Optional.
              </p>
              <FieldError id={errorId("label")} message={errors.label} />
            </div>

            <div>
              <FieldLabel htmlFor={id("sort_order")}>Sort order</FieldLabel>
              <input
                id={id("sort_order")}
                type="text"
                inputMode="numeric"
                autoComplete="off"
                className={INPUT_CLASS}
                value={sortOrder}
                aria-invalid={errors.sort_order ? "true" : undefined}
                aria-describedby={describedBy(id("sort_order-hint"), errors.sort_order && errorId("sort_order"))}
                onChange={(e) => {
                  setSortOrder(e.target.value);
                  clearError("sort_order");
                }}
              />
              <p id={id("sort_order-hint")} className="mt-1 text-xs text-slate-500">
                Lists are ordered by this first, then by key -- what puts Monday before Tuesday.
              </p>
              <FieldError id={errorId("sort_order")} message={errors.sort_order} />
            </div>

            <div className="flex items-center gap-2 sm:mt-7">
              <input
                id={id("active")}
                type="checkbox"
                className="h-6 w-6"
                checked={active}
                onChange={(e) => setActive(e.target.checked)}
              />
              <label htmlFor={id("active")} className="text-sm font-medium text-slate-700">
                Active
              </label>
            </div>
          </div>

          <fieldset className="border-t border-slate-200 pt-4">
            <legend className="text-sm font-semibold text-slate-900">Attributes</legend>
            <AttrsForm
              attributes={attributes}
              drafts={drafts}
              errors={errors}
              staleKeys={staleKeys}
              blocked={loopBlocked}
              onChange={(name, value) => {
                setDrafts((prev) => ({ ...prev, [name]: value }));
                clearError(attrField(name));
              }}
            />
          </fieldset>

          <div className="flex flex-wrap items-center gap-3">
            {canEdit && (
            <button
              type="submit"
              disabled={isSubmitting}
              className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isSubmitting ? "Saving…" : entity ? "Save entity" : "Create entity"}
            </button>
            )}
            <Link to={`/entities?type=${type.id}`} className="rounded px-3 py-2 text-sm text-slate-600 underline hover:text-slate-900">
              Cancel
            </Link>
          </div>
        </form>
      </section>

      {/* The relationships this entity takes part in. Until now an
          entity's page never showed which unit they work in, or which unit
          a unit sits under -- while the delete warning below counted those
          very rows. */}
      {entity && <RecordTrees entity={entity} />}

      {entity && <EntityRelationships entity={entity} entityType={type} />}

      {entity && canEdit && (
        <section aria-labelledby="delete-entity-heading" className="rounded-md border border-red-200 bg-white p-4">
          <h2 id="delete-entity-heading" className="mb-2 text-base font-semibold text-slate-900">
            Delete this entity
          </h2>
          <p className="mb-3 text-sm text-slate-600">
            Its relationships and any parameter values indexed by it go with it.
          </p>
          {refuses.length > 0 && (
            <div data-testid="delete-refused" className="mb-3 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-900">
              <p className="font-medium">It cannot be deleted while these records name it in a required field:</p>
              <ReferrerList fields={refuses} />
              <p className="mt-1">Point them at another record first.</p>
            </div>
          )}
          {clears.length > 0 && (
            <div data-testid="delete-clears" className="mb-3 text-sm text-slate-700">
              <p>Deleting it empties the field on records that name it:</p>
              <ReferrerList fields={clears} />
            </div>
          )}
          <button
            type="button"
            onClick={handleDelete}
            disabled={deleteEntity.isPending || refuses.length > 0}
            className="rounded-md border border-red-300 px-3 py-2 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-60"
          >
            Delete entity
          </button>
        </section>
      )}
    </div>
  );
}

function ReferrerList({ fields }: { fields: ReferrerField[] }) {
  return (
    <ul className="mt-1 space-y-1">
      {fields.map((f) => (
        <li key={`${f.kind}.${f.attribute}`}>
          <span className="font-mono">
            {f.kind}.{f.attribute}
          </span>
          {" — "}
          {f.records.map((r, i) => (
            <span key={r.id}>
              {i > 0 && ", "}
              <Link to={`/entities/${r.id}`} className="underline">
                {r.key}
              </Link>
            </span>
          ))}
          {f.count > f.records.length && ` and ${f.count - f.records.length} more`}
        </li>
      ))}
    </ul>
  );
}
