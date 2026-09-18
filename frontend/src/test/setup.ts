import "@testing-library/jest-dom/vitest";

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
