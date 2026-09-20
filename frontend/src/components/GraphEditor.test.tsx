import type { ComponentProps } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { fallbackColour, labelForeground } from "../lib/colour";
import GraphEditor, { applyGraphToCy, cyEdgeId, graphStylesheet, positionsAreDegenerate } from "./GraphEditor";

/**
 * The cytoscape double, and what it is allowed to be more permissive
 * about: nothing that this component can get wrong.
 *
 * Ruling 39 found the objects view drawing zero edges because node ids
 * (`entity.id`) and edge ids (`relationship.id`) are two identity
 * sequences in ONE cytoscape id space, and the double kept them in two
 * separate maps -- so no test could fail on it. That class of gap is what
 * this double now closes. Four rules, each verified against
 * cytoscape@3.34.3 and each pinned by a test in "the double matches the
 * library" below:
 *
 * 1. **One id space, first writer wins.** `cy.add()` for an id that is
 *    already taken does nothing at all -- no throw, no console message,
 *    the element simply never appears. It does NOT overwrite.
 * 2. **An edge with a missing endpoint throws**, synchronously, out of
 *    `add()`, taking the rest of the batch with it. That is what
 *    `applyGraphToCy`'s dangling-edge guard exists to prevent.
 * 3. **Removing a node removes its edges.** They cannot exist without
 *    their endpoints.
 * 4. **`getElementById` always returns a collection**, `length === 0`
 *    when nothing matches. It never returns undefined, and it never
 *    claims `length: 1` for an id that is not there.
 *
 * `refusedAdds` and `throwCount` are exposed so a test can assert that
 * the double really did refuse, rather than inferring it from an absence.
 */
const { mockCytoscapeInstance, mockCytoscape, registeredHandlersRef, elementStore, cyStats } =
  vi.hoisted(() => {
  const handlersRef: { current: Record<string, (...args: any[]) => void> } = { current: {} };
  const stats = { refusedAdds: [] as string[], throws: [] as string[] };

  type EleEntry = {
    data: Record<string, any>;
    isNode: boolean;
    styles: Record<string, any>;
    classes: Set<string>;
    position: { x: number; y: number };
  };
  const store = new Map<string, EleEntry>();

  function wrapEle(id: string) {
    return {
      id: () => id,
      isNode: () => store.get(id)?.isNode ?? false,
      data: (arg?: any) => {
        const entry = store.get(id);
        if (!entry) return undefined;
        if (arg === undefined) return { ...entry.data };
        if (typeof arg === "string") return entry.data[arg];
        Object.assign(entry.data, arg);
        return undefined;
      },
      move: (opts: { parent?: string | null }) => {
        const entry = store.get(id);
        if (!entry) return;
        entry.data.parent = opts.parent ?? undefined;
      },
      style: (key: string, value?: any) => {
        const entry = store.get(id);
        if (!entry) return undefined;
        if (value === undefined) return entry.styles[key];
        entry.styles[key] = value;
        return undefined;
      },
      // H-1: position getter/setter -- Arrow-key traversal orders nodes by this, and tests set
      // it explicitly (rather than relying on layout, which the mock never actually runs) to
      // exercise the left-to-right/top-to-bottom ordering.
      position: (val?: { x: number; y: number }) => {
        const entry = store.get(id);
        if (!entry) return undefined;
        if (val === undefined) return { ...entry.position };
        entry.position = { ...val };
        return undefined;
      },
      addClass: (cls: string) => store.get(id)?.classes.add(cls),
      removeClass: (cls: string) => cls.split(" ").forEach((c) => store.get(id)?.classes.delete(c)),
    };
  }

  // Rule 3: an edge cannot outlive either of its endpoints.
  function removeWithEdges(id: string) {
    if (!store.has(id)) return;
    const entry = store.get(id)!;
    store.delete(id);
    if (!entry.isNode) return;
    for (const [edgeId, edge] of [...store.entries()]) {
      if (!edge.isNode && (edge.data.source === id || edge.data.target === id)) {
        store.delete(edgeId);
      }
    }
  }

  function makeCollection(ids: string[]) {
    return {
      forEach: (fn: (ele: any) => void) => ids.forEach((id) => fn(wrapEle(id))),
      map: (fn: (ele: any) => any) => ids.map((id) => fn(wrapEle(id))),
      removeClass: (cls: string) => ids.forEach((id) => wrapEle(id).removeClass(cls)),
      remove: () => ids.forEach(removeWithEdges),
      length: ids.length,
    };
  }

  function idsOf(target: any): string[] {
    if (!target) return [];
    if (typeof target.id === "function") return [target.id()];
    if (Array.isArray(target)) return target.map((t: any) => (typeof t === "string" ? t : t.id()));
    if (typeof target.forEach === "function") {
      const out: string[] = [];
      target.forEach((e: any) => out.push(e.id()));
      return out;
    }
    return [];
  }

  const instance: any = {
    add: vi.fn((elements: any[]) => {
      const added: string[] = [];
      // In array order, one at a time: an element added earlier in the
      // same call has already taken its id, and an edge may name a node
      // added earlier in the same call. Both are what the library does.
      (elements ?? []).forEach((el: any) => {
        const isNode = !("source" in el.data);
        // Rule 1: first writer wins, silently.
        if (store.has(el.data.id)) {
          stats.refusedAdds.push(el.data.id);
          return;
        }
        // Rule 2: an edge with a missing endpoint is not skipped, it throws.
        if (!isNode) {
          for (const end of ["source", "target"] as const) {
            const endId = el.data[end];
            if (!store.has(endId) || !store.get(endId)!.isNode) {
              stats.throws.push(el.data.id);
              throw new Error(
                `Can not create edge \`${el.data.id}\` with nonexistent ${end} \`${endId}\``
              );
            }
          }
        }
        store.set(el.data.id, {
          data: { ...el.data },
          isNode,
          styles: {},
          classes: new Set(),
          position: el.position ? { ...el.position } : { x: 0, y: 0 },
        });
        added.push(el.data.id);
      });
      return makeCollection(added);
    }),
    remove: vi.fn((target: any) => {
      idsOf(target).forEach(removeWithEdges);
    }),
    // Rule 4: always a collection; `length` is 0 when nothing matches.
    getElementById: vi.fn((id: string) => ({ ...wrapEle(id), length: store.has(id) ? 1 : 0 })),
    nodes: vi.fn(() =>
      makeCollection([...store.entries()].filter(([, e]) => e.isNode).map(([id]) => id))
    ),
    edges: vi.fn(() =>
      makeCollection([...store.entries()].filter(([, e]) => !e.isNode).map(([id]) => id))
    ),
    elements: vi.fn(() => makeCollection([...store.keys()])),
    extent: vi.fn(() => ({ x1: 0, y1: 0, x2: 100, y2: 100 })),
    center: vi.fn(),
    autoungrabify: vi.fn(),
    layout: vi.fn(() => ({
      run: vi.fn(),
      on: vi.fn(),
      promiseOn: vi.fn(() => Promise.resolve()),
    })),
    fit: vi.fn(),
    destroy: vi.fn(),
    edgehandles: vi.fn(() => ({
      enableDrawMode: vi.fn(),
      disableDrawMode: vi.fn(),
      destroy: vi.fn(),
      start: vi.fn(),
    })),
    on: vi.fn((event: string, selectorOrHandler: any, maybeHandler?: any) => {
      if (typeof selectorOrHandler === "function") {
        handlersRef.current[event] = selectorOrHandler;
      } else {
        handlersRef.current[`${event}:${selectorOrHandler}`] = maybeHandler;
      }
    }),
  };
  const constructor: any = vi.fn(() => instance);
  constructor.use = vi.fn();
  return {
    mockCytoscapeInstance: instance,
    mockCytoscape: constructor,
    registeredHandlersRef: handlersRef,
    elementStore: store,
    cyStats: stats,
  };
});

vi.mock("cytoscape", () => ({ default: mockCytoscape }));
// Named, not bare `{}`: `cytoscape.use(elk)` and `cytoscape.use(edgehandles)`
// are two calls with two arguments, and two indistinguishable empty objects
// cannot tell them apart -- dropping one registration would still look
// registered. In the browser a missing `elk` is "Layout failed"; a missing
// `edgehandles` is a Connect button that does nothing.
vi.mock("cytoscape-elk", () => ({ default: { extension: "elk" } }));
vi.mock("cytoscape-edgehandles", () => ({ default: { extension: "edgehandles" } }));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { apiFetch, ApiError } from "../api/client";
// The two extension objects the mocks above hand to `cytoscape.use`, so the
// registration test can name which is which.
// @ts-expect-error -- cytoscape-elk ships no bundled type declarations
import elkExtension from "cytoscape-elk";
// @ts-expect-error -- cytoscape-edgehandles ships no bundled type declarations
import edgehandlesExtension from "cytoscape-edgehandles";

// --- v1 fixtures -----------------------------------------------------------
//
// Every `code` equals its `name`, because in schema v1 they are the same
// column (`entity_type.name` / `relationship_type.name`, Task 7's mapping).
// A fixture where they differ cannot catch the "{name} ({code})" template:
// it renders "Unit (unit)", which reads as deliberate. Here it renders
// "unit (unit)", which is the defect.

const GRAPH = {
  // Three levels of nesting: hq > ops > ahmed. One level would pass against
  // code that only ever sets a first-generation parent.
  nodes: [
    { id: "1", type: "unit", label: "hq", parent: null, attributes: {} },
    { id: "2", type: "unit", label: "ops", parent: "1", attributes: {} },
    { id: "3", type: "employee", label: "ahmed", parent: "2", attributes: { code: "E-1", status: "active" } },
  ],
  // `relationship.id = 1` and `entity.id = 1` -- two identity sequences in
  // one cytoscape id space (Ruling 39). The fixture used to pair nodes 1-3
  // with edge 10, which is the only reason the branch's biggest UI bug
  // survived every earlier task. A colliding pair is now the DEFAULT, so
  // the namespacing in `cyEdgeId` is exercised by every component test.
  edges: [{ id: "1", source: "1", target: "2", type: "reports_to", label: "reports_to", attributes: {} }],
  entity_types: [
    // Task 14b: `colour` on the wire. `employee` has one, `unit` does not,
    // so both the stored path and the deterministic fallback are exercised
    // by the same fixture.
    { id: "1", code: "employee", name: "employee", is_abstract: false, colour: "#1f77b4" },
    { id: "2", code: "unit", name: "unit", is_abstract: false, colour: null },
  ],
  relationship_types: [
    {
      id: "5",
      code: "reports_to",
      name: "reports_to",
      is_directed: true,
      source_entity_type: "unit",
      target_entity_type: "unit",
      colour: "#2ca02c",
    },
    {
      id: "6",
      code: "works_for",
      name: "works_for",
      is_directed: true,
      source_entity_type: "employee",
      target_entity_type: "unit",
      colour: null,
    },
  ],
  hierarchies: [{ id: "5", code: "reports_to", name: "reports_to" }],
  attribute_definitions: [],
};

const HIERARCHY_TYPES = {
  items: [
    {
      id: 5,
      domain_id: 1,
      name: "reports_to",
      from_type_id: 2,
      to_type_id: 2,
      cardinality: "one_to_many",
      is_hierarchy: true,
    },
  ],
  total: 1,
};

const ENTITY_TYPES = {
  items: [
    {
      id: 1,
      domain_id: 1,
      name: "employee",
      role: "agent",
      colour: "#1f77b4",
      // `code` and `status` are ordinary v1 attribute names. v0 hid them as
      // "built-in collisions"; v1 has no built-ins for them to collide with.
      attributes: [
        { id: 11, entity_type_id: 1, name: "code", data_type: "text", required: false, unit: null, enum_values: null, default_value: null },
        { id: 12, entity_type_id: 1, name: "status", data_type: "enum", required: false, unit: null, enum_values: ["active", "leave"], default_value: null },
        { id: 13, entity_type_id: 1, name: "grade", data_type: "integer", required: false, unit: null, enum_values: null, default_value: null },
      ],
    },
    {
      id: 2,
      domain_id: 1,
      name: "unit",
      role: "org",
      colour: null,
      // Shares the attribute NAME `code` with employee, which is what makes a
      // value typed for one type able to leak into the other's control.
      attributes: [
        { id: 21, entity_type_id: 2, name: "code", data_type: "text", required: false, unit: null, enum_values: null, default_value: null },
      ],
    },
  ],
  total: 2,
};

// Task 14b: every relationship type in the domain, which is what the TYPES
// view draws (the hierarchy-filtered list above is only the nesting
// picker). Two of them on purpose: `reports_to` is a self-referencing
// hierarchy -- a LOOP on `unit` -- and `works_for` runs employee -> unit.
// With only the loop, a builder that swapped `from` and `to` would still
// look right.
const ALL_RELATIONSHIP_TYPES = {
  items: [
    { ...HIERARCHY_TYPES.items[0], colour: "#2ca02c" },
    {
      id: 6,
      domain_id: 1,
      name: "works_for",
      from_type_id: 1,
      to_type_id: 2,
      cardinality: "many_to_one",
      is_hierarchy: false,
      colour: null,
    },
  ],
  total: 2,
};

type Stub = {
  graph?: unknown;
  graphError?: unknown;
  relationshipTypes?: unknown;
  allRelationshipTypes?: unknown;
  entityTypes?: unknown;
  write?: (path: string, options: RequestInit) => unknown;
};

/**
 * The API double. Two rules, both the opposite of what it used to do.
 *
 * **An unrecognised GET is refused, not answered with `{}`.** A stub that
 * resolves every path teaches nothing: a request to the wrong URL, or to a
 * route that no longer exists, comes back as an empty object and the
 * component renders its empty state, which is usually what the test was
 * checking anyway. Every other page test in this branch rejects; this one
 * now does too.
 *
 * **A write must be opted into, per test.** It used to resolve any
 * non-GET with a plausible-looking entity, so a test could "create a
 * node" without ever saying what the server answered -- and a test that
 * accidentally issued a write nobody meant to issue passed. `stub.write`
 * is now the only way a write succeeds, and it is handed the path and the
 * options so it can answer per route.
 */
function stubApi(stub: Stub = {}) {
  (apiFetch as any).mockImplementation((path: string, options?: RequestInit) => {
    if (options?.method && options.method !== "GET") {
      if (!stub.write) {
        return Promise.reject(
          new Error(
            `unexpected ${options.method} ${path} -- pass \`write\` to stubApi to allow it`
          )
        );
      }
      const answer = stub.write(path, options);
      return answer === undefined
        ? Promise.reject(new Error(`stubApi write handler did not answer ${options.method} ${path}`))
        : answer;
    }
    if (path.startsWith("/api/v1/graph")) {
      return stub.graphError ? Promise.reject(stub.graphError) : Promise.resolve(stub.graph ?? GRAPH);
    }
    if (path.startsWith("/api/v1/relationship-types")) {
      // The hierarchy picker asks with `is_hierarchy=true`; the types view
      // asks for all of them. They are different lists and a fixture that
      // returned one for both could not tell them apart.
      return Promise.resolve(
        path.includes("is_hierarchy")
          ? (stub.relationshipTypes ?? HIERARCHY_TYPES)
          : (stub.allRelationshipTypes ?? ALL_RELATIONSHIP_TYPES)
      );
    }
    if (path.startsWith("/api/v1/entity-types")) {
      return Promise.resolve(stub.entityTypes ?? ENTITY_TYPES);
    }
    return Promise.reject(new Error(`unexpected GET ${path}`));
  });
}

/** The answer the old `stubApi` gave every write for free. Tests that only
 * need "the write succeeded" pass this explicitly, so the fact that a write
 * happened at all is written down in the test. */
const WROTE_OK = () => Promise.resolve({ id: 99, key: "new", label: null, attrs: {} });

function bodyOf(call: any[]): any {
  return JSON.parse((call[1] as RequestInit).body as string);
}

function writeCalls(method: string, prefix: string): any[][] {
  return (apiFetch as any).mock.calls.filter(
    (call: any[]) => typeof call[0] === "string" && call[0].startsWith(prefix) && call[1]?.method === method
  );
}

function client() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function renderWithProviders(props: Partial<ComponentProps<typeof GraphEditor>> = {}) {
  return render(
    <QueryClientProvider client={client()}>
      <MemoryRouter>
        <GraphEditor
          domainId={1}
          mode="objects"
          onModeChange={vi.fn()}
          hierarchyTypeId={null}
          onHierarchyTypeChange={vi.fn()}
          {...props}
        />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

/** Opens the create-node form and picks the entity type named `typeName`. */
async function openCreateNodeFor(typeName: string) {
  fireEvent.click(screen.getByTestId("toggle-create-node"));
  const typeSelect = (await screen.findByLabelText(/^Entity type/)) as HTMLSelectElement;
  await waitFor(() => expect(within(typeSelect).getByText(typeName)).toBeInTheDocument());
  const option = within(typeSelect).getByText(typeName) as HTMLOptionElement;
  fireEvent.change(typeSelect, { target: { value: option.value } });
}

describe("GraphEditor", () => {
  beforeEach(() => {
    mockCytoscape.mockClear();
    mockCytoscapeInstance.add.mockClear();
    mockCytoscapeInstance.remove.mockClear();
    mockCytoscapeInstance.getElementById.mockClear();
    mockCytoscapeInstance.nodes.mockClear();
    mockCytoscapeInstance.edges.mockClear();
    mockCytoscapeInstance.elements.mockClear();
    mockCytoscapeInstance.extent.mockClear();
    mockCytoscapeInstance.center.mockClear();
    mockCytoscapeInstance.autoungrabify.mockClear();
    mockCytoscapeInstance.on.mockClear();
    mockCytoscapeInstance.edgehandles.mockClear();
    mockCytoscapeInstance.layout.mockClear();
    mockCytoscapeInstance.layout.mockImplementation(() => ({
      run: vi.fn(),
      on: vi.fn(),
      promiseOn: vi.fn(() => Promise.resolve()),
    }));
    registeredHandlersRef.current = {};
    elementStore.clear();
    (apiFetch as any).mockReset();
    stubApi();
  });

  // --- the extensions ----------------------------------------------------

  it("registers the layout and edge-handle extensions with cytoscape", () => {
    // Module-scope side effects of importing GraphEditor, so this asserts
    // the import, not a render. Dropping either registration is invisible
    // in the DOM and shows up in the browser as "Layout failed" (elk) or a
    // Connect button that does nothing (edgehandles) -- neither of which
    // any other test in this file can see.
    expect(mockCytoscape.use).toHaveBeenCalledWith(elkExtension);
    expect(mockCytoscape.use).toHaveBeenCalledWith(edgehandlesExtension);
  });

  // --- the v1 read -------------------------------------------------------

  it("reads the graph from the v1 route for its domain, naming the hierarchy type when one is selected", async () => {
    renderWithProviders({ hierarchyTypeId: 5 });
    await waitFor(() => expect(apiFetch).toHaveBeenCalledWith("/api/v1/graph?domain_id=1&hierarchy_type_id=5"));
  });

  it("creates the cytoscape instance empty, then adds nodes and edges via cy.add, nesting every generation", async () => {
    renderWithProviders({ hierarchyTypeId: 5 });
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalledTimes(1));
    expect(mockCytoscape.mock.calls[0][0].elements).toEqual([]);

    await waitFor(() => expect(mockCytoscapeInstance.add).toHaveBeenCalled());
    const added = mockCytoscapeInstance.add.mock.calls.flatMap((call: any[]) => call[0]);
    const nodes = added.filter((el: any) => !("source" in el.data));
    expect(nodes.map((el: any) => el.data.id)).toEqual(expect.arrayContaining(["1", "2", "3"]));
    // Two generations deep, not one.
    expect(nodes.find((el: any) => el.data.id === "2").data.parent).toBe("1");
    expect(nodes.find((el: any) => el.data.id === "3").data.parent).toBe("2");
    expect(added.filter((el: any) => "source" in el.data).map((el: any) => el.data.id)).toEqual([cyEdgeId("1")]);
  });

  // --- the hierarchy picker ---------------------------------------------

  it("lists the domain's hierarchy relationship types, filtered server-side, each named once", async () => {
    renderWithProviders();

    await waitFor(() =>
      expect(apiFetch).toHaveBeenCalledWith("/api/v1/relationship-types?domain_id=1&is_hierarchy=true&limit=500")
    );
    const select = screen.getByTestId("hierarchy-select");
    await waitFor(() => expect(within(select).getByText("reports_to")).toBeInTheDocument());
    // The v0 template rendered `{name} ({code})`, which in v1 is one string twice.
    expect(within(select).queryByText("reports_to (reports_to)")).not.toBeInTheDocument();
  });

  it("does not offer a relationship type that is not a hierarchy", async () => {
    renderWithProviders();
    const select = screen.getByTestId("hierarchy-select");
    await waitFor(() => expect(within(select).getByText("reports_to")).toBeInTheDocument());
    // `works_for` is in the graph payload's relationship_types but is not a
    // hierarchy, so the server-filtered list is what must feed this select.
    expect(within(select).queryByText("works_for")).not.toBeInTheDocument();
  });

  it("reports the chosen hierarchy type as a number, which is what the API takes", async () => {
    const onHierarchyTypeChange = vi.fn();
    renderWithProviders({ onHierarchyTypeChange });
    const select = screen.getByTestId("hierarchy-select");
    await waitFor(() => expect(within(select).getByText("reports_to")).toBeInTheDocument());

    fireEvent.change(select, { target: { value: "5" } });
    expect(onHierarchyTypeChange).toHaveBeenCalledWith(5);

    fireEvent.change(select, { target: { value: "" } });
    expect(onHierarchyTypeChange).toHaveBeenLastCalledWith(null);
  });

  // --- creating a node ---------------------------------------------------

  it("creates an entity through the v1 entities route, with its attrs typed by data_type", async () => {
    // The write is opted into explicitly. Before this round `stubApi`
    // resolved any non-GET for free, so this test asserted the request and
    // nothing about the response -- it would have passed just as happily
    // against a server that refused, with the error banner on screen and
    // nobody looking at it. The success is now asserted too.
    stubApi({ write: WROTE_OK });
    renderWithProviders();
    await openCreateNodeFor("employee");

    fireEvent.change(screen.getByLabelText(/^Key/), { target: { value: "ahmed" } });
    fireEvent.change(screen.getByLabelText(/^Label/), { target: { value: "Ahmed Z" } });
    fireEvent.change(screen.getByTestId("attr-code"), { target: { value: "E-9" } });
    fireEvent.change(screen.getByTestId("attr-status"), { target: { value: "leave" } });
    fireEvent.change(screen.getByTestId("attr-grade"), { target: { value: "7" } });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(writeCalls("POST", "/api/v1/entities")).toHaveLength(1));
    expect(bodyOf(writeCalls("POST", "/api/v1/entities")[0])).toEqual({
      entity_type_id: 1,
      key: "ahmed",
      label: "Ahmed Z",
      // 7 as a JSON number, not "7": entity_validate refuses a string for an
      // `integer` attribute.
      attrs: { code: "E-9", status: "leave", grade: 7 },
    });
    // The form closes only on success, which is what tells this apart from
    // a refusal -- whose request looks identical.
    await waitFor(() => expect(screen.queryByLabelText(/^Key/)).not.toBeInTheDocument());
  });

  it("offers an input for an attribute named code or status, which v1 has no built-in to collide with", async () => {
    renderWithProviders();
    await openCreateNodeFor("employee");

    expect(screen.getByTestId("attr-code")).toBeInTheDocument();
    expect(screen.getByTestId("attr-status")).toBeInTheDocument();
    expect(screen.queryByText(/collides with a built-in field/)).not.toBeInTheDocument();
  });

  it("starts the new type's controls empty when the type is changed, rather than carrying a same-named value across", async () => {
    renderWithProviders();
    await openCreateNodeFor("employee");
    fireEvent.change(screen.getByTestId("attr-code"), { target: { value: "E-9" } });

    const typeSelect = screen.getByLabelText(/^Entity type/) as HTMLSelectElement;
    fireEvent.change(typeSelect, { target: { value: "2" } });

    // unit's own `code`, not employee's value under the same name.
    expect(screen.getByTestId("attr-code")).toHaveValue("");
  });

  it("uses the v1 attribute vocabulary: an enum is a select of its values, an integer a numeric text box", async () => {
    renderWithProviders();
    await openCreateNodeFor("employee");

    const status = screen.getByTestId("attr-status") as HTMLSelectElement;
    expect(status.tagName).toBe("SELECT");
    expect(within(status).getByText("leave")).toBeInTheDocument();
    expect(screen.getByTestId("attr-grade")).toHaveAttribute("inputmode", "numeric");
  });

  it("refuses a decimal in an integer attribute before anything is sent", async () => {
    renderWithProviders();
    await openCreateNodeFor("employee");

    fireEvent.change(screen.getByLabelText(/^Key/), { target: { value: "ahmed" } });
    fireEvent.change(screen.getByTestId("attr-grade"), { target: { value: "2.5" } });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    expect(await screen.findByText(/grade: must be a whole number/)).toBeInTheDocument();
    expect(writeCalls("POST", "/api/v1/entities")).toHaveLength(0);
  });

  it("refuses an empty key before anything is sent", async () => {
    renderWithProviders();
    await openCreateNodeFor("unit");

    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    expect(await screen.findByText(/key is required/i)).toBeInTheDocument();
    expect(writeCalls("POST", "/api/v1/entities")).toHaveLength(0);
  });

  it("places a new node under the chosen parent by creating a relationship of the selected hierarchy type", async () => {
    stubApi({
      write: (path) =>
        path === "/api/v1/entities"
          ? Promise.resolve({ id: 42, entity_type_id: 2, key: "ops", label: null, sort_order: 0, active: true, attrs: {} })
          : Promise.resolve({ id: 77 }),
    });
    renderWithProviders({ hierarchyTypeId: 5 });
    await openCreateNodeFor("unit");

    fireEvent.change(screen.getByLabelText(/^Key/), { target: { value: "ops" } });
    fireEvent.change(screen.getByLabelText(/^Parent/), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(writeCalls("POST", "/api/v1/relationships")).toHaveLength(1));
    // from = parent, to = the new child: the hierarchy reads from_entity as
    // the parent of to_entity.
    expect(bodyOf(writeCalls("POST", "/api/v1/relationships")[0])).toEqual({
      relationship_type_id: 5,
      from_entity_id: 1,
      to_entity_id: 42,
    });
  });

  it("does not create a hierarchy relationship when no parent was chosen", async () => {
    stubApi({ write: WROTE_OK });
    renderWithProviders({ hierarchyTypeId: 5 });
    await openCreateNodeFor("unit");

    fireEvent.change(screen.getByLabelText(/^Key/), { target: { value: "ops" } });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(writeCalls("POST", "/api/v1/entities")).toHaveLength(1));
    // The entity write really succeeded (the form closed), so "no
    // relationship was written" means the code chose not to write one,
    // rather than never reaching that branch.
    await waitFor(() => expect(screen.queryByLabelText(/^Key/)).not.toBeInTheDocument());
    expect(writeCalls("POST", "/api/v1/relationships")).toHaveLength(0);
  });

  it("offers no parent picker when no hierarchy is selected, because there is no relationship type to place it in", async () => {
    renderWithProviders({ hierarchyTypeId: null });
    await openCreateNodeFor("unit");

    expect(screen.queryByLabelText(/^Parent/)).not.toBeInTheDocument();
  });

  // --- creating an edge --------------------------------------------------

  it("opens a type-filtered relationship picker on drag-connect and creates the relationship on confirm", async () => {
    renderWithProviders();
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());

    act(() => registeredHandlersRef.current["ehcomplete"](null, { id: () => "3" }, { id: () => "1" }));

    const picker = await screen.findByTestId("edge-type-picker");
    // employee -> unit: works_for only, and named once.
    expect(within(picker).getByRole("button", { name: "works_for" })).toBeInTheDocument();
    expect(within(picker).queryByRole("button", { name: "works_for (works_for)" })).not.toBeInTheDocument();
    expect(within(picker).queryByRole("button", { name: "reports_to" })).not.toBeInTheDocument();

    fireEvent.click(within(picker).getByRole("button", { name: "works_for" }));

    await waitFor(() => expect(writeCalls("POST", "/api/v1/relationships")).toHaveLength(1));
    expect(bodyOf(writeCalls("POST", "/api/v1/relationships")[0])).toEqual({
      relationship_type_id: 6,
      from_entity_id: 3,
      to_entity_id: 1,
    });
  });

  it("explains the dragged pair when no relationship type allows it", async () => {
    renderWithProviders();
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());

    // unit -> employee: neither type allows that direction.
    act(() => registeredHandlersRef.current["ehcomplete"](null, { id: () => "1" }, { id: () => "3" }));

    expect(await screen.findByText("No relationship type allows unit → employee")).toBeInTheDocument();
  });

  it("shows a cardinality violation's own message, without repeating the relationship type as a field name", async () => {
    stubApi({
      write: () =>
        Promise.reject(
          new ApiError(
            422,
            JSON.stringify({
              detail: [
                {
                  loc: ["body", "works_for"],
                  msg: 'relationship "works_for": target already has a source',
                  kind: "cardinality",
                },
              ],
            })
          )
        ),
    });
    renderWithProviders();
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());
    act(() => registeredHandlersRef.current["ehcomplete"](null, { id: () => "3" }, { id: () => "1" }));
    fireEvent.click(await screen.findByRole("button", { name: "works_for" }));

    const banner = await screen.findByTestId("graph-error");
    // Reworded into the From/To vocabulary the forms use, with the way
    // out -- "source" and "target" appear nowhere else in this UI.
    expect(banner).toHaveTextContent(
      '"works_for" allows each To entity at most one From entity, and this To entity already has one.'
    );
    expect(banner).toHaveTextContent(/Delete the existing "works_for" relationship first/);
    expect(banner.textContent).not.toMatch(/source|target/);
    expect(banner.textContent).not.toContain('works_for: relationship "works_for"');
  });

  it("shows a cycle violation's own message the same way -- the branch is on loc, not on kind", async () => {
    stubApi({
      write: () =>
        Promise.reject(
          new ApiError(
            422,
            JSON.stringify({
              detail: [
                { loc: ["body", "works_for"], msg: 'relationship "works_for": would create a cycle', kind: "cycle" },
              ],
            })
          )
        ),
    });
    renderWithProviders();
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());
    act(() => registeredHandlersRef.current["ehcomplete"](null, { id: () => "3" }, { id: () => "1" }));
    fireEvent.click(await screen.findByRole("button", { name: "works_for" }));

    const banner = await screen.findByTestId("graph-error");
    expect(banner).toHaveTextContent('relationship "works_for": would create a cycle');
  });

  it("dismisses the error banner", async () => {
    stubApi({
      write: () =>
        Promise.reject(
          new ApiError(422, JSON.stringify({ detail: [{ loc: ["body", "works_for"], msg: "nope", kind: "cycle" }] }))
        ),
    });
    renderWithProviders();
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());
    act(() => registeredHandlersRef.current["ehcomplete"](null, { id: () => "3" }, { id: () => "1" }));
    fireEvent.click(await screen.findByRole("button", { name: "works_for" }));
    await screen.findByTestId("graph-error");

    fireEvent.click(screen.getByRole("button", { name: "Dismiss error" }));
    expect(screen.queryByTestId("graph-error")).not.toBeInTheDocument();
  });

  // --- filtering ---------------------------------------------------------

  it("filters by the node's label, the only text a v1 node carries", async () => {
    renderWithProviders({ filter: { selectedTypes: null, search: "ahm", highlightIds: null } });
    await waitFor(() => expect(elementStore.size).toBeGreaterThan(0));

    await waitFor(() => expect(elementStore.get("3")?.styles.display).toBe("element"));
    expect(elementStore.get("1")?.styles.display).toBe("none");
  });

  it("does not match an attribute's value, so a query that only an attribute holds matches nothing", async () => {
    // "E-1" is node 3's `code` ATTRIBUTE. v0 matched it because `code` was a
    // built-in column; in v1 it is an ordinary attribute an entity type may
    // or may not declare, so search is over labels only.
    renderWithProviders({ filter: { selectedTypes: null, search: "E-1", highlightIds: null } });
    await waitFor(() => expect(elementStore.size).toBeGreaterThan(0));

    await waitFor(() => expect(elementStore.get("1")?.styles.display).toBe("none"));
    expect(elementStore.get("3")?.styles.display).toBe("none");
  });

  it("filters by entity type using the type's name", async () => {
    renderWithProviders({ filter: { selectedTypes: ["unit"], search: "", highlightIds: null } });
    await waitFor(() => expect(elementStore.size).toBeGreaterThan(0));

    await waitFor(() => expect(elementStore.get("1")?.styles.display).toBe("element"));
    expect(elementStore.get("3")?.styles.display).toBe("none");
  });

  // --- Task 14c: the expression filter, and how it composes ---------------

  it("hides the nodes an expression does not match, the same way the other filters hide them", async () => {
    // Same `display: none` convention, so the two are indistinguishable to
    // everything downstream (edges, hit-testing, the empty-state overlay).
    renderWithProviders({
      filter: { selectedTypes: null, search: "", highlightIds: null, expressionMatchIds: new Set(["1", "3"]) },
    });
    await waitFor(() => expect(elementStore.size).toBeGreaterThan(0));

    await waitFor(() => expect(elementStore.get("1")?.styles.display).toBe("element"));
    expect(elementStore.get("3")?.styles.display).toBe("element");
    expect(elementStore.get("2")?.styles.display).toBe("none");
  });

  it("filters nothing when there is no expression, so an empty one cannot blank the canvas", async () => {
    renderWithProviders({
      filter: { selectedTypes: null, search: "", highlightIds: null, expressionMatchIds: null },
    });
    await waitFor(() => expect(elementStore.size).toBeGreaterThan(0));

    for (const id of ["1", "2", "3"]) {
      await waitFor(() => expect(elementStore.get(id)?.styles.display).toBe("element"));
    }
  });

  it("ANDs the expression with the type checkboxes: a node must satisfy both", async () => {
    // Nodes 1 and 2 are units; the expression matches 2 and 3. Only node 2
    // is in both, and each of the other two would survive if either filter
    // were being ignored.
    renderWithProviders({
      filter: { selectedTypes: ["unit"], search: "", highlightIds: null, expressionMatchIds: new Set(["2", "3"]) },
    });
    await waitFor(() => expect(elementStore.size).toBeGreaterThan(0));

    await waitFor(() => expect(elementStore.get("2")?.styles.display).toBe("element"));
    expect(elementStore.get("1")?.styles.display).toBe("none");
    expect(elementStore.get("3")?.styles.display).toBe("none");
  });

  it("ANDs the expression with the search box: a node must satisfy both", async () => {
    // "o" matches "ops" (2) only; the expression matches 1 and 2.
    renderWithProviders({
      filter: { selectedTypes: null, search: "op", highlightIds: null, expressionMatchIds: new Set(["1", "2"]) },
    });
    await waitFor(() => expect(elementStore.size).toBeGreaterThan(0));

    await waitFor(() => expect(elementStore.get("2")?.styles.display).toBe("element"));
    expect(elementStore.get("1")?.styles.display).toBe("none");
    expect(elementStore.get("3")?.styles.display).toBe("none");
  });

  it("still highlights the selected node's connections while an expression is filtering", async () => {
    renderWithProviders({
      filter: {
        selectedTypes: null,
        search: "",
        highlightIds: ["1", "2"],
        expressionMatchIds: new Set(["1", "2"]),
      },
    });
    await waitFor(() => expect(elementStore.size).toBeGreaterThan(0));

    await waitFor(() => expect(elementStore.get("1")?.classes.has("graph-highlighted")).toBe(true));
    expect(elementStore.get("3")?.classes.has("graph-dimmed")).toBe(true);
    expect(elementStore.get("3")?.styles.display).toBe("none");
  });

  it("hides an edge whose endpoint an expression hid", async () => {
    // The edge (wire id 1, canvas id `edge:1`) runs node 1 -> node 2.
    // The expression keeps 1 and drops 2.
    renderWithProviders({
      filter: { selectedTypes: null, search: "", highlightIds: null, expressionMatchIds: new Set(["1", "3"]) },
    });
    await waitFor(() => expect(elementStore.size).toBeGreaterThan(0));

    await waitFor(() => expect(elementStore.get(cyEdgeId("1"))?.styles.display).toBe("none"));
  });

  it("announces how many nodes an expression left showing, and says nothing when there is none", async () => {
    const queryClient = client();
    const tree = (filter: ComponentProps<typeof GraphEditor>["filter"]) => (
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <GraphEditor
            domainId={1}
            mode="objects"
            onModeChange={vi.fn()}
            hierarchyTypeId={null}
            onHierarchyTypeChange={vi.fn()}
            filter={filter}
          />
        </MemoryRouter>
      </QueryClientProvider>
    );
    const { rerender } = render(tree({ selectedTypes: null, search: "", highlightIds: null, expressionMatchIds: null }));
    await waitFor(() => expect(elementStore.size).toBeGreaterThan(0));
    expect(screen.getByTestId("graph-live")).not.toHaveTextContent(/condition/i);

    rerender(tree({ selectedTypes: null, search: "", highlightIds: null, expressionMatchIds: new Set(["1"]) }));
    await waitFor(() => expect(screen.getByTestId("graph-live")).toHaveTextContent("1 of 3"));
  });

  // --- behaviour carried over from the v0 editor --------------------------

  it("reports the wire id when an edge is tapped, not the namespaced canvas id", async () => {
    // The property panel looks the selection up in `graph.edges`, and
    // deleting one calls DELETE /api/v1/relationships/{id}. Both need
    // `relationship.id`, so the prefix that keeps the canvas id out of the
    // nodes' id space must not leak past this boundary.
    const onSelectionChange = vi.fn();
    render(
      <QueryClientProvider client={client()}>
        <MemoryRouter><GraphEditor domainId={1} mode="objects" onModeChange={vi.fn()} hierarchyTypeId={null} onHierarchyTypeChange={vi.fn()} onSelectionChange={onSelectionChange} /></MemoryRouter>
      </QueryClientProvider>
    );
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());
    await waitFor(() => expect(elementStore.has(cyEdgeId("1"))).toBe(true));

    act(() =>
      registeredHandlersRef.current["tap:edge"]({
        target: mockCytoscapeInstance.getElementById(cyEdgeId("1")),
      })
    );

    expect(onSelectionChange).toHaveBeenCalledWith({ kind: "edge", id: "1" });
  });

  it("calls the latest onSelectionChange after a rerender, not the one captured at mount", async () => {
    const first = vi.fn();
    const second = vi.fn();
    const queryClient = client();
    const { rerender } = render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter><GraphEditor domainId={1} mode="objects" onModeChange={vi.fn()} hierarchyTypeId={null} onHierarchyTypeChange={vi.fn()} onSelectionChange={first} /></MemoryRouter>
      </QueryClientProvider>
    );
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());

    rerender(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter><GraphEditor domainId={1} mode="objects" onModeChange={vi.fn()} hierarchyTypeId={null} onHierarchyTypeChange={vi.fn()} onSelectionChange={second} /></MemoryRouter>
      </QueryClientProvider>
    );

    act(() => registeredHandlersRef.current["tap:node"]({ target: { id: () => "3" } }));
    expect(second).toHaveBeenCalledWith({ kind: "node", id: "3" });
    expect(first).not.toHaveBeenCalled();
  });

  it("passes ELK options that request hierarchy-safe layout to cy.layout", async () => {
    renderWithProviders();
    await waitFor(() => expect(mockCytoscapeInstance.layout).toHaveBeenCalled());
    const options = mockCytoscapeInstance.layout.mock.calls[0][0];
    expect(options.name).toBe("elk");
    expect(options.elk["elk.hierarchyHandling"]).toBe("INCLUDE_CHILDREN");
  });

  it("toggles edgehandles draw mode and autoungrabify when the Connect button is clicked", async () => {
    renderWithProviders();
    await waitFor(() => expect(mockCytoscapeInstance.edgehandles).toHaveBeenCalled());
    const eh = mockCytoscapeInstance.edgehandles.mock.results[0].value;

    fireEvent.click(screen.getByTestId("toggle-connect"));
    expect(eh.enableDrawMode).toHaveBeenCalled();
    expect(mockCytoscapeInstance.autoungrabify).toHaveBeenLastCalledWith(true);

    fireEvent.click(screen.getByTestId("toggle-connect"));
    expect(eh.disableDrawMode).toHaveBeenCalled();
    expect(mockCytoscapeInstance.autoungrabify).toHaveBeenLastCalledWith(false);
  });

  it("shows Layout failed in the error banner when the layout run rejects instead of throwing", async () => {
    mockCytoscapeInstance.layout.mockImplementation(() => ({
      run: vi.fn(() => Promise.reject(new Error("elk exploded"))),
      on: vi.fn(),
      promiseOn: vi.fn(() => Promise.resolve()),
    }));
    renderWithProviders();
    expect(await screen.findByText("Layout failed")).toBeInTheDocument();
  });

  it("clears the canvas when the graph query errors, so stale nodes aren't left drawn (I-2/M-5)", async () => {
    stubApi({ graphError: new ApiError(500, "boom") });
    renderWithProviders();
    expect(await screen.findByText("Failed to load graph")).toBeInTheDocument();
    expect(elementStore.size).toBe(0);
  });

  it("shows a Retry button next to a failed graph load that re-issues the request (D-4)", async () => {
    stubApi({ graphError: new ApiError(500, "boom") });
    renderWithProviders();
    await screen.findByText("Failed to load graph");
    const graphCalls = () =>
      (apiFetch as any).mock.calls.filter((c: any[]) => String(c[0]).startsWith("/api/v1/graph")).length;
    const before = graphCalls();

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() => expect(graphCalls()).toBeGreaterThan(before));
  });

  it("gives every toolbar control an accessible name and a title, and renders a help line that changes with Connect (F-2)", async () => {
    renderWithProviders();
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());

    expect(screen.getByTestId("hierarchy-select")).toHaveAccessibleName();
    expect(screen.getByRole("button", { name: "Re-run automatic layout" })).toHaveAttribute("title");
    expect(screen.getByRole("button", { name: "Fit the whole graph in view" })).toHaveAttribute("title");
    expect(screen.getByTestId("graph-help")).toHaveTextContent(/Boxes group nodes by hierarchy/);

    fireEvent.click(screen.getByTestId("toggle-connect"));
    expect(screen.getByTestId("graph-help")).toHaveTextContent("Drag from one node to another to connect them.");
  });

  it("gives node labels their own colour (distinct from the node background) and a text outline (F-3)", async () => {
    renderWithProviders();
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());
    const style = mockCytoscape.mock.calls[0][0].style.find((s: any) => s.selector === "node").style;
    expect(style.color).not.toBe(style["background-color"]);
    expect(style["text-outline-width"]).toBeGreaterThan(0);
  });

  it("sizes the canvas container from its flex parent rather than a fixed pixel height (F-4)", async () => {
    renderWithProviders();
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());
    const container = screen.getByTestId("cytoscape-container");
    expect(container.className).toContain("h-full");
    expect(container.className).not.toMatch(/h-\[600px\]/);
  });

  it("shows an empty-state overlay with a 'Create the first node' button when the graph has no nodes", async () => {
    stubApi({ graph: { ...GRAPH, nodes: [], edges: [] } });
    renderWithProviders();
    expect(await screen.findByTestId("graph-empty-state")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Create the first node" }));
    expect(screen.getByTestId("create-node-form")).toBeInTheDocument();
  });

  it("does not show the empty-state overlay once the graph has nodes", async () => {
    renderWithProviders();
    await waitFor(() => expect(mockCytoscapeInstance.add).toHaveBeenCalled());
    expect(screen.queryByTestId("graph-empty-state")).not.toBeInTheDocument();
  });

  it("closes the create-node form on Escape and returns focus to the '+ New Node' trigger (H-7)", async () => {
    renderWithProviders();
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());
    fireEvent.click(screen.getByTestId("toggle-create-node"));
    const form = screen.getByTestId("create-node-form");

    fireEvent.keyDown(form, { key: "Escape" });

    expect(screen.queryByTestId("create-node-form")).not.toBeInTheDocument();
    expect(document.activeElement).toBe(screen.getByTestId("toggle-create-node"));
  });

  it("makes the canvas focusable with an accessible name naming the node count and arrow-key usage (H-1)", async () => {
    renderWithProviders();
    const container = screen.getByTestId("cytoscape-container");
    expect(container).toHaveAttribute("role", "application");
    expect(container).toHaveAttribute("tabindex", "0");
    await waitFor(() => expect(container.getAttribute("aria-label")).toContain("3 nodes"));
    expect(container.getAttribute("aria-label")).toContain("arrow keys");
  });

  it("moves a roving keyboard focus between nodes with ArrowRight/ArrowLeft, ringed by .kb-focus, and centres the viewport (H-1)", async () => {
    renderWithProviders();
    await waitFor(() => expect(elementStore.size).toBeGreaterThan(0));
    elementStore.get("1")!.position = { x: 0, y: 0 };
    elementStore.get("2")!.position = { x: 10, y: 0 };
    elementStore.get("3")!.position = { x: 20, y: 0 };
    const container = screen.getByTestId("cytoscape-container");

    fireEvent.keyDown(container, { key: "ArrowRight" });
    expect(elementStore.get("1")!.classes.has("kb-focus")).toBe(true);
    expect(mockCytoscapeInstance.center).toHaveBeenCalled();

    fireEvent.keyDown(container, { key: "ArrowRight" });
    expect(elementStore.get("1")!.classes.has("kb-focus")).toBe(false);
    expect(elementStore.get("2")!.classes.has("kb-focus")).toBe(true);

    fireEvent.keyDown(container, { key: "ArrowLeft" });
    expect(elementStore.get("1")!.classes.has("kb-focus")).toBe(true);
  });

  it("calls onSelectionChange for the keyboard-focused node when Enter is pressed on the canvas (H-1)", async () => {
    const onSelectionChange = vi.fn();
    renderWithProviders({ onSelectionChange });
    await waitFor(() => expect(elementStore.size).toBeGreaterThan(0));
    const container = screen.getByTestId("cytoscape-container");

    fireEvent.keyDown(container, { key: "ArrowRight" });
    fireEvent.keyDown(container, { key: "Enter" });

    expect(onSelectionChange).toHaveBeenCalledWith({ kind: "node", id: expect.any(String) });
  });

  // --- the keyboard only reaches what is on screen -----------------------
  //
  // With a filter showing 1 of 3 nodes, the arrow keys used to announce the
  // other two by name, the canvas panned to empty space, and Enter opened an
  // editable panel -- with a Delete button -- for a node that was not
  // displayed. `filter.expressionMatchIds` is used here because it is the
  // narrowest of the three filters to state in a test; the type checkboxes
  // and the search box set the same `display` and are covered by the same
  // code path.
  describe("a filtered canvas", () => {
    const only = (...ids: string[]) => ({
      selectedTypes: null,
      search: "",
      highlightIds: null,
      expressionMatchIds: new Set(ids),
    });

    async function renderFiltered(ids: string[]) {
      const view = renderWithProviders({ filter: only(...ids) });
      await waitFor(() => expect(elementStore.size).toBeGreaterThan(0));
      await waitFor(() => expect(elementStore.get("3")!.styles.display).toBeDefined());
      elementStore.get("1")!.position = { x: 0, y: 0 };
      elementStore.get("2")!.position = { x: 10, y: 0 };
      elementStore.get("3")!.position = { x: 20, y: 0 };
      return view;
    }

    it("walks only the nodes that are displayed", async () => {
      await renderFiltered(["3"]);
      const container = screen.getByTestId("cytoscape-container");

      fireEvent.keyDown(container, { key: "ArrowRight" });
      // Node 1 is leftmost and hidden; the selection lands on 3, the only
      // one drawn.
      expect(elementStore.get("1")!.classes.has("kb-focus")).toBe(false);
      expect(elementStore.get("2")!.classes.has("kb-focus")).toBe(false);
      expect(elementStore.get("3")!.classes.has("kb-focus")).toBe(true);

      // And it stays there: there is nowhere else to go.
      fireEvent.keyDown(container, { key: "ArrowRight" });
      fireEvent.keyDown(container, { key: "ArrowLeft" });
      expect(elementStore.get("3")!.classes.has("kb-focus")).toBe(true);
      expect(elementStore.get("1")!.classes.has("kb-focus")).toBe(false);
    });

    it("announces only a displayed node's label", async () => {
      await renderFiltered(["3"]);
      fireEvent.keyDown(screen.getByTestId("cytoscape-container"), { key: "ArrowRight" });
      const live = screen.getByTestId("graph-live");
      await waitFor(() => expect(live).toHaveTextContent("ahmed"));
      expect(live).not.toHaveTextContent("hq");
    });

    it("does not open the property panel for a node that is not displayed", async () => {
      const onSelectionChange = vi.fn();
      const view = renderWithProviders({ onSelectionChange });
      await waitFor(() => expect(elementStore.size).toBeGreaterThan(0));
      const container = screen.getByTestId("cytoscape-container");
      fireEvent.keyDown(container, { key: "ArrowRight" });
      onSelectionChange.mockClear();

      // The filter arrives after the selection did. Enter must not open an
      // editable panel -- it has a Delete button -- for a node the person
      // cannot see.
      view.rerender(
        <QueryClientProvider client={client()}>
          <MemoryRouter>
            <GraphEditor
              domainId={1}
              mode="objects"
              onModeChange={vi.fn()}
              hierarchyTypeId={null}
              onHierarchyTypeChange={vi.fn()}
              onSelectionChange={onSelectionChange}
              filter={only("3")}
            />
          </MemoryRouter>
        </QueryClientProvider>
      );
      await waitFor(() => expect(elementStore.get("1")!.styles.display).toBe("none"));

      fireEvent.keyDown(container, { key: "Enter" });
      expect(onSelectionChange).not.toHaveBeenCalled();
      // The ring goes with it, rather than sitting on something nobody can see.
      await waitFor(() => expect(elementStore.get("1")!.classes.has("kb-focus")).toBe(false));
    });

    it("refuses Enter for a node cytoscape is not drawing, even before the filter props catch up", async () => {
      // Two mechanisms guard this and they guard different frames: the
      // effect above drops the ring when `filter` changes, and Enter itself
      // re-reads cytoscape's `display`, which is what actually decides what
      // is painted. This pins the second -- a keypress landing in the same
      // frame as the filter change, before any effect has run.
      const onSelectionChange = vi.fn();
      renderWithProviders({ onSelectionChange });
      await waitFor(() => expect(elementStore.size).toBeGreaterThan(0));
      elementStore.get("1")!.position = { x: 0, y: 0 };
      elementStore.get("2")!.position = { x: 10, y: 0 };
      elementStore.get("3")!.position = { x: 20, y: 0 };
      const container = screen.getByTestId("cytoscape-container");
      fireEvent.keyDown(container, { key: "ArrowRight" });
      expect(elementStore.get("1")!.classes.has("kb-focus")).toBe(true);
      onSelectionChange.mockClear();

      elementStore.get("1")!.styles.display = "none";
      fireEvent.keyDown(container, { key: "Enter" });
      expect(onSelectionChange).not.toHaveBeenCalled();
    });

    it("names the canvas after what is shown, not after what was loaded", async () => {
      await renderFiltered(["3"]);
      await waitFor(() =>
        expect(screen.getByTestId("cytoscape-container").getAttribute("aria-label")).toContain(
          "1 of 3 nodes shown"
        )
      );
    });

    it("says plainly how many nodes there are when nothing is filtered", async () => {
      // "3 of 3 nodes shown" would make an unfiltered canvas sound filtered.
      renderWithProviders();
      await waitFor(() =>
        expect(screen.getByTestId("cytoscape-container").getAttribute("aria-label")).toContain(
          "3 nodes"
        )
      );
      expect(screen.getByTestId("cytoscape-container").getAttribute("aria-label")).not.toContain(
        "of 3"
      );
    });
  });

  it("returns focus to the toolbar's first control (hierarchy select) when Escape is pressed on the canvas (H-1)", async () => {
    renderWithProviders();
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());

    fireEvent.keyDown(screen.getByTestId("cytoscape-container"), { key: "Escape" });

    expect(document.activeElement).toBe(screen.getByTestId("hierarchy-select"));
  });

  it("moves the roving keyboard focus to a node when focusRequest's token changes (H-1 fix round 1)", async () => {
    const queryClient = client();
    function view(focusRequest: { nodeId: string; token: number } | null) {
      return (
        <QueryClientProvider client={queryClient}>
          <MemoryRouter>
            <GraphEditor
              domainId={1}
              mode="objects"
              onModeChange={vi.fn()}
              hierarchyTypeId={null}
              onHierarchyTypeChange={vi.fn()}
              focusRequest={focusRequest}
            />
          </MemoryRouter>
        </QueryClientProvider>
      );
    }
    const { rerender } = render(view(null));
    await waitFor(() => expect(elementStore.size).toBeGreaterThan(0));

    rerender(view({ nodeId: "3", token: 1 }));
    await waitFor(() => expect(elementStore.get("3")!.classes.has("kb-focus")).toBe(true));

    // The SAME node again: keyed on the token, not the id, so it re-rings and
    // re-announces rather than being treated as no change.
    elementStore.get("3")!.classes.delete("kb-focus");
    rerender(view({ nodeId: "3", token: 2 }));
    await waitFor(() => expect(elementStore.get("3")!.classes.has("kb-focus")).toBe(true));
  });

  it("announces the keyboard-focused node's label in a polite live region (H-1)", async () => {
    renderWithProviders();
    await waitFor(() => expect(elementStore.size).toBeGreaterThan(0));
    elementStore.get("1")!.position = { x: 0, y: 0 };
    elementStore.get("2")!.position = { x: 10, y: 0 };
    elementStore.get("3")!.position = { x: 20, y: 0 };
    const live = screen.getByTestId("graph-live");
    expect(live).toHaveAttribute("aria-live", "polite");

    fireEvent.keyDown(screen.getByTestId("cytoscape-container"), { key: "ArrowRight" });

    await waitFor(() => expect(live).toHaveTextContent("hq"));
  });

  it("applies data changes incrementally without recreating the cytoscape instance", async () => {
    const queryClient = client();
    const { rerender } = render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter><GraphEditor domainId={1} mode="objects" onModeChange={vi.fn()} hierarchyTypeId={null} onHierarchyTypeChange={vi.fn()} /></MemoryRouter>
      </QueryClientProvider>
    );
    await waitFor(() => expect(mockCytoscapeInstance.add).toHaveBeenCalled());
    expect(mockCytoscape).toHaveBeenCalledTimes(1);

    rerender(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <GraphEditor
            domainId={1}
            mode="objects"
            onModeChange={vi.fn()}
            hierarchyTypeId={null}
            onHierarchyTypeChange={vi.fn()}
            filter={{ selectedTypes: null, search: "hq", highlightIds: null }}
          />
        </MemoryRouter>
      </QueryClientProvider>
    );
    expect(mockCytoscape).toHaveBeenCalledTimes(1);
  });

  // --- Task 14b: colours ------------------------------------------------

  describe("type colours", () => {
    it("drives every fill and label from element data, not from a fixed style", () => {
      const style = graphStylesheet();
      const node = style.find((rule: any) => rule.selector === "node") as any;
      // The three that make a user-chosen colour reach the canvas at all.
      expect(node.style["background-color"]).toBe("data(colour)");
      expect(node.style.color).toBe("data(labelColour)");
      // F-3's halo, now in the node's OWN colour: a label drifting over a
      // neighbour still reads because its outline is its own node's fill.
      expect(node.style["text-outline-color"]).toBe("data(colour)");

      const edge = style.find((rule: any) => rule.selector === "edge") as any;
      expect(edge.style["line-color"]).toBe("data(colour)");
      expect(edge.style["target-arrow-color"]).toBe("data(colour)");
      // The types view puts the cardinality on a second line.
      expect(edge.style["text-wrap"]).toBe("wrap");

      const compound = style.find((rule: any) => rule.selector === "$node > node") as any;
      // A compound node is a 15% tint, so the label does NOT sit on the
      // type's colour and the computed foreground would be the wrong
      // answer. Fixed dark-on-white is correct for every tint.
      expect(compound.style["background-opacity"]).toBe(0.15);
      expect(compound.style.color).not.toBe("data(labelColour)");
      expect(compound.style.color).toBe("#0f172a");
    });

    it("writes each node's fill and readable label colour into cytoscape data", () => {
      const cy = mockCytoscapeInstance as unknown as any;
      applyGraphToCy(cy, GRAPH as any);

      // ahmed is an employee, which HAS a colour.
      expect(elementStore.get("3")?.data.colour).toBe("#1f77b4");
      expect(elementStore.get("3")?.data.labelColour).toBe(labelForeground("#1f77b4"));
      // hq is a unit, which has none: the fallback is keyed on the entity
      // TYPE's id (2 on the wire), not on the node or a list position.
      expect(elementStore.get("1")?.data.colour).toBe(fallbackColour("2"));
      expect(elementStore.get("1")?.data.labelColour).toBe(labelForeground(fallbackColour("2")));
      // Two nodes of the same type share a colour; two types do not.
      expect(elementStore.get("2")?.data.colour).toBe(elementStore.get("1")?.data.colour);
      expect(elementStore.get("3")?.data.colour).not.toBe(elementStore.get("1")?.data.colour);
    });

    it("colours an edge from its relationship type", () => {
      const cy = mockCytoscapeInstance as unknown as any;
      applyGraphToCy(cy, GRAPH as any);
      expect(elementStore.get(cyEdgeId("1"))?.data.colour).toBe("#2ca02c");
    });

    it("repaints existing elements when a type's colour changes", () => {
      // The update path, not just the add path: a colour changed in the
      // property panel must reach a node cytoscape already holds.
      const cy = mockCytoscapeInstance as unknown as any;
      applyGraphToCy(cy, GRAPH as any);
      expect(elementStore.get("3")?.data.colour).toBe("#1f77b4");

      const recoloured = {
        ...GRAPH,
        entity_types: GRAPH.entity_types.map((option) =>
          option.name === "employee" ? { ...option, colour: "#b8860b" } : option
        ),
      };
      applyGraphToCy(cy, recoloured as any);
      expect(elementStore.get("3")?.data.colour).toBe("#b8860b");
      // #b8860b is the one palette-ish colour that takes the DARK label, so
      // this also proves the label is recomputed rather than carried over.
      expect(elementStore.get("3")?.data.labelColour).toBe(labelForeground("#b8860b"));
      expect(elementStore.get("3")?.data.labelColour).not.toBe(labelForeground("#1f77b4"));
    });

    it("uses the palette it is given rather than re-deriving one", () => {
      const cy = mockCytoscapeInstance as unknown as any;
      applyGraphToCy(cy, GRAPH as any, {
        nodeFill: { "3": "#000000" },
        nodeLabel: { "3": "#ffffff" },
        edgeColour: {},
      });
      expect(elementStore.get("3")?.data.colour).toBe("#000000");
      expect(elementStore.get("3")?.data.labelColour).toBe("#ffffff");
    });
  });

  // --- Task 14b: the types/objects toggle --------------------------------

  describe("the types/objects toggle", () => {
    it("offers both views and marks the current one pressed", async () => {
      renderWithProviders({ mode: "objects" });
      await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());
      expect(screen.getByTestId("graph-mode-objects")).toHaveAttribute("aria-pressed", "true");
      expect(screen.getByTestId("graph-mode-types")).toHaveAttribute("aria-pressed", "false");
      expect(screen.getByRole("group", { name: "Graph view" })).toBeInTheDocument();
    });

    it("asks its caller to change mode rather than changing it itself", async () => {
      const onModeChange = vi.fn();
      renderWithProviders({ mode: "objects", onModeChange });
      await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());
      fireEvent.click(screen.getByTestId("graph-mode-types"));
      expect(onModeChange).toHaveBeenCalledWith("types");
    });

    it("draws the domain's ENTITY TYPES in the types view, not its entities", async () => {
      // The fixture's two halves differ in both count and name -- 3 entities
      // (hq, ops, ahmed) against 2 entity types (employee, unit) -- so a
      // toggle that drew the same thing twice could not pass this.
      renderWithProviders({ mode: "types" });
      await waitFor(() => expect(elementStore.size).toBeGreaterThan(0));

      const nodes = [...elementStore.values()].filter((entry) => entry.isNode);
      expect(nodes.map((entry) => entry.data.label).sort()).toEqual(["employee", "unit"]);
      expect(nodes.map((entry) => entry.data.id).sort()).toEqual(["type-1", "type-2"]);
      // ... and none of the objects view's nodes survived.
      expect([...elementStore.keys()]).not.toContain("1");
    });

    it("draws relationship types as edges, including a self-referencing loop", async () => {
      renderWithProviders({ mode: "types" });
      await waitFor(() => expect(elementStore.size).toBeGreaterThan(0));
      const edges = [...elementStore.values()]
        .filter((entry) => !entry.isNode)
        .map((entry) => [entry.data.id, entry.data.source, entry.data.target]);
      expect(edges).toEqual(
        expect.arrayContaining([
          // reports_to: unit -> unit, a loop on one node.
          [cyEdgeId("reltype-5"), "type-2", "type-2"],
          // works_for: employee -> unit. A swapped from/to would read
          // [cyEdgeId("reltype-6"), "type-2", "type-1"] here, which the loop alone
          // could never reveal.
          [cyEdgeId("reltype-6"), "type-1", "type-2"],
        ])
      );
      expect(edges).toHaveLength(2);
    });

    it("labels a types edge with its cardinality and hierarchy flag", async () => {
      renderWithProviders({ mode: "types" });
      await waitFor(() => expect(elementStore.size).toBeGreaterThan(0));
      expect(elementStore.get(cyEdgeId("reltype-5"))?.data.label).toBe("reports_to\n1 → n · hierarchy");
      expect(elementStore.get(cyEdgeId("reltype-6"))?.data.label).toBe("works_for\nn → 1");
    });

    it("colours types nodes and edges from the types' own colours", async () => {
      renderWithProviders({ mode: "types" });
      await waitFor(() => expect(elementStore.size).toBeGreaterThan(0));
      expect(elementStore.get("type-1")?.data.colour).toBe("#1f77b4");
      expect(elementStore.get("type-2")?.data.colour).toBe(fallbackColour("2"));
      expect(elementStore.get("type-1")?.data.labelColour).toBe(labelForeground("#1f77b4"));
      expect(elementStore.get(cyEdgeId("reltype-5"))?.data.colour).toBe("#2ca02c");
    });

    it("does not request the objects graph while the types view is showing", async () => {
      renderWithProviders({ mode: "types" });
      await waitFor(() => expect(elementStore.size).toBeGreaterThan(0));
      const graphCalls = (apiFetch as any).mock.calls.filter((call: any[]) =>
        String(call[0]).startsWith("/api/v1/graph")
      );
      expect(graphCalls).toHaveLength(0);
    });

    it("hides the controls that write entities and relationships", async () => {
      renderWithProviders({ mode: "types" });
      await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());
      // All three create or nest ROWS, which a schema has none of.
      expect(screen.queryByTestId("hierarchy-select")).not.toBeInTheDocument();
      expect(screen.queryByTestId("toggle-connect")).not.toBeInTheDocument();
      expect(screen.queryByTestId("toggle-create-node")).not.toBeInTheDocument();
      // ... while the view-independent ones stay.
      expect(screen.getByRole("button", { name: "Re-run automatic layout" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Fit the whole graph in view" })).toBeInTheDocument();
    });

    it("keeps them in the objects view", async () => {
      renderWithProviders({ mode: "objects" });
      await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());
      expect(screen.getByTestId("hierarchy-select")).toBeInTheDocument();
      expect(screen.getByTestId("toggle-connect")).toBeInTheDocument();
      expect(screen.getByTestId("toggle-create-node")).toBeInTheDocument();
    });

    it("announces the change in the live region", async () => {
      const queryClient = client();
      const view = (mode: "objects" | "types") => (
        <QueryClientProvider client={queryClient}>
          <MemoryRouter>
            <GraphEditor
              domainId={1}
              mode={mode}
              onModeChange={vi.fn()}
              hierarchyTypeId={null}
              onHierarchyTypeChange={vi.fn()}
            />
          </MemoryRouter>
        </QueryClientProvider>
      );
      const { rerender } = render(view("objects"));
      await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());
      // Arriving on the page is not a change, and must not announce one.
      expect(screen.getByTestId("graph-live")).toHaveTextContent("");

      rerender(view("types"));
      await waitFor(() => expect(screen.getByTestId("graph-live")).toHaveTextContent(/types view/i));
      rerender(view("objects"));
      await waitFor(() =>
        expect(screen.getByTestId("graph-live")).toHaveTextContent(/objects view/i)
      );
    });

    it("names the view in the canvas's accessible name", async () => {
      renderWithProviders({ mode: "types" });
      await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());
      expect(screen.getByTestId("cytoscape-container")).toHaveAccessibleName(/types view/i);
      expect(screen.getByTestId("cytoscape-container")).toHaveAttribute("role", "application");
    });

    it("still moves the roving keyboard selection with the arrow keys", async () => {
      renderWithProviders({ mode: "types" });
      await waitFor(() => expect(elementStore.size).toBeGreaterThan(0));
      elementStore.get("type-1")!.position = { x: 0, y: 0 };
      elementStore.get("type-2")!.position = { x: 100, y: 0 };

      const canvas = screen.getByTestId("cytoscape-container");
      fireEvent.keyDown(canvas, { key: "ArrowRight" });
      expect(elementStore.get("type-1")?.classes.has("kb-focus")).toBe(true);
      await waitFor(() => expect(screen.getByTestId("graph-live")).toHaveTextContent("employee"));
      fireEvent.keyDown(canvas, { key: "ArrowRight" });
      expect(elementStore.get("type-2")?.classes.has("kb-focus")).toBe(true);
    });

    it("returns focus to the first toolbar control on Escape, which is now the toggle", async () => {
      renderWithProviders({ mode: "types" });
      await waitFor(() => expect(mockCytoscape).toHaveBeenCalled());
      fireEvent.keyDown(screen.getByTestId("cytoscape-container"), { key: "Escape" });
      // The hierarchy select is not rendered here, so the toggle is the
      // first control and Escape must not drop focus onto the body.
      expect(document.activeElement).toBe(screen.getByTestId("graph-mode-objects"));
    });

    it("points an empty schema at the entity types page rather than at a create form", async () => {
      stubApi({ entityTypes: { items: [], total: 0 }, allRelationshipTypes: { items: [], total: 0 } });
      renderWithProviders({ mode: "types" });
      const empty = await screen.findByTestId("graph-empty-state");
      expect(empty).toHaveTextContent(/No entity types/i);
      expect(within(empty).getByRole("link", { name: /Define the first entity type/i })).toHaveAttribute(
        "href",
        "/entity-types"
      );
    });
  });

});

describe("applyGraphToCy", () => {
  const base = {
    entity_types: [],
    relationship_types: [],
    hierarchies: [],
    attribute_definitions: [],
  };

  /**
   * The unit double for `applyGraphToCy`, under the same four rules as the
   * hoisted one above (see its comment for why each is there and what the
   * real library does). It keeps ONE store, because cytoscape keeps one id
   * space; `_nodes` and `_edges` are views over it, so the assertions
   * below still read the way they did while no longer being able to pass
   * on a graph the library would refuse to draw.
   */
  function cyDouble() {
    type Entry = { data: Record<string, any>; isNode: boolean };
    const store = new Map<string, Entry>();
    const added: any[] = [];
    const refused: string[] = [];

    function ele(id: string) {
      return {
        // Rule 4: a collection, and `length` tells the truth.
        length: store.has(id) ? 1 : 0,
        id: () => id,
        isNode: () => store.get(id)?.isNode ?? false,
        data: (arg?: any) => {
          const entry = store.get(id);
          if (!entry) return undefined;
          if (arg === undefined) return { ...entry.data };
          if (typeof arg === "string") return entry.data[arg];
          Object.assign(entry.data, arg);
          return undefined;
        },
        move: (opts: { parent?: string | null }) => {
          const entry = store.get(id);
          if (entry) entry.data.parent = opts.parent ?? undefined;
        },
      };
    }

    // Rule 3: an edge cannot outlive either of its endpoints.
    function removeWithEdges(id: string) {
      const entry = store.get(id);
      if (!entry) return;
      store.delete(id);
      if (!entry.isNode) return;
      for (const [edgeId, edge] of [...store.entries()]) {
        if (!edge.isNode && (edge.data.source === id || edge.data.target === id)) {
          store.delete(edgeId);
        }
      }
    }

    const view = (isNode: boolean) =>
      new Map([...store.entries()].filter(([, e]) => e.isNode === isNode).map(([id, e]) => [id, e.data]));

    return {
      get _nodes() {
        return view(true);
      },
      get _edges() {
        return view(false);
      },
      added,
      refused,
      seedNode: (data: any) => store.set(data.id, { data: { ...data }, isNode: true }),
      nodes: () => ({
        forEach: (fn: any) =>
          [...store.entries()].filter(([, e]) => e.isNode).forEach(([id]) => fn(ele(id))),
      }),
      edges: () => ({
        forEach: (fn: any) =>
          [...store.entries()].filter(([, e]) => !e.isNode).forEach(([id]) => fn(ele(id))),
      }),
      getElementById: (id: string) => ele(id),
      remove: (target: any) => removeWithEdges(target.id()),
      extent: () => ({ x1: 0, y1: 0, x2: 100, y2: 100 }),
      add: (elements: any[]) => {
        elements.forEach((el) => {
          const isNode = !("source" in el.data);
          // Rule 1: first writer wins, silently.
          if (store.has(el.data.id)) {
            refused.push(el.data.id);
            return;
          }
          // Rule 2: a dangling edge throws out of add(), aborting the batch.
          if (!isNode) {
            for (const end of ["source", "target"] as const) {
              const endId = el.data[end];
              if (!store.has(endId) || !store.get(endId)!.isNode) {
                throw new Error(
                  `Can not create edge \`${el.data.id}\` with nonexistent ${end} \`${endId}\``
                );
              }
            }
          }
          added.push(el);
          store.set(el.data.id, { data: { ...el.data }, isNode });
        });
      },
    } as any;
  }

  it("returns structureChanged: false when only a label changed", () => {
    const cy = cyDouble();
    cy.seedNode({ id: "1", label: "old", type: "unit" });
    const result = applyGraphToCy(cy, {
      ...base,
      nodes: [{ id: "1", type: "unit", label: "new", parent: null, attributes: {} }],
      edges: [],
    } as any);
    expect(result.structureChanged).toBe(false);
    expect(cy._nodes.get("1").label).toBe("new");
  });

  it("returns structureChanged: true when a node is added", () => {
    const cy = cyDouble();
    const result = applyGraphToCy(cy, {
      ...base,
      nodes: [{ id: "1", type: "unit", label: "hq", parent: null, attributes: {} }],
      edges: [],
    } as any);
    expect(result.structureChanged).toBe(true);
  });

  it("re-parents an existing node at every generation when the hierarchy selection changes", () => {
    const cy = cyDouble();
    cy.seedNode({ id: "1", label: "hq", type: "unit" });
    cy.seedNode({ id: "2", label: "ops", type: "unit" });
    cy.seedNode({ id: "3", label: "ahmed", type: "employee" });

    const result = applyGraphToCy(cy, {
      ...base,
      nodes: [
        { id: "1", type: "unit", label: "hq", parent: null, attributes: {} },
        { id: "2", type: "unit", label: "ops", parent: "1", attributes: {} },
        { id: "3", type: "employee", label: "ahmed", parent: "2", attributes: {} },
      ],
      edges: [],
    } as any);

    expect(result.structureChanged).toBe(true);
    expect(cy._nodes.get("2").parent).toBe("1");
    // The grandchild too: code that only re-parents the first generation
    // leaves this undefined.
    expect(cy._nodes.get("3").parent).toBe("2");
  });

  it("returns structureChanged: false when only an edge is added", () => {
    const cy = cyDouble();
    cy.seedNode({ id: "1", label: "hq", type: "unit" });
    cy.seedNode({ id: "2", label: "ops", type: "unit" });
    const result = applyGraphToCy(cy, {
      ...base,
      nodes: [
        { id: "1", type: "unit", label: "hq", parent: null, attributes: {} },
        { id: "2", type: "unit", label: "ops", parent: null, attributes: {} },
      ],
      edges: [{ id: "10", source: "1", target: "2", type: "reports_to", label: "reports_to", attributes: {} }],
    } as any);
    expect(result.structureChanged).toBe(false);
    expect(cy._edges.has(cyEdgeId("10"))).toBe(true);
  });

  // ---------------------------------------------------------------------
  // Cytoscape keeps nodes and edges in ONE id space. In schema v1 the
  // objects view's node ids are `entity.id` and its edge ids are
  // `relationship.id` -- two independent bigint identity sequences, so in
  // any database seeded from empty they overlap from the very first row.
  //
  // Real cytoscape answers `cy.add()` for an id that already exists by
  // silently doing nothing: no throw, no console message, the element just
  // never appears. Measured on the seeded demo (23 entities, 10
  // relationships), the canvas drew 23 nodes and **0** edges.
  //
  // `cyDouble` used to keep nodes and edges in two separate maps, which is
  // exactly why no earlier test could see this -- it was more permissive
  // than the thing it stood for. It now keeps one, so the rule is in the
  // double rather than in a wrapper that only three tests remembered to
  // use.
  // ---------------------------------------------------------------------

  const COLLIDING = {
    ...base,
    nodes: [
      { id: "1", type: "unit", label: "Head Office", parent: null, attributes: {} },
      { id: "2", type: "unit", label: "North Region", parent: null, attributes: {} },
    ],
    // `relationship.id = 1`, the same number as `entity.id = 1`.
    edges: [
      { id: "1", source: "1", target: "2", type: "reports_to", label: "reports_to", attributes: {} },
    ],
  };

  it("draws an edge whose id collides with a node's id", () => {
    const cy = cyDouble();
    applyGraphToCy(cy, COLLIDING as any);

    expect(cy.refused).toEqual([]);
    expect(cy._nodes.size).toBe(2);
    expect(cy._edges.size).toBe(1);
  });

  it("namespaces edge element ids away from node element ids", () => {
    const cy = cyDouble();
    applyGraphToCy(cy, COLLIDING as any);

    const edgeIds = [...cy._edges.keys()];
    const nodeIds = [...cy._nodes.keys()];
    expect(edgeIds).toEqual([cyEdgeId("1")]);
    expect(nodeIds).not.toContain(cyEdgeId("1"));
    // The wire id survives on the element, because that is what selection,
    // the property panel and DELETE /api/v1/relationships/{id} need.
    expect(cy._edges.get(cyEdgeId("1")).graphId).toBe("1");
  });

  it("updates, rather than duplicates, a colliding edge on a redraw", () => {
    const cy = cyDouble();
    applyGraphToCy(cy, COLLIDING as any);
    applyGraphToCy(
      cy,
      { ...COLLIDING, edges: [{ ...COLLIDING.edges[0], label: "renamed" }] } as any
    );

    expect(cy._edges.size).toBe(1);
    expect(cy._edges.get(cyEdgeId("1")).label).toBe("renamed");
    // Not removed and re-added: a diff that failed to recognise the
    // existing element would show up here as a refusal.
    expect(cy.refused).toEqual([]);
  });

  it("removes a colliding edge that is no longer in the payload", () => {
    const cy = cyDouble();
    applyGraphToCy(cy, COLLIDING as any);
    applyGraphToCy(cy, { ...COLLIDING, edges: [] } as any);

    expect(cy._edges.size).toBe(0);
    expect(cy._nodes.size).toBe(2);
  });

  it("gives every newly-added node its own position object, even though their coordinates are equal (M-2)", () => {
    const cy = cyDouble();
    applyGraphToCy(cy, {
      ...base,
      nodes: [
        { id: "1", type: "unit", label: "hq", parent: null, attributes: {} },
        { id: "2", type: "unit", label: "ops", parent: null, attributes: {} },
      ],
      edges: [],
    } as any);
    const positions = cy.added.filter((el: any) => el.position).map((el: any) => el.position);
    expect(positions).toHaveLength(2);
    expect(positions[0]).not.toBe(positions[1]);
    expect(positions[0]).toEqual(positions[1]);
  });

  // --- the dangling-edge guard (GraphEditor.tsx) -------------------------
  //
  // Until this round the one test here asserted `cy._edges.has("10")` is
  // false -- which the Ruling 39 fix made true whether or not the guard
  // ran, because a drawn edge is stored under `edge:10`, never "10". The
  // double could not throw either, so deleting the guard entirely left
  // all 1108 tests passing. Both halves are fixed: the double throws the
  // way cytoscape does, and these three tests name the canvas id.
  describe("an edge whose endpoint is missing", () => {
    const dangling = {
      ...base,
      nodes: [{ id: "1", type: "unit", label: "hq", parent: null, attributes: {} }],
      edges: [{ id: "10", source: "1", target: "999", type: "reports_to", label: "reports_to", attributes: {} }],
    };

    it("is skipped, and does not throw out of the update", () => {
      const cy = cyDouble();
      // Without the guard this is the real library's synchronous
      // "Can not create edge `edge:10` with nonexistent target `999`".
      expect(() => applyGraphToCy(cy, dangling as any)).not.toThrow();
      expect(cy._edges.has(cyEdgeId("10"))).toBe(false);
      expect(cy._edges.size).toBe(0);
    });

    it("does not take the rest of the batch down with it", () => {
      // The failure the guard actually prevents: one bad edge aborting
      // `cy.add()` means the NODES in the same call never appear either,
      // and the canvas stays empty with nothing on screen to say why.
      const cy = cyDouble();
      applyGraphToCy(cy, {
        ...base,
        nodes: [
          { id: "1", type: "unit", label: "hq", parent: null, attributes: {} },
          { id: "2", type: "unit", label: "ops", parent: null, attributes: {} },
        ],
        edges: [
          { id: "10", source: "1", target: "999", type: "reports_to", label: "x", attributes: {} },
          { id: "11", source: "1", target: "2", type: "reports_to", label: "good", attributes: {} },
        ],
      } as any);
      expect([...cy._nodes.keys()].sort()).toEqual(["1", "2"]);
      expect([...cy._edges.keys()]).toEqual([cyEdgeId("11")]);
    });

    it("says so on the console rather than disappearing silently", () => {
      const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
      applyGraphToCy(cyDouble(), dangling as any);
      expect(warn).toHaveBeenCalledWith(expect.stringContaining("skipped 1 edge"));
      warn.mockRestore();
    });
  });

  // --- the double matches the library ------------------------------------
  //
  // Four rules, each verified against cytoscape@3.34.3. They are asserted
  // here because a double nobody checks drifts, and every drift makes a
  // real defect unreachable -- which is exactly how Ruling 39's bug
  // survived. See the comment on the hoisted double at the top of the file.
  describe("the cytoscape double", () => {
    it("drops a duplicate id silently, first writer wins", () => {
      const cy = cyDouble();
      cy.add([{ data: { id: "1", label: "first" } }]);
      cy.add([{ data: { id: "1", label: "second" } }]);
      expect(cy._nodes.get("1").label).toBe("first");
      expect(cy.refused).toEqual(["1"]);
    });

    it("throws for an edge whose endpoint does not exist", () => {
      const cy = cyDouble();
      cy.add([{ data: { id: "1" } }]);
      expect(() => cy.add([{ data: { id: "e", source: "1", target: "nope" } }])).toThrow(
        /nonexistent target/
      );
    });

    it("accepts an edge naming a node added earlier in the same call", () => {
      const cy = cyDouble();
      expect(() =>
        cy.add([
          { data: { id: "1" } },
          { data: { id: "2" } },
          { data: { id: "e", source: "1", target: "2" } },
        ])
      ).not.toThrow();
      expect(cy._edges.has("e")).toBe(true);
    });

    it("removes a node's edges with it", () => {
      const cy = cyDouble();
      cy.add([
        { data: { id: "1" } },
        { data: { id: "2" } },
        { data: { id: "e", source: "1", target: "2" } },
      ]);
      cy.remove(cy.getElementById("1"));
      expect(cy._nodes.has("1")).toBe(false);
      expect(cy._edges.has("e")).toBe(false);
    });

    it("answers getElementById for a missing id with an empty collection", () => {
      const cy = cyDouble();
      expect(cy.getElementById("nope").length).toBe(0);
      cy.add([{ data: { id: "1" } }]);
      expect(cy.getElementById("1").length).toBe(1);
    });
  });

  it("removes a node that is no longer in the graph", () => {
    const cy = cyDouble();
    cy.seedNode({ id: "1", label: "hq", type: "unit" });
    const result = applyGraphToCy(cy, { ...base, nodes: [], edges: [] } as any);
    expect(result.structureChanged).toBe(true);
    expect(cy._nodes.has("1")).toBe(false);
  });
});

describe("positionsAreDegenerate", () => {
  it("returns false for fewer than 2 positions", () => {
    expect(positionsAreDegenerate([])).toBe(false);
    expect(positionsAreDegenerate([{ x: 1, y: 1 }])).toBe(false);
  });

  it("returns false when positions are meaningfully spread out", () => {
    expect(
      positionsAreDegenerate([
        { x: 0, y: 0 },
        { x: 50, y: 20 },
      ])
    ).toBe(false);
  });

  it("returns true when every position is within 1px of every other", () => {
    expect(
      positionsAreDegenerate([
        { x: 10, y: 10 },
        { x: 10.2, y: 10.1 },
        { x: 10.4, y: 9.9 },
      ])
    ).toBe(true);
  });
});
