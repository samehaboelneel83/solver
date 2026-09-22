import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import type { AttrType, EntityType, Id } from "../api/v1";
import { buildFieldCatalogue, ENTITY_COLUMNS, type RelationshipDirection } from "./fields";
import { degreeKey, evaluateExpression, type EvaluationTarget } from "./evaluate";
import { validateExpression } from "./validate";
import type { ExpressionDocument } from "./document";

/**
 * The browser half of the client/server cross-check.
 *
 * `backend/tests/expression_cross_check.json` describes a small world --
 * two entity types, eight and two attributes, one relationship type, five
 * entities -- and a list of documents, each carrying the keys it must
 * select and the hand derivation of why. `test_api_entities_expression.py`
 * compiles each document to SQL and executes it against that world in
 * Postgres; this file evaluates the same documents in the evaluator the
 * canvas uses, over the same world in memory.
 *
 * **Both assert the `expect` in the file, never each other's output.** Two
 * implementations that agree with each other and disagree with the intent
 * would prove nothing, so the answers were derived by hand from the
 * semantics written down in `evaluate.ts` and are pinned in the fixture
 * next to the reasoning. The cases that exist specifically because the two
 * could plausibly diverge:
 *
 * - a missing attribute key versus a stored JSON `null` (both absent);
 * - an integer compared as a number where text order would differ;
 * - a date compared as TEXT -- including a stored value that is not a
 *   date at all, which the `entity_validate` trigger permits and which a
 *   `::date` cast would raise on rather than answer;
 * - a time with seconds against one without (Ruling 36);
 * - `not` over a rule that is false because the value is absent, where
 *   SQL's three-valued logic would drop rows this evaluator keeps.
 */

const FIXTURE_PATH = (() => {
  const relative = "backend/tests/expression_cross_check.json";
  for (let dir = process.cwd(); ; dir = dirname(dir)) {
    const candidate = resolve(dir, relative);
    if (existsSync(candidate)) return candidate;
    if (dirname(dir) === dir) throw new Error(`${relative} was not found above ${process.cwd()}`);
  }
})();

type Fixture = {
  entityTypes: { name: string; role: string; attributes: { name: string; data_type: AttrType; enum_values?: string[] }[] }[];
  relationshipTypes: { name: string; from: string; to: string }[];
  entities: {
    type: string;
    key: string;
    label: string | null;
    sort_order: number;
    active: boolean;
    attrs: Record<string, unknown>;
  }[];
  relationships: { type: string; from: string; to: string }[];
  cases: { name: string; why: string; document: unknown; expect: string[] }[];
};

const fixture = JSON.parse(readFileSync(FIXTURE_PATH, "utf8")) as Fixture;

// Synthetic ids, assigned the way the database assigns them: in order,
// from 1, across both tables independently. Nothing depends on the actual
// numbers -- the documents name types by `@name` and both sides substitute
// the ids they have.
const entityTypeIds = new Map(fixture.entityTypes.map((t, index) => [t.name, index + 1]));
const relationshipTypeIds = new Map(fixture.relationshipTypes.map((t, index) => [t.name, index + 1]));

function substitute(template: unknown): ExpressionDocument {
  let raw = JSON.stringify(template);
  // `split`/`join` rather than `replaceAll`, which this project's `lib`
  // (ES2020) does not declare.
  for (const [name, id] of entityTypeIds) raw = raw.split(`@${name}:`).join(`${id}:`);
  for (const [name, id] of relationshipTypeIds) raw = raw.split(`@${name}:`).join(`${id}:`);
  expect(raw).not.toContain("@");
  return JSON.parse(raw) as ExpressionDocument;
}

const entityTypes: EntityType[] = fixture.entityTypes.map((spec) => ({
  id: entityTypeIds.get(spec.name) as Id,
  domain_id: 1 as Id,
  name: spec.name,
  role: "other",
  colour: null,
  icon: null,
  updated_at: "2026-09-20T09:00:00+00:00",
  attributes: spec.attributes.map((attribute, index) => ({
    id: (index + 1) as Id,
    sort_order: index + 1,
    entity_type_id: entityTypeIds.get(spec.name) as Id,
    name: attribute.name,
    data_type: attribute.data_type,
    // Every attribute in the fixture is optional, which is what makes the
    // null operators available on them.
    required: false,
    unit: null,
    enum_values: attribute.enum_values ?? null,
    default_value: null,
  })),
}));

const catalogue = buildFieldCatalogue({
  entityTypes,
  relationshipTypes: [...relationshipTypeIds].map(([name, id]) => ({ id, name })),
  columns: ENTITY_COLUMNS.map((c) => c.column),
});

/** The relationship counts the graph adapter would compute, from the
 * fixture's rows: a row is outgoing at its `from` end, incoming at its
 * `to` end, and counted once in `any` at each distinct end. */
function degrees(): Map<string, Map<string, number>> {
  const out = new Map<string, Map<string, number>>();
  const bump = (key: string, relationshipTypeId: number, direction: RelationshipDirection) => {
    let byKey = out.get(key);
    if (!byKey) out.set(key, (byKey = new Map()));
    const k = degreeKey(String(relationshipTypeId), direction);
    byKey.set(k, (byKey.get(k) ?? 0) + 1);
  };
  for (const row of fixture.relationships) {
    const id = relationshipTypeIds.get(row.type) as number;
    bump(row.from, id, "outgoing");
    bump(row.to, id, "incoming");
    bump(row.from, id, "any");
    if (row.to !== row.from) bump(row.to, id, "any");
  }
  return out;
}

const allDegrees = degrees();

const targets = new Map<string, EvaluationTarget>(
  fixture.entities.map((entity) => [
    entity.key,
    {
      entityTypeId: String(entityTypeIds.get(entity.type)),
      columns: {
        key: entity.key,
        label: entity.label,
        sort_order: entity.sort_order,
        active: entity.active,
      },
      attrs: entity.attrs,
      degrees: allDegrees.get(entity.key) ?? new Map(),
    },
  ])
);

function matching(document: ExpressionDocument): string[] {
  const keys: string[] = [];
  for (const [key, target] of targets) {
    if (evaluateExpression(document, catalogue, target)) keys.push(key);
  }
  return keys.sort();
}

describe("the client evaluator, over the shared cross-check fixture", () => {
  it.each(fixture.cases.map((c) => [c.name, c] as const))("%s", (_name, testCase) => {
    const document = substitute(testCase.document);
    // A case the validator refuses is a case neither side would ever run,
    // so an invalid document in the fixture must fail loudly rather than
    // quietly evaluate to nothing.
    const validation = validateExpression(document, catalogue);
    expect(validation.problems, testCase.name).toEqual([]);
    expect(matching(document), testCase.why).toEqual([...testCase.expect].sort());
  });

  it("treats a value whose type disagrees with its declaration as uncomparable, but present", () => {
    // The shape `backend/tests/test_api_entities_expression.py`'s
    // `..._disagrees_with_the_declaration_...` pins on the server. The
    // trigger cannot write it, but changing an `attribute_def.data_type`
    // leaves rows behind it, so both sides have to answer -- and answer
    // the same. `note` is text; this target stores a number under it.
    const drifted: EvaluationTarget = {
      entityTypeId: String(entityTypeIds.get("unit")),
      columns: {},
      attrs: { note: 5 },
      degrees: new Map(),
    };
    const rule = (operator: string, value: unknown) =>
      ({ version: 1, query: { combinator: "and", rules: [{ field: "attr:@unit:note", operator, value }] } });
    const run = (operator: string, value: unknown) =>
      evaluateExpression(substitute(rule(operator, value)), catalogue, drifted);

    expect(run("=", "5")).toBe(false);
    expect(run("contains", "5")).toBe(false);
    // Present, so not empty -- "cannot be compared" is not "has no value".
    expect(run("null", null)).toBe(false);
    expect(run("notNull", null)).toBe(true);
  });

  it("really does store a JSON null for u1 and no key at all for u2", () => {
    const u1 = fixture.entities.find((e) => e.key === "u1");
    const u2 = fixture.entities.find((e) => e.key === "u2");
    expect(Object.prototype.hasOwnProperty.call(u1?.attrs ?? {}, "note")).toBe(true);
    expect(u1?.attrs.note).toBeNull();
    expect(Object.prototype.hasOwnProperty.call(u2?.attrs ?? {}, "note")).toBe(false);
  });

  it("really does store a non-date in a date attribute", () => {
    const u3 = fixture.entities.find((e) => e.key === "u3");
    expect(u3?.attrs.hired).toBe("not-a-date");
  });

  it("really does store the same time in two spellings", () => {
    expect(fixture.entities.find((e) => e.key === "u1")?.attrs.starts).toBe("09:30");
    expect(fixture.entities.find((e) => e.key === "u2")?.attrs.starts).toBe("09:30:00");
  });
});
