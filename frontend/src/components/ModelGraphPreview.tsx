import { lazy, Suspense, useMemo, useState } from "react";
import { buildModelView, modelDetails, type ModelPart } from "../lib/modelGraph";
import type { EntityType } from "../api/v1";
import { readLayout, writeLayout, type Positions } from "../model/graphLayout";

const FlowView = lazy(() => import("./modelStyles/FlowView"));

export default function ModelGraphPreview({ ir, entityTypes, editorHref, selection, onSelect, layoutKey }: {
  ir: Record<string, unknown>;
  entityTypes: EntityType[];
  editorHref?: (part: ModelPart) => string;
  selection?: string | null;
  onSelect?: (id: string, part: ModelPart) => void;
  /** Where to keep card positions (per account, in this browser); without it they last as long as the graph. */
  layoutKey?: string;
}) {
  const view = useMemo(() => buildModelView(ir, entityTypes), [ir, entityTypes]);
  const [positions, setPositions] = useState<Positions>(() => (layoutKey ? readLayout(layoutKey) : {}));
  const [unsaved, setUnsaved] = useState(false);
  const arrange = (next: Positions) => {
    setPositions(next);
    if (layoutKey) setUnsaved(!writeLayout(layoutKey, next));
  };
  const [layoutRevision, setLayoutRevision] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const selectedNode = view.graph.nodes.find(node => node.id === (selection === undefined ? selected : selection));
  const select = (id: string) => {
    setSelected(id);
    const node = view.graph.nodes.find(item => item.id === id);
    if (node) onSelect?.(id, node.attributes?.part as ModelPart);
  };
  const details = modelDetails(selectedNode);
  const part = selectedNode?.attributes?.part as ModelPart | undefined;
  return <section aria-label="Visual Graph preview" className="mb-6 space-y-3">
    <p className="rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm text-blue-900">
      {editorHref ? "Select a card to focus its editor below and inspect its dependencies. Create variables, rules and objectives with the guided forms in this workspace. Connections follow the model expressions; dragging cards only rearranges the preview." : "Preview of the current draft. Select a card to inspect it."}
    </p>
    <Suspense fallback={<p role="status">Loading visual graph…</p>}>
      <div className="h-[32rem] rounded-xl border border-slate-200">
        <FlowView key={`${layoutRevision}:${JSON.stringify(ir)}`} {...view} ir={ir} onSelect={select}
          positions={positions} onMove={(id, position) => arrange({ ...positions, [id]: position })} />
      </div>
    </Suspense>
    <div className="flex items-center gap-3 text-sm">
      <button type="button" className="rounded border px-3 py-2" onClick={() => { arrange({}); setLayoutRevision(value => value + 1); }}>Reset graph layout</button>
      <span className="text-slate-600">
        {!layoutKey ? "Card positions stay while editing this graph. They are not saved with the model."
          : unsaved ? "This browser could not save the card positions; they last until you leave this graph."
            : "Card positions are kept for you in this browser. They are never part of the model, and Undo edit does not move them."}
      </span>
    </div>
    <details><summary className="cursor-pointer py-2 text-sm font-medium">Model parts as a list</summary>
      <ul className="flex flex-wrap gap-2">{view.graph.nodes.map(node => <li key={node.id}>
        <button type="button" className="rounded border px-3 py-2 text-sm" aria-pressed={selectedNode?.id === node.id} onClick={() => select(node.id)}>{node.label ?? node.id}</button>
      </li>)}</ul>
    </details>
    {part && editorHref && <a className="inline-block rounded border border-blue-300 px-3 py-2 text-blue-800 underline" href={editorHref(part)}>Edit {part === "rules" ? "rules" : part === "objective" ? "objective" : "declarations"} below</a>}
    {details && <pre className="overflow-auto rounded-lg bg-slate-50 p-4 text-sm" aria-label="Selected model part">{JSON.stringify(details, null, 2)}</pre>}
  </section>;
}
