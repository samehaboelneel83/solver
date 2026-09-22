import { FormEvent, useEffect, useId, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { formatApiError, isStaleRecordError } from "../api/errors";
import { relationshipErrorMessage } from "../api/graph";
import {
  useDeleteEntity,
  useDeleteRelationship,
  useEntityRecord,
  useEntityType,
  useEntityTypes,
  useRelationship,
  useRelationshipType,
  useUpdateEntity,
  useUpdateEntityType,
  useUpdateRelationship,
  useUpdateRelationshipType,
  type AttributeDef,
  type Entity,
  type Id,
} from "../api/v1";
import AttrsForm, { buildAttrs, draftsFromAttrs, staleAttrKeys, type AttrDrafts } from "./AttrsForm";
import ColourField from "./ColourField";
import { FieldLabel, INPUT_CLASS, roleLabel, useFieldErrors, type FieldErrors } from "./attrTypes";
import { entityServerErrors } from "../pages/EntityRecord";
import { confirmDeleteRelationship, deletedRelationshipMessage } from "../lib/relationships";
import { useCapabilities } from "../hooks/useCapability";
import { useToast } from "./ToastProvider";
import StaleRecordNotice from "./StaleRecordNotice";
import { mergeReload } from "../lib/staleRecord";
import {
  CARDINALITY_LABEL,
  entityTypeIdFromNodeId,
  relationshipTypeIdFromEdgeId,
  type GraphMode,
} from "../lib/typesGraph";
import type { GraphResponse } from "../types/graph";

/**
 * The selected node's or edge's editor, beside the canvas.
 *
 * Two things about it are v1-shaped rather than v0-shaped.
 *
 * **A node is an `entity`, and its editable content is `label` plus
 * `attrs`.** v0's `code`/`status`/`description` columns are gone; the
 * attribute definitions are the whole story, and an attribute is entitled
 * to be *called* `code` or `status` (there is nothing built-in left for it
 * to collide with, so nothing is hidden here any more). The controls are
 * `AttrsForm`'s -- the same ones the entity record page uses -- so an
 * `integer` attribute is refused a decimal here exactly as it is there.
 *
 * **The stored entity is fetched, not read off the canvas.** `GraphNode`
 * carries `label` already falling back to `entity.key` (a node with no text
 * is unusable), and `attributes` without knowing which definitions exist.
 * Seeding the Label box from the node would therefore write the key into
 * `label` on the next save, and the attribute controls would have no types,
 * units, enum values or defaults. Both come from `GET /api/v1/entities/{id}`
 * and `GET /api/v1/entity-types?domain_id=` instead -- the latter is the
 * same query the create-node form runs, so React Query serves it once.
 */

type Selection = { kind: "node" | "edge"; id: string } | null;

type PropertyPanelProps = {
  domainId: Id;
  /** Which view the canvas is drawing. In the types view a node is an
   * `entity_type` and an edge is a `relationship_type`, so the panel edits
   * something else entirely. */
  mode: GraphMode;
  graph: GraphResponse;
  selection: Selection;
  onClose: () => void;
};

export default function PropertyPanel({
  domainId,
  mode,
  graph,
  selection,
  onClose,
}: PropertyPanelProps) {
  if (!selection) {
    return <p className="text-sm text-slate-500">Select a node or edge to see its properties.</p>;
  }
  if (mode === "types") {
    return selection.kind === "node" ? (
      <EntityTypePanel nodeId={selection.id} onClose={onClose} />
    ) : (
      <RelationshipTypePanel edgeId={selection.id} onClose={onClose} />
    );
  }
  if (selection.kind === "node") {
    return <NodePanel domainId={domainId} graph={graph} nodeId={selection.id} onClose={onClose} />;
  }
  return <EdgePanel graph={graph} edgeId={selection.id} onClose={onClose} />;
}

const BUTTON_ROW = "flex flex-wrap gap-2 pt-1";
const PRIMARY_BUTTON =
  "rounded-md bg-slate-900 px-3 py-1 text-sm text-white disabled:cursor-not-allowed disabled:opacity-60";
const DANGER_BUTTON =
  "rounded-md border border-red-300 px-3 py-1 text-sm text-red-600 disabled:cursor-not-allowed disabled:opacity-60";
// H-9: px-2 py-1 clears the 24px Target Size floor.
const QUIET_BUTTON = "rounded px-2 py-1 text-sm text-slate-500";

function NodePanel({
  domainId,
  graph,
  nodeId,
  onClose,
}: {
  domainId: Id;
  graph: GraphResponse;
  nodeId: string;
  onClose: () => void;
}) {
  const node = graph.nodes.find((n) => n.id === nodeId);
  const entityId = Number(nodeId);
  const entityQuery = useEntityRecord(Number.isSafeInteger(entityId) ? entityId : null);
  const typesQuery = useEntityTypes(domainId, { limit: 500 });

  if (!node) return null;
  const entityType = typesQuery.data?.items.find((type) => type.name === node.type);

  if (entityQuery.error || typesQuery.error) {
    return <p className="text-sm text-red-600">{formatApiError(entityQuery.error ?? typesQuery.error)}</p>;
  }
  if (!entityQuery.data || !entityType) {
    return <p className="text-sm text-slate-500">Loading…</p>;
  }

  return (
    <NodeForm
      key={entityQuery.data.id}
      // The heading names the type once. In v1 a type has ONE name, and the
      // wire's `code` is that same string -- "{name} ({code})" rendered every
      // type as "unit (unit)".
      typeName={entityType.name}
      attributes={entityType.attributes}
      entity={entityQuery.data}
      onClose={onClose}
    />
  );
}

function NodeForm({
  typeName,
  attributes,
  entity,
  onClose,
}: {
  typeName: string;
  attributes: AttributeDef[];
  entity: Entity;
  onClose: () => void;
}) {
  const { can } = useCapabilities();
  const canEdit = can("domain.edit");
  const [label, setLabel] = useState(entity.label ?? "");
  const [drafts, setDrafts] = useState<AttrDrafts>(() => draftsFromAttrs(attributes, entity.attrs));
  const [stored, setStored] = useState<Record<string, unknown>>(entity.attrs);
  const [serverErrors, setServerErrors] = useState<FieldErrors | null>(null);
  const [general, setGeneral] = useState<string | null>(null);
  const { errors, replace } = useFieldErrors(serverErrors);
  const updateEntity = useUpdateEntity();
  const deleteEntity = useDeleteEntity();
  const toast = useToast();
  const baseId = useId();

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setGeneral(null);
    const built = buildAttrs(attributes, drafts);
    if (!built.ok) {
      replace(built.errors);
      return;
    }
    replace({});
    try {
      // `attrs` is replaced wholesale and rebuilt from the CURRENT
      // definitions, so a key whose definition was deleted clears itself
      // (Task 12's binding finding) rather than failing as an unknown
      // attribute. `key`, `sort_order` and `active` are omitted, which PATCH
      // reads as "leave them alone" -- they belong to the record page.
      const saved = await updateEntity.mutateAsync({
        id: entity.id,
        body: { label: label.trim() === "" ? null : label, attrs: built.attrs },
      });
      // The trigger materialises defaults into `attrs` on write, so re-seed
      // from what was stored rather than from what was sent.
      setDrafts(draftsFromAttrs(attributes, saved.attrs));
      setStored(saved.attrs);
      toast.success(`${saved.label ?? saved.key} saved`);
    } catch (err) {
      // `entityServerErrors` also maps errors for columns this panel does not
      // show (a duplicate `key` is the real case: a 409 whose message belongs
      // to the record page's Key box). Those would be invisible here, so they
      // join the general message instead of being dropped.
      const result = entityServerErrors(err, attributes.map((attribute) => attribute.name));
      const attrErrors: FieldErrors = {};
      const unplaceable: string[] = [];
      for (const [field, message] of Object.entries(result.fields)) {
        if (field.startsWith("attr:")) attrErrors[field] = message;
        else unplaceable.push(message);
      }
      setServerErrors(attrErrors);
      const rest = [result.general, ...unplaceable].filter(Boolean) as string[];
      setGeneral(rest.length > 0 ? rest.join("\n") : null);
    }
  }

  async function handleDelete() {
    const confirmed = window.confirm(
      `Delete entity "${entity.key}"? This also deletes every relationship it takes part in and every parameter ` +
        `value indexed by it. This cannot be undone.`
    );
    if (!confirmed) return;
    try {
      await deleteEntity.mutateAsync(entity.id);
      toast.success(`${entity.label ?? entity.key} deleted`);
      onClose();
    } catch (err) {
      setGeneral(formatApiError(err));
    }
  }

  const labelId = `${baseId}-label`;
  return (
    <div>
      {/* N-3: the page's <h1> is GraphDemo's own, so this subsection is an
          <h2>; an <h3> here would skip a level. */}
      <h2 className="mb-2 text-sm font-semibold text-slate-900">
        {typeName}: {entity.label ?? entity.key}
      </h2>
      {general && <p className="mb-2 whitespace-pre-line text-sm text-red-600">{general}</p>}
      <form onSubmit={handleSubmit} className="space-y-3" data-testid="node-property-form">
        <p className="text-xs text-slate-500">
          Key <span data-testid="node-key" className="font-mono text-slate-700">{entity.key}</span>
        </p>
        <div>
          <FieldLabel htmlFor={labelId}>Label</FieldLabel>
          <input
            id={labelId}
            className={INPUT_CLASS}
            value={label}
            onChange={(event) => setLabel(event.target.value)}
            autoComplete="off"
          />
          <p className="mt-1 text-xs text-slate-500">Leave empty to show the key instead.</p>
        </div>
        <AttrsForm
          attributes={attributes}
          drafts={drafts}
          errors={errors}
          staleKeys={staleAttrKeys(attributes, stored)}
          onChange={(name, value) => setDrafts((prev) => ({ ...prev, [name]: value }))}
        />
        <div className={BUTTON_ROW}>
          {canEdit && (
            <>
          <button type="submit" disabled={updateEntity.isPending} className={PRIMARY_BUTTON}>
            Save
          </button>
          <button type="button" onClick={handleDelete} disabled={deleteEntity.isPending} className={DANGER_BUTTON}>
            Delete
          </button>
            </>
          )}
          <button type="button" onClick={onClose} className={QUIET_BUTTON}>
            Close
          </button>
        </div>
      </form>
    </div>
  );
}

/**
 * One relationship, beside the canvas.
 *
 * Until this round it showed the relationship TYPE's name and a JSON box,
 * and nothing else -- not which two entities it joined -- and its Delete
 * button removed it on one click, with no confirmation, no undo and a
 * toast naming only the type. Every other delete in the product asks
 * first and counts what goes with the record, and this one had the worst
 * case for not asking: there was no relationships list, so an accidental
 * delete was invisible afterwards.
 *
 * Both endpoints are read from the graph the canvas is already drawn
 * from, in the edge's own direction (from -> to, which for a hierarchy is
 * parent -> child), so no extra request is made to say what is on screen.
 * A node the payload does not hold shows as `#id` rather than blank --
 * the same spelling the type lists use -- because a confirmation that
 * silently drops one end is worse than one that admits it.
 *
 * The stored row is fetched rather than read off the canvas, so the form
 * can send `updated_at` (migration 0021) and a concurrent attrs overwrite
 * is refused instead of last-save-wins. When the type has declared
 * `attribute_def` rows (migration 0024), those attrs are the same typed
 * controls an entity uses; otherwise the JSON box remains.
 */
function EdgePanel({ graph, edgeId, onClose }: { graph: GraphResponse; edgeId: string; onClose: () => void }) {
  const { can } = useCapabilities();
  const canEdit = can("domain.edit");
  const edge = graph.edges.find((e) => e.id === edgeId);
  const relationshipId = Number(edgeId);
  const query = useRelationship(Number.isSafeInteger(relationshipId) ? relationshipId : null);
  const typeQuery = useRelationshipType(query.data?.relationship_type_id ?? null);
  const attributes = typeQuery.data?.attributes;
  const typed = (attributes?.length ?? 0) > 0;
  const nodeLabel = (id: string) => graph.nodes.find((node) => node.id === id)?.label ?? `#${id}`;
  const fromLabel = edge ? nodeLabel(edge.source) : "";
  const toLabel = edge ? nodeLabel(edge.target) : "";
  const seeded = useRef("");
  const loadedId = useRef<number | null>(null);
  const [draft, setDraft] = useState("");
  const [drafts, setDrafts] = useState<AttrDrafts>({});
  const [stored, setStored] = useState<Record<string, unknown>>({});
  const [serverErrors, setServerErrors] = useState<FieldErrors | null>(null);
  const { errors, replace } = useFieldErrors(serverErrors);
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);
  const [stale, setStale] = useState<string | null>(null);
  const [reloading, setReloading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const updateRelationship = useUpdateRelationship();
  const deleteRelationship = useDeleteRelationship();
  const toast = useToast();
  const attrsId = useId();

  useEffect(() => {
    loadedId.current = null;
  }, [edgeId]);

  useEffect(() => {
    if (!query.data || loadedId.current === query.data.id) return;
    loadedId.current = query.data.id;
    const text = JSON.stringify(query.data.attrs ?? {}, null, 2);
    seeded.current = text;
    setDraft(text);
    setStored(query.data.attrs ?? {});
    setUpdatedAt(query.data.updated_at);
    setStale(null);
  }, [query.data]);

  useEffect(() => {
    if (!query.data || !attributes?.length) return;
    setDrafts(draftsFromAttrs(attributes, query.data.attrs ?? {}));
  }, [query.data, attributes]);

  if (!edge) return null;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setStale(null);
    setServerErrors(null);
    let attrs: Record<string, unknown>;
    if (typed && attributes) {
      const built = buildAttrs(attributes, drafts);
      if (!built.ok) {
        replace(built.errors);
        return;
      }
      replace({});
      attrs = built.attrs;
    } else {
      try {
        attrs = JSON.parse(draft);
      } catch {
        setError("Attributes must be valid JSON.");
        return;
      }
    }
    try {
      // When the type has declared defs, attrs are rebuilt from those
      // (same as an entity). Otherwise the JSON box remains, for a type
      // that has not declared any. The whole object is replaced, which
      // is why `updated_at` is sent.
      const body = updatedAt === null ? { attrs } : { attrs, updated_at: updatedAt };
      const saved = await updateRelationship.mutateAsync({ id: Number(edge!.id), body });
      const text = JSON.stringify(saved.attrs ?? {}, null, 2);
      seeded.current = text;
      setDraft(text);
      setStored(saved.attrs ?? {});
      setDrafts(draftsFromAttrs(attributes ?? [], saved.attrs ?? {}));
      setUpdatedAt(saved.updated_at);
      toast.success(`${edge!.type} saved`);
    } catch (err) {
      if (isStaleRecordError(err)) {
        setError(null);
        setStale(formatApiError(err));
        return;
      }
      if (typed && attributes) {
        const result = entityServerErrors(err, attributes.map((attribute) => attribute.name));
        setServerErrors(result.fields);
        setError(result.general);
        return;
      }
      setError(relationshipErrorMessage(err));
    }
  }

  async function handleReload() {
    setReloading(true);
    try {
      const fresh = (await query.refetch()).data;
      if (!fresh) return;
      const freshText = JSON.stringify(fresh.attrs ?? {}, null, 2);
      if (typed && attributes) {
        const baseline = draftsFromAttrs(attributes, stored);
        const merged = mergeReload(baseline, drafts, draftsFromAttrs(attributes, fresh.attrs ?? {}));
        setDrafts(merged);
      } else {
        const merged = mergeReload({ json: seeded.current }, { json: draft }, { json: freshText });
        setDraft(merged.json);
      }
      setStored(fresh.attrs ?? {});
      setUpdatedAt(fresh.updated_at);
      setStale(null);
      seeded.current = freshText;
      toast.success("Reloaded, keeping your edits.");
    } finally {
      setReloading(false);
    }
  }

  async function handleDelete() {
    setError(null);
    // The same wording as the relationships page and an entity's own
    // section: three screens can now remove a relationship, and a
    // confirmation that differs between them is three chances to be
    // wrong about what is destroyed.
    const confirmed = window.confirm(confirmDeleteRelationship(edge!.type, fromLabel, toLabel));
    if (!confirmed) return;
    try {
      await deleteRelationship.mutateAsync(Number(edge!.id));
      toast.success(deletedRelationshipMessage(edge!.type, fromLabel, toLabel));
      onClose();
    } catch (err) {
      setError(relationshipErrorMessage(err));
    }
  }

  return (
    <div>
      {/* N-3: same level as the node heading. The relationship type's name,
          once -- `type` and `label` are the same string in v1. */}
      <h2 className="mb-2 text-sm font-semibold text-slate-900">{edge.type}</h2>
      {/* The two entities this edge joins, in its own direction. Without
          them the panel described a TYPE and left the reader to work out
          which of that type's edges they had clicked. */}
      <p data-testid="edge-ends" className="mb-2 text-xs text-slate-600">
        From <span className="font-medium text-slate-900">{fromLabel}</span> to{" "}
        <span className="font-medium text-slate-900">{toLabel}</span>
      </p>
      {query.error && (
        <p className="mb-2 whitespace-pre-line text-sm text-red-600">{formatApiError(query.error)}</p>
      )}
      {stale && (
        <div className="mb-2">
          <StaleRecordNotice message={stale} onReload={handleReload} reloading={reloading} />
        </div>
      )}
      {error && <p className="mb-2 whitespace-pre-line text-sm text-red-600">{error}</p>}
      {!query.data ? (
        <p className="text-sm text-slate-500">Loading…</p>
      ) : (
      <form onSubmit={handleSubmit} className="space-y-2" data-testid="edge-property-form">
        {typed ? (
          <AttrsForm
            attributes={attributes ?? []}
            drafts={drafts}
            errors={errors}
            staleKeys={staleAttrKeys(attributes ?? [], stored)}
            onChange={(name, value) => setDrafts((prev) => ({ ...prev, [name]: value }))}
          />
        ) : (
          <>
            <FieldLabel htmlFor={attrsId}>Attributes (JSON)</FieldLabel>
            <textarea
              id={attrsId}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              rows={4}
              className={`${INPUT_CLASS} font-mono text-xs`}
            />
          </>
        )}
        <div className={BUTTON_ROW}>
          {canEdit && (
            <>
          <button type="submit" disabled={updateRelationship.isPending} className={PRIMARY_BUTTON}>
            Save
          </button>
          <button
            type="button"
            onClick={handleDelete}
            disabled={deleteRelationship.isPending}
            className={DANGER_BUTTON}
          >
            Delete
          </button>
            </>
          )}
          <button type="button" onClick={onClose} className={QUIET_BUTTON}>
            Close
          </button>
        </div>
      </form>
      )}
    </div>
  );
}

/**
 * The types view's node panel: one `entity_type`.
 *
 * It edits exactly one thing -- the colour -- and links to the type's own
 * page for everything else. That is deliberate: name, role and attribute
 * definitions all have a full editor already (`EntityTypeDetail`, Task 11),
 * and a second, smaller copy of it beside the canvas would be two forms
 * that have to agree about the same validation.
 *
 * The row is fetched rather than read off the canvas, for the same reason
 * `NodePanel` fetches its entity: the built graph carries only what the
 * canvas draws, and saving from a projection would write back a projection.
 */
function EntityTypePanel({ nodeId, onClose }: { nodeId: string; onClose: () => void }) {
  const { can } = useCapabilities();
  const canEdit = can("domain.edit");
  const entityTypeId = entityTypeIdFromNodeId(nodeId);
  const query = useEntityType(entityTypeId);
  const update = useUpdateEntityType();
  const toast = useToast();
  const [error, setError] = useState<string | null>(null);

  if (entityTypeId === null) return null;
  if (query.error) return <p className="text-sm text-red-600">{formatApiError(query.error)}</p>;
  if (!query.data) return <p className="text-sm text-slate-500">Loading…</p>;
  const type = query.data;

  async function save(colour: string | null) {
    setError(null);
    try {
      await update.mutateAsync({ id: type.id, body: { colour } });
      toast.success(`${type.name} saved`);
    } catch (err) {
      setError(formatApiError(err));
    }
  }

  return (
    <div data-testid="entity-type-panel">
      <h2 className="mb-2 text-sm font-semibold text-slate-900">
        Entity type: <span className="font-mono">{type.name}</span>
      </h2>
      {error && <p className="mb-2 whitespace-pre-line text-sm text-red-600">{error}</p>}
      <dl className="mb-3 space-y-1 text-xs text-slate-600">
        <div className="flex gap-2">
          <dt className="font-medium">Role</dt>
          <dd data-testid="entity-type-role">{roleLabel(type.role)}</dd>
        </div>
        <div className="flex gap-2">
          <dt className="font-medium">Attributes</dt>
          <dd data-testid="entity-type-attribute-count">{type.attributes.length}</dd>
        </div>
      </dl>
      <ColourField
        value={type.colour}
        // The id the canvas hashes for the fallback, so the preview shows
        // the colour the node is actually drawn in today.
        fallbackKey={String(type.id)}
        sampleText={type.name}
        disabled={update.isPending || !canEdit}
        onChange={save}
      />
      <div className={`${BUTTON_ROW} mt-3`}>
        <Link
          to={`/entity-types/${type.id}`}
          className="rounded-md border border-slate-300 px-3 py-1 text-sm text-blue-600 underline"
        >
          Edit this type
        </Link>
        <button type="button" onClick={onClose} className={QUIET_BUTTON}>
          Close
        </button>
      </div>
    </div>
  );
}

/**
 * The types view's edge panel: one `relationship_type`.
 *
 * There is no relationship-type page in this app -- relationship types have
 * only ever been created through the API -- so unlike `EntityTypePanel`
 * this is the ONLY place a user can set one's colour. It still edits just
 * the colour: changing `from_type_id`, `cardinality` or `is_hierarchy`
 * re-judges every existing row through the trigger, which wants a real
 * form with the trigger's errors mapped onto its fields, not a side panel.
 */
function RelationshipTypePanel({ edgeId, onClose }: { edgeId: string; onClose: () => void }) {
  const { can } = useCapabilities();
  const canEdit = can("domain.edit");
  const relationshipTypeId = relationshipTypeIdFromEdgeId(edgeId);
  const query = useRelationshipType(relationshipTypeId);
  const typesQuery = useEntityTypes(query.data?.domain_id ?? null, { limit: 500 });
  const update = useUpdateRelationshipType();
  const toast = useToast();
  const [error, setError] = useState<string | null>(null);

  if (relationshipTypeId === null) return null;
  if (query.error) return <p className="text-sm text-red-600">{formatApiError(query.error)}</p>;
  if (!query.data) return <p className="text-sm text-slate-500">Loading…</p>;
  const type = query.data;
  const nameOf = (id: Id) =>
    typesQuery.data?.items.find((candidate) => candidate.id === id)?.name ?? `#${id}`;

  async function save(colour: string | null) {
    setError(null);
    try {
      await update.mutateAsync({ id: type.id, body: { colour } });
      toast.success(`${type.name} saved`);
    } catch (err) {
      setError(formatApiError(err));
    }
  }

  return (
    <div data-testid="relationship-type-panel">
      <h2 className="mb-2 text-sm font-semibold text-slate-900">
        Relationship type: <span className="font-mono">{type.name}</span>
      </h2>
      {error && <p className="mb-2 whitespace-pre-line text-sm text-red-600">{error}</p>}
      <dl className="mb-3 space-y-1 text-xs text-slate-600">
        <div className="flex gap-2">
          <dt className="font-medium">From → to</dt>
          <dd data-testid="relationship-type-ends" className="font-mono">
            {nameOf(type.from_type_id)} → {nameOf(type.to_type_id)}
          </dd>
        </div>
        <div className="flex gap-2">
          <dt className="font-medium">Cardinality</dt>
          <dd data-testid="relationship-type-cardinality">
            {CARDINALITY_LABEL[type.cardinality] ?? type.cardinality}
          </dd>
        </div>
        <div className="flex gap-2">
          <dt className="font-medium">Hierarchy</dt>
          <dd data-testid="relationship-type-hierarchy">{type.is_hierarchy ? "Yes" : "No"}</dd>
        </div>
      </dl>
      <ColourField
        value={type.colour}
        fallbackKey={String(type.id)}
        sampleText={type.name}
        disabled={update.isPending || !canEdit}
        onChange={save}
      />
      <div className={`${BUTTON_ROW} mt-3`}>
        <button type="button" onClick={onClose} className={QUIET_BUTTON}>
          Close
        </button>
      </div>
    </div>
  );
}
