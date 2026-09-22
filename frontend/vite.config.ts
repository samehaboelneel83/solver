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
  },
});
