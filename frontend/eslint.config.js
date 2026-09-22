import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

// The stock Vite React-TS set, minus the rules that would start this
// tree on a wall. `@typescript-eslint/no-explicit-any` is a typing
// debate (200+ sites). react-hooks v7's compiler rules (`set-state-in-effect`,
// `refs`) and `react-refresh/only-export-components` would rewrite
// working pages for HMR / effect style. Those stay off until someone
// wants that debate. Unused bindings that start with `_` are already
// the house convention.
export default tseslint.config(
  { ignores: ["dist", "node_modules", "*.config.js", "*.config.ts", "_browser_check_*.mjs"] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2020,
      globals: { ...globals.browser, ...globals.vitest },
    },
    plugins: {
      "react-hooks": reactHooks,
    },
    linterOptions: {
      reportUnusedDisableDirectives: "error",
    },
    rules: {
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "error",
      "@typescript-eslint/no-explicit-any": "off",
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_", caughtErrorsIgnorePattern: "^_" },
      ],
    },
  },
);
