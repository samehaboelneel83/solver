import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8010",
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
