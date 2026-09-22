import { useEffect, useRef } from "react";
import { createRoot } from "react-dom/client";
import { ClassicPreset, NodeEditor, type GetSchemes } from "rete";
import { AreaExtensions, AreaPlugin } from "rete-area-plugin";
import { Presets, ReactPlugin, type ReactArea2D } from "rete-react-plugin";
import { layoutModel, PART_TITLE } from "../../lib/modelLayout";
import type { ModelPart } from "../../lib/modelGraph";
import { reteNodes } from "../../lib/modelNodes";
import type { ModelStyleProps } from "./types";

type Node = ClassicPreset.Node;
type Schemes = GetSchemes<Node, ClassicPreset.Connection<Node, Node>>;
type AreaExtra = ReactArea2D<Schemes>;

// Until a node is drawn its size is a guess; the layout uses what the
// browser measured, and this only if a node could not be measured.
const FALLBACK = { width: 200, height: 160 };

const nextFrame = () => new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));

/**
 * The model as a Rete.js node editor: every part a node, a socket for each
 * thing it reads, and a wire from the part that supplies it. Sets supply
 * "members", decisions and data supply "value", a soft rule supplies its
 * "penalty" to the goal. Nodes can be dragged to see behind them; nothing
 * can be connected or changed.
 */
export default function ReteView({ graph, onSelect }: ModelStyleProps) {
  const host = useRef<HTMLDivElement>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  useEffect(() => {
    if (!host.current) return;
    // Each editor draws into an element of its own, removed whole on
    // cleanup: destroying the area leaves behind views it was still
    // drawing, and a second editor in the same element would sit on them.
    const container = document.createElement("div");
    container.style.width = "100%";
    container.style.height = "100%";
    host.current.appendChild(container);
    // Built synchronously, so the cleanup below always has it to destroy;
    // the async part stops at its next step once cancelled -- React runs
    // this effect twice in development, and a first editor that kept adding
    // nodes after being destroyed left them drawn, unplaced, on top.
    let cancelled = false;
    const socket = new ClassicPreset.Socket("value");
    const editor = new NodeEditor<Schemes>();
    const area = new AreaPlugin<Schemes, AreaExtra>(container);

    (async () => {
      const render = new ReactPlugin<Schemes, AreaExtra>({ createRoot });
      render.addPreset(Presets.classic.setup());
      editor.use(area);
      area.use(render);
      AreaExtensions.simpleNodesOrder(area);
      AreaExtensions.selectableNodes(area, AreaExtensions.selector(), {
        accumulating: AreaExtensions.accumulateOnCtrl(),
      });

      const specs = reteNodes(graph);
      const byGraphId = new Map<string, Node>();
      const graphIdOf = new Map<string, string>();
      for (const spec of specs) {
        const node = new ClassicPreset.Node(`${PART_TITLE[spec.part as ModelPart] ?? ""}: ${spec.name}`);
        for (const input of spec.inputs) node.addInput(input.key, new ClassicPreset.Input(socket, input.label));
        if (spec.output) node.addOutput("out", new ClassicPreset.Output(socket, spec.output));
        if (spec.summary) {
          node.addControl("summary", new ClassicPreset.InputControl("text", { initial: spec.summary, readonly: true }));
        }
        await editor.addNode(node);
        if (cancelled) return;
        byGraphId.set(spec.id, node);
        graphIdOf.set(node.id, spec.id);
      }
      for (const spec of specs) {
        for (const input of spec.inputs) {
          const source = byGraphId.get(input.from);
          const target = byGraphId.get(spec.id);
          if (source && target) await editor.addConnection(new ClassicPreset.Connection(source, "out", target, input.key));
          if (cancelled) return;
        }
      }

      // Measure what React drew -- a long rule id or input label wraps --
      // and lay out from that, so no node sits on another.
      await nextFrame();
      await nextFrame();
      if (cancelled) return;
      const sizeOf = (id: string) => {
        const node = byGraphId.get(id);
        const element = node ? area.nodeViews.get(node.id)?.element.firstElementChild : null;
        const box = element instanceof HTMLElement ? { width: element.offsetWidth, height: element.offsetHeight } : null;
        return box && box.width > 0 && box.height > 0 ? box : FALLBACK;
      };
      const boxes = layoutModel(graph, sizeOf, { columnGap: 140, rowGap: 30 });
      for (const [id, box] of boxes) {
        const node = byGraphId.get(id);
        if (node) await area.translate(node.id, { x: box.x, y: box.y });
        if (cancelled) return;
      }
      await AreaExtensions.zoomAt(area, editor.getNodes());

      area.addPipe((context) => {
        if (context.type === "nodepicked") {
          const id = graphIdOf.get(context.data.id);
          if (id) onSelectRef.current(id);
        }
        return context;
      });
    })();

    return () => {
      cancelled = true;
      area.destroy();
      container.remove();
    };
  }, [graph]);

  return (
    <div
      ref={host}
      className="h-full w-full bg-[radial-gradient(#cbd5e1_1px,transparent_1px)] [background-size:18px_18px]"
      data-testid="model-style-view-rete"
    />
  );
}
