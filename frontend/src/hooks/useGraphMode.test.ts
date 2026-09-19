import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GRAPH_MODE_STORAGE_KEY, parseGraphMode, useGraphMode } from "./useGraphMode";

/**
 * Persistence, tested as persistence.
 *
 * The trap this file exists to avoid: a "reload" that only re-renders, or
 * re-imports nothing, proves only that the module's own in-memory copy of
 * the value is still there -- which it would be even if `localStorage`
 * were never written at all. Every test here that claims persistence
 * either clears the module with `vi.resetModules()` and imports a fresh
 * one, or reads `localStorage` directly.
 */

beforeEach(() => {
  localStorage.clear();
  vi.resetModules();
});

afterEach(() => {
  localStorage.clear();
});

describe("parseGraphMode", () => {
  it("accepts the two known modes and defaults everything else to objects", () => {
    expect(parseGraphMode("types")).toBe("types");
    expect(parseGraphMode("objects")).toBe("objects");
    // A value written by a future (or a past) version of this code.
    expect(parseGraphMode("schema")).toBe("objects");
    expect(parseGraphMode("")).toBe("objects");
    expect(parseGraphMode(null)).toBe("objects");
  });
});

describe("useGraphMode", () => {
  it("starts in the objects view", () => {
    const { result } = renderHook(() => useGraphMode());
    expect(result.current.mode).toBe("objects");
  });

  it("actually writes the choice to localStorage", () => {
    const { result } = renderHook(() => useGraphMode());
    act(() => result.current.setMode("types"));
    expect(result.current.mode).toBe("types");
    // The assertion that distinguishes "stored" from "remembered": read
    // the storage key, not the hook.
    expect(localStorage.getItem(GRAPH_MODE_STORAGE_KEY)).toBe("types");
  });

  it("survives a reload -- a FRESH module reading a storage it did not write", async () => {
    // Write through one instance of the module...
    const first = await import("./useGraphMode");
    const one = renderHook(() => first.useGraphMode());
    act(() => one.result.current.setMode("types"));
    one.unmount();

    // ... then throw the module away, exactly as a page reload does, and
    // load it again. Its module-level `memoryValue` is back to the
    // default, so anything it reports now came from localStorage.
    vi.resetModules();
    const reloaded = await import("./useGraphMode");
    expect(reloaded).not.toBe(first);
    const two = renderHook(() => reloaded.useGraphMode());
    expect(two.result.current.mode).toBe("types");
  });

  it("does not survive a reload that cleared storage", async () => {
    const first = await import("./useGraphMode");
    const one = renderHook(() => first.useGraphMode());
    act(() => one.result.current.setMode("types"));
    one.unmount();

    localStorage.clear();
    vi.resetModules();
    const reloaded = await import("./useGraphMode");
    const two = renderHook(() => reloaded.useGraphMode());
    // The control for the test above: if it still said "types" here, the
    // previous test would have been proving the in-memory copy.
    expect(two.result.current.mode).toBe("objects");
  });

  it("shares the choice between every component that reads it", () => {
    const a = renderHook(() => useGraphMode());
    const b = renderHook(() => useGraphMode());
    act(() => a.result.current.setMode("types"));
    expect(b.result.current.mode).toBe("types");
  });

  it("keeps working when localStorage throws, for the page's lifetime", () => {
    const setItem = vi
      .spyOn(Storage.prototype, "setItem")
      .mockImplementation(() => {
        throw new Error("blocked");
      });
    try {
      const { result } = renderHook(() => useGraphMode());
      act(() => result.current.setMode("types"));
      expect(result.current.mode).toBe("types");
    } finally {
      setItem.mockRestore();
    }
  });
});
