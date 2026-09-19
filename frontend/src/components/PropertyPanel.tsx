import { FormEvent, useEffect, useId, useState } from "react";
import { formatApiError } from "../api/errors";
import { relationshipErrorMessage } from "../api/graph";
import {
  useDeleteEntity,
  useDeleteRelationship,
  useEntityRecord,
  useEntityTypes,
  useUpdateEntity,
  useUpdateRelationship,
  type AttributeDef,
  type Entity,
  type Id,
} from "../api/v1";
import AttrsForm, { buildAttrs, draftsFromAttrs, staleAttrKeys, type AttrDrafts } from "./AttrsForm";
import { FieldLabel, INPUT_CLASS, useFieldErrors, type FieldErrors } from "./attrTypes";
import { entityServerErrors } from "../pages/EntityRecord";
import { useToast } from "./ToastProvider";
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
  graph: GraphResponse;
  selection: Selection;
  onClose: () => void;
};

export default function PropertyPanel({ domainId, graph, selection, onClose }: PropertyPanelProps) {
  if (!selection) {
    return <p className="text-sm text-slate-500">Select a node or edge to see its properties.</p>;
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
          <button type="submit" disabled={updateEntity.isPending} className={PRIMARY_BUTTON}>
            Save
          </button>
          <button type="button" onClick={handleDelete} disabled={deleteEntity.isPending} className={DANGER_BUTTON}>
            Delete
          </button>
          <button type="button" onClick={onClose} className={QUIET_BUTTON}>
            Close
          </button>
        </div>
      </form>
    </div>
  );
}

function EdgePanel({ graph, edgeId, onClose }: { graph: GraphResponse; edgeId: string; onClose: () => void }) {
  const edge = graph.edges.find((e) => e.id === edgeId);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const updateRelationship = useUpdateRelationship();
  const deleteRelationship = useDeleteRelationship();
  const toast = useToast();
  const attrsId = useId();

  useEffect(() => {
    setDraft(JSON.stringify(edge?.attributes ?? {}, null, 2));
  }, [edgeId, edge?.attributes]);

  if (!edge) return null;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    let attrs: Record<string, unknown>;
    try {
      attrs = JSON.parse(draft);
    } catch {
      setError("Attributes must be valid JSON.");
      return;
    }
    try {
      // A relationship's `attrs` has no `attribute_def` behind it in v1 --
      // only entities' do -- so this stays a JSON box rather than becoming a
      // typed form.
      await updateRelationship.mutateAsync({ id: Number(edge!.id), body: { attrs } });
      toast.success(`${edge!.type} saved`);
    } catch (err) {
      setError(relationshipErrorMessage(err));
    }
  }

  async function handleDelete() {
    setError(null);
    try {
      await deleteRelationship.mutateAsync(Number(edge!.id));
      toast.success(`${edge!.type} deleted`);
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
      {error && <p className="mb-2 whitespace-pre-line text-sm text-red-600">{error}</p>}
      <form onSubmit={handleSubmit} className="space-y-2" data-testid="edge-property-form">
        <FieldLabel htmlFor={attrsId}>Attributes (JSON)</FieldLabel>
        <textarea
          id={attrsId}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          rows={4}
          className={`${INPUT_CLASS} font-mono text-xs`}
        />
        <div className={BUTTON_ROW}>
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
          <button type="button" onClick={onClose} className={QUIET_BUTTON}>
            Close
          </button>
        </div>
      </form>
    </div>
  );
}
