import { describe, expect, it } from "vitest";
import { DESKTOP_QUERY } from "./AppShell";
// Vite's `?raw` suffix (declared by vite/client.d.ts, referenced from
// vite-env.d.ts) loads the file's source as a plain string -- avoids a
// node:fs/node:path dependency this project doesn't otherwise have (no
// @types/node installed, and adding one is out of scope here).
import tailwindConfigSource from "../../tailwind.config.js?raw";

// AppShell.tsx's DESKTOP_QUERY and tailwind.config.js's `lg` breakpoint are
// two independent string literals with nothing but comments linking them
// (see both files). Nothing else in the suite catches drift between them:
// every test that exercises `isDesktop` stubs `window.matchMedia` to return
// a fixed `matches` value while ignoring the query string it was called
// with, so changing DESKTOP_QUERY to something that no longer matches the
// CSS breakpoint would keep every one of those tests green. `drawerInert`,
// the Tab trap, and the drawer's initial-focus effect all gate on
// `isDesktop`, so drift here would silently reintroduce the bug where most
// of the drawer's tab stops sit off-screen below the real breakpoint.
//
// This test reads tailwind.config.js's own source (rather than hardcoding
// a second copy of "64em" here, which would just be a third literal that
// could itself drift) and asserts DESKTOP_QUERY still names the same value.
describe("AppShell desktop breakpoint stays in sync with tailwind.config.js", () => {
  it("DESKTOP_QUERY's min-width matches the `lg` breakpoint Tailwind defines", () => {
    // The value must start with a digit (a CSS length like "64em") so this
    // can't accidentally match the word "lg:" inside one of the file's own
    // prose comments (e.g. "`md:`/`lg:` switches...") and capture unrelated
    // comment text between two backticks instead of the real screens entry.
    const match = tailwindConfigSource.match(/\blg:\s*["'`](\d[^"'`]*)["'`]/);
    expect(match, "expected to find an `lg: \"...\"` entry in tailwind.config.js").not.toBeNull();
    const lgValue = match![1];

    expect(DESKTOP_QUERY).toBe(`(min-width: ${lgValue})`);
  });
});
