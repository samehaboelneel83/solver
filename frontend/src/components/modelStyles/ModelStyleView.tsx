import { lazy, Suspense } from "react";
import type { ModelStyle, ModelStyleProps } from "./types";

// Each style is its own chunk, fetched the first time it is chosen: Blockly,
// Rete.js and React Flow together are several times the rest of the app,
// and most visits never leave the graph.
const VIEWS = {
  blockly: lazy(() => import("./BlocklyView")),
  rete: lazy(() => import("./ReteView")),
  flow: lazy(() => import("./FlowView")),
};

/** The optimization view drawn in one of the non-Cytoscape styles. */
export default function ModelStyleView({ style, ...props }: ModelStyleProps & { style: Exclude<ModelStyle, "graph"> }) {
  const View = VIEWS[style];
  return (
    <Suspense
      fallback={
        <p role="status" className="p-4 text-sm text-slate-500">
          Loading the {style === "blockly" ? "Blockly" : style === "rete" ? "Rete.js" : "React Flow"} view…
        </p>
      }
    >
      <View {...props} />
    </Suspense>
  );
}
