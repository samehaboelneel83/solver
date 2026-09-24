/**
 * The model as editable blocks, over the shared draft (Blockly edit mode
 * spec §6). The draft is the only truth: the blocks are loaded from it, and
 * every change that alters meaning is turned back into IR (`blocksToIr`) and
 * handed to `onChange`, which writes the draft.
 *
 * The editor's behaviour is in `bindWorkspace` and `showIr`, exported so
 * they are tested on a headless workspace; this component only injects
 * Blockly around them (jsdom cannot measure text, so injecting is checked
 * in a real browser).
 */
import { useEffect, useRef } from "react";
import * as Blockly from "blockly";
import { setCatalogue, type BlockCatalogue } from "../lib/irBlocks/catalogue";
import { irToBlocks, type IrLoc } from "../lib/irBlocks/toBlocks";
import { blockForLoc, blocksToIr } from "../lib/irBlocks/toIr";
import { defineIrBlocks, loadBlocks, toolboxFor } from "../lib/irBlocks/vocabulary";

export type BlocksChange = (ir: Record<string, unknown>, paths: Map<string, IrLoc>, outside: number) => void;
export type BlockRefusal = { loc: IrLoc; message: string };

/** Where each block landed in the IR the workspace makes. */
function pathsOf(workspace: Blockly.Workspace): Map<string, IrLoc> {
  return blocksToIr(Blockly.serialization.workspaces.save(workspace) as Parameters<typeof blocksToIr>[0]).paths;
}

/**
 * Put `refusal` on the block that caused it -- the block whose place in the
 * IR is the longest prefix of the refusal's, else the model block itself --
 * clearing the block the last
 * one was on. Returns the id it landed on. Showing a warning is not an edit,
 * so no event is announced (it must never write the draft).
 */
export function showRefusal(
  workspace: Blockly.Workspace,
  paths: Map<string, IrLoc>,
  refusal: BlockRefusal | null | undefined,
  previous: string | null
): string | null {
  Blockly.Events.disable();
  try {
    if (previous) workspace.getBlockById(previous)?.setWarningText(null);
    // A refusal of the model as a whole (no decisions at all) lands on the model block.
    const id = refusal ? blockForLoc(paths, refusal.loc) ?? "model-root" : null;
    const block = id ? workspace.getBlockById(id) : null;
    if (!refusal || !block) return null;
    block.setWarningText(refusal.message);
    return block.id;
  } finally {
    Blockly.Events.enable();
  }
}

/** Load `ir` into `workspace` without announcing it as an edit: showing the draft is not changing it. */
export function showIr(workspace: Blockly.Workspace, ir: Record<string, unknown>): void {
  Blockly.Events.disable();
  try {
    workspace.clear();
    loadBlocks(workspace, irToBlocks(ir, { editable: true }));
  } finally {
    Blockly.Events.enable();
  }
}

/**
 * Report every change that alters meaning, as IR -- coalesced so a drag
 * that fires a dozen events writes the draft once. Selection, scrolling and
 * other UI events change nothing and are ignored. Returns the unbinding.
 */
export function bindWorkspace(
  workspace: Blockly.Workspace,
  onChange: BlocksChange,
  schedule: (run: () => void) => void = (run) => requestAnimationFrame(run)
): () => void {
  let pending = false;
  let stopped = false;
  const listener = (event: Blockly.Events.Abstract) => {
    if (event.isUiEvent || pending) return;
    pending = true;
    schedule(() => {
      pending = false;
      // Unbound (the editor closed) while this waited: the workspace may be gone.
      if (stopped) return;
      const { ir, paths, outside } = blocksToIr(
        Blockly.serialization.workspaces.save(workspace) as Parameters<typeof blocksToIr>[0]
      );
      onChange(ir, paths, outside);
    });
  };
  workspace.addChangeListener(listener);
  return () => {
    stopped = true;
    workspace.removeChangeListener(listener);
  };
}

export default function BlocksEditor({
  ir,
  catalogue,
  onChange,
  refusal = null,
  fill = false,
}: {
  ir: Record<string, unknown>;
  catalogue: BlockCatalogue;
  onChange: BlocksChange;
  /** Why the draft may not be published yet, and where: shown as a warning on that block. */
  refusal?: BlockRefusal | null;
  /** Fill the parent's height (the optimization view) rather than take most of the window's. */
  fill?: boolean;
}) {
  const host = useRef<HTMLDivElement>(null);
  const workspace = useRef<Blockly.WorkspaceSvg | null>(null);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  // What this editor last wrote: the draft echoing it back must not reload
  // the blocks under the person's hands.
  const lastEmitted = useRef<string | null>(null);
  const irRef = useRef(ir);
  irRef.current = ir;
  // Where each block sits in the IR, and the block now carrying a refusal.
  const paths = useRef<Map<string, IrLoc>>(new Map());
  const warned = useRef<string | null>(null);
  const refusalRef = useRef(refusal);
  refusalRef.current = refusal;

  useEffect(() => {
    if (!host.current) return;
    defineIrBlocks();
    const ws = Blockly.inject(host.current, {
      renderer: "zelos",
      theme: Blockly.Themes.Classic,
      toolbox: toolboxFor(catalogue),
      trashcan: true,
      sounds: false,
      move: { scrollbars: true, drag: true, wheel: true },
      zoom: { controls: true, wheel: false, startScale: 0.75, maxScale: 2, minScale: 0.3, scaleSpeed: 1.2 },
    });
    workspace.current = ws;
    setCatalogue(ws, catalogue);
    showIr(ws, irRef.current);
    lastEmitted.current = JSON.stringify(irRef.current);
    paths.current = pathsOf(ws);
    warned.current = showRefusal(ws, paths.current, refusalRef.current, null);
    const unbind = bindWorkspace(ws, (next, where, outside) => {
      lastEmitted.current = JSON.stringify(next);
      paths.current = where;
      onChangeRef.current(next, where, outside);
    });
    const observer = new ResizeObserver(() => Blockly.svgResize(ws));
    observer.observe(host.current);
    return () => {
      observer.disconnect();
      unbind();
      ws.dispose();
      workspace.current = null;
    };
    // The workspace is made once; the catalogue and the IR are followed below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const ws = workspace.current;
    if (!ws) return;
    setCatalogue(ws, catalogue);
    ws.updateToolbox(toolboxFor(catalogue));
  }, [catalogue]);

  useEffect(() => {
    const ws = workspace.current;
    const text = JSON.stringify(ir);
    if (!ws || text === lastEmitted.current) return;
    // Changed from elsewhere: Discard, the Forms tab, another browser tab.
    showIr(ws, ir);
    lastEmitted.current = text;
    paths.current = pathsOf(ws);
    warned.current = showRefusal(ws, paths.current, refusalRef.current, null);
  }, [ir]);

  useEffect(() => {
    const ws = workspace.current;
    if (!ws) return;
    warned.current = showRefusal(ws, paths.current, refusal, warned.current);
  }, [refusal?.message, JSON.stringify(refusal?.loc ?? null)]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div
      ref={host}
      className={`${fill ? "h-full" : "h-[70vh] min-h-[420px]"} w-full rounded-md border border-slate-200`}
      data-testid="blocks-editor"
    />
  );
}
