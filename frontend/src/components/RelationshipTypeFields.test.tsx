import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import RelationshipTypeFields, {
  RELATIONSHIP_TYPE_FIELDS,
  constrainDraft,
  type RelationshipTypeDraft,
} from "./RelationshipTypeFields";
import type { EntityType } from "../api/v1";

const ENTITY_TYPES = [
  { id: 5, domain_id: 7, name: "employee", role: "agent", colour: "#1f77b4", attributes: [] },
  { id: 9, domain_id: 7, name: "shift", role: "time", colour: null, attributes: [] },
  { id: 12, domain_id: 7, name: "site", role: "resource", colour: null, attributes: [] },
] as unknown as EntityType[];

/** The two ends and the cardinality start **different from** what a
 * hierarchy requires. A fixture whose pickers already agreed could not show
 * that ticking the box constrained anything. */
const FREE_DRAFT: RelationshipTypeDraft = {
  name: "works_on",
  from_type_id: 5,
  to_type_id: 9,
  cardinality: "many_to_many",
  is_hierarchy: false,
  colour: null,
};

function Harness({ initial = FREE_DRAFT }: { initial?: RelationshipTypeDraft }) {
  const [draft, setDraft] = useState(initial);
  return (
    <>
      <RelationshipTypeFields
        draft={draft}
        onChange={setDraft}
        entityTypes={ENTITY_TYPES}
        errors={{}}
        fallbackKey="new"
      />
      <output data-testid="draft">{JSON.stringify(draft)}</output>
    </>
  );
}

function draftNow(): RelationshipTypeDraft {
  return JSON.parse(screen.getByTestId("draft").textContent ?? "{}");
}

const from = () => screen.getByLabelText(/^From entity type/);
const to = () => screen.getByLabelText(/^To entity type/);
const cardinality = () => screen.getByLabelText(/^Cardinality/);
const hierarchy = () => screen.getByRole("checkbox", { name: /hierarchy/i });

describe("constrainDraft (the invariant, on its own)", () => {
  it("forces both ends together and one-to-many when the flag is on", () => {
    const constrained = constrainDraft({ ...FREE_DRAFT, is_hierarchy: true });
    expect(constrained.to_type_id).toBe(5);
    expect(constrained.cardinality).toBe("one_to_many");
  });

  it("leaves a non-hierarchy draft exactly as it is", () => {
    expect(constrainDraft(FREE_DRAFT)).toEqual(FREE_DRAFT);
    expect(constrainDraft({ ...FREE_DRAFT, cardinality: "many_to_one" }).cardinality).toBe("many_to_one");
  });

  it("does not invent a from_type_id that was never chosen", () => {
    const constrained = constrainDraft({ ...FREE_DRAFT, from_type_id: null, to_type_id: 9, is_hierarchy: true });
    expect(constrained.to_type_id).toBeNull();
  });
});

describe("RelationshipTypeFields: the hierarchy combination is unreachable", () => {
  it("ticking hierarchy moves the second end onto the first and forces one-to-many", () => {
    render(<Harness />);
    // Proof the fixture started apart, so the change below is the tick's doing.
    expect((to() as HTMLSelectElement).value).toBe("9");
    expect((cardinality() as HTMLSelectElement).value).toBe("many_to_many");

    fireEvent.click(hierarchy());

    expect((to() as HTMLSelectElement).value).toBe("5");
    expect((cardinality() as HTMLSelectElement).value).toBe("one_to_many");
    expect(draftNow()).toMatchObject({ from_type_id: 5, to_type_id: 5, cardinality: "one_to_many", is_hierarchy: true });
  });

  it("locks the second end and the cardinality while hierarchy is ticked", () => {
    render(<Harness />);
    expect(to()).toBeEnabled();
    expect(cardinality()).toBeEnabled();

    fireEvent.click(hierarchy());

    expect(to()).toBeDisabled();
    expect(cardinality()).toBeDisabled();
  });

  it("keeps the two ends together when the first end is changed", () => {
    render(<Harness />);
    fireEvent.click(hierarchy());
    fireEvent.change(from(), { target: { value: "12" } });

    expect((to() as HTMLSelectElement).value).toBe("12");
    expect(draftNow()).toMatchObject({ from_type_id: 12, to_type_id: 12, cardinality: "one_to_many" });
  });

  it("says why, rather than leaving two dead controls unexplained", () => {
    render(<Harness />);
    expect(screen.queryByTestId("hierarchy-constraint")).not.toBeInTheDocument();

    fireEvent.click(hierarchy());

    const note = screen.getByTestId("hierarchy-constraint");
    expect(note).toHaveTextContent(/same entity type/i);
    expect(note).toHaveTextContent(/one parent/i);
  });

  it("restores the free choice when hierarchy is unticked", () => {
    render(<Harness />);
    fireEvent.click(hierarchy());
    expect(draftNow()).toMatchObject({ to_type_id: 5, cardinality: "one_to_many" });

    fireEvent.click(hierarchy());

    expect(to()).toBeEnabled();
    expect(cardinality()).toBeEnabled();
    expect((to() as HTMLSelectElement).value).toBe("9");
    expect((cardinality() as HTMLSelectElement).value).toBe("many_to_many");
    expect(draftNow()).toMatchObject({ to_type_id: 9, cardinality: "many_to_many", is_hierarchy: false });
  });

  it("restores what the user last chose freely, not a hard-coded default", () => {
    render(<Harness initial={{ ...FREE_DRAFT, to_type_id: 12, cardinality: "many_to_one" }} />);
    fireEvent.click(hierarchy());
    fireEvent.click(hierarchy());

    expect(draftNow()).toMatchObject({ to_type_id: 12, cardinality: "many_to_one" });
  });
});

describe("RelationshipTypeFields: the ordinary controls", () => {
  it("offers only the entity types it was given, on both ends", () => {
    render(<Harness />);
    // The first option is the "choose one" placeholder, whose VALUE is
    // empty; filtering on its text would have been a guess at its wording.
    const names = (select: HTMLElement) =>
      Array.from((select as HTMLSelectElement).options)
        .filter((option) => option.value !== "")
        .map((option) => option.text);
    expect(names(from())).toEqual(["employee", "shift", "site"]);
    expect(names(to())).toEqual(["employee", "shift", "site"]);
  });

  it("carries a freely chosen cardinality into the draft", () => {
    render(<Harness />);
    fireEvent.change(cardinality(), { target: { value: "many_to_one" } });
    expect(draftNow().cardinality).toBe("many_to_one");
  });

  it("names its fields in the order the error summary lists them", () => {
    expect(RELATIONSHIP_TYPE_FIELDS).toEqual([
      "name",
      "from_type_id",
      "to_type_id",
      "cardinality",
      "is_hierarchy",
      "colour",
    ]);
  });
});
