import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

const { apiFetch } = await import("../api/client");
const { default: LearnedRules } = await import("./LearnedRules");
const mockFetch = apiFetch as unknown as ReturnType<typeof vi.fn>;

const RULE = {
  id: "c_learnt_assign_employee_max",
  forall: [{ index: "e", set: "employee" }],
  left: { sum: { var: "assign", index: ["e", "d"] }, over: [{ index: "d", set: "day" }] },
  relation: "<=",
  right: { const: 3 },
  severity: "hard",
};

describe("LearnedRules", () => {
  it("learns from the approved plans and adds a rule under a free id", async () => {
    mockFetch.mockResolvedValueOnce({
      plans: 4, source: "approved", runs: [1, 2, 3, 4], says: "1 rule every one of the 4 plans kept and the model does not.",
      rules: [{ id: RULE.id, decision: "assign", by: ["employee"], over: ["day"], direction: "most", bound: 3,
        model_allows: 5, plans: 4, says: "assign, summed over day, for each employee: at most 3", rule: RULE }],
    });
    const onAdd = vi.fn();
    render(<LearnedRules problemId={9} taken={[RULE.id]} onAdd={onAdd} />);
    fireEvent.click(screen.getByText("Rules your past plans kept"));
    fireEvent.change(screen.getByLabelText(/Learn from/), { target: { value: "answered" } });
    fireEvent.click(screen.getByRole("button", { name: "Learn rules" }));
    await waitFor(() => expect(mockFetch).toHaveBeenCalledWith("/api/v1/problems/9/learned-rules?source=answered"));
    expect(await screen.findByText("assign, summed over day, for each employee: at most 3")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Add as a rule" }));
    expect(onAdd).toHaveBeenCalledWith({ ...RULE, id: `${RULE.id}_2` });
    expect(screen.getByText("Added to the draft")).toBeInTheDocument();
  });

  it("says why when nothing can be learnt", async () => {
    mockFetch.mockResolvedValueOnce({ plans: 1, source: "approved", runs: [1], rules: [],
      says: "Rules are learnt from at least 2 plans; there is 1." });
    render(<LearnedRules problemId={9} taken={[]} onAdd={vi.fn()} />);
    fireEvent.click(screen.getByText("Rules your past plans kept"));
    fireEvent.click(screen.getByRole("button", { name: "Learn rules" }));
    expect(await screen.findByText(/at least 2 plans; there is 1/)).toBeInTheDocument();
  });
});
