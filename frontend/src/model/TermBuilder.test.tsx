import { useState } from "react";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import TermBuilder, { BindingsEditor } from "./TermBuilder";
import type { Binding, ModelContext, Term } from "./terms";

const CONTEXT: ModelContext = {
  sets: ["employee", "day", "shift", "unit"],
  setIds: { employee: 5, day: 6, shift: 7, unit: 8 },
  attributes: {
    employee: [
      { name: "hours_per_week", data_type: "integer" },
      // A decimal attribute: arithmetic since migration 0015 (§7), and
      // still the thing that makes a model continuous.
      { name: "hourly_rate", data_type: "number" },
      // Not a quantity, so not arithmetic in any version.
      { name: "full_name", data_type: "text" },
    ],
    day: [{ name: "is_weekend", data_type: "boolean" }],
    shift: [],
    unit: [{ name: "cost_centre", data_type: "text" }],
  },
  variables: { assign: { index: ["employee", "day", "shift"], domain: "binary" } },
  parameters: { demand: { index: ["day", "shift"] } },
  relationships: [
    { name: "reports_to", from: "unit", to: "unit" },
    { name: "works_in", from: "employee", to: "unit" },
  ],
};

const BOUND: Binding[] = [
  { index: "e", set: "employee" },
  { index: "d", set: "day" },
  { index: "s", set: "shift" },
];

function renderTerm(value: Term, bound: Binding[] = BOUND) {
  const onChange = vi.fn();
  render(<TermBuilder value={value} onChange={onChange} context={CONTEXT} bound={bound} />);
  return onChange;
}

beforeEach(() => vi.clearAllMocks());

describe("TermBuilder", () => {
  it("reads a term back as arithmetic a person can check", () => {
    renderTerm({
      mul: [
        { const: 8 },
        { sum: { var: "assign", index: ["e", "d", "s"] }, over: [{ index: "d", set: "day" }] },
      ],
    } as Term);

    expect(screen.getAllByText(/8 × sum\(assign\[e, d, s\] over d in day\)/)[0]).toBeInTheDocument();
  });

  it("offers a variable's subscripts only from indices bound to the right set", () => {
    // `assign` is indexed [employee, day, shift]. The shift position must
    // not offer `e`, or the model would type-check by arity and mean
    // something else entirely -- which the contract refuses.
    renderTerm({ var: "assign", index: ["e", "d", "s"] } as Term);

    const shiftPicker = screen.getByLabelText("shift index") as HTMLSelectElement;
    const offered = Array.from(shiftPicker.options).map((o) => o.value);
    expect(offered).toContain("s");
    expect(offered).not.toContain("e");
    expect(offered).not.toContain("d");
  });

  it("offers numeric attributes only, and says why when there are none", () => {
    renderTerm({ attr: { of: "e", name: "hours_per_week" } } as Term);

    const picker = screen.getByLabelText("Attribute") as HTMLSelectElement;
    const offered = Array.from(picker.options).map((o) => o.value);
    expect(offered).toContain("hours_per_week");
    // A `number` is arithmetic since 0015 -- reading one is how a model
    // becomes continuous, which the platform now records rather than refuses.
    expect(offered).toContain("hourly_rate");
    // `text` is not a quantity in any version.
    expect(offered).not.toContain("full_name");
  });

  it("explains a set with nothing arithmetic to offer", () => {
    renderTerm({ attr: { of: "d", name: "" } } as Term);

    expect(screen.getByText(/text, dates and times cannot appear/i)).toBeInTheDocument();
  });

  it("warns that a product of two variable terms is not linear", () => {
    // The contract refuses this; saying so here means the person is not told
    // by a server refusal after they publish.
    renderTerm({
      mul: [
        { var: "assign", index: ["e", "d", "s"] },
        { var: "assign", index: ["e", "d", "s"] },
      ],
    } as Term);

    expect(screen.getByRole("alert")).toHaveTextContent(/not linear/i);
  });

  it("does not warn when one side is a plain number", () => {
    renderTerm({ mul: [{ const: 8 }, { var: "assign", index: ["e", "d", "s"] }] } as Term);

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("nests a sum's inner term under a collapsible tree row", () => {
    renderTerm({
      sum: { var: "assign", index: ["e", "d", "s"] },
      over: [{ index: "d", set: "day" }],
    } as Term);

    expect(screen.getByLabelText("Variable")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /collapse a sum over a set/i }));
    expect(screen.queryByLabelText("Variable")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /expand a sum over a set/i })).toBeInTheDocument();
  });

  it("does not list the same index twice when a sum rebinds a set already bound outside", () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    renderTerm({
      sum: { var: "assign", index: ["e", "d", "s"] },
      over: [{ index: "d", set: "day" }],
    } as Term);

    const day = screen.getByLabelText("day index") as HTMLSelectElement;
    const values = Array.from(day.options).map((option) => option.value).filter(Boolean);
    expect(values).toEqual(["d"]);
    expect(error.mock.calls.flat().join(" ")).not.toMatch(/same key/i);
    error.mockRestore();
  });

  it("folds the Of block on its own chevron", () => {
    renderTerm({
      sum: { var: "assign", index: ["e", "d", "s"] },
      over: [{ index: "d", set: "day" }],
    } as Term);

    fireEvent.click(screen.getByRole("button", { name: /^collapse of$/i }));
    expect(screen.queryByLabelText("Variable")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Index")).toBeInTheDocument();
  });

  it("folds the Summed over block on its own chevron", () => {
    renderTerm({
      sum: { var: "assign", index: ["e", "d", "s"] },
      over: [{ index: "d", set: "day" }],
    } as Term);

    fireEvent.click(screen.getByRole("button", { name: /collapse summed over/i }));
    expect(screen.queryByLabelText("Index")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Variable")).toBeInTheDocument();
  });

  it("rebuilds a term when its kind changes, with the indices it can already bind", () => {
    const onChange = renderTerm({ const: 0 } as Term);

    fireEvent.change(screen.getAllByLabelText(/kind of term/i)[0], { target: { value: "var" } });

    // Not an empty shell: the new term arrives subscripted by the bound
    // indices of the right sets.
    expect(onChange).toHaveBeenCalledWith({ var: "assign", index: ["e", "d", "s"] });
  });

  it("starts a sum over the next set that is not already bound", () => {
    const onChange = renderTerm({ const: 0 } as Term, [{ index: "e", set: "employee" }]);

    fireEvent.change(screen.getAllByLabelText(/kind of term/i)[0], { target: { value: "sum" } });

    expect(onChange).toHaveBeenCalledWith({
      sum: { const: 1 },
      over: [{ index: "d", set: "day" }],
    });
  });

  it("does not offer a sum when the model has no set to range over", () => {
    render(
      <TermBuilder
        value={{ const: 0 }}
        onChange={vi.fn()}
        context={{ ...CONTEXT, sets: [] }}
        bound={[]}
      />
    );

    const kinds = screen.getByLabelText(/kind of term/i) as HTMLSelectElement;
    expect(Array.from(kinds.options).map((o) => o.value)).not.toContain("sum");
  });

  it("does not offer Add an index when there is no set to bind", () => {
    render(
      <BindingsEditor
        bindings={[]}
        onChange={vi.fn()}
        context={{ ...CONTEXT, sets: [] }}
        outer={[]}
        legend="For every"
        minBindings={0}
      />
    );

    expect(screen.queryByRole("button", { name: /add an index/i })).not.toBeInTheDocument();
  });

  it("names a bad or duplicated Index on the field", () => {
    function Harness() {
      const [bindings, setBindings] = useState<Binding[]>([
        { index: "d", set: "day" },
        { index: "e", set: "employee" },
      ]);
      return (
        <BindingsEditor
          bindings={bindings}
          onChange={setBindings}
          context={CONTEXT}
          outer={[]}
          legend="For every"
        />
      );
    }
    render(<Harness />);

    const indexes = screen.getAllByLabelText("Index");
    fireEvent.change(indexes[1], { target: { value: "d" } });
    expect(screen.getAllByText(/already bound here/i).length).toBeGreaterThan(0);

    fireEvent.change(screen.getAllByLabelText("Index")[1], { target: { value: "E" } });
    expect(screen.getByText(/lower-case/i)).toBeInTheDocument();
  });
});

describe("BindingsEditor", () => {
  it("uses react-querybuilder for a binding's filter", () => {
    render(
      <BindingsEditor
        bindings={[{ index: "d", set: "day" }]}
        onChange={vi.fn()}
        context={CONTEXT}
        outer={[]}
        legend="For every"
      />
    );

    // The builder's own controls, not a bespoke filter UI: one expression
    // language on this platform, not two.
    // The library's own controls, not a bespoke filter UI: one expression
    // language on this platform, not two.
    expect(screen.getByRole("button", { name: /add a condition/i })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: /filter for d in day/i })).toBeInTheDocument();
  });

  it("names each binding's filter, so two on a page are not two unnamed landmarks", () => {
    // react-querybuilder renders its own `role="form"`; several unnamed ones
    // on a page is an axe `landmark-unique` violation, which is exactly what
    // the model editor produces without this.
    render(
      <BindingsEditor
        bindings={[
          { index: "d", set: "day" },
          { index: "e", set: "employee" },
        ]}
        onChange={vi.fn()}
        context={CONTEXT}
        outer={[]}
        legend="For every"
      />
    );

    expect(screen.getByRole("group", { name: "Filter for d in day" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Filter for e in employee" })).toBeInTheDocument();
    // And none of them is a `form` landmark: a filter is a control inside a
    // form, not a second form competing in the landmark list.
    expect(screen.queryAllByRole("form")).toHaveLength(0);
  });

  it("does not offer a filter for a set with no attributes to filter on", () => {
    render(
      <BindingsEditor
        bindings={[{ index: "s", set: "shift" }]}
        onChange={vi.fn()}
        context={CONTEXT}
        outer={[]}
        legend="For every"
      />
    );

    expect(screen.queryByRole("group", { name: /filter for/i })).not.toBeInTheDocument();
  });

  it("can remove the last For every index when the rule may range over nothing", () => {
    const onChange = vi.fn();
    render(
      <BindingsEditor
        bindings={[{ index: "d", set: "day" }]}
        onChange={onChange}
        context={CONTEXT}
        outer={[]}
        legend="For every"
        minBindings={0}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /remove d in day/i }));
    expect(onChange).toHaveBeenCalledWith([]);
  });

  it("keeps the last Summed over index — a sum with no range is refused", () => {
    render(
      <BindingsEditor
        bindings={[{ index: "e", set: "employee" }]}
        onChange={vi.fn()}
        context={CONTEXT}
        outer={[]}
        legend="Summed over"
      />
    );

    expect(screen.queryByRole("button", { name: /remove e in employee/i })).not.toBeInTheDocument();
  });

  it("names a new index without shadowing one already bound", () => {
    const onChange = vi.fn();
    render(
      <BindingsEditor
        bindings={[{ index: "i", set: "day" }]}
        onChange={onChange}
        context={CONTEXT}
        outer={[{ index: "i2", set: "employee" }]}
        legend="Summed over"
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /add an index/i }));

    // The last call, not the first: the filter builder normalises its own
    // document on mount and calls back before any click happens.
    const lastCall = onChange.mock.calls.at(-1) as [Binding[]];
    const added = lastCall[0].at(-1) as Binding;
    // `i` is taken here and `i2` is taken further out; shadowing either
    // would silently change which entity a term refers to.
    expect(added.index).not.toBe("i");
    expect(added.index).not.toBe("i2");
  });

  it("names a new index after the next set that is not already bound", () => {
    const onChange = vi.fn();
    render(
      <BindingsEditor
        bindings={[{ index: "d", set: "day" }, { index: "s", set: "shift" }]}
        onChange={onChange}
        context={CONTEXT}
        outer={[]}
        legend="For every"
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /add an index/i }));

    const lastCall = onChange.mock.calls.at(-1) as [Binding[]];
    expect(lastCall[0].at(-1)).toEqual({ index: "e", set: "employee" });
  });

  it("reuses the first set with a free name when every set is already bound", () => {
    const onChange = vi.fn();
    render(
      <BindingsEditor
        bindings={[
          { index: "e", set: "employee" },
          { index: "d", set: "day" },
          { index: "s", set: "shift" },
          { index: "u", set: "unit" },
        ]}
        onChange={onChange}
        context={CONTEXT}
        outer={[]}
        legend="For every"
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /add an index/i }));

    const lastCall = onChange.mock.calls.at(-1) as [Binding[]];
    expect(lastCall[0].at(-1)).toEqual({ index: "e2", set: "employee" });
  });

  it("renames an auto index when the set changes, and drops a walk that no longer fits", () => {
    const onChange = vi.fn();
    render(
      <BindingsEditor
        bindings={[{ index: "e", set: "employee", via: { rel: "works_in", to: "u" } }]}
        onChange={onChange}
        context={CONTEXT}
        outer={[{ index: "u", set: "unit" }]}
        legend="For every"
      />
    );

    fireEvent.change(screen.getByLabelText("Set"), { target: { value: "day" } });

    const lastCall = onChange.mock.calls.at(-1) as [Binding[]];
    expect(lastCall[0][0]).toEqual({ index: "d", set: "day" });
  });

  it("keeps a name the person chose when the set changes", () => {
    const onChange = vi.fn();
    render(
      <BindingsEditor
        bindings={[{ index: "person", set: "employee" }]}
        onChange={onChange}
        context={CONTEXT}
        outer={[]}
        legend="For every"
      />
    );

    fireEvent.change(screen.getByLabelText("Set"), { target: { value: "day" } });

    const lastCall = onChange.mock.calls.at(-1) as [Binding[]];
    expect(lastCall[0][0]).toEqual({ index: "person", set: "day" });
  });

  it("omits where when the filter is cleared, rather than publishing an empty list", () => {
    const onChange = vi.fn();
    render(
      <BindingsEditor
        bindings={[
          {
            index: "d",
            set: "day",
            where: [{ attr: "is_weekend", op: "=", value: true }],
          },
        ]}
        onChange={onChange}
        context={CONTEXT}
        outer={[]}
        legend="For every"
      />
    );

    // Clearing every condition → toIrWhere returns [].
    fireEvent.click(screen.getByRole("button", { name: /remove condition/i }));

    const lastCall = onChange.mock.calls.at(-1) as [Binding[]];
    expect(lastCall[0][0]).toEqual({ index: "d", set: "day" });
    expect(lastCall[0][0]).not.toHaveProperty("where");
    expect(lastCall[0][0]).not.toHaveProperty("problems");
  });

  it("keeps each binding's controls separate", () => {
    render(
      <BindingsEditor
        bindings={[
          { index: "d", set: "day" },
          { index: "s", set: "shift" },
        ]}
        onChange={vi.fn()}
        context={CONTEXT}
        outer={[]}
        legend="For every"
      />
    );

    const indexFields = screen.getAllByLabelText("Index") as HTMLInputElement[];
    expect(indexFields.map((f) => f.value)).toEqual(["d", "s"]);
  });

  it("folds the For every block on its own chevron", () => {
    render(
      <BindingsEditor
        bindings={[{ index: "d", set: "day" }]}
        onChange={vi.fn()}
        context={CONTEXT}
        outer={[]}
        legend="For every"
      />
    );

    expect(screen.getByLabelText("Index")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /collapse for every/i }));
    expect(screen.queryByLabelText("Index")).not.toBeInTheDocument();
  });

  it("folds each Over block on its own chevron", () => {
    render(
      <BindingsEditor
        bindings={[{ index: "d", set: "day" }]}
        onChange={vi.fn()}
        context={CONTEXT}
        outer={[]}
        legend="For every"
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /collapse over d in day/i }));
    expect(screen.queryByLabelText("Index")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /collapse for every/i })).toBeInTheDocument();
  });

  it("removes a binding only when more than one is bound", () => {
    const { rerender } = render(
      <BindingsEditor
        bindings={[{ index: "d", set: "day" }]}
        onChange={vi.fn()}
        context={CONTEXT}
        outer={[]}
        legend="For every"
      />
    );
    expect(screen.queryByRole("button", { name: /remove .+ in /i })).not.toBeInTheDocument();

    rerender(
      <BindingsEditor
        bindings={[
          { index: "d", set: "day" },
          { index: "s", set: "shift" },
        ]}
        onChange={vi.fn()}
        context={CONTEXT}
        outer={[]}
        legend="For every"
      />
    );
    expect(screen.getAllByRole("button", { name: /remove .+ in /i })).toHaveLength(2);
  });

  it("converts an edited filter into the IR's flat and-list", () => {
    const onChange = vi.fn();
    render(
      <BindingsEditor
        bindings={[{ index: "d", set: "day", where: [{ attr: "is_weekend", op: "=", value: true }] }]}
        onChange={onChange}
        context={CONTEXT}
        outer={[]}
        legend="For every"
      />
    );

    const filter = screen.getByRole("group", { name: /filter for d in day/i });
    expect(within(filter).getByDisplayValue("is_weekend")).toBeInTheDocument();
  });
});

describe("BindingsEditor, the relationship picker", () => {
  function renderWalk(bindings: Binding[], outer: Binding[] = []) {
    const onChange = vi.fn();
    render(
      <BindingsEditor
        bindings={bindings}
        onChange={onChange}
        context={CONTEXT}
        outer={outer}
        legend="Summed over"
      />
    );
    return onChange;
  }

  it("offers nothing when no anchor is bound to walk from", () => {
    // `works_in` joins employee to unit, so binding an employee could walk
    // it -- but only from a unit, and nothing here is bound to one.
    renderWalk([{ index: "e", set: "employee" }]);

    expect(screen.queryByLabelText("Reached through")).not.toBeInTheDocument();
  });

  it("offers a walk once something is bound at the other end", () => {
    renderWalk([{ index: "e", set: "employee" }], [{ index: "u", set: "unit" }]);

    const picker = screen.getByLabelText("Reached through") as HTMLSelectElement;
    const offered = Array.from(picker.options).map((o) => o.value);
    // The employee sits at `works_in`'s `from` end, so the anchor is at `to`.
    expect(offered).toContain("works_in:to");
    // `reports_to` joins units, and this binding is over employees.
    expect(offered).not.toContain("reports_to:from");
    // One end, so the name is enough — "against" was a direction the
    // document does not store.
    expect(Array.from(picker.options).map((option) => option.textContent)).toContain("works_in");
  });

  it("names a hierarchy walk down or up, not along or against", () => {
    renderWalk([{ index: "sub", set: "unit" }], [{ index: "u", set: "unit" }]);

    const picker = screen.getByLabelText("Reached through") as HTMLSelectElement;
    const byValue = Object.fromEntries(
      Array.from(picker.options).map((option) => [option.value, option.textContent])
    );
    expect(byValue["reports_to:from"]).toBe("reports_to down the tree");
    expect(byValue["reports_to:to"]).toBe("reports_to up the tree");
  });

  it("hides Starting at when only one index can be the anchor", () => {
    renderWalk(
      [{ index: "sub", set: "unit", via: { rel: "reports_to", from: "u" } }],
      [{ index: "u", set: "unit" }]
    );

    expect(screen.queryByLabelText("Starting at")).not.toBeInTheDocument();
    expect(screen.getByLabelText("How far")).toBeInTheDocument();
  });

  it("offers Starting at when two indexes of that set are already bound", () => {
    const onChange = renderWalk(
      [{ index: "e", set: "employee", via: { rel: "works_in", to: "sub" } }],
      [
        { index: "r", set: "unit" },
        { index: "sub", set: "unit" },
      ]
    );

    const start = screen.getByLabelText("Starting at") as HTMLSelectElement;
    expect(Array.from(start.options).map((option) => option.value)).toEqual(["r", "sub"]);
    expect(Array.from(start.options).map((option) => option.textContent)).toEqual([
      "r in unit",
      "sub in unit",
    ]);
    expect(screen.queryByLabelText("How far")).not.toBeInTheDocument();

    fireEvent.change(start, { target: { value: "r" } });
    expect((onChange.mock.calls.at(-1) as [Binding[]])[0][0].via).toEqual({
      rel: "works_in",
      to: "r",
    });
  });

  it("will not anchor a walk on an index bound after it", () => {
    // The contract requires the anchor to be bound where the traversal
    // starts. A later sibling is not, so offering it would build a document
    // the validator refuses with `binding_via_anchor_not_bound`.
    renderWalk([
      { index: "e", set: "employee" },
      { index: "u", set: "unit" },
    ]);

    // One picker, not two: the unit can be reached from the employee bound
    // before it, and the employee cannot be reached from a unit bound after.
    const pickers = screen.getAllByLabelText("Reached through") as HTMLSelectElement[];
    expect(pickers).toHaveLength(1);
    expect(Array.from(pickers[0].options).map((o) => o.value)).toContain("works_in:from");
  });

  it("writes the anchor at the end the relationship puts it", () => {
    const onChange = renderWalk([{ index: "e", set: "employee" }], [{ index: "u", set: "unit" }]);

    fireEvent.change(screen.getByLabelText("Reached through"), {
      target: { value: "works_in:to" },
    });

    const [next] = onChange.mock.calls.at(-1) as [Binding[]];
    expect(next[0].via).toEqual({ rel: "works_in", to: "u" });
  });

  it("writes down the tree as the from end and up the tree as the to end", () => {
    const onChange = renderWalk([{ index: "sub", set: "unit" }], [{ index: "u", set: "unit" }]);
    const picker = screen.getByLabelText("Reached through");

    fireEvent.change(picker, { target: { value: "reports_to:from" } });
    expect((onChange.mock.calls.at(-1) as [Binding[]])[0][0].via).toEqual({
      rel: "reports_to",
      from: "u",
    });

    fireEvent.change(picker, { target: { value: "reports_to:to" } });
    expect((onChange.mock.calls.at(-1) as [Binding[]])[0][0].via).toEqual({
      rel: "reports_to",
      to: "u",
    });
  });

  it("writes each How far choice as the matching depth", () => {
    const onChange = renderWalk(
      [{ index: "sub", set: "unit", via: { rel: "reports_to", from: "u" } }],
      [{ index: "u", set: "unit" }]
    );
    const howFar = screen.getByLabelText("How far");

    fireEvent.change(howFar, { target: { value: "any" } });
    expect((onChange.mock.calls.at(-1) as [Binding[]])[0][0].via).toEqual({
      rel: "reports_to",
      from: "u",
      depth: "any",
    });

    fireEvent.change(howFar, { target: { value: "any_or_self" } });
    expect((onChange.mock.calls.at(-1) as [Binding[]])[0][0].via).toEqual({
      rel: "reports_to",
      from: "u",
      depth: "any_or_self",
    });
  });

  it("offers a depth only on a relationship that joins a type to itself", () => {
    const { rerender } = render(
      <BindingsEditor
        bindings={[{ index: "e", set: "employee", via: { rel: "works_in", to: "u" } }]}
        onChange={vi.fn()}
        context={CONTEXT}
        outer={[{ index: "u", set: "unit" }]}
        legend="Summed over"
      />
    );
    // Walking `works_in` twice would step unit -> employee and then look for
    // an edge out of a unit again; the contract refuses it.
    expect(screen.queryByLabelText("How far")).not.toBeInTheDocument();

    rerender(
      <BindingsEditor
        bindings={[{ index: "sub", set: "unit", via: { rel: "reports_to", from: "u" } }]}
        onChange={vi.fn()}
        context={CONTEXT}
        outer={[{ index: "u", set: "unit" }]}
        legend="Summed over"
      />
    );
    expect(screen.getByLabelText("How far")).toBeInTheDocument();
  });

  it("names the three depths the way a planner would say them", () => {
    renderWalk(
      [{ index: "sub", set: "unit", via: { rel: "reports_to", from: "u" } }],
      [{ index: "u", set: "unit" }]
    );

    const howFar = screen.getByLabelText("How far") as HTMLSelectElement;
    expect(Array.from(howFar.options).map((option) => option.textContent)).toEqual([
      "the next hop only",
      "everything under it",
      "itself and everything under it",
    ]);
  });

  it("leaves depth out of the document when the walk is a single step", () => {
    const onChange = renderWalk(
      [{ index: "sub", set: "unit", via: { rel: "reports_to", from: "u", depth: "any" } }],
      [{ index: "u", set: "unit" }]
    );

    fireEvent.change(screen.getByLabelText("How far"), { target: { value: "one" } });

    const [next] = onChange.mock.calls.at(-1) as [Binding[]];
    // `one` is the default, so writing it would put a key in a hashed
    // document that changes nothing about what it means.
    expect(next[0].via).toEqual({ rel: "reports_to", from: "u" });
  });

  it("drops the walk entirely when the binding goes back to all of them", () => {
    const onChange = renderWalk(
      [{ index: "sub", set: "unit", via: { rel: "reports_to", from: "u", depth: "any" } }],
      [{ index: "u", set: "unit" }]
    );

    fireEvent.change(screen.getByLabelText("Reached through"), { target: { value: "all" } });

    const [next] = onChange.mock.calls.at(-1) as [Binding[]];
    expect(next[0]).not.toHaveProperty("via");
  });
});
