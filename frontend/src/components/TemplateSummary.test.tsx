import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import TemplateSummary from "./TemplateSummary";

it("summarizes large seed data and reveals bounded technical details without opening the row", async () => {
  const navigate = vi.fn();
  render(<div onClick={navigate}><TemplateSummary kind="seed" value={{ note: "Weekly staffing example", entity_types: [{}], entities: [{ key: "hidden_record" }, {}], parameters: [{}] }} /></div>);
  expect(screen.getByText("1 record type · 2 sample records · 1 parameter")).toBeInTheDocument();
  expect(screen.queryByText(/hidden_record/)).toBeNull();
  fireEvent.click(screen.getByText("Technical details (sample data)"));
  await waitFor(() => expect(screen.getByLabelText("Sample data JSON")).toHaveTextContent("hidden_record"));
  expect(screen.getByLabelText("Sample data JSON")).toHaveClass("max-h-64", "overflow-auto");
  expect(navigate).not.toHaveBeenCalled();
});

it("summarizes decision and constraint counts", () => {
  render(<TemplateSummary kind="model" value={{ variables: { assign: {} }, sets: ["staff", "day"], constraints: [{}, {}], objective: { sense: "minimize" } }} />);
  expect(screen.getByText("1 decision · 2 rules · 2 sets")).toBeInTheDocument();
  expect(screen.getByText("Objective: minimize")).toBeInTheDocument();
});
