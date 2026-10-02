import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import EmptyRanges, { groupEmptyRanges } from "./EmptyRanges";

const at = (site: string) => ({ constraint_id: "no_outage", kind: "sum", index: { s: site } });

describe("rules that ranged over nobody, grouped", () => {
  it("keeps one line per rule and kind, with its places", () => {
    const groups = groupEmptyRanges([at("S1"), at("S2"), { constraint_id: "cap", kind: "forall", index: {} }]);
    expect(groups).toEqual([
      { rule: "no_outage", kind: "sum", places: ["S1", "S2"] },
      { rule: "cap", kind: "forall", places: [] },
    ]);
  });

  it("names five places, then the rest on request, by their labels", () => {
    const items = Array.from({ length: 15 }, (_, i) => at(`S${i + 1}`));
    render(<EmptyRanges items={items} name={(key) => `Site ${key.slice(1)}`} />);
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    expect(screen.getByText(/counted nobody at 15 places/)).toBeInTheDocument();
    expect(screen.getByText("Site 1, Site 2, Site 3, Site 4, Site 5")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "and 10 more" }));
    expect(screen.getByText(/Site 15$/)).toBeInTheDocument();
  });
});
