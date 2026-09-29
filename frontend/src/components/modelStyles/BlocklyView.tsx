import { useEffect, useRef } from "react";
import * as Blockly from "blockly";
import { partFor, readOnlyWorkspace } from "../../lib/irBlocks/readOnly";
import { defineIrBlocks, loadBlocks } from "../../lib/irBlocks/vocabulary";
import type { ModelStyleProps } from "./types";

/**
 * The model as Blockly blocks, read-only: the same blocks the Model editor's
 * Blocks tab edits, each fixed in place, not editable or deletable, but
 * selectable -- which opens the same side panel as the other styles -- and
 * the workspace pans and zooms.
 */
export default function BlocklyView({ graph, ir, title, onSelect }: ModelStyleProps) {
  const host = useRef<HTMLDivElement>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  useEffect(() => {
    if (!host.current) return;
    defineIrBlocks();
    const workspace = Blockly.inject(host.current, {
      renderer: "zelos",
      // Blockly's icons from this app, not blockly-demo.appspot.com: an offline or
      // firewalled install has no route there (operator trial F11).
      media: `${import.meta.env.BASE_URL}blockly-media/`,
      theme: Blockly.Themes.Classic,
      trashcan: false,
      sounds: false,
      move: { scrollbars: true, drag: true, wheel: true },
      zoom: { controls: true, wheel: false, startScale: 0.75, maxScale: 2, minScale: 0.3, scaleSpeed: 1.2 },
    });
    loadBlocks(workspace, readOnlyWorkspace(ir, graph, title));
    const root = workspace.getBlockById("model-root");
    if (root) {
      // Start at the top of the model, not its middle: a long model's first
      // rules are the ones a reader looks for.
      const xy = root.getRelativeToSurfaceXY();
      workspace.scroll(-xy.x * workspace.scale + 16, -xy.y * workspace.scale + 16);
    }

    const known = new Set(graph.nodes.map((node) => node.id));
    const listener = (event: Blockly.Events.Abstract) => {
      if (event.type !== Blockly.Events.SELECTED) return;
      const id = (event as Blockly.Events.Selected).newElementId ?? null;
      const part = partFor(id, (blockId) => workspace.getBlockById(blockId)?.getParent()?.id ?? null, known);
      if (part) onSelectRef.current(part);
    };
    workspace.addChangeListener(listener);

    const observer = new ResizeObserver(() => Blockly.svgResize(workspace));
    observer.observe(host.current);
    return () => {
      observer.disconnect();
      workspace.dispose();
    };
  }, [graph, ir, title]);

  return <div ref={host} className="h-full w-full" data-testid="model-style-view-blockly" />;
}
