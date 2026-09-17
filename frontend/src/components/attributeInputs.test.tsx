import { describe, expect, it } from "vitest";
import { attributeValueFromForm } from "./attributeInputs";
import type { AttributeDefinitionOption } from "../types/graph";

const numberDef: AttributeDefinitionOption = {
  id: "a1",
  entity_type_id: "t1",
  code: "rank",
  name: "Rank",
  data_type: "number",
};

function formWith(name: string, value: string): FormData {
  const form = new FormData();
  form.set(name, value);
  return form;
}

describe("attributeValueFromForm", () => {
  it("returns null for an empty string, regardless of data_type", () => {
    expect(attributeValueFromForm(formWith("attr:rank", ""), numberDef)).toBeNull();
  });

  it("returns null for a whitespace-only string", () => {
    expect(attributeValueFromForm(formWith("attr:rank", "   "), numberDef)).toBeNull();
  });

  it("throws for a non-numeric string on a number attribute instead of silently coercing to NaN", () => {
    // Number("abc") is NaN, and JSON.stringify(NaN) is `null` -- without the Number.isFinite
    // guard this would silently clear the attribute (a 200) instead of surfacing a validation
    // error, exactly the "typed a number as text crashed the save" class of bug Task 9 fixes.
    expect(() => attributeValueFromForm(formWith("attr:rank", "abc"), numberDef)).toThrow(/Rank/);
  });

  it("throws for a numeric string that overflows to Infinity (non-finite)", () => {
    // Number("1e400") is Infinity, not NaN -- also non-finite, also silently becomes `null`
    // under JSON.stringify without the guard, so it must be rejected the same way.
    expect(() => attributeValueFromForm(formWith("attr:rank", "1e400"), numberDef)).toThrow(/Rank/);
  });

  it("returns a real JS number (not a string) for a valid numeric input", () => {
    const value = attributeValueFromForm(formWith("attr:rank", "3.5"), numberDef);
    expect(value).toBe(3.5);
    expect(typeof value).toBe("number");
  });

  it("returns a parsed value for a valid json attribute and throws for invalid JSON", () => {
    const jsonDef: AttributeDefinitionOption = { ...numberDef, code: "meta", name: "Meta", data_type: "json" };
    expect(attributeValueFromForm(formWith("attr:meta", "{\"a\":1}"), jsonDef)).toEqual({ a: 1 });
    expect(() => attributeValueFromForm(formWith("attr:meta", "{not json"), jsonDef)).toThrow(/Meta/);
  });

  it("always returns true/false for a boolean attribute, never null", () => {
    const boolDef: AttributeDefinitionOption = { ...numberDef, code: "active", name: "Active", data_type: "boolean" };
    expect(attributeValueFromForm(formWith("attr:active", "on"), boolDef)).toBe(true);
    expect(attributeValueFromForm(new FormData(), boolDef)).toBe(false);
  });
});
