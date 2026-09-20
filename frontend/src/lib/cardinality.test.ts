import { describe, expect, it } from "vitest";
import {
  CARDINALITIES,
  CARDINALITY_LABEL,
  CARDINALITY_NAME,
  HIERARCHY_CARDINALITY,
  cardinalityOptionLabel,
} from "./cardinality";

/**
 * The four labels are `backend/app/api/relationships.py`'s `Cardinality`
 * Literal, which is itself the `relationship_type.cardinality` CHECK in
 * migration 0006. Nothing keeps the two in step automatically (the same
 * family as Task 14b's three-places colour note), so these tests at least
 * pin the client's own copy to be complete and in a stable order.
 */
describe("cardinality vocabulary", () => {
  it("offers every cardinality the API accepts, exactly once", () => {
    // `CARDINALITY_NAME` is a `Record<Cardinality, string>`, so the compiler
    // refuses a missing key; this catches an option list that drops one.
    expect(CARDINALITIES.map((option) => option.value).sort()).toEqual(
      (Object.keys(CARDINALITY_NAME) as string[]).sort()
    );
    expect(new Set(CARDINALITIES.map((option) => option.value)).size).toBe(4);
  });

  it("lists them in the order the API declares them", () => {
    expect(CARDINALITIES.map((option) => option.value)).toEqual([
      "one_to_one",
      "one_to_many",
      "many_to_one",
      "many_to_many",
    ]);
  });

  it("labels each one distinctly, in words and in the graph's short form", () => {
    expect(new Set(CARDINALITIES.map((option) => option.label)).size).toBe(4);
    expect(new Set(Object.values(CARDINALITY_LABEL)).size).toBe(4);
  });

  it("puts both the words and the short form in an option label", () => {
    // A picker that showed only "1 → n" would be a puzzle; one that showed
    // only "One to many" would not match the graph's edge labels.
    expect(cardinalityOptionLabel("one_to_many")).toContain("One to many");
    expect(cardinalityOptionLabel("one_to_many")).toContain(CARDINALITY_LABEL.one_to_many);
    expect(CARDINALITIES.find((o) => o.value === "many_to_one")?.label).toBe(
      cardinalityOptionLabel("many_to_one")
    );
  });

  it("names the one cardinality a hierarchy is allowed to have", () => {
    // The DDL's CHECK, not a preference: `CHECK (NOT is_hierarchy OR
    // (from_type_id = to_type_id AND cardinality = 'one_to_many'))`.
    expect(HIERARCHY_CARDINALITY).toBe("one_to_many");
  });
});
