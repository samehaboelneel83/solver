import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ExpressionBuilder, { defaultValueFor } from "./ExpressionBuilder";
import { EXPRESSION_VERSION, type ExpressionDocument } from "./document";
import { buildFieldCatalogue, encodeFieldId } from "./fields";
import { ENTITY_TYPES, RELATIONSHIP_TYPES } from "./testFixtures";

/**
 * react-querybuilder is a third-party UI, and axe has been 0 on every
 * state of this app so far. Its defaults give each control a `title` and
 * nothing else, so every rule's Field select is called "Field" -- five
 * rules, five identical names, and a remove button that is a bare "⨯"
 * glyph a dozen pixels across. The wrapper therefore supplies its own
 * controls; these tests are what keeps them supplied.
 */

const catalogue = buildFieldCatalogue({
  entityTypes: ENTITY_TYPES,
  relationshipTypes: RELATIONSHIP_TYPES,
});

const CAPACITY = encodeFieldId({ kind: "attribute", entityTypeId: "1", attribute: "capacity" }); // integer
const CODE = encodeFieldId({ kind: "attribute", entityTypeId: "1", attribute: "code" }); // text
const ACTIVE = encodeFieldId({ kind: "attribute", entityTypeId: "1", attribute: "active" }); // boolean
const BAND = encodeFieldId({ kind: "attribute", entityTypeId: "1", attribute: "band" }); // enum
const OPENED = encodeFieldId({ kind: "attribute", entityTypeId: "1", attribute: "opened" }); // date
const GRADE = encodeFieldId({ kind: "attribute", entityTypeId: "1", attribute: "grade" }); // number, optional

function docWith(...rules: unknown[]): ExpressionDocument {
  return { version: EXPRESSION_VERSION, query: { combinator: "and", rules } } as ExpressionDocument;
}

function renderBuilder(value: ExpressionDocument | null, onChange = vi.fn()) {
  render(<ExpressionBuilder catalogue={catalogue} value={value} onChange={onChange} />);
  return onChange;
}

/** The document the last onChange call carried. */
function lastDoc(onChange: ReturnType<typeof vi.fn>): ExpressionDocument {
  return onChange.mock.calls[onChange.mock.calls.length - 1][0];
}

describe("ExpressionBuilder — structure", () => {
  it("renders one row per rule, with a field, an operator and a value control", () => {
    renderBuilder(docWith({ field: CAPACITY, operator: ">", value: 3 }));
    expect(screen.getAllByTestId("expression-field")).toHaveLength(1);
    expect(screen.getAllByTestId("expression-operator")).toHaveLength(1);
    expect(screen.getAllByTestId("expression-value")).toHaveLength(1);
  });

  it("groups the field list by entity type so the same attribute name on two types is tellable apart", () => {
    renderBuilder(docWith({ field: CAPACITY, operator: ">", value: 3 }));
    const select = screen.getAllByTestId("expression-field")[0];
    const groups = Array.from(select.querySelectorAll("optgroup")).map((g) => g.getAttribute("label"));
    expect(groups).toContain("unit");
    expect(groups).toContain("shift");
  });

  it("offers only the operators of the field's data type", () => {
    renderBuilder(docWith({ field: CODE, operator: "contains", value: "a" }));
    const operators = Array.from(
      screen.getAllByTestId("expression-operator")[0].querySelectorAll("option")
    ).map((o) => o.getAttribute("value"));
    expect(operators).toContain("contains");
    expect(operators).not.toContain(">");
  });

  it("starts from an empty and-group when it is given no document", () => {
    renderBuilder(null);
    expect(screen.queryAllByTestId("expression-field")).toHaveLength(0);
    expect(screen.getByTestId("expression-add-rule")).toBeInTheDocument();
  });
});

describe("ExpressionBuilder — values keep their JSON type", () => {
  it("emits a number for an integer field, not the string the input holds", () => {
    const onChange = renderBuilder(docWith({ field: CAPACITY, operator: ">", value: 3 }));
    fireEvent.change(screen.getAllByTestId("expression-value")[0], { target: { value: "12" } });
    const rule = lastDoc(onChange).query.rules[0] as { value: unknown };
    expect(rule.value).toBe(12);
    expect(typeof rule.value).toBe("number");
  });

  it("emits what was typed when it is not a number, so the validator can say why", () => {
    // Swallowing it here would leave the user with a box that shows "1x"
    // and a filter that silently used 1. The builder is controlled, so the
    // document it emits is then rendered back into it -- which is where
    // the message appears.
    const onChange = renderBuilder(docWith({ field: CAPACITY, operator: ">", value: 3 }));
    fireEvent.change(screen.getAllByTestId("expression-value")[0], { target: { value: "1x" } });
    const emitted = lastDoc(onChange);
    expect((emitted.query.rules[0] as { value: unknown }).value).toBe("1x");

    cleanup();
    renderBuilder(emitted);
    expect(screen.getByTestId("expression-value")).toHaveValue("1x");
    expect(screen.getByTestId("expression-problems")).toHaveTextContent(/whole number/i);
  });

  it("emits a boolean for a boolean field", () => {
    const onChange = renderBuilder(docWith({ field: ACTIVE, operator: "=", value: true }));
    const select = screen.getAllByTestId("expression-value")[0];
    expect(select.tagName).toBe("SELECT");
    fireEvent.change(select, { target: { value: "false" } });
    const value = (lastDoc(onChange).query.rules[0] as { value: unknown }).value;
    expect(value).toBe(false);
    expect(typeof value).toBe("boolean");
  });

  it("offers an enum's own values and emits one of them", () => {
    const onChange = renderBuilder(docWith({ field: BAND, operator: "=", value: "low" }));
    const select = screen.getAllByTestId("expression-value")[0];
    expect(Array.from(select.querySelectorAll("option")).map((o) => o.textContent)).toEqual(["low", "high"]);
    fireEvent.change(select, { target: { value: "high" } });
    expect((lastDoc(onChange).query.rules[0] as { value: unknown }).value).toBe("high");
  });

  it("offers a checkbox per enum value for `is one of`, and emits an array", () => {
    const onChange = renderBuilder(docWith({ field: BAND, operator: "in", value: ["low"] }));
    const group = screen.getAllByTestId("expression-value")[0];
    const high = within(group).getByLabelText("high") as HTMLInputElement;
    const low = within(group).getByLabelText("low") as HTMLInputElement;
    expect(low.checked).toBe(true);
    expect(high.checked).toBe(false);
    fireEvent.click(high);
    expect((lastDoc(onChange).query.rules[0] as { value: unknown }).value).toEqual(["low", "high"]);
  });

  it("uses a date input for a date field and emits the ISO string", () => {
    const onChange = renderBuilder(docWith({ field: OPENED, operator: ">=", value: "2026-01-01" }));
    const input = screen.getAllByTestId("expression-value")[0] as HTMLInputElement;
    expect(input.getAttribute("type")).toBe("date");
    fireEvent.change(input, { target: { value: "2026-03-04" } });
    expect((lastDoc(onChange).query.rules[0] as { value: unknown }).value).toBe("2026-03-04");
  });

  it("renders no value control at all for `is empty`", () => {
    renderBuilder(docWith({ field: GRADE, operator: "null", value: null }));
    expect(screen.queryAllByTestId("expression-value")).toHaveLength(0);
  });
});

describe("defaultValueFor", () => {
  const field = (id: string) => catalogue.get(id)!;

  it("starts a new rule at a value of the field's own type", () => {
    expect(defaultValueFor(field(CAPACITY), "=")).toBe(0);
    expect(defaultValueFor(field(CODE), "=")).toBe("");
    expect(defaultValueFor(field(ACTIVE), "=")).toBe(true);
    expect(defaultValueFor(field(BAND), "=")).toBe("low");
    expect(defaultValueFor(field(OPENED), "=")).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it("gives a list operator a LIST, not the bare value", () => {
    expect(defaultValueFor(field(BAND), "in")).toEqual(["low"]);
  });

  it("gives a unary operator no value at all", () => {
    expect(defaultValueFor(field(GRADE), "null")).toBeNull();
  });
});

describe("ExpressionBuilder — reports only edits", () => {
  // react-querybuilder reports its query once on mount unless told not to.
  // That report is nobody's edit, and it arrives a moment after the render
  // it came from: in the model editor it climbed a chain of handlers, each
  // rebuilding its value from the props of that earlier render, and wrote a
  // stale copy of the whole rule over whatever the person had just changed
  // -- a rule made "preferred" snapped back to "required".
  it("does not call onChange just for being shown", async () => {
    const onChange = renderBuilder(docWith({ field: CAPACITY, operator: ">", value: 3 }));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(onChange).not.toHaveBeenCalled();
  });

  it("does not call onChange for being shown empty", async () => {
    const onChange = renderBuilder(null);
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(onChange).not.toHaveBeenCalled();
  });
});

describe("ExpressionBuilder — editing", () => {
  it("emits a versioned document whenever anything changes", () => {
    const onChange = renderBuilder(docWith({ field: CODE, operator: "contains", value: "a" }));
    fireEvent.change(screen.getAllByTestId("expression-value")[0], { target: { value: "ab" } });
    expect(lastDoc(onChange).version).toBe(EXPRESSION_VERSION);
  });

  it("adds a rule that is valid on arrival rather than one the user must fix first", () => {
    const onChange = renderBuilder(null);
    fireEvent.click(screen.getByTestId("expression-add-rule"));
    const doc = lastDoc(onChange);
    expect(doc.query.rules).toHaveLength(1);
    // Re-rendered with what it emitted, the builder shows no problem.
    render(<ExpressionBuilder catalogue={catalogue} value={doc} onChange={vi.fn()} />);
    expect(screen.queryAllByTestId("expression-problems")).toHaveLength(0);
  });

  it("moves the operator and the value to the new field's type when the field changes", () => {
    // `contains` is meaningless on an integer, and "abc" is not one.
    const onChange = renderBuilder(docWith({ field: CODE, operator: "contains", value: "abc" }));
    fireEvent.change(screen.getAllByTestId("expression-field")[0], { target: { value: CAPACITY } });
    const rule = lastDoc(onChange).query.rules[0] as { operator: string; value: unknown };
    expect(rule.operator).not.toBe("contains");
    expect(typeof rule.value).not.toBe("string");
  });

  it("removes a rule", () => {
    const onChange = renderBuilder(docWith({ field: CODE, operator: "contains", value: "a" }));
    fireEvent.click(screen.getAllByTestId("expression-remove-rule")[0]);
    expect(lastDoc(onChange).query.rules).toHaveLength(0);
  });

  it("adds and removes a group", () => {
    const onChange = renderBuilder(null);
    fireEvent.click(screen.getByTestId("expression-add-group"));
    expect(lastDoc(onChange).query.rules).toHaveLength(1);
    render(<ExpressionBuilder catalogue={catalogue} value={lastDoc(onChange)} onChange={onChange} />);
    fireEvent.click(screen.getAllByTestId("expression-remove-group")[0]);
    expect(lastDoc(onChange).query.rules).toHaveLength(0);
  });

  it("changes a group's combinator, which sits between conditions", () => {
    const onChange = renderBuilder(docWith(
      { field: CODE, operator: "contains", value: "a" },
      { field: CODE, operator: "contains", value: "b" },
    ));
    fireEvent.change(screen.getAllByTestId("expression-combinator")[0], { target: { value: "or" } });
    expect(lastDoc(onChange).query.combinator).toBe("or");
  });

  it("offers no combinator ahead of a single condition", () => {
    renderBuilder(docWith({ field: CODE, operator: "contains", value: "a" }));
    expect(screen.queryByTestId("expression-combinator")).toBeNull();
  });

  it("adds beside the last condition, not in the header, once there is one", () => {
    const onChange = renderBuilder(docWith(
      { field: CODE, operator: "contains", value: "a" },
      { field: CODE, operator: "contains", value: "b" },
    ));
    // One add of each kind for the group, on the last row.
    const rows = screen.getAllByTestId("expression-rule");
    expect(screen.getAllByTestId("expression-add-rule")).toHaveLength(1);
    expect(rows[1]).toContainElement(screen.getByTestId("expression-add-rule"));
    expect(rows[0].querySelector('[data-testid="expression-add-rule"]')).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Add a condition" }));
    expect(lastDoc(onChange).query.rules).toHaveLength(3);
    fireEvent.click(screen.getByRole("button", { name: "Add a group of conditions" }));
    expect(lastDoc(onChange).query.rules.some((rule: object) => "rules" in rule)).toBe(true);
  });

  it("keeps the header adds for an empty filter", () => {
    renderBuilder(docWith());
    expect(screen.getByRole("button", { name: "Add a condition" })).toHaveTextContent("+ Condition");
    expect(screen.getByRole("button", { name: "Add a group of conditions" })).toHaveTextContent("+ Group");
  });
});

describe("ExpressionBuilder — what is wrong, shown in the builder", () => {
  it("lists a problem and marks the rule it belongs to", () => {
    renderBuilder(docWith({ field: CAPACITY, operator: "=", value: "eight" }));
    const problems = screen.getByTestId("expression-problems");
    expect(problems).toHaveAttribute("role", "alert");
    // axe, in the browser: `role="alert"` ON the <ul> overrides its list
    // role, which orphans every <li> inside it (`listitem`,
    // `aria-allowed-role`). The alert wraps the list instead.
    expect(problems.tagName).not.toBe("UL");
    expect(problems.querySelector("ul > li")).not.toBeNull();
    expect(problems).toHaveTextContent(/capacity/);
    expect(screen.getAllByTestId("expression-rule")[0]).toHaveAttribute("data-invalid", "true");
  });

  it("shows nothing when the document is valid", () => {
    renderBuilder(docWith({ field: CAPACITY, operator: "=", value: 8 }));
    expect(screen.queryByTestId("expression-problems")).not.toBeInTheDocument();
    expect(screen.getAllByTestId("expression-rule")[0]).toHaveAttribute("data-invalid", "false");
  });

  it("warns, without refusing, when an and-group mixes two entity types", () => {
    renderBuilder(
      docWith(
        { field: CAPACITY, operator: ">", value: 1 },
        { field: encodeFieldId({ kind: "attribute", entityTypeId: "2", attribute: "capacity" }), operator: ">", value: 1 }
      )
    );
    expect(screen.queryByTestId("expression-problems")).not.toBeInTheDocument();
    expect(screen.getByTestId("expression-warnings")).toHaveTextContent(/entity type/i);
  });
});

describe("ExpressionBuilder — accessibility", () => {
  const query = docWith(
    { field: CAPACITY, operator: ">", value: 3 },
    { combinator: "or", rules: [{ field: CODE, operator: "contains", value: "a" }] }
  );

  it("gives every control an accessible name that says which condition it belongs to", () => {
    renderBuilder(query);
    // Not five selects all called "Field", which is what the library's own
    // `title="Field"` produces.
    const names = screen.getAllByTestId("expression-field").map((el) => el.getAttribute("aria-label"));
    expect(new Set(names).size).toBe(names.length);
    for (const name of names) {
      expect(name).toMatch(/condition/i);
    }
    for (const testid of ["expression-operator", "expression-value", "expression-combinator"]) {
      for (const el of screen.getAllByTestId(testid)) {
        expect(el.getAttribute("aria-label"), testid).toBeTruthy();
      }
    }
  });

  it("gives every add/remove button an accessible name beyond its glyph", () => {
    renderBuilder(query);
    for (const button of screen.getAllByRole("button")) {
      const name = button.getAttribute("aria-label") ?? button.textContent ?? "";
      expect(name.trim().length, button.outerHTML).toBeGreaterThan(2);
    }
  });

  it("meets the 24px target size on every add/remove button (audit H-9)", () => {
    renderBuilder(query);
    for (const testid of [
      "expression-add-rule",
      "expression-add-group",
      "expression-remove-rule",
      "expression-remove-group",
    ]) {
      for (const button of screen.getAllByTestId(testid)) {
        const style = getComputedStyle(button);
        expect(Number.parseFloat(style.minWidth), `${testid} width`).toBeGreaterThanOrEqual(24);
        expect(Number.parseFloat(style.minHeight), `${testid} height`).toBeGreaterThanOrEqual(24);
      }
    }
  });

  it("names the builder as a group rather than leaving a bare unnamed region", () => {
    renderBuilder(query);
    expect(screen.getByTestId("expression-builder")).toHaveAttribute("aria-label");
  });
});

describe("ExpressionBuilder — and only", () => {
  it("offers no groups and no “or” where conditions can only be joined with “and”", () => {
    render(<ExpressionBuilder catalogue={catalogue} value={docWith({ field: CAPACITY, operator: ">", value: 3 }, { field: CODE, operator: "=", value: "a" })} onChange={vi.fn()} andOnly />);
    expect(screen.queryByTestId("expression-add-group")).toBeNull();
    expect(screen.getByTestId("expression-add-rule")).toBeInTheDocument();
    const joiner = screen.getByTestId("expression-combinator");
    expect(joiner.tagName).toBe("SPAN");
    expect(joiner).toHaveTextContent("and");
  });
});
