import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { DOMAIN_STORAGE_KEY, resolveDomainId, useDomain } from "./useDomain";

function Probe({ testId = "probe" }: { testId?: string }) {
  const { domainId, setDomainId } = useDomain();
  return (
    <div>
      <span data-testid={testId}>{domainId === null ? "none" : String(domainId)}</span>
      <button type="button" onClick={() => setDomainId(42)}>
        set-{testId}
      </button>
      <button type="button" onClick={() => setDomainId(null)}>
        clear-{testId}
      </button>
    </div>
  );
}

describe("useDomain", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("reads the stored domain id as a number", () => {
    localStorage.setItem(DOMAIN_STORAGE_KEY, "17");
    render(<Probe />);
    expect(screen.getByTestId("probe")).toHaveTextContent("17");
  });

  it.each(["abc", "", "-3", "0", "1.5", "1e3", " 4"])("treats a stored %j as no domain", (raw) => {
    localStorage.setItem(DOMAIN_STORAGE_KEY, raw);
    render(<Probe />);
    expect(screen.getByTestId("probe")).toHaveTextContent("none");
  });

  it("persists setDomainId to localStorage and shares it with every other consumer", () => {
    render(
      <>
        <Probe testId="a" />
        <Probe testId="b" />
      </>
    );
    act(() => screen.getByText("set-a").click());
    expect(localStorage.getItem(DOMAIN_STORAGE_KEY)).toBe("42");
    expect(screen.getByTestId("a")).toHaveTextContent("42");
    expect(screen.getByTestId("b")).toHaveTextContent("42");

    act(() => screen.getByText("clear-b").click());
    expect(localStorage.getItem(DOMAIN_STORAGE_KEY)).toBeNull();
    expect(screen.getByTestId("a")).toHaveTextContent("none");
  });

  it("follows a change made in another tab (the storage event)", () => {
    render(<Probe />);
    act(() => {
      localStorage.setItem(DOMAIN_STORAGE_KEY, "9");
      window.dispatchEvent(new StorageEvent("storage", { key: DOMAIN_STORAGE_KEY, newValue: "9" }));
    });
    expect(screen.getByTestId("probe")).toHaveTextContent("9");
  });
});

describe("resolveDomainId", () => {
  // Deliberately not in id order: "first" means first as listed (the
  // selector's own order), which a lowest-id default would get wrong.
  const domains = [
    { id: 7, name: "alpha" },
    { id: 3, name: "beta" },
    { id: 12, name: "gamma" },
  ];

  it("keeps a stored id that is still in the list, even when it isn't first", () => {
    expect(resolveDomainId(3, domains)).toBe(3);
  });

  it("falls back to the first listed domain when the stored one is gone", () => {
    expect(resolveDomainId(99, domains)).toBe(7);
  });

  it("falls back to the first listed domain when nothing is stored", () => {
    expect(resolveDomainId(null, domains)).toBe(7);
  });

  it("returns null when there are no domains at all", () => {
    expect(resolveDomainId(3, [])).toBeNull();
  });
});
