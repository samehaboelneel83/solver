import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import AttributeDefEditor from "./AttributeDefEditor";
import { parseDefaultValue, serverFieldErrors } from "./attrTypes";
import { ApiError } from "../api/client";
import type { AttrType, AttributeDef, AttributeDefCreate } from "../api/v1";

const NON_ENUM_TYPES: AttrType[] = ["integer", "number", "text", "boolean", "time", "date"];

function renderEditor(props: Partial<Parameters<typeof AttributeDefEditor>[0]> = {}) {
  const onSubmit = vi.fn<(body: AttributeDefCreate) => void>();
  render(<AttributeDefEditor submitLabel="Add attribute" onSubmit={onSubmit} {...props} />);
  return { onSubmit };
}

function setName(value: string) {
  fireEvent.change(screen.getByLabelText(/^Name/), { target: { value } });
}
function setType(value: AttrType) {
  fireEvent.change(screen.getByLabelText(/^Data type/), { target: { value } });
}
function setEnumValues(text: string) {
  fireEvent.change(screen.getByLabelText(/^Allowed values/), { target: { value: text } });
}
function defaultInput() {
  return screen.getByLabelText(/^Default value/) as HTMLInputElement | HTMLSelectElement;
}
function setDefault(value: string) {
  fireEvent.change(defaultInput(), { target: { value } });
}
function submit() {
  fireEvent.click(screen.getByRole("button", { name: "Add attribute" }));
}
function lastBody(onSubmit: ReturnType<typeof vi.fn>): AttributeDefCreate {
  expect(onSubmit).toHaveBeenCalledTimes(1);
  return onSubmit.mock.calls[0][0] as AttributeDefCreate;
}

describe("AttributeDefEditor: the enum_values editor", () => {
  it("is hidden for a new attribute, whose type starts as something other than enum", () => {
    renderEditor();
    expect(screen.queryByLabelText(/^Allowed values/)).not.toBeInTheDocument();
  });

  it("appears when the type becomes enum and disappears for every other type", () => {
    renderEditor();
    for (const type of NON_ENUM_TYPES) {
      setType("enum");
      expect(screen.getByLabelText(/^Allowed values/)).toBeInTheDocument();
      setType(type);
      expect(screen.queryByLabelText(/^Allowed values/)).not.toBeInTheDocument();
    }
  });

  it("sends enum_values for an enum, one per line, trimmed, blank lines dropped", () => {
    const { onSubmit } = renderEditor();
    setName("shift_kind");
    setType("enum");
    setEnumValues(" day \n\nnight\n");
    submit();
    expect(lastBody(onSubmit).enum_values).toEqual(["day", "night"]);
  });

  it("sends enum_values: null for a non-enum type even after values were typed under enum", () => {
    const { onSubmit } = renderEditor();
    setName("hours");
    setType("enum");
    setEnumValues("a\nb");
    setType("integer");
    submit();
    const body = lastBody(onSubmit);
    expect(body.data_type).toBe("integer");
    expect(body.enum_values).toBeNull();
  });

  it("refuses an enum with no values (the server would accept it, and no value could ever satisfy it)", () => {
    const { onSubmit } = renderEditor();
    setName("kind");
    setType("enum");
    setEnumValues("\n  \n");
    submit();
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByLabelText(/^Allowed values/)).toHaveAttribute("aria-invalid", "true");
  });

  it("refuses duplicate enum values", () => {
    const { onSubmit } = renderEditor();
    setName("kind");
    setType("enum");
    setEnumValues("day\nnight\nday");
    submit();
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByLabelText(/^Allowed values/)).toHaveAttribute("aria-invalid", "true");
  });
});

describe("AttributeDefEditor: the default is typed by data_type", () => {
  it("integer: a text box in numeric mode, so a non-number is visible to validation rather than blanked by the browser", () => {
    renderEditor();
    setType("integer");
    const input = defaultInput();
    expect(input.tagName).toBe("INPUT");
    expect(input).toHaveAttribute("type", "text");
    expect(input).toHaveAttribute("inputmode", "numeric");
  });

  it.each([["2.5"], ["banana"], ["1e3"], ["5 apples"], ["9007199254740993"], ["   "], ["0x10"]])(
    "integer: refuses %j, marks the default field, and does not submit",
    (raw) => {
      const { onSubmit } = renderEditor();
      setName("headcount");
      setType("integer");
      setDefault(raw);
      submit();
      expect(onSubmit).not.toHaveBeenCalled();
      expect(defaultInput()).toHaveAttribute("aria-invalid", "true");
      expect(screen.getByLabelText(/^Name/)).not.toHaveAttribute("aria-invalid");
    }
  );

  it("integer: says a decimal is not a whole number, rather than some other reason", () => {
    renderEditor();
    setName("headcount");
    setType("integer");
    setDefault("2.5");
    submit();
    expect(defaultInput()).toHaveAccessibleDescription(/must be a whole number/i);
  });

  it.each([
    ["7", 7],
    ["-3", -3],
    [" 12 ", 12],
  ])("integer: sends %j as the JSON number %j, never the string", (raw, expected) => {
    const { onSubmit } = renderEditor();
    setName("headcount");
    setType("integer");
    setDefault(raw);
    submit();
    expect(lastBody(onSubmit).default_value).toStrictEqual(expected);
  });

  it("number: accepts a decimal and sends it as a number", () => {
    const { onSubmit } = renderEditor();
    setName("rate");
    setType("number");
    expect(defaultInput()).toHaveAttribute("inputmode", "decimal");
    setDefault("2.5");
    submit();
    expect(lastBody(onSubmit).default_value).toStrictEqual(2.5);
  });

  it.each([["banana"], ["Infinity"], ["1.2.3"], ["   "], ["0x10"], ["1,5"]])("number: refuses %j", (raw) => {
    const { onSubmit } = renderEditor();
    setName("rate");
    setType("number");
    setDefault(raw);
    submit();
    expect(onSubmit).not.toHaveBeenCalled();
    expect(defaultInput()).toHaveAttribute("aria-invalid", "true");
  });

  it("boolean: a select of no default / true / false, sent as a real boolean", () => {
    const { onSubmit } = renderEditor();
    setName("active");
    setType("boolean");
    const select = defaultInput();
    expect(select.tagName).toBe("SELECT");
    expect(within(select).getAllByRole("option").map((o) => (o as HTMLOptionElement).value)).toEqual([
      "",
      "true",
      "false",
    ]);
    setDefault("false");
    submit();
    expect(lastBody(onSubmit).default_value).toStrictEqual(false);
  });

  it("enum: a select offering exactly the allowed values as typed, and the chosen one is sent", () => {
    const { onSubmit } = renderEditor();
    setName("shift_kind");
    setType("enum");
    setEnumValues("day\nnight");
    const select = defaultInput();
    expect(select.tagName).toBe("SELECT");
    expect(within(select).getAllByRole("option").map((o) => (o as HTMLOptionElement).value)).toEqual([
      "",
      "day",
      "night",
    ]);
    setDefault("night");
    submit();
    const body = lastBody(onSubmit);
    expect(body.default_value).toBe("night");
    expect(body.enum_values).toEqual(["day", "night"]);
  });

  it("enum: follows the allowed values as they are edited", () => {
    renderEditor();
    setType("enum");
    setEnumValues("a");
    setEnumValues("a\nb\nc");
    expect(within(defaultInput()).getAllByRole("option").map((o) => (o as HTMLOptionElement).value)).toEqual([
      "",
      "a",
      "b",
      "c",
    ]);
  });

  it("enum: refuses a default that was removed from the allowed values", () => {
    const { onSubmit } = renderEditor();
    setName("shift_kind");
    setType("enum");
    setEnumValues("day\nnight");
    setDefault("night");
    setEnumValues("day");
    submit();
    expect(onSubmit).not.toHaveBeenCalled();
    expect(defaultInput()).toHaveAttribute("aria-invalid", "true");
  });

  it("text: sends the string as typed", () => {
    const { onSubmit } = renderEditor();
    setName("note");
    setType("text");
    expect(defaultInput()).toHaveAttribute("type", "text");
    setDefault("5");
    submit();
    expect(lastBody(onSubmit).default_value).toStrictEqual("5");
  });

  it("date: a date input, sent as the ISO date string", () => {
    const { onSubmit } = renderEditor();
    setName("start");
    setType("date");
    expect(defaultInput()).toHaveAttribute("type", "date");
    setDefault("2026-09-19");
    submit();
    expect(lastBody(onSubmit).default_value).toBe("2026-09-19");
  });

  it("time: a time input, sent as HH:MM", () => {
    const { onSubmit } = renderEditor();
    setName("opens");
    setType("time");
    expect(defaultInput()).toHaveAttribute("type", "time");
    setDefault("08:30");
    submit();
    expect(lastBody(onSubmit).default_value).toBe("08:30");
  });

  it.each([...NON_ENUM_TYPES, "enum" as AttrType])(
    "%s: leaving the default empty sends an explicit default_value: null (Ruling 18: SQL NULL)",
    (type) => {
      const { onSubmit } = renderEditor();
      setName("thing");
      setType(type);
      if (type === "enum") setEnumValues("x");
      submit();
      const body = lastBody(onSubmit);
      expect("default_value" in body).toBe(true);
      expect(body.default_value).toBeNull();
    }
  );

  it("clears the default when the data type changes, so a value typed for one type never travels to another", () => {
    const { onSubmit } = renderEditor();
    setName("thing");
    setType("text");
    setDefault("banana");
    setType("integer");
    expect(defaultInput().value).toBe("");
    submit();
    expect(lastBody(onSubmit).default_value).toBeNull();
  });
});

describe("parseDefaultValue", () => {
  it("is the single rule the form applies", () => {
    expect(parseDefaultValue("integer", "2.5", [])).toMatchObject({ ok: false });
    expect(parseDefaultValue("integer", "banana", [])).toMatchObject({ ok: false });
    expect(parseDefaultValue("integer", "42", [])).toEqual({ ok: true, value: 42 });
    expect(parseDefaultValue("number", "0.5", [])).toEqual({ ok: true, value: 0.5 });
    expect(parseDefaultValue("boolean", "true", [])).toEqual({ ok: true, value: true });
    expect(parseDefaultValue("enum", "b", ["a"])).toMatchObject({ ok: false });
    expect(parseDefaultValue("enum", "a", ["a"])).toEqual({ ok: true, value: "a" });
    expect(parseDefaultValue("date", "2026-02-30", [])).toMatchObject({ ok: false });
    expect(parseDefaultValue("time", "25:00", [])).toMatchObject({ ok: false });
    expect(parseDefaultValue("text", "", [])).toEqual({ ok: true, value: null });
  });
});

describe("AttributeDefEditor: the materialised-default note (spec §3)", () => {
  it("is shown next to the default when editing an existing attribute, and describes the input", () => {
    const initial: AttributeDef = {
      id: 11,
      entity_type_id: 5,
      name: "headcount",
      data_type: "integer",
      required: false,
      unit: null,
      enum_values: null,
      default_value: 3,
    };
    renderEditor({ initial, submitLabel: "Save attribute" });
    expect(defaultInput()).toHaveAccessibleDescription(/existing entities keep the default they were given/i);
  });

  it("is shown when adding an attribute too, since existing entities only receive it when next saved", () => {
    renderEditor();
    expect(screen.getByText(/existing entities keep the default they were given/i)).toBeInTheDocument();
  });
});

describe("AttributeDefEditor: names", () => {
  it.each([["Employee"], ["1st"], ["id"], ["has space"], [""]])("refuses the name %j before sending", (name) => {
    const { onSubmit } = renderEditor();
    setName(name);
    setType("text");
    submit();
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByLabelText(/^Name/)).toHaveAttribute("aria-invalid", "true");
  });
});

describe("AttributeDefEditor: editing an existing attribute", () => {
  const enumAttr: AttributeDef = {
    id: 12,
    entity_type_id: 5,
    name: "shift_kind",
    data_type: "enum",
    required: true,
    unit: "slot",
    enum_values: ["day", "night"],
    default_value: "night",
  };

  it("prefills every field, including the typed default", () => {
    renderEditor({ initial: enumAttr, submitLabel: "Save attribute" });
    expect(screen.getByLabelText(/^Name/)).toHaveValue("shift_kind");
    expect(screen.getByLabelText(/^Data type/)).toHaveValue("enum");
    expect(screen.getByLabelText(/^Required/)).toBeChecked();
    expect(screen.getByLabelText(/^Unit/)).toHaveValue("slot");
    expect(screen.getByLabelText(/^Allowed values/)).toHaveValue("day\nnight");
    expect(defaultInput()).toHaveValue("night");
  });

  it("sends unit: null when the unit is cleared", () => {
    const { onSubmit } = renderEditor({ initial: enumAttr, submitLabel: "Save attribute" });
    fireEvent.change(screen.getByLabelText(/^Unit/), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Save attribute" }));
    expect(lastBody(onSubmit).unit).toBeNull();
  });

  it("shows a stored default that no longer fits, and refuses to save it unchanged", () => {
    const broken: AttributeDef = { ...enumAttr, data_type: "integer", enum_values: null, default_value: "banana" };
    const { onSubmit } = renderEditor({ initial: broken, submitLabel: "Save attribute" });
    expect(defaultInput()).toHaveValue("banana");
    fireEvent.click(screen.getByRole("button", { name: "Save attribute" }));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(defaultInput()).toHaveAttribute("aria-invalid", "true");
  });
});

describe("AttributeDefEditor: server errors", () => {
  it("marks the field a server error names -- and only that one", () => {
    renderEditor({ serverErrors: { unit: "unit: too long" } });
    const unit = screen.getByLabelText(/^Unit/);
    expect(unit).toHaveAttribute("aria-invalid", "true");
    expect(unit).toHaveAccessibleDescription(/too long/);
    expect(screen.getByLabelText(/^Name/)).not.toHaveAttribute("aria-invalid");
    expect(defaultInput()).not.toHaveAttribute("aria-invalid");
    expect(screen.getByRole("alert")).toHaveTextContent("unit: too long");
  });
});

describe("serverFieldErrors", () => {
  const FIELDS = ["name", "data_type", "unit", "enum_values", "default_value"];

  it("maps each list-shaped 422 entry to the field its loc names", () => {
    const err = new ApiError(
      422,
      JSON.stringify({
        detail: [
          { loc: ["body", "enum_values"], msg: "must list its allowed values", type: "value_error" },
          { loc: ["body", "name"], msg: "must match", type: "value_error" },
        ],
      })
    );
    expect(serverFieldErrors(err, FIELDS, "attribute")).toEqual({
      fields: { enum_values: "must list its allowed values", name: "must match" },
      general: null,
    });
  });

  it("keeps an entry whose loc names no known field as a general message", () => {
    const err = new ApiError(422, JSON.stringify({ detail: [{ loc: ["body"], msg: "bad body" }] }));
    expect(serverFieldErrors(err, FIELDS, "attribute")).toEqual({ fields: {}, general: "bad body" });
  });

  it("turns the duplicate-name 409 into a message on the name field", () => {
    const err = new ApiError(
      409,
      JSON.stringify({ detail: "a attribute_def row with the same entity_type_id_name already exists" })
    );
    const result = serverFieldErrors(err, FIELDS, "attribute");
    expect(Object.keys(result.fields)).toEqual(["name"]);
    expect(result.fields.name).toMatch(/already has an attribute with this name/i);
    expect(result.general).toBeNull();
  });

  it("leaves any other 409 as a general message, verbatim", () => {
    const err = new ApiError(409, JSON.stringify({ detail: "referenced domain_id does not exist" }));
    expect(serverFieldErrors(err, FIELDS, "attribute")).toEqual({
      fields: {},
      general: "referenced domain_id does not exist",
    });
  });
});
