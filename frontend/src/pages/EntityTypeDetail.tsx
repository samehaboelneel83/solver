import { FormEvent, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import AttributeDefEditor, { ATTRIBUTE_FIELDS } from "../components/AttributeDefEditor";
import {
  ErrorSummary,
  colourFieldError,
  dataTypeLabel,
  formatDefault,
  nameProblem,
  serverFieldErrors,
  useFieldErrors,
  type FieldErrors,
} from "../components/attrTypes";
import OfflineNotice from "../components/OfflineNotice";
import StaleRecordNotice from "../components/StaleRecordNotice";
import { useToast } from "../components/ToastProvider";
import { ApiError } from "../api/client";
import { formatApiError, isStaleRecordError } from "../api/errors";
import {
  useCreateAttribute,
  useDeleteAttribute,
  useDeleteEntityType,
  useEntityType,
  useUpdateAttribute,
  useUpdateEntityType,
  type AttributeDef,
  type AttributeDefCreate,
  type EntityRole,
  type EntityType,
} from "../api/v1";
import { useCapabilities } from "../hooks/useCapability";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { parseRouteId } from "../lib/routeId";
import { mergeReload, reloadedKeys } from "../lib/staleRecord";
import { ENTITY_TYPE_FIELDS, EntityTypeFields } from "./EntityTypes";

const BACK_LINK = "inline-block rounded py-1 text-sm text-blue-600 underline";

/**
 * One entity type and its attribute definitions, edited together: the
 * type's own name and role at the top, its attributes below, each added,
 * edited or removed in place.
 */
export default function EntityTypeDetail() {
  const { id: rawId } = useParams();
  const id = parseRouteId(rawId);
  const { data, error, isError, refetch, fetchStatus } = useEntityType(id);
  useDocumentTitle(data ? `Entity type ${data.name}` : "Entity type");

  if (id === null || (isError && error instanceof ApiError && error.status === 404)) {
    return (
      <div>
        {/* Every page needs a level-1 heading, including this one: without
            it the page has none at all (axe `page-has-heading-one`) and a
            screen-reader user has nothing to land on. */}
        <h1 className="mb-2 text-lg font-semibold text-slate-900">Entity type not found.</h1>
        <Link to="/entity-types" className={BACK_LINK}>
          Back to entity types
        </Link>
      </div>
    );
  }
  if (fetchStatus === "paused" && !data) return <OfflineNotice subject="This entity type" />;
  if (isError && !data) {
    return (
      <div>
        <div className="mb-2 flex flex-wrap items-center gap-3">
          <p className="text-sm text-red-600">{formatApiError(error)}</p>
          <button
            type="button"
            onClick={() => refetch()}
            className="rounded-md border border-red-300 px-2 py-1 text-xs font-medium text-red-700 hover:bg-red-50"
          >
            Retry
          </button>
        </div>
        <Link to="/entity-types" className={BACK_LINK}>
          Back to entity types
        </Link>
      </div>
    );
  }
  if (!data) return <p className="text-sm text-slate-500">Loading…</p>;

  return (
    <Editor
      key={data.id}
      type={data}
      // Ruling 42: the read behind "Reload and keep my changes".
      reload={async () => (await refetch()).data ?? null}
    />
  );
}

function Editor({ type, reload }: { type: EntityType; reload: () => Promise<EntityType | null> }) {
  return (
    <div className="max-w-4xl space-y-6">
      <div>
        <nav aria-label="Breadcrumb" className="mb-2 text-sm">
          <Link to="/entity-types" className={BACK_LINK}>
            Entity types
          </Link>
        </nav>
        <h1 className="text-lg font-semibold text-slate-900">
          <span className="sr-only">Entity type </span>
          <span className="font-mono">{type.name}</span>
        </h1>
      </div>
      <TypeForm type={type} reload={reload} />
      <Attributes type={type} />
      <DeleteType type={type} />
    </div>
  );
}

/** The three controls this form holds, as the reload merge compares
 * them. The attributes below are edited through their own routes and are
 * not part of the type's own row -- see `test_api_concurrency.py`. */
type TypeDrafts = { name: string; role: EntityRole; colour: string | null };

const typeDraftsOf = (type: EntityType): TypeDrafts => ({
  name: type.name,
  role: type.role,
  colour: type.colour,
});

function TypeForm({ type, reload }: { type: EntityType; reload: () => Promise<EntityType | null> }) {
  const { can } = useCapabilities();
  const [name, setName] = useState(type.name);
  const [role, setRole] = useState<EntityRole>(type.role);
  const [colour, setColour] = useState<string | null>(type.colour);
  // See `EntityTypes.CreateTypeForm`: an unparseable entry has no value to
  // hold, so the reason it has none is held instead.
  const [colourProblem, setColourProblem] = useState<string | null>(null);
  const [serverErrors, setServerErrors] = useState<FieldErrors | null>(null);
  const [general, setGeneral] = useState<string | null>(null);
  const { errors, replace, summaryRef } = useFieldErrors(serverErrors);
  // Ruling 42 -- see `EntityRecord.tsx` for the full reasoning; this form
  // has the same defect and the same remedy, with three controls instead
  // of four plus a generated set.
  const [updatedAt, setUpdatedAt] = useState(type.updated_at);
  const [stale, setStale] = useState<string | null>(null);
  const [reloading, setReloading] = useState(false);
  const seeded = useRef<TypeDrafts>(typeDraftsOf(type));
  const updateType = useUpdateEntityType();
  const toast = useToast();

  async function handleReload() {
    setReloading(true);
    try {
      const fresh = await reload();
      if (!fresh) return;
      const freshDrafts = typeDraftsOf(fresh);
      const current: TypeDrafts = { name, role, colour };
      const merged = mergeReload(seeded.current, current, freshDrafts);
      setName(merged.name);
      setRole(merged.role);
      setColour(merged.colour);
      const brought = reloadedKeys(seeded.current, current, freshDrafts);
      setUpdatedAt(fresh.updated_at);
      setStale(null);
      seeded.current = freshDrafts;
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
    const problems: FieldErrors = {};
    const problem = nameProblem(name, false);
    if (problem) problems.name = problem;
    const colourMessage = colourFieldError(colourProblem);
    if (colourMessage) problems.colour = colourMessage;
    replace(problems);
    if (Object.keys(problems).length > 0) return;
    try {
      const saved = await updateType.mutateAsync({
        id: type.id,
        body: { name, role, colour, updated_at: updatedAt },
      });
      setUpdatedAt(saved.updated_at);
      seeded.current = typeDraftsOf(saved);
      toast.success("Entity type saved");
    } catch (err) {
      if (isStaleRecordError(err)) {
        setServerErrors(null);
        setGeneral(null);
        setStale(formatApiError(err));
        return;
      }
      const result = serverFieldErrors(err, ENTITY_TYPE_FIELDS, "entity type");
      setServerErrors(result.fields);
      setGeneral(result.general);
    }
  }

  return (
    <section aria-labelledby="type-heading" className="rounded-md border border-slate-200 bg-white p-4">
      <h2 id="type-heading" className="mb-3 text-base font-semibold text-slate-900">
        Type
      </h2>
      <form aria-label="Entity type" onSubmit={handleSubmit} noValidate className="space-y-4">
        <ErrorSummary errors={errors} order={ENTITY_TYPE_FIELDS} summaryRef={summaryRef} />
        {stale && <StaleRecordNotice message={stale} onReload={handleReload} reloading={reloading} />}
        {general && <p className="whitespace-pre-line text-sm text-red-600">{general}</p>}
        <EntityTypeFields
          name={name}
          role={role}
          colour={colour}
          errors={errors}
          fallbackKey={String(type.id)}
          onColour={setColour}
          onColourProblem={setColourProblem}
          onName={(value) => {
            setName(value);
            if (errors.name) {
              const { name: _drop, ...rest } = errors;
              replace(rest);
            }
          }}
          onRole={(value) => {
            setRole(value);
            if (errors.role) {
              const { role: _drop, ...rest } = errors;
              replace(rest);
            }
          }}
        />
        {can("domain.edit") && (
          <button
            type="submit"
            disabled={updateType.isPending}
            className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {updateType.isPending ? "Saving…" : "Save entity type"}
          </button>
        )}
      </form>
    </section>
  );
}

/** Which editor is open: none, a new attribute, or an existing one by id. */
type Editing = null | "new" | number;

function Attributes({ type }: { type: EntityType }) {
  const { can } = useCapabilities();
  const canEdit = can("domain.edit");
  const [editing, setEditing] = useState<Editing>(null);
  const [serverErrors, setServerErrors] = useState<FieldErrors | null>(null);
  const [general, setGeneral] = useState<string | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const createAttribute = useCreateAttribute();
  const updateAttribute = useUpdateAttribute();
  const deleteAttribute = useDeleteAttribute();
  const toast = useToast();

  const editingAttribute = typeof editing === "number" ? type.attributes.find((a) => a.id === editing) : undefined;

  function open(next: Editing) {
    setServerErrors(null);
    setGeneral(null);
    setEditing(next);
  }

  function close() {
    open(null);
    headingRef.current?.focus();
  }

  function refused(err: unknown) {
    const result = serverFieldErrors(err, ATTRIBUTE_FIELDS, "attribute");
    setServerErrors(result.fields);
    setGeneral(result.general);
  }

  async function handleCreate(body: AttributeDefCreate) {
    setGeneral(null);
    try {
      const created = await createAttribute.mutateAsync({ entityTypeId: type.id, body });
      toast.success(`Attribute "${created.name}" added`);
      close();
    } catch (err) {
      refused(err);
    }
  }

  async function handleUpdate(attribute: AttributeDef, body: AttributeDefCreate) {
    setGeneral(null);
    try {
      const saved = await updateAttribute.mutateAsync({ id: attribute.id, body });
      toast.success(`Attribute "${saved.name}" saved`);
      close();
    } catch (err) {
      refused(err);
    }
  }

  async function handleDelete(attribute: AttributeDef) {
    const confirmed = window.confirm(
      `Delete attribute "${attribute.name}"? Values already stored on entities are not removed: an entity that ` +
        `still holds a "${attribute.name}" value will be refused on its next save (unknown attribute) until that ` +
        `value is removed. This cannot be undone.`
    );
    if (!confirmed) return;
    try {
      await deleteAttribute.mutateAsync(attribute.id);
      toast.success(`Attribute "${attribute.name}" deleted`);
      if (editing === attribute.id) close();
    } catch (err) {
      toast.error(formatApiError(err));
    }
  }

  return (
    <section aria-labelledby="attributes-heading" className="rounded-md border border-slate-200 bg-white p-4">
      <h2 id="attributes-heading" ref={headingRef} tabIndex={-1} className="mb-3 text-base font-semibold text-slate-900">
        Attributes
      </h2>

      {type.attributes.length === 0 ? (
        <p className="mb-4 text-sm text-slate-600">No attributes yet. Every entity of this type will have only a key and a label until you add some.</p>
      ) : (
        <div className="mb-4 overflow-x-auto">
          <table className="w-full text-left text-sm" aria-label="Attributes">
            <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-600">
              <tr>
                <th scope="col" className="px-2 py-2 font-semibold">Name</th>
                <th scope="col" className="px-2 py-2 font-semibold">Data type</th>
                <th scope="col" className="px-2 py-2 font-semibold">Required</th>
                <th scope="col" className="px-2 py-2 font-semibold">Unit</th>
                <th scope="col" className="px-2 py-2 font-semibold">Allowed values</th>
                <th scope="col" className="px-2 py-2 font-semibold">Default</th>
                <th scope="col" className="px-2 py-2 font-semibold">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {type.attributes.map((attribute) => (
                <tr key={attribute.id} className="border-b border-slate-100 last:border-0 align-top">
                  <th scope="row" className="px-2 py-2 font-mono font-normal text-slate-900">
                    {attribute.name}
                  </th>
                  <td className="px-2 py-2 text-slate-700">{dataTypeLabel(attribute.data_type)}</td>
                  <td className="px-2 py-2 text-slate-700">{attribute.required ? "Yes" : "No"}</td>
                  <td className="px-2 py-2 text-slate-700">{attribute.unit ?? "—"}</td>
                  <td className="px-2 py-2 text-slate-700">
                    {attribute.enum_values ? attribute.enum_values.join(", ") : "—"}
                  </td>
                  <td className="px-2 py-2 text-slate-700">{formatDefault(attribute.default_value)}</td>
                  <td className="whitespace-nowrap px-2 py-1 text-right">
                    {canEdit && (
                      <>
                    <button
                      type="button"
                      aria-label={`Edit ${attribute.name}`}
                      onClick={() => open(attribute.id)}
                      className="rounded px-2 py-1.5 text-sm text-blue-600 underline hover:text-blue-800"
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      aria-label={`Delete ${attribute.name}`}
                      onClick={() => handleDelete(attribute)}
                      className="rounded px-2 py-1.5 text-sm text-red-700 underline hover:text-red-900"
                    >
                      Delete
                    </button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {editing === null && canEdit && (
        <button
          type="button"
          onClick={() => open("new")}
          className="rounded-md border border-slate-300 px-3 py-2 text-sm font-medium text-slate-800 hover:bg-slate-50"
        >
          Add attribute
        </button>
      )}

      {editing !== null && (
        <div className="rounded-md border border-slate-200 bg-slate-50 p-4">
          <h3 className="mb-3 text-sm font-semibold text-slate-900">
            {editing === "new" ? "New attribute" : `Edit attribute ${editingAttribute?.name ?? ""}`}
          </h3>
          {general && <p className="mb-3 whitespace-pre-line text-sm text-red-600">{general}</p>}
          {editing === "new" ? (
            <AttributeDefEditor
              key="new"
              submitLabel="Add attribute"
              onSubmit={handleCreate}
              onCancel={close}
              isSubmitting={createAttribute.isPending}
              serverErrors={serverErrors}
              autoFocus
            />
          ) : editingAttribute ? (
            <AttributeDefEditor
              key={editingAttribute.id}
              initial={editingAttribute}
              submitLabel="Save attribute"
              onSubmit={(body) => handleUpdate(editingAttribute, body)}
              onCancel={close}
              isSubmitting={updateAttribute.isPending}
              serverErrors={serverErrors}
              autoFocus
            />
          ) : (
            <p className="text-sm text-slate-600">This attribute no longer exists.</p>
          )}
        </div>
      )}
    </section>
  );
}

function DeleteType({ type }: { type: EntityType }) {
  const { can } = useCapabilities();
  const deleteType = useDeleteEntityType();
  const toast = useToast();
  const navigate = useNavigate();

  async function handleDelete() {
    const count = type.attributes.length;
    const attributes = count === 1 ? "its 1 attribute definition" : `its ${count} attribute definitions`;
    // What goes with it is the database's ON DELETE CASCADE chain
    // (migration 0006): attribute_def and entity reference entity_type;
    // relationship_type references it on both ends, and relationship
    // references relationship_type. parameter_def.index_type_ids is a
    // plain bigint[] with no foreign key, so it is left dangling.
    const confirmed = window.confirm(
      `Delete entity type "${type.name}"? This also deletes ${attributes}, every entity of this type, ` +
        `all relationship types that use it, and their relationships. Parameters indexed by it are not deleted, ` +
        `but are left pointing at a type that no longer exists. This cannot be undone.`
    );
    if (!confirmed) return;
    try {
      await deleteType.mutateAsync(type.id);
      toast.success(`Entity type "${type.name}" deleted`);
      navigate("/entity-types");
    } catch (err) {
      toast.error(formatApiError(err));
    }
  }

  if (!can("domain.edit")) return null;

  return (
    <section aria-labelledby="delete-type-heading" className="rounded-md border border-red-200 bg-white p-4">
      <h2 id="delete-type-heading" className="mb-2 text-base font-semibold text-slate-900">
        Delete this type
      </h2>
      <p className="mb-3 text-sm text-slate-600">
        Deleting a type also deletes its attributes, its entities and the relationship types that use it.
      </p>
      <button
        type="button"
        onClick={handleDelete}
        disabled={deleteType.isPending}
        className="rounded-md border border-red-300 px-3 py-2 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-60"
      >
        Delete entity type
      </button>
    </section>
  );
}
