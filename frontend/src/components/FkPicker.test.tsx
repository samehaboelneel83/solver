import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import FkPicker from "./FkPicker";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { apiFetch } from "../api/client";

function renderPicker(value = "", onChange = vi.fn(), extraProps: Record<string, unknown> = {}) {
  const queryClient = new QueryClient();
  render(
    <QueryClientProvider client={queryClient}>
      <FkPicker fkTable="iam.organization" value={value} onChange={onChange} testId="field-organization_id" {...extraProps} />
    </QueryClientProvider>
  );
  return onChange;
}

describe("FkPicker", () => {
  beforeEach(() => {
    (apiFetch as any).mockImplementation((path: string) => {
      if (path.startsWith("/api/iam/organization/options?q=nur")) {
        return Promise.resolve([{ id: "org-2", label: "Nur Hospital" }]);
      }
      if (path === "/api/iam/organization/options?ids=org-1") {
        return Promise.resolve([{ id: "org-1", label: "Acme" }]);
      }
      return Promise.resolve([]);
    });
  });

  it("searches by typed query and lists results by label", async () => {
    renderPicker();

    const input = screen.getByTestId("field-organization_id");
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "nur" } });

    await waitFor(
      () => {
        expect(apiFetch).toHaveBeenCalledWith(expect.stringContaining("/options?q=nur"));
      },
      { timeout: 5000 }
    );

    expect(await screen.findByRole("option", { name: "Nur Hospital" })).toBeInTheDocument();
  });

  it("selecting an option calls onChange with the id and shows its label", async () => {
    const onChange = renderPicker();

    const input = screen.getByTestId("field-organization_id");
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "nur" } });

    const option = await screen.findByRole("option", { name: "Nur Hospital" });
    fireEvent.mouseDown(option);

    expect(onChange).toHaveBeenCalledWith("org-2");
    await waitFor(() => {
      expect((screen.getByTestId("field-organization_id") as HTMLInputElement).value).toBe("Nur Hospital");
    });
  });

  it("resolves an initial value's label via ids=", async () => {
    renderPicker("org-1");

    await waitFor(() => {
      expect(apiFetch).toHaveBeenCalledWith("/api/iam/organization/options?ids=org-1");
    });
    await waitFor(() => {
      expect((screen.getByTestId("field-organization_id") as HTMLInputElement).value).toBe("Acme");
    });
  });

  it("clear button calls onChange with an empty string", async () => {
    const onChange = renderPicker("org-1");

    await waitFor(() => {
      expect((screen.getByTestId("field-organization_id") as HTMLInputElement).value).toBe("Acme");
    });

    fireEvent.click(screen.getByRole("button", { name: "Clear selection" }));
    expect(onChange).toHaveBeenCalledWith("");
  });

  it("does not query /options?q= before the picker is opened", async () => {
    (apiFetch as any).mockClear();
    renderPicker();

    await screen.findByTestId("field-organization_id");
    expect(apiFetch).not.toHaveBeenCalledWith(expect.stringContaining("/options?q="));
  });

  it("shows a prompt before typing and 'No matches' when a search is empty", async () => {
    renderPicker();

    const input = screen.getByTestId("field-organization_id");
    fireEvent.focus(input);
    expect(screen.getByText("Type to search")).toBeInTheDocument();

    fireEvent.change(input, { target: { value: "zzz" } });
    await waitFor(
      () => {
        expect(screen.getByText("No matches")).toBeInTheDocument();
      },
      { timeout: 5000 }
    );
  });
});

// C-2: the field used to look like a plain, unlabelled text box -- nothing
// signalled that typing searches a list, which is exactly what made C-1
// (below) reachable in the first place.
describe("FkPicker affordances (C-2)", () => {
  beforeEach(() => {
    (apiFetch as any).mockImplementation((path: string) => {
      if (path === "/api/meta/schema") {
        return Promise.resolve([
          { schema: "iam", table: "organization", fields: [], label: "Organization", label_plural: "Organizations" },
        ]);
      }
      return Promise.resolve([]);
    });
  });

  it("has a placeholder that says what it searches, derived from the target table's label", async () => {
    renderPicker();

    await waitFor(() => {
      expect(screen.getByTestId("field-organization_id")).toHaveAttribute("placeholder", "Search organizations…");
    });
  });

  it("falls back to a generic placeholder when the target table's label isn't known", async () => {
    (apiFetch as any).mockImplementation(() => Promise.resolve([]));
    renderPicker();

    expect(screen.getByTestId("field-organization_id")).toHaveAttribute("placeholder", "Search…");
  });

  it("renders a chevron affordance", () => {
    renderPicker();

    expect(screen.getByTestId("field-organization_id-chevron")).toBeInTheDocument();
  });

  it("shows a chosen value styled as a token, alongside the existing clear button", async () => {
    (apiFetch as any).mockImplementation((path: string) => {
      if (path === "/api/iam/organization/options?ids=org-1") {
        return Promise.resolve([{ id: "org-1", label: "Acme" }]);
      }
      return Promise.resolve([]);
    });
    renderPicker("org-1");

    const input = await screen.findByDisplayValue("Acme");
    expect(input.className).toMatch(/bg-slate-100/);
    expect(screen.getByRole("button", { name: "Clear selection" })).toBeInTheDocument();
  });
});

// C-1: typing into the field and clicking away without picking from the
// list used to silently empty it -- no message, no mark, so a user could
// submit believing the field was set.
describe("FkPicker keeps typed text instead of silently discarding it (C-1)", () => {
  beforeEach(() => {
    // Matches on the decoded `q` param rather than the raw path string, so
    // this survives URL-encoding of spaces/case in a typed query like "Nur
    // Hospital" instead of silently never matching.
    (apiFetch as any).mockImplementation((path: string) => {
      const q = new URL(path, "http://example.test").searchParams.get("q") ?? "";
      if (q.toLowerCase() === "nur hospital") {
        return Promise.resolve([{ id: "org-2", label: "Nur Hospital" }]);
      }
      return Promise.resolve([]);
    });
  });

  it("keeps the typed text and shows a 'no match' message on blur when nothing was selected", async () => {
    const onChange = renderPicker();

    const input = screen.getByTestId("field-organization_id");
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "zzz" } });
    await waitFor(
      () => {
        expect(screen.getByText("No matches")).toBeInTheDocument();
      },
      { timeout: 5000 }
    );

    fireEvent.blur(input);

    expect((input as HTMLInputElement).value).toBe("zzz");
    expect(screen.getByText("No match — choose from the list")).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("selects the option instead of showing 'no match' when exactly one option matches the typed text exactly", async () => {
    const onChange = renderPicker();

    const input = screen.getByTestId("field-organization_id");
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "Nur Hospital" } });
    await screen.findByRole("option", { name: "Nur Hospital" });

    fireEvent.blur(input);

    expect(onChange).toHaveBeenCalledWith("org-2");
    await waitFor(() => {
      expect((input as HTMLInputElement).value).toBe("Nur Hospital");
    });
    expect(screen.queryByText("No match — choose from the list")).not.toBeInTheDocument();
  });
});

// Fix round 1: a reviewer found that once a prior selection existed,
// blurring on unmatched text left `value`/`onChange` untouched while
// displaying the newly-typed text -- so the screen showed one row (e.g.
// "zzz-t6-probe-nomatch") while the stored id still pointed at the
// previously selected row (e.g. Alpha). A submit at that point saved the
// old id under new-looking text. The display must never be able to
// disagree with `value`.
describe("FkPicker reverts to the prior selection instead of showing unmatched text (fix round 1)", () => {
  beforeEach(() => {
    (apiFetch as any).mockImplementation((path: string) => {
      if (path === "/api/iam/organization/options?ids=org-1") {
        return Promise.resolve([{ id: "org-1", label: "Acme" }]);
      }
      const q = new URL(path, "http://example.test").searchParams.get("q") ?? "";
      if (q.toLowerCase() === "nur") {
        return Promise.resolve([{ id: "org-2", label: "Nur Hospital" }]);
      }
      return Promise.resolve([]);
    });
  });

  async function selectAcmeThenTypeUnmatched(onChange = vi.fn()) {
    renderPicker("org-1", onChange);
    const input = screen.getByTestId("field-organization_id") as HTMLInputElement;
    await waitFor(() => expect(input.value).toBe("Acme"));

    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "zzz-t6-probe-nomatch" } });
    await waitFor(
      () => {
        expect(screen.getByText("No matches")).toBeInTheDocument();
      },
      { timeout: 5000 }
    );
    fireEvent.blur(input);
    return { input, onChange };
  }

  it("(a) leaves onChange uncalled and reverts the displayed value to the original label", async () => {
    const { input, onChange } = await selectAcmeThenTypeUnmatched();

    expect(onChange).not.toHaveBeenCalled();
    expect(input.value).toBe("Acme");
  });

  it("(b) names both the failed query and the kept selection in the message", async () => {
    await selectAcmeThenTypeUnmatched();

    expect(
      screen.getByText('No match for "zzz-t6-probe-nomatch" — keeping "Acme"')
    ).toBeInTheDocument();
  });

  it("(c) still allows picking a different option after an unmatched blur reverted the display", async () => {
    const { input, onChange } = await selectAcmeThenTypeUnmatched();
    expect(input.value).toBe("Acme");

    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "nur" } });
    const option = await screen.findByRole("option", { name: "Nur Hospital" });
    fireEvent.mouseDown(option);

    expect(onChange).toHaveBeenCalledWith("org-2");
    await waitFor(() => {
      expect(input.value).toBe("Nur Hospital");
    });
  });

  it("(d) still keeps the typed text (not a revert) when there was no prior selection to fall back to", async () => {
    const onChange = vi.fn();
    renderPicker("", onChange);
    const input = screen.getByTestId("field-organization_id") as HTMLInputElement;

    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "zzz-t6-probe-nomatch" } });
    await waitFor(
      () => {
        expect(screen.getByText("No matches")).toBeInTheDocument();
      },
      { timeout: 5000 }
    );
    fireEvent.blur(input);

    expect(onChange).not.toHaveBeenCalled();
    expect(input.value).toBe("zzz-t6-probe-nomatch");
    expect(screen.getByText("No match — choose from the list")).toBeInTheDocument();
  });
});

// H-12 (combobox half): aria-activedescendant was never set, so a
// screen-reader user arrowing through options was never told which option
// was highlighted, and aria-controls pointed at a listbox id that didn't
// exist until the user typed.
describe("FkPicker combobox accessibility (H-12)", () => {
  beforeEach(() => {
    (apiFetch as any).mockImplementation((path: string) => {
      if (path.startsWith("/api/iam/organization/options?q=nur")) {
        return Promise.resolve([
          { id: "org-2", label: "Nur Hospital" },
          { id: "org-3", label: "Nurse Depot" },
        ]);
      }
      return Promise.resolve([]);
    });
  });

  it("has no aria-activedescendant until an option is highlighted, then tracks it while arrowing", async () => {
    renderPicker();

    const input = screen.getByTestId("field-organization_id");
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "nur" } });
    const first = await screen.findByRole("option", { name: "Nur Hospital" });
    const second = screen.getByRole("option", { name: "Nurse Depot" });

    expect(input).not.toHaveAttribute("aria-activedescendant");

    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(input).toHaveAttribute("aria-activedescendant", first.id);

    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(input).toHaveAttribute("aria-activedescendant", second.id);
  });

  it("only sets aria-controls while the listbox is actually rendered", async () => {
    renderPicker();

    const input = screen.getByTestId("field-organization_id");
    expect(input).not.toHaveAttribute("aria-controls");

    fireEvent.focus(input);
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    expect(input).toHaveAttribute("aria-controls", screen.getByRole("listbox").id);

    fireEvent.blur(input);
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(input).not.toHaveAttribute("aria-controls");
  });
});

// Carried forward from Task 5's review: EntityForm couldn't mark a
// required-but-empty FK field because FkPicker didn't accept or forward
// aria-invalid/aria-describedby/id.
describe("FkPicker forwards id/aria-invalid/aria-describedby", () => {
  it("passes id, aria-invalid and aria-describedby through to the input", () => {
    renderPicker("", vi.fn(), { id: "my-fk-field", "aria-invalid": "true", "aria-describedby": "my-fk-field-error" });

    const input = screen.getByTestId("field-organization_id");
    expect(input).toHaveAttribute("id", "my-fk-field");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAttribute("aria-describedby", "my-fk-field-error");
  });
});
