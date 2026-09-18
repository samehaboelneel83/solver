import { describe, expect, it } from "vitest";
import { fieldLabel, lowerFirst, schemaLabel, tableLabel, tableLabelPlural } from "./labels";

describe("tableLabel", () => {
  it("returns the backend label when present", () => {
    expect(tableLabel({ table: "entity_type", label: "Entity type" })).toBe("Entity type");
  });

  it("falls back to the raw table name when no label is present", () => {
    expect(tableLabel({ table: "entity_type" })).toBe("entity_type");
  });
});

describe("tableLabelPlural", () => {
  it("returns the backend plural label when present", () => {
    expect(
      tableLabelPlural({ table: "entity_type", label: "Entity type", label_plural: "Entity types" })
    ).toBe("Entity types");
  });

  it("falls back to the singular label when no plural label is present", () => {
    expect(tableLabelPlural({ table: "entity_type", label: "Entity type" })).toBe("Entity type");
  });

  it("falls back to the raw table name when neither label is present", () => {
    expect(tableLabelPlural({ table: "entity_type" })).toBe("entity_type");
  });
});

describe("fieldLabel", () => {
  it("returns the backend label when present", () => {
    expect(fieldLabel({ name: "source_entity_id", label: "From" })).toBe("From");
  });

  it("falls back to the raw field name when no label is present", () => {
    expect(fieldLabel({ name: "source_entity_id" })).toBe("source_entity_id");
  });
});

describe("schemaLabel (B-1)", () => {
  it("maps the three known schemas to their human label", () => {
    expect(schemaLabel("domain")).toBe("Domain model");
    expect(schemaLabel("problem")).toBe("Problem");
    expect(schemaLabel("iam")).toBe("Access");
  });

  it("falls back to a capitalised raw name for an unmapped schema", () => {
    expect(schemaLabel("scratch")).toBe("Scratch");
  });

  it("returns an empty string unchanged", () => {
    expect(schemaLabel("")).toBe("");
  });
});

describe("lowerFirst", () => {
  it("lower-cases only the first character", () => {
    expect(lowerFirst("Entity type")).toBe("entity type");
  });

  it("returns an empty string unchanged", () => {
    expect(lowerFirst("")).toBe("");
  });
});
