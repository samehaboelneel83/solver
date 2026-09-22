import "@testing-library/jest-dom/vitest";
import { configure } from "@testing-library/react";

// How long `findBy*` and `waitFor` wait for something to appear. The default
// is one second, and the full suite runs ~76 files on every core at once:
// under that load a lazily loaded chunk (the expression builder) or a chain
// of queries can take longer, and a different, unrelated test failed on each
// full run -- while every one passed alone. Waiting longer does not hide a
// real failure: an element that never appears still fails the test, only
// after five seconds instead of one.
configure({ asyncUtilTimeout: 5000 });

// jsdom doesn't implement matchMedia at all -- AppShell uses it (G-2 fix
// round 1) to tell the static desktop sidebar apart from the off-canvas
// drawer for accessibility purposes. Default to "not desktop" (matches:
// false) so existing small-screen-oriented drawer tests keep their current
// behavior; individual tests can override `window.matchMedia` to simulate a
// wide viewport.
if (typeof window !== "undefined" && typeof window.matchMedia !== "function") {
  window.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }) as unknown as MediaQueryList;
}
