import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it } from "vitest";
import WhatThisAppDoes, { STAGES } from "./WhatThisAppDoes";

beforeEach(() => localStorage.clear());

it("lists the sixteen steps in order, each linked to its page in the workspace (benchmark, October 2026)", () => {
  render(<MemoryRouter><WhatThisAppDoes domainId={7} /></MemoryRouter>);
  expect(STAGES.flatMap((s) => s.steps)).toHaveLength(16);
  expect(screen.getByRole("link", { name: "Import data" })).toHaveAttribute("href", "/domains/7/data/records");
  expect(screen.getByRole("link", { name: "Forecasts" })).toHaveAttribute("href", "/domains/7/data/predictors");
  // A problem's page, with no problem open: the problems, to pick one.
  expect(screen.getByRole("link", { name: "Goals" })).toHaveAttribute("href", "/domains/7/problems");
  expect(within(screen.getByRole("region", { name: "Read and share the answer" })).getAllByRole("listitem")).toHaveLength(3);
});

it("goes to the problem's own pages when one is open, and stays closed once closed", () => {
  const { unmount } = render(<MemoryRouter><WhatThisAppDoes domainId={7} problemId={3} /></MemoryRouter>);
  expect(screen.getByRole("link", { name: "Goals" })).toHaveAttribute("href", "/domains/7/problems/3/model");
  const panel = screen.getByText(/What can this app do/).closest("details")!;
  panel.open = false;
  fireEvent(panel, new Event("toggle"));
  unmount();
  render(<MemoryRouter><WhatThisAppDoes domainId={null} /></MemoryRouter>);
  expect(screen.getByText(/What can this app do/).closest("details")!.open).toBe(false);
  expect(screen.getByRole("link", { name: "Import data" })).toHaveAttribute("href", "/domains");
});
