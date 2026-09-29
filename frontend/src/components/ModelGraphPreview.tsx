import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { buildModelView, modelDetails, type ModelPart } from "../lib/modelGraph";
import { getGraphLayout, saveGraphLayout, type EntityType, type Id } from "../api/v1";
import { readLayout, writeLayout, type Positions } from "../model/graphLayout";
import type { FormDraft } from "../model/draftIr";
import { connect, connectionFor, type Connection } from "../model/graphCommands";
import GraphInspector, { type GraphEdit, type GraphPart } from "./GraphInspector";

const FlowView = lazy(() => import("./modelStyles/FlowView"));

/** How long the graph waits after the last move before saving to the server. */
const SAVE_AFTER_MS = 500;

/** How far one press of a move button shifts a card, in canvas pixels. */
const STEP = 40;
const MOVES = [
  { name: "left", dx: -STEP, dy: 0, arrow: "←" },
  { name: "up", dx: 0, dy: -STEP, arrow: "↑" },
  { name: "down", dx: 0, dy: STEP, arrow: "↓" },
  { name: "right", dx: STEP, dy: 0, arrow: "→" },
] as const;

/** A card as the graph commands name it: its part, and its name (a rule's id) from its first line. */
function partOf(node: { id: string; label?: string | null; attributes?: Record<string, unknown> }): GraphPart {
  const label = String(node.label ?? node.id);
  return { nodeId: node.id, part: node.attributes?.part as ModelPart, name: label.split("\n")[0], label: label.replace(/\s+/g, " ").trim() };
}

export default function ModelGraphPreview({ ir, entityTypes, editorHref, selection, onSelect, layoutKey, layoutProblemId, draft, onEdit }: {
  ir: Record<string, unknown>;
  entityTypes: EntityType[];
  editorHref?: (part: ModelPart) => string;
  selection?: string | null;
  onSelect?: (id: string, part: ModelPart) => void;
  /** Where to keep card positions (per account, in this browser); without it they last as long as the graph. */
  layoutKey?: string;
  /** Also keep the positions on the server, per account and problem, so they follow the person to another browser. */
  layoutProblemId?: Id;
  /** With both, the graph edits the model (Epic UX, U-2): inspectors, connections, deletion, keyboard. */
  draft?: FormDraft | null;
  onEdit?: (edit: GraphEdit) => void;
}) {
  const editable = Boolean(draft && onEdit);
  const [mode, setMode] = useState<"inspect" | "connect" | "delete">("inspect");
  const [said, setSaid] = useState<string | null>(null);
  const edit = (change: GraphEdit, done: string) => {
    // The functional form keeps an edit made on a newer draft than this render's.
    onEdit?.((current) => {
      try {
        return change(current);
      } catch {
        return current;
      }
    });
    setSaid(done);
  };
  const view = useMemo(() => buildModelView(ir, entityTypes), [ir, entityTypes]);
  const [positions, setPositions] = useState<Positions>(() => (layoutKey ? readLayout(layoutKey) : {}));
  const [unsaved, setUnsaved] = useState(false);
  const [nudge, setNudge] = useState<{ id: string; dx: number; dy: number; seq: number } | null>(null);
  const [layoutRevision, setLayoutRevision] = useState(0);
  // The server copy (when there is a problem to keep it under). This browser's
  // copy shows at once; the server's replaces it unless a card moved first.
  const [server, setServer] = useState<"off" | "kept" | "failed">(layoutProblemId == null ? "off" : "kept");
  const moved = useRef(false);
  const pending = useRef<{ timer: ReturnType<typeof setTimeout>; send: () => void } | null>(null);
  const initial = useRef(positions);
  useEffect(() => {
    if (layoutProblemId == null) return;
    let live = true;
    getGraphLayout(layoutProblemId).then((remote) => {
      if (!live) return;
      const kept = remote.positions ?? {};
      if (Object.keys(kept).length > 0 && !moved.current) {
        setPositions(kept);
        if (layoutKey) writeLayout(layoutKey, kept);
        setLayoutRevision((value) => value + 1);
      } else if (Object.keys(kept).length === 0 && Object.keys(initial.current).length > 0 && !moved.current) {
        // A layout from before the server kept them: hand it over once.
        void saveGraphLayout(layoutProblemId, initial.current).catch(() => live && setServer("failed"));
      }
    }).catch(() => live && setServer("failed"));
    return () => {
      live = false;
      // Leaving the graph saves a move still waiting for its pause.
      if (pending.current) {
        clearTimeout(pending.current.timer);
        pending.current.send();
        pending.current = null;
      }
    };
  }, [layoutProblemId, layoutKey]);
  const arrange = (next: Positions) => {
    moved.current = true;
    setPositions(next);
    if (layoutKey) setUnsaved(!writeLayout(layoutKey, next));
    if (layoutProblemId != null) {
      if (pending.current) clearTimeout(pending.current.timer);
      const send = () => {
        saveGraphLayout(layoutProblemId, next).then(() => setServer("kept"), () => setServer("failed"));
      };
      pending.current = { send, timer: setTimeout(() => { pending.current = null; send(); }, SAVE_AFTER_MS) };
    }
  };
  const [selected, setSelected] = useState<string | null>(null);
  const selectedNode = view.graph.nodes.find(node => node.id === (selection === undefined ? selected : selection));
  const select = (id: string) => {
    setSelected(id);
    setMode("inspect");
    const node = view.graph.nodes.find(item => item.id === id);
    if (node) onSelect?.(id, node.attributes?.part as ModelPart);
  };
  // A card's label may run over lines; a button's name reads as one.
  const selectedName = selectedNode ? String(selectedNode.label ?? selectedNode.id).replace(/\s+/g, " ").trim() : "";
  const details = modelDetails(selectedNode);
  const part = selectedNode?.attributes?.part as ModelPart | undefined;
  return <section aria-label="Visual Graph preview" className="mb-6 space-y-3">
    <p className="rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm text-blue-900">
      {editable ? "Select a card to inspect and edit it. Drag from one card's right edge to another card to connect them: a set to a decision or rule, a decision to a rule or the goal, a parameter to a rule. Every edit also shows in Guided Form."
        : editorHref ? "Select a card to focus its editor below and inspect its dependencies. Create variables, rules and objectives with the guided forms in this workspace. Connections follow the model expressions; dragging cards only rearranges the preview." : "Preview of the current draft. Select a card to inspect it."}
    </p>
    <Suspense fallback={<p role="status">Loading visual graph…</p>}>
      <div className="h-[32rem] rounded-xl border border-slate-200">
        <FlowView key={`${layoutRevision}:${JSON.stringify(ir)}`} {...view} ir={ir} onSelect={select}
          positions={positions} onMove={(id, position) => arrange({ ...positions, [id]: position })} nudge={nudge}
          onConnect={editable ? (sourceId, targetId) => {
            const source = view.graph.nodes.find((node) => node.id === sourceId);
            const target = view.graph.nodes.find((node) => node.id === targetId);
            if (!source || !target || !draft) return;
            const from = partOf(source);
            const to = partOf(target);
            const found = connectionFor(from, to);
            if ("refused" in found) return setSaid(`Not connected: ${found.refused}`);
            // A drag makes the connection with coefficient 1; the Connect form sets another.
            const connection: Connection =
              found.kind === "index" ? { kind: "index", set: from.name, variable: to.name }
                : found.kind === "for-each" ? { kind: "for-each", set: from.name, rule: to.name }
                  : found.kind === "use-in-rule" ? { kind: "use-in-rule", source: from, rule: to.name, coefficient: 1 }
                    : { kind: "use-in-objective", variable: from.name, coefficient: 1 };
            try {
              connect(draft, connection);
              edit((current) => connect(current, connection), `Connected: ${found.says}.`);
            } catch (error) {
              setSaid(`Not connected: ${(error as Error).message}`);
            }
          } : undefined} />
      </div>
    </Suspense>
    {selectedNode && <div role="group" aria-label={`Move ${selectedName}`} className="flex flex-wrap items-center gap-2 text-sm">
      <span className="text-slate-700">Move the selected card without dragging:</span>
      {MOVES.map(move => <button key={move.name} type="button" className="rounded border px-3 py-2"
        aria-label={`Move ${selectedName} ${move.name}`}
        onClick={() => setNudge(current => ({ id: selectedNode.id, dx: move.dx, dy: move.dy, seq: (current?.seq ?? 0) + 1 }))}>
        {move.arrow}
      </button>)}
    </div>}
    <div className="flex items-center gap-3 text-sm">
      <button type="button" className="rounded border px-3 py-2" onClick={() => { arrange({}); setLayoutRevision(value => value + 1); }}>Reset graph layout</button>
      <span className="text-slate-600">
        {server === "kept" ? "Card positions are kept for you on the server, so they follow you to another browser. They are never part of the model, and Undo edit does not move them."
          : server === "failed" ? "The server could not keep the card positions; this browser keeps them for now."
            : !layoutKey ? "Card positions stay while editing this graph. They are not saved with the model."
              : unsaved ? "This browser could not save the card positions; they last until you leave this graph."
                : "Card positions are kept for you in this browser. They are never part of the model, and Undo edit does not move them."}
      </span>
    </div>
    {said && <p role="status" className="rounded border border-slate-200 bg-slate-50 p-2 text-sm">{said}</p>}
    {editable && selectedNode && draft && <GraphInspector draft={draft} part={partOf(selectedNode)}
      parts={view.graph.nodes.map(partOf)} onEdit={edit} mode={mode} onMode={setMode} />}
    <details open={editable || undefined}><summary className="cursor-pointer py-2 text-sm font-medium">Model parts as a list</summary>
      {editable && <p className="mb-2 text-sm text-slate-600">
        With a part focused: Enter inspects it, <kbd>C</kbd> connects it to another part, <kbd>Delete</kbd> deletes it (you see what goes with it first).
      </p>}
      <ul className="flex flex-wrap gap-2">{view.graph.nodes.map(node => <li key={node.id}>
        <button type="button" className="rounded border px-3 py-2 text-sm" aria-pressed={selectedNode?.id === node.id}
          aria-keyshortcuts={editable ? "C Delete" : undefined}
          onClick={() => select(node.id)}
          onKeyDown={editable ? (event) => {
            if (event.key === "c" || event.key === "C") {
              event.preventDefault();
              select(node.id);
              setMode("connect");
            } else if (event.key === "Delete" || event.key === "Backspace") {
              event.preventDefault();
              select(node.id);
              setMode("delete");
            }
          } : undefined}>{node.label ?? node.id}</button>
      </li>)}</ul>
    </details>
    {part && editorHref && <a className="inline-block rounded border border-blue-300 px-3 py-2 text-blue-800 underline" href={editorHref(part)}>Edit {part === "rules" ? "rules" : part === "objective" ? "objective" : "declarations"} below</a>}
    {details && <pre className="overflow-auto rounded-lg bg-slate-50 p-4 text-sm" aria-label="Selected model part">{JSON.stringify(details, null, 2)}</pre>}
  </section>;
}
