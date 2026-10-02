import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/** Large libraries in chunks of their own: cached across deploys of the app's own code, and fetched
 * only by the pages that use them (the model editor's blocks, the graph, the flow and rule views). */
const LIBRARY_CHUNKS: [RegExp, string][] = [
  [/node_modules\/blockly\//, "blockly"],
  [/node_modules\/(cytoscape|cytoscape-[\w-]+|elkjs)\//, "graph"],
  [/node_modules\/(rete|rete-[\w-]+|styled-components)\//, "rete"],
  [/node_modules\/@xyflow\//, "flow"],
  [/node_modules\/framer-motion\//, "motion"],
  [/node_modules\/react-querybuilder\//, "querybuilder"],
  [/node_modules\/lucide-react\//, "icons"],
  [/node_modules\/(react|react-dom|scheduler|react-router|react-router-dom|@remix-run|@tanstack)\//, "react"],
];

export default defineConfig({
  plugins: [react()],
  build: {
    // The two chunks over 500 kB are libraries fetched only by their pages (the graph's layout engine,
    // Blockly), never by the first screen; the warning is kept for anything larger than those.
    chunkSizeWarningLimit: 2000,
    rollupOptions: {
      output: {
        manualChunks(id) {
          for (const [pattern, name] of LIBRARY_CHUNKS) if (pattern.test(id)) return name;
          return undefined;
        },
      },
    },
  },
  preview: {
    proxy: { "/api/": "http://localhost:8010" },
  },
  server: {
    proxy: {
      // "/api/", not "/api": a page such as /api-keys is the app's, not the server's (operator trial F15).
      "/api/": "http://localhost:8010",
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    globals: true,
    // Above the five-second wait in src/test/setup.ts, so a slow wait fails
    // as the assertion it is rather than as an unexplained test timeout.
    testTimeout: 15000,
    // Half the cores, not all of them. With every core running a jsdom
    // file, one render could take longer than any wait: on 2026-09-23 five
    // different tests failed that way, each only under the full suite and
    // each green alone. Half the workers costs seconds; the flakes cost runs.
    maxWorkers: "50%",
    minWorkers: 1,
  },
});
