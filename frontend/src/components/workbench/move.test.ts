import { beforeEach, describe, expect, it, vi } from "vitest";
import { moveEdge, moveRecord, moveWords } from "./move";
import type { WorkbenchSchema } from "../../api/workbench";

vi.mock("../../api/client", async () => {
  const actual = await vi.importActual<typeof import("../../api/client")>("../../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { apiFetch } from "../../api/client";

const mockFetch = apiFetch as unknown as ReturnType<typeof vi.fn>;

// unit nests in unit by a hierarchy (reports_to); depot sits under a unit by its `unit` field.
const SCHEMA: WorkbenchSchema = {
  domain_id: 7,
  kinds: [
    { id: 1, name: "unit", is_abstract: false, inherited_from: null, count: 3 },
    { id: 2, name: "depot", is_abstract: false, inherited_from: null, count: 1 },
  ],
  edges: [
    { group_key: "rel:60", child_kind: 1, parent_kind: 1, field: "reports_to", required: false, relationship_type_id: 60, child_end: "to_entity_id" },
    { group_key: "ref:11", child_kind: 2, parent_kind: 1, field: "unit", required: true, relationship_type_id: 61, child_end: "from_entity_id" },
  ],
  roots: [1],
};
const north = { id: 10, key: "north", entity_type_id: 1 };
const south = { id: 11, key: "south", entity_type_id: 1 };
const depot = { id: 20, key: "D1", entity_type_id: 2 };

const calls = () => mockFetch.mock.calls.map(([path, init]) => `${init?.method ?? "GET"} ${path}${init?.body ? ` ${init.body}` : ""}`);

beforeEach(() => mockFetch.mockReset());

describe("moving a record in the tree", () => {
  it("sets the reference field to the new parent's key", async () => {
    mockFetch.mockImplementation((path: string, init?: RequestInit) =>
      Promise.resolve(init?.method ? {} : { ...depot, attrs: { unit: "north", bays: 4 }, updated_at: "t1" }));
    const edge = moveEdge(SCHEMA, 2, 1)!;
    expect(moveWords(edge, south)).toBe("unit = south");
    await moveRecord(edge, depot, south);
    expect(calls()).toEqual([
      "GET /api/v1/entities/20",
      `PATCH /api/v1/entities/20 ${JSON.stringify({ attrs: { unit: "south", bays: 4 }, updated_at: "t1" })}`,
    ]);
  });

  it("re-points a hierarchy's one link to its parent in place", async () => {
    mockFetch.mockImplementation((path: string, init?: RequestInit) =>
      Promise.resolve(init?.method ? {} : { items: [{ id: 99, relationship_type_id: 60, from_entity_id: 10, to_entity_id: 12, updated_at: "t2" }], total: 1 }));
    const edge = moveEdge(SCHEMA, 1, 1)!;
    expect(moveWords(edge, south)).toBe("its reports_to parent becomes south");
    await moveRecord(edge, { id: 12, key: "east", entity_type_id: 1 }, south);
    expect(calls()).toEqual([
      "GET /api/v1/relationships?relationship_type_id=60&to_entity_id=12&limit=1",
      `PATCH /api/v1/relationships/99 ${JSON.stringify({ from_entity_id: 11, updated_at: "t2" })}`,
    ]);
  });

  it("links a record that had no parent in the hierarchy", async () => {
    mockFetch.mockImplementation((path: string, init?: RequestInit) => Promise.resolve(init?.method ? {} : { items: [], total: 0 }));
    await moveRecord(moveEdge(SCHEMA, 1, 1)!, north, south);
    expect(calls()[1]).toBe(`POST /api/v1/relationships ${JSON.stringify({ relationship_type_id: 60, from_entity_id: 11, to_entity_id: 10 })}`);
  });

  it("knows when a kind cannot sit under another", () => {
    expect(moveEdge(SCHEMA, 1, 2)).toBeNull();
  });
});
