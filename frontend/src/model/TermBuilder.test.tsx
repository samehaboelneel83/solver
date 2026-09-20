import { render, screen, fireEvent, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import TermBuilder, { BindingsEditor } from "./TermBuilder";
import type { Binding, ModelContext, Term } from "./terms";

const CONTEXT: ModelContext = {
  sets: ["employee", "day", "shift"],
  setIds: { employee: 5, day: 6, shift: 7 },
  attributes: {
    employee: [
      { name: "hours_per_week", data_type: "integer" },
      // A decimal attribute: offered as a filter, never as arithmetic (§7).
      { name: "hourly_rate", data_type: "number" },
    ],
    day: [{ name: "is_weekend", data_type: "boolean" }],
    shift: [],
  },
  variables: { assign: { index: ["employee", "day", "shift"], domain: "binary" } },
  parameters: { demand: { index: ["day", "shift"] } },
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

  it("offers whole-number attributes only, and says why when there are none", () => {
    renderTerm({ attr: { of: "e", name: "hours_per_week" } } as Term);

    const picker = screen.getByLabelText("Attribute") as HTMLSelectElement;
    const offered = Array.from(picker.options).map((o) => o.value);
    expect(offered).toContain("hours_per_week");
    // `hourly_rate` is a `number`; admitting it would make the model
    // continuous without anyone deciding to.
    expect(offered).not.toContain("hourly_rate");
  });

  it("explains a set with nothing arithmetic to offer", () => {
    renderTerm({ attr: { of: "d", name: "" } } as Term);

    expect(screen.getByText(/whole-number attributes only/i)).toBeInTheDocument();
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

  it("rebuilds a term when its kind changes, with the indices it can already bind", () => {
    const onChange = renderTerm({ const: 0 } as Term);

    fireEvent.change(screen.getAllByLabelText(/kind of term/i)[0], { target: { value: "var" } });

    // Not an empty shell: the new term arrives subscripted by the bound
    // indices of the right sets.
    expect(onChange).toHaveBeenCalledWith({ var: "assign", index: ["e", "d", "s"] });
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
    expect(screen.getByRole("form")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /add a condition/i })).toBeInTheDocument();
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

    expect(screen.queryByRole("form")).not.toBeInTheDocument();
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
    expect(screen.queryByRole("button", { name: /^remove$/i })).not.toBeInTheDocument();

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
    expect(screen.getAllByRole("button", { name: /^remove$/i })).toHaveLength(2);
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

    const form = screen.getByRole("form");
    expect(within(form).getByDisplayValue("is_weekend")).toBeInTheDocument();
  });
});
