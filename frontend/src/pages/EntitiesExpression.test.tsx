import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useSearchParams } from "react-router-dom";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import Entities from "./Entities";
import { ToastProvider } from "../components/ToastProvider";
import { DOMAIN_STORAGE_KEY } from "../hooks/useDomain";
import { editorQueryClient } from "../test/me";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { ApiError, apiFetch } from "../api/client";

// The page loads the expression builder lazily. Under the full suite, on
// every core, fetching that chunk inside a test could take longer than
// any wait in it; loaded once here, `lazy()` finds it already there.
beforeAll(async () => {
  await import("../expressions/ExpressionBuilder");
}, 30000);

const mockFetch = apiFetch as unknown as ReturnType<typeof vi.fn>;

/**
 * The Entities page's condition builder (Task 14d).
 *
 * The thing worth testing here is not that a builder renders -- Task 14c's
 * own tests do that -- but the three decisions this page makes about it:
 * what it sends, what it does NOT send, and what it does with a refusal
 * that came back from a compiler it cannot see.
 */

const TYPES = {
  items: [
    {
      id: 5,
      domain_id: 7,
      name: "employee",
      role: "agent",
      colour: null,
      attributes: [
        { id: 11, entity_type_id: 5, name: "grade", data_type: "integer", required: false, unit: null, enum_values: null, default_value: null },
        { id: 12, entity_type_id: 5, name: "note", data_type: "text", required: false, unit: null, enum_values: null, default_value: null },
      ],
    },
    { id: 9, domain_id: 7, name: "shift", role: "time", colour: null, attributes: [] },
  ],
  total: 2,
};

const RELATIONSHIP_TYPES = {
  items: [
    { id: 3, domain_id: 7, name: "covers", from_type_id: 5, to_type_id: 9, cardinality: "many_to_many", is_hierarchy: false, colour: null },
  ],
  total: 1,
};

const ENTITIES = {
  items: [
    { id: 42, entity_type_id: 5, key: "zoe", label: "Zoe", sort_order: 1, active: true, attrs: { grade: 3 } },
  ],
  total: 1,
};

const GRADE = "attr:5:grade";

const GRADE_EQUALS_FOUR = {
  version: 1,
  query: { combinator: "and", rules: [{ field: GRADE, operator: "=", value: 4 }] },
};

function paths(): string[] {
  return mockFetch.mock.calls.map((call) => call[0] as string);
}

/** The documents sent, decoded from the `expr` parameter of each entity
 * list request that carried one. */
function sentExpressions(): unknown[] {
  return paths()
    .filter((path) => path.startsWith("/api/v1/entities?") && path.includes("expr="))
    .map((path) => JSON.parse(decodeURIComponent(new URLSearchParams(path.split("?")[1]).get("expr") as string)));
}

function serve(over: Record<string, unknown> = {}) {
  mockFetch.mockImplementation((path: string) => {
    for (const [prefix, value] of Object.entries(over)) {
      if (path.startsWith(prefix)) {
        return value instanceof Error ? Promise.reject(value) : Promise.resolve(value);
      }
    }
    if (path.startsWith("/api/v1/entity-types")) return Promise.resolve(TYPES);
    if (path.startsWith("/api/v1/relationship-types")) return Promise.resolve(RELATIONSHIP_TYPES);
    if (path.startsWith("/api/v1/entities")) return Promise.resolve(ENTITIES);
    return Promise.reject(new Error(`unexpected ${path}`));
  });
}

/** An expression request that fails the way the server fails one: FastAPI's
 * list shape, `loc` under ["query","expr"], pointing into the document. */
function refusal(loc: (string | number)[], msg: string) {
  return new ApiError(422, JSON.stringify({ detail: [{ type: "value_error", loc, msg }] }));
}

function renderPage(entry = "/entities") {
  const queryClient = editorQueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <MemoryRouter initialEntries={[entry]}>
          <Routes>
            <Route
              path="/entities"
              element={
                <>
                  <SearchSpy />
                  <Entities />
                </>
              }
            />
          </Routes>
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}

function SearchSpy() {
  const [params] = useSearchParams();
  return <span data-testid="entities-search">{params.toString()}</span>;
}

async function openPanel() {
  const toggle = await screen.findByTestId("entities-conditions-toggle");
  if (toggle.getAttribute("aria-expanded") !== "true") {
    fireEvent.click(toggle);
  }
  // The builder is lazy, so it arrives a tick later.
  return screen.findByTestId("expression-builder");
}

beforeEach(() => {
  mockFetch.mockReset();
  localStorage.setItem(DOMAIN_STORAGE_KEY, "7");
});

describe("Entities: the conditions panel", () => {
  it("starts closed, and the builder is not mounted until it is opened", async () => {
    serve();
    renderPage();
    const toggle = await screen.findByTestId("entities-conditions-toggle");
    expect(toggle).toHaveTextContent("No conditions");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("expression-builder")).not.toBeInTheDocument();

    await openPanel();
    expect(screen.getByTestId("entities-conditions-toggle")).toHaveAttribute("aria-expanded", "true");
  });

  it("offers only the selected type's attributes, so a rule cannot name another type's", async () => {
    serve();
    renderPage();
    await openPanel();
    fireEvent.click(screen.getByTestId("expression-add-rule"));
    const groups = Array.from(
      screen.getAllByTestId("expression-field")[0].querySelectorAll("optgroup")
    ).map((g) => g.getAttribute("label"));
    expect(groups).toContain("employee");
    // `shift` is a type of this domain, and deliberately not on offer: the
    // list is one type's, so a rule about another would match nothing.
    expect(groups).not.toContain("shift");
  });

  it("offers count() over the domain's relationship types", async () => {
    serve();
    renderPage();
    await openPanel();
    fireEvent.click(screen.getByTestId("expression-add-rule"));
    const labels = Array.from(
      screen.getAllByTestId("expression-field")[0].querySelectorAll("option")
    ).map((o) => o.textContent);
    expect(labels).toContain("count(covers, outgoing)");
  });

  it("counts the conditions on the button", async () => {
    serve();
    renderPage();
    await openPanel();
    fireEvent.click(screen.getByTestId("expression-add-rule"));
    await waitFor(() =>
      expect(screen.getByTestId("entities-conditions-toggle")).toHaveTextContent("1 condition")
    );
  });
});

describe("Entities: what reaches the server", () => {
  it("sends a valid condition as the expr parameter", async () => {
    serve();
    renderPage();
    await openPanel();
    fireEvent.click(screen.getByTestId("expression-add-rule"));
    fireEvent.change(screen.getAllByTestId("expression-field")[0], { target: { value: GRADE } });
    fireEvent.change(screen.getAllByTestId("expression-value")[0], { target: { value: "4" } });

    await waitFor(() => expect(sentExpressions()).toHaveLength(1));
    expect(sentExpressions()[0]).toEqual({
      version: 1,
      query: { combinator: "and", rules: [{ field: GRADE, operator: "=", value: 4 }] },
    });
  });

  it("does not send an invalid condition", async () => {
    serve();
    renderPage();
    await openPanel();
    fireEvent.click(screen.getByTestId("expression-add-rule"));
    fireEvent.change(screen.getAllByTestId("expression-field")[0], { target: { value: GRADE } });
    // "1x" is not a whole number; the editor keeps what was typed so the
    // decimal point survives, and the validator says why.
    fireEvent.change(screen.getAllByTestId("expression-value")[0], { target: { value: "1x" } });

    expect(await screen.findByTestId("expression-problems")).toHaveTextContent(/whole number/i);
    await new Promise((resolve) => setTimeout(resolve, 700));
    expect(sentExpressions()).toEqual([]);
  });

  it("does not send a condition nobody has touched yet", async () => {
    // The reported defect: "+ Condition" produces a complete, structurally
    // valid rule, so it used to be sent the moment the button was pressed
    // -- the list went from its rows to none before a character was typed.
    // The list request still goes out; it simply carries no `expr`.
    serve();
    renderPage();
    await openPanel();
    fireEvent.click(screen.getByTestId("expression-add-rule"));
    await waitFor(() =>
      expect(screen.getByTestId("entities-conditions-toggle")).toHaveTextContent("1 condition")
    );
    await new Promise((resolve) => setTimeout(resolve, 700));
    expect(sentExpressions()).toEqual([]);
    expect(paths().some((p) => p.startsWith("/api/v1/entities?"))).toBe(true);
    // And no error is shown for it either: an untouched condition is not a
    // mistake, it is a row waiting to be filled in.
    expect(screen.queryByTestId("expression-problems")).not.toBeInTheDocument();
  });

  it("starts a new condition on the key column, not on a generated call", async () => {
    // It used to start on `abs(<the alphabetically first numeric
    // attribute>)`, which is neither something the person chose nor
    // something most people know exists.
    serve();
    renderPage();
    await openPanel();
    fireEvent.click(screen.getByTestId("expression-add-rule"));
    expect((screen.getAllByTestId("expression-field")[0] as HTMLSelectElement).value).toBe("col:key");
  });

  it("sends the condition as soon as one of its controls is changed, even the operator alone", async () => {
    serve();
    renderPage();
    await openPanel();
    fireEvent.click(screen.getByTestId("expression-add-rule"));
    fireEvent.change(screen.getAllByTestId("expression-operator")[0], { target: { value: "contains" } });

    await waitFor(() => expect(sentExpressions()).toHaveLength(1));
    expect(sentExpressions()[0]).toEqual({
      version: 1,
      query: { combinator: "and", rules: [{ field: "col:key", operator: "contains", value: "" }] },
    });
  });

  it("stops sending a condition that is edited back to exactly its starting state", async () => {
    serve();
    renderPage();
    await openPanel();
    fireEvent.click(screen.getByTestId("expression-add-rule"));
    fireEvent.change(screen.getAllByTestId("expression-value")[0], { target: { value: "zo" } });
    await waitFor(() => expect(sentExpressions()).toHaveLength(1));

    fireEvent.change(screen.getAllByTestId("expression-value")[0], { target: { value: "" } });
    const before = sentExpressions().length;
    await new Promise((resolve) => setTimeout(resolve, 700));
    // `key = ""` matches nothing and was never asked for; back to no filter.
    expect(sentExpressions()).toHaveLength(before);
    expect(paths().filter((p) => p.startsWith("/api/v1/entities?")).at(-1)).not.toContain("expr=");
  });

  it("does not send an empty condition set", async () => {
    serve();
    renderPage();
    await openPanel();
    await new Promise((resolve) => setTimeout(resolve, 700));
    expect(sentExpressions()).toEqual([]);
    expect(paths().some((p) => p.startsWith("/api/v1/entities?"))).toBe(true);
  });

  it("keeps the search box working alongside the conditions", async () => {
    serve();
    renderPage();
    await openPanel();
    fireEvent.click(screen.getByTestId("expression-add-rule"));
    fireEvent.change(screen.getAllByTestId("expression-field")[0], { target: { value: GRADE } });
    await waitFor(() => expect(sentExpressions()).toHaveLength(1));

    fireEvent.change(await screen.findByLabelText(/^Search/), { target: { value: "zo" } });
    fireEvent.click(screen.getByRole("button", { name: /^Search$/ }));
    await waitFor(() =>
      expect(paths().some((p) => p.includes("q=zo") && p.includes("expr="))).toBe(true)
    );
  });

  it("clears the conditions, and stops sending them", async () => {
    serve();
    renderPage();
    await openPanel();
    fireEvent.click(screen.getByTestId("expression-add-rule"));
    fireEvent.change(screen.getAllByTestId("expression-field")[0], { target: { value: GRADE } });
    await waitFor(() => expect(sentExpressions()).toHaveLength(1));

    fireEvent.click(screen.getByTestId("entities-conditions-clear"));
    await waitFor(() =>
      expect(screen.getByTestId("entities-conditions-toggle")).toHaveTextContent("No conditions")
    );
    const before = sentExpressions().length;
    await new Promise((resolve) => setTimeout(resolve, 700));
    expect(sentExpressions()).toHaveLength(before);
  });
});

describe("Entities: a refusal from the server", () => {
  const REFUSED = {
    "/api/v1/entities?": refusal(
      ["query", "expr", "query", "rules", 0, "value"],
      '"z" is not one of a, b, c.'
    ),
  };

  it("shows the server's message against the condition its loc names", async () => {
    serve(REFUSED);
    renderPage();
    await openPanel();
    fireEvent.click(screen.getByTestId("expression-add-rule"));
    fireEvent.change(screen.getAllByTestId("expression-field")[0], { target: { value: GRADE } });

    const problems = await screen.findByTestId("expression-problems");
    // Condition 1 is `rules[0]`; the message is the server's, verbatim.
    expect(problems).toHaveTextContent('Condition 1: "z" is not one of a, b, c.');
  });

  it("points at a nested condition when the loc does", async () => {
    serve({
      "/api/v1/entities?": refusal(
        ["query", "expr", "query", "rules", 1, "rules", 0, "operator"],
        "nope",
      ),
    });
    renderPage();
    await openPanel();
    fireEvent.click(screen.getByTestId("expression-add-rule"));
    fireEvent.change(screen.getAllByTestId("expression-field")[0], { target: { value: GRADE } });
    const problems = await screen.findByTestId("expression-problems");
    // 2.1 -- read from `loc`, not from a `kind` (Ruling 30).
    expect(problems).toHaveTextContent("Condition 2.1: nope");
  });

  it("opens the panel by itself, because a refusal nobody can see cannot be fixed", async () => {
    serve();
    renderPage();
    await openPanel();
    fireEvent.click(screen.getByTestId("expression-add-rule"));
    fireEvent.change(screen.getAllByTestId("expression-field")[0], { target: { value: GRADE } });
    await waitFor(() => expect(sentExpressions()).toHaveLength(1));

    // Close it, then make the next request fail.
    fireEvent.click(screen.getByTestId("entities-conditions-toggle"));
    expect(screen.queryByTestId("expression-builder")).not.toBeInTheDocument();
    serve(REFUSED);
    fireEvent.change(screen.getByLabelText(/^Search/), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: /^Search$/ }));

    expect(await screen.findByTestId("expression-builder")).toBeInTheDocument();
    expect(screen.getByTestId("expression-problems")).toHaveTextContent("is not one of");
  });

  it("does not show a 422 as a generic list failure with a retry button", async () => {
    serve(REFUSED);
    renderPage();
    await openPanel();
    fireEvent.click(screen.getByTestId("expression-add-rule"));
    fireEvent.change(screen.getAllByTestId("expression-field")[0], { target: { value: GRADE } });
    // The suite's own wait (src/test/setup.ts): the expression builder is
    // lazily loaded, and a shorter one timed out under the full suite.
    expect(await screen.findByTestId("entities-expression-refused")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();
  });

  it("still shows a retry for a failure that is not about the expression", async () => {
    serve({ "/api/v1/entities": new ApiError(500, JSON.stringify({ detail: "boom" })) });
    renderPage();
    expect(await screen.findByRole("button", { name: /retry/i })).toBeInTheDocument();
    expect(screen.queryByTestId("entities-expression-refused")).not.toBeInTheDocument();
  });
});

describe("Entities: a filtered list is a link", () => {
  it("reads the condition from the URL and sends it, with the panel already open", async () => {
    serve();
    renderPage(`/entities?type=5&expr=${encodeURIComponent(JSON.stringify(GRADE_EQUALS_FOUR))}`);

    await waitFor(() => expect(sentExpressions()[0]).toEqual(GRADE_EQUALS_FOUR));
    expect(screen.getByTestId("entities-conditions-toggle")).toHaveAttribute("aria-expanded", "true");
    expect(await screen.findByTestId("expression-builder")).toBeInTheDocument();
  });

  it("writes a valid condition into the URL so the list can be shared", async () => {
    serve();
    renderPage();
    await openPanel();
    fireEvent.click(screen.getByTestId("expression-add-rule"));
    fireEvent.change(screen.getAllByTestId("expression-field")[0], { target: { value: GRADE } });
    fireEvent.change(screen.getAllByTestId("expression-value")[0], { target: { value: "4" } });

    await waitFor(() => {
      const params = new URLSearchParams(screen.getByTestId("entities-search").textContent ?? "");
      expect(JSON.parse(params.get("expr") ?? "null")).toEqual(GRADE_EQUALS_FOUR);
    });
  });

  it("drops the condition from the URL when the conditions are cleared", async () => {
    serve();
    renderPage(`/entities?type=5&expr=${encodeURIComponent(JSON.stringify(GRADE_EQUALS_FOUR))}`);
    await screen.findByTestId("expression-builder");

    fireEvent.click(screen.getByTestId("entities-conditions-clear"));
    await waitFor(() => {
      const params = new URLSearchParams(screen.getByTestId("entities-search").textContent ?? "");
      expect(params.get("expr")).toBeNull();
    });
  });

  it("drops the condition when the type changes, because the fields are a different type's", async () => {
    serve();
    renderPage(`/entities?type=5&expr=${encodeURIComponent(JSON.stringify(GRADE_EQUALS_FOUR))}`);
    await screen.findByTestId("expression-builder");

    fireEvent.change(screen.getByLabelText(/entity type/i), { target: { value: "9" } });
    await waitFor(() => {
      const params = new URLSearchParams(screen.getByTestId("entities-search").textContent ?? "");
      expect(params.get("type")).toBe("9");
      expect(params.get("expr")).toBeNull();
    });
  });
});
