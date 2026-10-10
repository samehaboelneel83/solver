import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { downloadFrom } from "../../api/download";
import Markdown from "./Markdown";

vi.mock("../../api/download", () => ({ downloadFrom: vi.fn(() => Promise.resolve()) }));

it("shows the platform's fold closed, not as its tags (the Delta Pharma trace)", () => {
  render(<Markdown text={"I stopped.\n\n<details><summary>Technical detail</summary>\n\nmul has exactly two factors\n\n</details>"} />);
  const summary = screen.getByText("Technical detail");
  expect(summary.tagName).toBe("SUMMARY");
  expect((summary.parentElement as HTMLDetailsElement).open).toBe(false);
  expect(summary.parentElement).toHaveTextContent("mul has exactly two factors");
  expect(screen.queryByText(/<details>/)).not.toBeInTheDocument();
});

it("saves a file of the API when its link is clicked, and opens a page of the app as a page", () => {
  render(<MemoryRouter><Markdown text={"[PDF report](/api/v1/runs/159/export?format=pdf) and [the run](/domains/1/problems/2/runs/159)"} /></MemoryRouter>);
  fireEvent.click(screen.getByRole("button", { name: "PDF report" }));
  expect(vi.mocked(downloadFrom)).toHaveBeenCalledWith("/api/v1/runs/159/export?format=pdf");
  expect(screen.getByRole("link", { name: "the run" })).toHaveAttribute("href", "/domains/1/problems/2/runs/159");
});
