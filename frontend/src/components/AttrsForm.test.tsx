import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import AttrsForm, {
  attrField,
  buildAttrs,
  draftsFromAttrs,
  formatAttrValue,
  staleAttrKeys,
  type AttrDrafts,
} from "./AttrsForm";
import type { AttrType, AttributeDef } from "../api/v1";

let nextId = 1;
function def(name: string, data_type: AttrType, extra: Partial<AttributeDef> = {}): AttributeDef {
  return {
    id: nextId++,
    entity_type_id: 5,
    name,
    data_type,
    required: false,
    unit: null,
    enum_values: data_type === "enum" ? ["day", "night"] : null,
    default_value: null,
    sort_order: 0,
    ...extra,
  };
}

// Deliberately NOT in alphabetical order (`rate` before `note`): the API
// returns attributes ordered by name, so a form that sorted them itself --
// or rendered them from Object.keys(attrs) -- would look identical under an
// alphabetical fixture.
function everyType(): AttributeDef[] {
  nextId = 1;
  return [
    def("grade", "integer"),
    def("rate", "number", { unit: "per hour" }),
    def("note", "text"),
    def("on_call", "boolean"),
    def("shift_kind", "enum"),
    def("start_date", "date"),
    def("start_time", "time"),
  ];
}

const ORDER = ["grade", "rate", "note", "on_call", "shift_kind", "start_date", "start_time"];

function renderForm(props: Partial<Parameters<typeof AttrsForm>[0]> = {}) {
  const onChange = vi.fn<(name: string, value: string) => void>();
  const attributes = props.attributes ?? everyType();
  const view = render(
    <AttrsForm
      attributes={attributes}
      drafts={props.drafts ?? {}}
      errors={props.errors ?? {}}
      staleKeys={props.staleKeys ?? []}
      onChange={props.onChange ?? onChange}
    />
  );
  return { onChange, attributes, ...view };
}

function controlOrder(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll<HTMLElement>("[data-testid^='attr-']")).map((el) =>
    (el.dataset.testid as string).replace(/^attr-/, "")
  );
}

describe("AttrsForm: one control per attribute definition", () => {
  it("renders exactly one control per definition, in definition order rather than alphabetically", () => {
    const { container } = renderForm();
    expect(controlOrder(container)).toEqual(ORDER);
  });

  it("labels each control with the attribute's name", () => {
    renderForm();
    for (const name of ORDER) {
      expect(screen.getByLabelText(name, { exact: false })).toBeInTheDocument();
    }
  });

  it("shows the unit in the label when the attribute has one, and nothing extra when it does not", () => {
    renderForm();
    expect(screen.getByLabelText("rate (per hour)")).toBeInTheDocument();
    expect(screen.getByLabelText("grade")).toBeInTheDocument();
    expect(screen.queryByLabelText("grade ()")).not.toBeInTheDocument();
  });

  it("marks required attributes and leaves optional ones unmarked", () => {
    const attributes = [def("grade", "integer", { required: true }), def("note", "text")];
    const { container } = renderForm({ attributes });
    const labelOf = (name: string) => {
      const control = container.querySelector<HTMLElement>(`[data-testid='attr-${name}']`);
      return container.querySelector(`label[for='${control?.id}']`);
    };
    const required = labelOf("grade");
    const optional = labelOf("note");
    // The asterisk is aria-hidden, so it is a visual mark only and the
    // accessible name stays the attribute's own name.
    expect(container.querySelector("[data-testid='attr-grade']")).toHaveAccessibleName("grade");
    expect(required?.textContent).toContain("*");
    expect(optional?.textContent).not.toContain("*");
  });

  it("uses the control each attr_type needs: a select for boolean and enum, native date/time inputs, and a numeric text box for integer and number", () => {
    renderForm();
    expect(screen.getByLabelText("on_call").tagName).toBe("SELECT");
    expect(screen.getByLabelText("shift_kind").tagName).toBe("SELECT");
    expect(screen.getByLabelText("start_date")).toHaveAttribute("type", "date");
    expect(screen.getByLabelText("start_time")).toHaveAttribute("type", "time");
    // Not type="number": an invalid entry there is reported as "", which is
    // indistinguishable from "empty" (Task 11's finding, brief correction 3).
    expect(screen.getByLabelText("grade")).toHaveAttribute("type", "text");
    expect(screen.getByLabelText("grade")).toHaveAttribute("inputmode", "numeric");
    expect(screen.getByLabelText("rate (per hour)")).toHaveAttribute("type", "text");
    expect(screen.getByLabelText("rate (per hour)")).toHaveAttribute("inputmode", "decimal");
  });

  it("offers the enum's own allowed values plus an explicit empty choice", () => {
    renderForm();
    const options = within(screen.getByLabelText("shift_kind") as HTMLSelectElement)
      .getAllByRole("option")
      .map((o) => (o as HTMLOptionElement).value);
    expect(options).toEqual(["", "day", "night"]);
  });

  it("offers a boolean both values and an empty choice, so an optional boolean can be left unset", () => {
    renderForm();
    const options = within(screen.getByLabelText("on_call") as HTMLSelectElement)
      .getAllByRole("option")
      .map((o) => (o as HTMLOptionElement).value);
    expect(options).toEqual(["", "true", "false"]);
  });

  it("shows a stored enum value that is no longer allowed rather than silently blanking it", () => {
    renderForm({ drafts: { shift_kind: "weekend" } });
    const select = screen.getByLabelText("shift_kind") as HTMLSelectElement;
    expect(select.value).toBe("weekend");
    expect(within(select).getByRole("option", { name: /weekend/ }).textContent).toMatch(/not allowed/i);
  });

  it("reports each change by attribute name", () => {
    const { onChange } = renderForm();
    fireEvent.change(screen.getByLabelText("grade"), { target: { value: "7" } });
    expect(onChange).toHaveBeenCalledWith("grade", "7");
    fireEvent.change(screen.getByLabelText("on_call"), { target: { value: "false" } });
    expect(onChange).toHaveBeenCalledWith("on_call", "false");
  });

  it("marks the failing control and points it at its message", () => {
    const attributes = everyType();
    renderForm({ attributes, errors: { [attrField("rate")]: "rate: must be a number, such as 2.5." } });
    const control = screen.getByLabelText("rate (per hour)");
    expect(control).toHaveAttribute("aria-invalid", "true");
    const described = (control.getAttribute("aria-describedby") ?? "").split(" ");
    const message = described.map((id) => document.getElementById(id)).find((el) => el?.textContent?.includes("must be a number"));
    expect(message).toBeTruthy();
    expect(screen.getByLabelText("grade")).not.toHaveAttribute("aria-invalid");
  });

  it("says so when the type has no attributes at all", () => {
    renderForm({ attributes: [] });
    expect(screen.getByText(/no attributes/i)).toBeInTheDocument();
  });

  it("names the default an empty control will fall back to, including a false one", () => {
    const attributes = [
      def("on_call", "boolean", { default_value: false }),
      def("grade", "integer", { default_value: 0 }),
      def("note", "text"),
    ];
    renderForm({ attributes });
    expect(screen.getByText(/leave empty to use the default \(No\)/i)).toBeInTheDocument();
    expect(screen.getByText(/leave empty to use the default \(0\)/i)).toBeInTheDocument();
    expect(screen.getByText(/leave empty for no value/i)).toBeInTheDocument();
  });

  it("warns about stored keys whose definition has been deleted, naming them", () => {
    renderForm({ staleKeys: ["retired", "gone"] });
    const warning = screen.getByTestId("stale-attrs");
    expect(warning.textContent).toContain("retired");
    expect(warning.textContent).toContain("gone");
    expect(warning.textContent).toMatch(/removed/i);
  });

  it("shows no stale-key warning when there are none", () => {
    renderForm();
    expect(screen.queryByTestId("stale-attrs")).not.toBeInTheDocument();
  });
});

describe("draftsFromAttrs: a stored entity as the controls' text", () => {
  it("keeps falsy values visible instead of blanking them", () => {
    const attributes = everyType();
    const drafts = draftsFromAttrs(attributes, {
      grade: 0,
      rate: 0,
      note: "",
      on_call: false,
      shift_kind: "day",
      start_date: "2026-09-19",
      start_time: "07:30",
    });
    expect(drafts).toStrictEqual({
      grade: "0",
      rate: "0",
      note: "",
      on_call: "false",
      shift_kind: "day",
      start_date: "2026-09-19",
      start_time: "07:30",
    });
  });

  it("gives an empty draft for an attribute the entity does not hold, and for a stored JSON null", () => {
    const attributes = [def("grade", "integer"), def("note", "text")];
    expect(draftsFromAttrs(attributes, { note: null })).toStrictEqual({ grade: "", note: "" });
  });

  it("reads only the current definitions, so a key whose definition was deleted never becomes a draft", () => {
    const attributes = [def("grade", "integer")];
    expect(draftsFromAttrs(attributes, { grade: 4, retired: "x" })).toStrictEqual({ grade: "4" });
  });

  it("does not prefill a new entity from the definition's default -- the server materialises it", () => {
    const attributes = [def("grade", "integer", { default_value: 3 })];
    expect(draftsFromAttrs(attributes, {})).toStrictEqual({ grade: "" });
  });
});

describe("staleAttrKeys", () => {
  it("names the stored keys that no current definition covers", () => {
    const attributes = [def("grade", "integer"), def("note", "text")];
    expect(staleAttrKeys(attributes, { grade: 4, retired: "x", also_gone: 1 })).toEqual(["retired", "also_gone"]);
  });

  it("is empty when every stored key is still defined", () => {
    const attributes = [def("grade", "integer")];
    expect(staleAttrKeys(attributes, { grade: 4 })).toEqual([]);
  });
});

describe("buildAttrs: the object sent to the server", () => {
  it("round-trips every attr_type with values that change shape if mistyped", () => {
    const attributes = everyType();
    const drafts: AttrDrafts = {
      grade: "0",
      rate: "0",
      note: "0",
      on_call: "false",
      shift_kind: "night",
      start_date: "2026-09-19",
      start_time: "07:30",
    };
    const result = buildAttrs(attributes, drafts);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.attrs).toStrictEqual({
      grade: 0,
      rate: 0,
      note: "0",
      on_call: false,
      shift_kind: "night",
      start_date: "2026-09-19",
      start_time: "07:30",
    });
    // toStrictEqual would accept "0" for 0 in neither direction, but spell
    // the JSON types out anyway: these are exactly the three a sloppy
    // conversion confuses.
    expect(typeof result.attrs.grade).toBe("number");
    expect(typeof result.attrs.note).toBe("string");
    expect(typeof result.attrs.on_call).toBe("boolean");
  });

  it("keeps a false boolean and a zero, rather than dropping falsy values", () => {
    const attributes = [def("on_call", "boolean"), def("grade", "integer"), def("rate", "number")];
    const result = buildAttrs(attributes, { on_call: "false", grade: "0", rate: "0.0" });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(Object.keys(result.attrs).sort()).toEqual(["grade", "on_call", "rate"]);
    expect(result.attrs.on_call).toBe(false);
    expect(result.attrs.grade).toBe(0);
    expect(result.attrs.rate).toBe(0);
  });

  it("omits an empty control entirely -- not null, not an empty string -- so the server can materialise the default", () => {
    const attributes = [def("grade", "integer", { default_value: 3 }), def("note", "text"), def("on_call", "boolean")];
    const result = buildAttrs(attributes, { grade: "", note: "", on_call: "" });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.attrs).toStrictEqual({});
    expect(Object.keys(result.attrs)).toEqual([]);
  });

  it("builds from the current definitions only, so a stored key whose definition was deleted is not sent back", () => {
    const attributes = [def("grade", "integer")];
    // The drafts still carry the deleted key, as they would if the form
    // merged what it loaded instead of rebuilding.
    const result = buildAttrs(attributes, { grade: "4", retired: "still here" });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.attrs).toStrictEqual({ grade: 4 });
    expect(result.attrs).not.toHaveProperty("retired");
  });

  it("refuses a non-numeric entry in a number field, naming the attribute", () => {
    const attributes = everyType();
    const result = buildAttrs(attributes, { rate: "banana" });
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.errors[attrField("rate")]).toBe("rate: must be a number, such as 2.5.");
  });

  it.each([
    ["banana", "not a number at all"],
    ["   ", "whitespace, which Number() reads as 0"],
    ["0x10", "a hex literal, which Number() reads as 16"],
    ["1.2.3", "two decimal points"],
    ["Infinity", "not finite"],
  ])("refuses %s in a number field (%s)", (raw) => {
    const result = buildAttrs([def("rate", "number")], { rate: raw });
    expect(result.ok).toBe(false);
  });

  it("refuses a decimal in an integer field rather than silently rounding it", () => {
    const result = buildAttrs([def("grade", "integer")], { grade: "2.5" });
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.errors[attrField("grade")]).toContain("whole number");
  });

  it("refuses a date that does not exist", () => {
    const result = buildAttrs([def("start_date", "date")], { start_date: "2026-02-30" });
    expect(result.ok).toBe(false);
  });

  it("refuses an enum value that has since been dropped from enum_values", () => {
    const result = buildAttrs([def("shift_kind", "enum")], { shift_kind: "weekend" });
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.errors[attrField("shift_kind")]).toContain("not one of the allowed values");
  });

  it("reports every bad control at once, not just the first", () => {
    const attributes = everyType();
    const result = buildAttrs(attributes, { grade: "2.5", rate: "banana" });
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(Object.keys(result.errors).sort()).toEqual([attrField("grade"), attrField("rate")].sort());
  });

  it("refuses an empty required attribute that has no default", () => {
    const result = buildAttrs([def("grade", "integer", { required: true })], { grade: "" });
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.errors[attrField("grade")]).toMatch(/required/i);
  });

  it("allows an empty required attribute that has a default, because the server materialises it", () => {
    const attributes = [def("grade", "integer", { required: true, default_value: 3 })];
    const result = buildAttrs(attributes, { grade: "" });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.attrs).toStrictEqual({});
  });

  it("treats a false default as a default, not as 'no default'", () => {
    const attributes = [def("on_call", "boolean", { required: true, default_value: false })];
    expect(buildAttrs(attributes, { on_call: "" }).ok).toBe(true);
  });

  it("treats a zero default as a default, not as 'no default'", () => {
    const attributes = [def("grade", "integer", { required: true, default_value: 0 })];
    expect(buildAttrs(attributes, { grade: "" }).ok).toBe(true);
  });

  it("sends nothing when the type has no attributes", () => {
    expect(buildAttrs([], { stray: "x" })).toStrictEqual({ ok: true, attrs: {} });
  });
});

describe("formatAttrValue: a stored value in a list cell", () => {
  it.each([
    [false, "No"],
    [true, "Yes"],
    [0, "0"],
    [2.5, "2.5"],
    ["", "(empty)"],
    ["night", "night"],
    [null, "—"],
    [undefined, "—"],
  ])("renders %p as %p", (value, expected) => {
    expect(formatAttrValue(value)).toBe(expected);
  });
});
/*
 * `hours_per_week`'s help read "A whole number, such as 8 or -2." -- an
 * example generic to the TYPE and blind to the FIELD, offering a negative
 * number of hours worked in a week.
 */
describe("AttrsForm: the help under a numeric control", () => {
  function hintFor(name: string): string {
    const control = screen.getByTestId(`attr-${name}`);
    const described = control.getAttribute("aria-describedby") ?? "";
    const hintId = described.split(" ").find((id) => id.endsWith("-hint"));
    return hintId ? (document.getElementById(hintId)?.textContent ?? "") : "";
  }

  it("says decimals are refused without inventing a number for the field", () => {
    renderForm({ attributes: [def("hours_per_week", "integer", { unit: "h/week" })] });
    const hint = hintFor("hours_per_week");
    expect(hint).toContain("whole number");
    expect(hint).toContain("no decimals");
    expect(hint).not.toContain("-2");
  });

  it("lets the field's own default be the concrete example, since that one is true of it", () => {
    renderForm({
      attributes: [def("hours_per_week", "integer", { unit: "h/week", default_value: 40 })],
    });
    expect(hintFor("hours_per_week")).toContain("Leave empty to use the default (40).");
  });

  it("keeps the decimal example on a number, where it is not a lie", () => {
    renderForm({ attributes: [def("hourly_rate", "number", { unit: "EUR/h" })] });
    expect(hintFor("hourly_rate")).toContain("2.5");
  });
});

describe("a map shape in a records cell (UX audit A-4)", () => {
  it("reads as words, not GeoJSON", () => {
    expect(formatAttrValue({ type: "Point", coordinates: [31.235712, 30.044420] })).toBe("Point (31.2357, 30.0444)");
    expect(formatAttrValue({ type: "Polygon", coordinates: [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]] })).toBe("Area, 4 corners");
    expect(formatAttrValue({ type: "MultiPolygon", coordinates: [[[[0, 0]]], [[[1, 1]]]] })).toBe("Area in 2 parts");
    expect(formatAttrValue({ a: 1 })).toBe('{"a":1}');
  });
});
