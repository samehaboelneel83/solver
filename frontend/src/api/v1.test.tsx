import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./client", async () => {
  const actual = await vi.importActual<typeof import("./client")>("./client");
  return { ...actual, apiFetch: vi.fn() };
});

import { ApiError, apiFetch } from "./client";
import {
  createAttribute,
  createEntity,
  createEntityType,
  createParameter,
  createRelationship,
  createRelationshipType,
  createScenario,
  createVersion,
  deleteAttribute,
  deleteEntity,
  deleteEntityType,
  deleteParameter,
  deleteRelationship,
  deleteRelationshipType,
  deleteScenario,
  getEntity,
  getEntityType,
  getParameter,
  getParameterValues,
  getRelationship,
  getRelationshipType,
  getScenario,
  getVersion,
  listAttributes,
  listDomains,
  listEntities,
  listEntityTypes,
  listParameters,
  listRelationships,
  listRelationshipTypes,
  listScenarios,
  listVersions,
  putParameterValues,
  updateAttribute,
  updateEntity,
  updateEntityType,
  updateParameter,
  updateRelationship,
  updateRelationshipType,
  updateScenario,
  useDeleteEntity,
  useEntitiesOfTypes,
  useEntityTypes,
  useRuns,
  validationErrors,
} from "./v1";

const mockFetch = apiFetch as unknown as ReturnType<typeof vi.fn>;

/** The (path, method, parsed body) of the single apiFetch call just made. */
function lastCall(): { path: string; method: string; body: unknown } {
  expect(mockFetch).toHaveBeenCalledTimes(1);
  const [path, options] = mockFetch.mock.calls[0] as [string, RequestInit | undefined];
  return {
    path,
    method: options?.method ?? "GET",
    body: options?.body === undefined ? undefined : JSON.parse(String(options.body)),
  };
}

beforeEach(() => {
  mockFetch.mockReset();
  mockFetch.mockResolvedValue(undefined);
});

// Each case pins one client to the route the backend actually mounts
// (backend/app/api/*.py as of Task 9), not to the plan's prose. The methods
// matter as much as the paths: every v1 update route is PATCH, and a PUT
// would 405 -- except parameter values, whose only write route *is* PUT.
describe("v1 clients hit the routes the backend mounts", () => {
  const cases: [string, () => Promise<unknown>, string, string, unknown?][] = [
    // Task 5 -- entity types and attribute definitions
    ["listEntityTypes", () => listEntityTypes({ domainId: 7, limit: 20, offset: 40 }), "GET", "/api/v1/entity-types?domain_id=7&limit=20&offset=40"],
    ["getEntityType", () => getEntityType(12), "GET", "/api/v1/entity-types/12"],
    ["createEntityType", () => createEntityType({ domain_id: 7, name: "employee", role: "agent" }), "POST", "/api/v1/entity-types", { domain_id: 7, name: "employee", role: "agent" }],
    ["updateEntityType", () => updateEntityType(12, { role: "resource" }), "PATCH", "/api/v1/entity-types/12", { role: "resource" }],
    ["deleteEntityType", () => deleteEntityType(12), "DELETE", "/api/v1/entity-types/12"],
    ["listAttributes", () => listAttributes(12), "GET", "/api/v1/entity-types/12/attributes"],
    ["createAttribute", () => createAttribute(12, { name: "rank", data_type: "integer" }), "POST", "/api/v1/entity-types/12/attributes", { name: "rank", data_type: "integer" }],
    ["updateAttribute", () => updateAttribute(33, { enum_values: null }), "PATCH", "/api/v1/attributes/33", { enum_values: null }],
    ["deleteAttribute", () => deleteAttribute(33), "DELETE", "/api/v1/attributes/33"],
    // Task 6 -- entities
    ["listEntities", () => listEntities({ entityTypeId: 12, q: "mon", limit: 50, offset: 0 }), "GET", "/api/v1/entities?entity_type_id=12&q=mon&limit=50&offset=0"],
    ["getEntity", () => getEntity(5), "GET", "/api/v1/entities/5"],
    ["createEntity", () => createEntity({ entity_type_id: 12, key: "mon", attrs: { rank: 1 } }), "POST", "/api/v1/entities", { entity_type_id: 12, key: "mon", attrs: { rank: 1 } }],
    ["updateEntity", () => updateEntity(5, { attrs: {} }), "PATCH", "/api/v1/entities/5", { attrs: {} }],
    ["deleteEntity", () => deleteEntity(5), "DELETE", "/api/v1/entities/5"],
    // Task 7 -- relationship types and relationships
    ["listRelationshipTypes", () => listRelationshipTypes({ domainId: 7, isHierarchy: true }), "GET", "/api/v1/relationship-types?domain_id=7&is_hierarchy=true"],
    ["getRelationshipType", () => getRelationshipType(8), "GET", "/api/v1/relationship-types/8"],
    ["createRelationshipType", () => createRelationshipType({ domain_id: 7, name: "reports_to", from_type_id: 1, to_type_id: 1, is_hierarchy: true }), "POST", "/api/v1/relationship-types", { domain_id: 7, name: "reports_to", from_type_id: 1, to_type_id: 1, is_hierarchy: true }],
    ["updateRelationshipType", () => updateRelationshipType(8, { cardinality: "many_to_one" }), "PATCH", "/api/v1/relationship-types/8", { cardinality: "many_to_one" }],
    ["deleteRelationshipType", () => deleteRelationshipType(8), "DELETE", "/api/v1/relationship-types/8"],
    ["listRelationships", () => listRelationships({ relationshipTypeId: 8, fromEntityId: 1, toEntityId: 2 }), "GET", "/api/v1/relationships?relationship_type_id=8&from_entity_id=1&to_entity_id=2"],
    ["getRelationship", () => getRelationship(9), "GET", "/api/v1/relationships/9"],
    ["createRelationship", () => createRelationship({ relationship_type_id: 8, from_entity_id: 1, to_entity_id: 2 }), "POST", "/api/v1/relationships", { relationship_type_id: 8, from_entity_id: 1, to_entity_id: 2 }],
    ["updateRelationship", () => updateRelationship(9, { to_entity_id: 3 }), "PATCH", "/api/v1/relationships/9", { to_entity_id: 3 }],
    ["deleteRelationship", () => deleteRelationship(9), "DELETE", "/api/v1/relationships/9"],
    // Task 8 -- parameters
    ["listParameters", () => listParameters({ domainId: 7 }), "GET", "/api/v1/parameters?domain_id=7"],
    ["getParameter", () => getParameter(4), "GET", "/api/v1/parameters/4"],
    ["createParameter", () => createParameter({ domain_id: 7, name: "demand", index_type_ids: [1, 2] }), "POST", "/api/v1/parameters", { domain_id: 7, name: "demand", index_type_ids: [1, 2] }],
    ["updateParameter", () => updateParameter(4, { default_value: 2 }), "PATCH", "/api/v1/parameters/4", { default_value: 2 }],
    ["deleteParameter", () => deleteParameter(4), "DELETE", "/api/v1/parameters/4"],
    ["getParameterValues", () => getParameterValues(4), "GET", "/api/v1/parameters/4/values"],
    ["putParameterValues", () => putParameterValues(4, { cells: [{ entity_ids: [1, 2], value: 5 }] }), "PUT", "/api/v1/parameters/4/values", { cells: [{ entity_ids: [1, 2], value: 5 }] }],
    // Task 9 -- model versions and scenarios
    ["listVersions", () => listVersions(3, { limit: 10 }), "GET", "/api/v1/problems/3/versions?limit=10"],
    ["createVersion", () => createVersion(3, { ir: { sets: [] }, note: "first" }), "POST", "/api/v1/problems/3/versions", { ir: { sets: [] }, note: "first" }],
    ["getVersion", () => getVersion(11), "GET", "/api/v1/versions/11"],
    ["listScenarios", () => listScenarios({ problemId: 3, modelVersionId: 11 }), "GET", "/api/v1/scenarios?problem_id=3&model_version_id=11"],
    ["getScenario", () => getScenario(6), "GET", "/api/v1/scenarios/6"],
    ["createScenario", () => createScenario({ problem_id: 3, model_version_id: 11, name: "base" }), "POST", "/api/v1/scenarios", { problem_id: 3, model_version_id: 11, name: "base" }],
    ["updateScenario", () => updateScenario(6, { patch: { disable: ["c1"] } }), "PATCH", "/api/v1/scenarios/6", { patch: { disable: ["c1"] } }],
    ["deleteScenario", () => deleteScenario(6), "DELETE", "/api/v1/scenarios/6"],
    // Task 4 -- domains come from the generic layer, not /api/v1
    ["listDomains", () => listDomains(), "GET", "/api/domain/?limit=500&order_by=name&order=asc"],
  ];

  it.each(cases)("%s", async (_name, call, method, path, body) => {
    await call();
    const actual = lastCall();
    expect(actual.path).toBe(path);
    expect(actual.method).toBe(method);
    expect(actual.body).toEqual(body);
  });

  it("omits unset list filters instead of sending them empty", async () => {
    await listRelationshipTypes({ domainId: 7 });
    // An empty `is_hierarchy=` would 422 (not a bool), and `domain_id=` would too.
    expect(lastCall().path).toBe("/api/v1/relationship-types?domain_id=7");
  });

  it("sends is_hierarchy=false explicitly, since false is a real filter value", async () => {
    await listRelationshipTypes({ domainId: 7, isHierarchy: false });
    expect(lastCall().path).toBe("/api/v1/relationship-types?domain_id=7&is_hierarchy=false");
  });
});

describe("validationErrors", () => {
  it("returns the list-shaped 422 detail, keeping a trigger's kind (Rulings 19, 21, 23)", () => {
    const detail = [
      { type: "value_error", loc: ["body", "cells", 2, "entity_ids"], msg: "wrong index types", kind: "parameter_index" },
      { type: "missing", loc: ["body", "name"], msg: "Field required" },
    ];
    const err = new ApiError(422, JSON.stringify({ detail }));
    expect(validationErrors(err)).toEqual(detail);
  });

  it("returns [] for a 409 with a string detail, a non-ApiError, and a 422 whose detail is not a list", () => {
    expect(validationErrors(new ApiError(409, JSON.stringify({ detail: "name already exists" })))).toEqual([]);
    expect(validationErrors(new Error("boom"))).toEqual([]);
    // options.py still sends this shape for a malformed ?ids= value.
    expect(validationErrors(new ApiError(422, JSON.stringify({ detail: "invalid id 'x'" })))).toEqual([]);
    expect(validationErrors(new ApiError(422, "not json"))).toEqual([]);
  });
});

describe("v1 hooks", () => {
  function wrapper(queryClient: QueryClient) {
    return ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  }

  it("does not query a domain-scoped list until there is a domain", async () => {
    const queryClient = new QueryClient();
    const { result, rerender } = renderHook(({ domainId }) => useEntityTypes(domainId), {
      wrapper: wrapper(queryClient),
      initialProps: { domainId: null as number | null },
    });
    expect(result.current.fetchStatus).toBe("idle");
    expect(mockFetch).not.toHaveBeenCalled();

    mockFetch.mockResolvedValue({ items: [], total: 0 });
    rerender({ domainId: 7 });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockFetch).toHaveBeenCalledWith("/api/v1/entity-types?domain_id=7");
  });

  it("asks for the runs again while one is still running (benchmark round 5)", async () => {
    mockFetch.mockReset();
    mockFetch.mockResolvedValueOnce({ items: [{ id: 9, status: "running" }], total: 1 })
      .mockResolvedValue({ items: [{ id: 9, status: "optimal" }], total: 1 });
    const { result } = renderHook(() => useRuns(4), { wrapper: wrapper(new QueryClient()) });
    await waitFor(() => expect(result.current.data?.items[0].status).toBe("optimal"), { timeout: 4000 });
  });

  it("reads a kind's records once when a data value is over it twice (benchmark round 4)", async () => {
    mockFetch.mockReset();
    mockFetch.mockResolvedValue({ items: [{ id: 1, entity_type_id: 3, key: "a" }, { id: 2, entity_type_id: 3, key: "b" }], total: 2 });
    const { result } = renderHook(() => useEntitiesOfTypes([3, 3]), { wrapper: wrapper(new QueryClient()) });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.items).toHaveLength(2);
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it("invalidates every v1 query after a mutation, since deletes cascade across resources", async () => {
    const queryClient = new QueryClient();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    const { result } = renderHook(() => useDeleteEntity(), { wrapper: wrapper(queryClient) });
    await act(() => result.current.mutateAsync(5));
    expect(mockFetch).toHaveBeenCalledWith("/api/v1/entities/5", { method: "DELETE" });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["v1"] });
  });
});
