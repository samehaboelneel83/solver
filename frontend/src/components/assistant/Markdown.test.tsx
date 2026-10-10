import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import Markdown from "./Markdown";

it("shows the platform's fold closed, not as its tags (the Delta Pharma trace)", () => {
  render(<Markdown text={"I stopped.\n\n<details><summary>Technical detail</summary>\n\nmul has exactly two factors\n\n</details>"} />);
  const summary = screen.getByText("Technical detail");
  expect(summary.tagName).toBe("SUMMARY");
  expect((summary.parentElement as HTMLDetailsElement).open).toBe(false);
  expect(summary.parentElement).toHaveTextContent("mul has exactly two factors");
  expect(screen.queryByText(/<details>/)).not.toBeInTheDocument();
});
