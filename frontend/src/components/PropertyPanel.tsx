import { FormEvent, useState } from "react";
import { useDeleteEdge, useDeleteNode, useUpdateEdge, useUpdateNode } from "../api/graph";
import type { GraphResponse } from "../types/graph";

type Selection = { kind: "node" | "edge"; id: string } | null;

type PropertyPanelProps = {
  organizationId: string;
  hierarchyId: string | null;
  graph: GraphResponse;
  selection: Selection;
  onClose: () => void;
};

export default function PropertyPanel({ organizationId, hierarchyId, graph, selection, onClose }: PropertyPanelProps) {
  const updateNode = useUpdateNode(organizationId, hierarchyId);
  const deleteNode = useDeleteNode(organizationId, hierarchyId);
  const updateEdge = useUpdateEdge(organizationId, hierarchyId);
  const deleteEdge = useDeleteEdge(organizationId, hierarchyId);
  const [error, setError] = useState<string | null>(null);

  if (!selection) {
    return <p className="text-sm text-slate-400">Select a node or edge to see its properties.</p>;
  }

  if (selection.kind === "node") {
    const node = graph.nodes.find((n) => n.id === selection.id);
    if (!node) {
      return null;
    }
    const entityType = graph.entity_types.find((et) => et.code === node.type);
    const definitions = graph.attribute_definitions.filter((d) => d.entity_type_id === entityType?.id);

    function handleSubmit(event: FormEvent<HTMLFormElement>) {
      event.preventDefault();
      setError(null);
      const form = new FormData(event.currentTarget);
      const name = String(form.get("name") ?? "");
      const status = String(form.get("status") ?? "") || undefined;
      const description = String(form.get("description") ?? "") || undefined;
      const attributes: Record<string, unknown> = {};
      for (const def of definitions) {
        const raw = form.get(`attr:${def.code}`);
        if (raw !== null && raw !== "") {
          attributes[def.code] = def.data_type === "boolean" ? raw === "true" : raw;
        }
      }
      updateNode.mutate(
        { entityId: node!.id, payload: { name, status, description, attributes } },
        { onError: (err) => setError(err instanceof Error ? err.message : "Failed to save") }
      );
    }

    function handleDelete() {
      setError(null);
      deleteNode.mutate(node!.id, {
        onError: (err) => setError(err instanceof Error ? err.message : "Failed to delete"),
      });
    }

    return (
      <div>
        <h3 className="mb-2 text-sm font-semibold text-slate-900">
          {node.type}: {node.label}
        </h3>
        {error && <p className="mb-2 text-sm text-red-600">{error}</p>}
        <form onSubmit={handleSubmit} className="space-y-2" data-testid="node-property-form">
          <label className="block text-xs">
            Name
            <input
              name="name"
              defaultValue={node.label}
              className="block w-full rounded-md border border-slate-300 px-2 py-1 text-sm"
            />
          </label>
          <label className="block text-xs">
            Status
            <input
              name="status"
              defaultValue={String(node.attributes.status ?? "")}
              className="block w-full rounded-md border border-slate-300 px-2 py-1 text-sm"
            />
          </label>
          <label className="block text-xs">
            Description
            <input
              name="description"
              defaultValue={String(node.attributes.description ?? "")}
              className="block w-full rounded-md border border-slate-300 px-2 py-1 text-sm"
            />
          </label>
          {definitions.map((def) => (
            <label key={def.id} className="block text-xs">
              {def.name}
              <input
                name={`attr:${def.code}`}
                defaultValue={String(node.attributes[def.code] ?? "")}
                className="block w-full rounded-md border border-slate-300 px-2 py-1 text-sm"
              />
            </label>
          ))}
          <div className="flex gap-2">
            <button type="submit" className="rounded-md bg-slate-900 px-3 py-1 text-sm text-white">
              Save
            </button>
            <button
              type="button"
              onClick={handleDelete}
              className="rounded-md border border-red-300 px-3 py-1 text-sm text-red-600"
            >
              Delete
            </button>
            <button type="button" onClick={onClose} className="text-sm text-slate-500">
              Close
            </button>
          </div>
        </form>
      </div>
    );
  }

  const edge = graph.edges.find((e) => e.id === selection.id);
  if (!edge) {
    return null;
  }

  function handleEdgeSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const form = new FormData(event.currentTarget);
    const raw = String(form.get("attributes") ?? "{}");
    let attributes: Record<string, unknown> = {};
    try {
      attributes = JSON.parse(raw);
    } catch {
      setError("Attributes must be valid JSON");
      return;
    }
    updateEdge.mutate(
      { relationshipId: edge!.id, attributes },
      { onError: (err) => setError(err instanceof Error ? err.message : "Failed to save") }
    );
  }

  function handleEdgeDelete() {
    setError(null);
    deleteEdge.mutate(edge!.id, {
      onError: (err) => setError(err instanceof Error ? err.message : "Failed to delete"),
    });
  }

  return (
    <div>
      <h3 className="mb-2 text-sm font-semibold text-slate-900">{edge.type}</h3>
      {error && <p className="mb-2 text-sm text-red-600">{error}</p>}
      <form onSubmit={handleEdgeSubmit} className="space-y-2" data-testid="edge-property-form">
        <label className="block text-xs">
          Attributes (JSON)
          <textarea
            name="attributes"
            defaultValue={JSON.stringify(edge.attributes ?? {}, null, 2)}
            rows={4}
            className="block w-full rounded-md border border-slate-300 px-2 py-1 font-mono text-xs"
          />
        </label>
        <div className="flex gap-2">
          <button type="submit" className="rounded-md bg-slate-900 px-3 py-1 text-sm text-white">
            Save
          </button>
          <button
            type="button"
            onClick={handleEdgeDelete}
            className="rounded-md border border-red-300 px-3 py-1 text-sm text-red-600"
          >
            Delete
          </button>
          <button type="button" onClick={onClose} className="text-sm text-slate-500">
            Close
          </button>
        </div>
      </form>
    </div>
  );
}
