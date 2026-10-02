import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NewRelationshipForm } from "./RelationshipEditor";
import { ToastProvider } from "./ToastProvider";
import type { Entity, Id, RelationshipType } from "../api/v1";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { apiFetch } from "../api/client";
import { editorQueryClient } from "../test/me";

const mockFetch = apiFetch as unknown as ReturnType<typeof vi.fn>;

/**
 * The hierarchy case, on its own.
 *
 * A hierarchy's two ends are the same entity type by the table CHECK, so
 * a unit's own page is where the form has to offer BOTH readings -- "this
 * unit is the parent" and "this unit is the child". That is also the only
 * shape in which the subject could be offered as its own other end, and
 * the only one where switching between two options leaves the previous
 * choice still a legal value; neither is reachable from the cross-type
 * fixtures the two page tests use.
 */
const REPORTS_TO: RelationshipType = {
  id: 6,
  domain_id: 7,
  name: "reports_to",
  from_type_id: 2,
  to_type_id: 2,
  cardinality: "one_to_many",
  is_hierarchy: true,
  colour: null,
  updated_at: "t",
};

function unit(id: number, key: string, label: string | null): Entity {
  return { id, entity_type_id: 2, key, label, sort_order: 0, active: true, attrs: {}, updated_at: "t" };
}

const HQ = unit(21, "hq", "Head Office");
const NORTH = unit(22, "north", "North Region");
const DEPOT = unit(23, "depot", "North Depot");

function renderForm(subjectEntity: Entity = NORTH) {
  const queryClient = editorQueryClient();
  const entitiesByType = new Map<Id, Entity[]>([[2, [HQ, NORTH, DEPOT]]]);
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <MemoryRouter>
          <NewRelationshipForm
            types={[REPORTS_TO]}
            entitiesByType={entitiesByType}
            entityTypeNames={new Map([[2, "unit"]])}
            subject={{ id: subjectEntity.id, entityTypeId: 2, label: subjectEntity.label ?? subjectEntity.key }}
            heading="Add a relationship"
          />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}

function writes() {
  return mockFetch.mock.calls
    .filter((call) => (call[1] as RequestInit | undefined)?.method === "POST")
    .map((call) => JSON.parse((call[1] as RequestInit).body as string));
}

const options = (testId: string) =>
  within(screen.getByTestId(testId))
    .getAllByRole("option")
    .map((option) => option.textContent);

describe("NewRelationshipForm, anchored to an entity of a hierarchy's own type", () => {
  beforeEach(() => {
    mockFetch.mockReset();
    mockFetch.mockResolvedValue({ id: 1, relationship_type_id: 6, from_entity_id: 22, to_entity_id: 23, attrs: {} });
  });

  it("offers both readings, so a unit can be given a parent AND a child", () => {
    renderForm();
    expect(options("relationship-type-select")).toEqual([
      "North Region reports_to a unit",
      "a unit reports_to North Region",
    ]);
  });

  it("never offers the entity itself as its own other end", () => {
    // `from = to` is refused outright for a hierarchy, and for anything
    // else it is never what was meant -- so it is not offered rather than
    // offered and then refused.
    renderForm();
    expect(options("relationship-other-select")).not.toEqual(expect.arrayContaining(["North Region"]));
    expect(options("relationship-other-select")).toEqual(
      expect.arrayContaining(["Head Office", "North Depot"])
    );
  });

  it("clears the chosen other end when the reading is switched", async () => {
    // Both readings offer the SAME entities here, so a form that did not
    // clear would silently carry a choice made for the opposite direction
    // into a row that means the other thing.
    renderForm();
    fireEvent.change(screen.getByTestId("relationship-other-select"), { target: { value: "23" } });
    expect(screen.getByTestId("relationship-other-select")).toHaveValue("23");

    fireEvent.change(screen.getByTestId("relationship-type-select"), { target: { value: "6:to" } });

    await waitFor(() => expect(screen.getByTestId("relationship-other-select")).toHaveValue(""));
  });

  it("sends the subject as the From end when it is the parent", async () => {
    renderForm();
    fireEvent.change(screen.getByTestId("relationship-other-select"), { target: { value: "23" } });
    fireEvent.click(screen.getByRole("button", { name: "Add relationship" }));
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0]).toEqual({ relationship_type_id: 6, from_entity_id: 22, to_entity_id: 23 });
  });

  it("sends the subject as the To end when it is the child, with the SAME controls", async () => {
    renderForm();
    fireEvent.change(screen.getByTestId("relationship-type-select"), { target: { value: "6:to" } });
    fireEvent.change(screen.getByTestId("relationship-other-select"), { target: { value: "21" } });
    fireEvent.click(screen.getByRole("button", { name: "Add relationship" }));
    await waitFor(() => expect(writes()).toHaveLength(1));
    // Reversed, from the same two picks: this is the half of a hierarchy
    // that dragging on a canvas makes hardest to get right.
    expect(writes()[0]).toEqual({ relationship_type_id: 6, from_entity_id: 21, to_entity_id: 22 });
  });

  it("names the far end by the type it must be, on both readings", () => {
    renderForm();
    expect(screen.getByLabelText(/^To entity/)).toBe(screen.getByTestId("relationship-other-select"));
    fireEvent.change(screen.getByTestId("relationship-type-select"), { target: { value: "6:to" } });
    expect(screen.getByLabelText(/^From entity/)).toBe(screen.getByTestId("relationship-other-select"));
  });

  it("falls back to an entity's key when it has no label, rather than an empty option", () => {
    render(
      <QueryClientProvider client={editorQueryClient()}>
        <ToastProvider>
          <MemoryRouter>
            <NewRelationshipForm
              types={[REPORTS_TO]}
              entitiesByType={new Map<Id, Entity[]>([[2, [unit(24, "unlabelled", null)]]])}
              entityTypeNames={new Map([[2, "unit"]])}
              subject={{ id: 22, entityTypeId: 2, label: "North Region" }}
              heading="Add a relationship"
            />
          </MemoryRouter>
        </ToastProvider>
      </QueryClientProvider>
    );
    expect(options("relationship-other-select")).toContain("unlabelled");
  });
});

describe("NewRelationshipForm, for a kind with more records than one page", () => {
  // 500 units listed (the page limit), so the form searches instead of listing.
  const MANY = Array.from({ length: 500 }, (_, i) => unit(1000 + i, `u${i}`, `Unit ${i}`));
  const FAR = unit(9999, "far", "Far Unit");

  beforeEach(() => {
    mockFetch.mockReset();
    mockFetch.mockImplementation((path: string, init?: RequestInit) => {
      if (init?.method === "POST") return Promise.resolve({ id: 1, relationship_type_id: 6, from_entity_id: 22, to_entity_id: 9999, attrs: {} });
      if (path.includes("/trees")) return Promise.resolve({ entity_id: 22, trees: [] });
      if (path.includes("q=far")) return Promise.resolve({ items: [FAR], total: 1 });
      return Promise.resolve({ items: MANY.slice(0, 20), total: 501 });
    });
  });

  it("searches the server for the other end and links the record found, past the first page", async () => {
    render(
      <QueryClientProvider client={editorQueryClient()}>
        <ToastProvider>
          <MemoryRouter>
            <NewRelationshipForm types={[REPORTS_TO]} entitiesByType={new Map<Id, Entity[]>([[2, MANY]])}
              entityTypeNames={new Map([[2, "unit"]])} subject={{ id: 22, entityTypeId: 2, label: "North Region" }}
              heading="Add a relationship" />
          </MemoryRouter>
        </ToastProvider>
      </QueryClientProvider>
    );
    const other = screen.getByTestId("relationship-other-select");
    expect(other).toHaveAttribute("role", "combobox");
    fireEvent.focus(other);
    fireEvent.change(other, { target: { value: "far" } });
    fireEvent.mouseDown(await screen.findByRole("option", { name: "far — Far Unit" }));
    fireEvent.click(screen.getByRole("button", { name: "Add relationship" }));
    await waitFor(() => expect(writes()).toEqual([{ relationship_type_id: 6, from_entity_id: 22, to_entity_id: 9999 }]));
  });
});
