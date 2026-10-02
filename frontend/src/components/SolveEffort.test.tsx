import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import SolveEffort, { useSolveSeconds } from "./SolveEffort";

afterEach(() => localStorage.clear());

function Shows() {
  const [seconds] = useSolveSeconds();
  return <output data-testid="seconds">{seconds}</output>;
}

it("lets the person give the solver longer, shared by every Solve button and remembered (benchmark, October 2026)", () => {
  const { unmount } = render(<><SolveEffort /><Shows /></>);
  expect(screen.getByTestId("seconds")).toHaveTextContent("30");
  fireEvent.change(screen.getByLabelText("How long to look for an answer"), { target: { value: "600" } });
  expect(screen.getByTestId("seconds")).toHaveTextContent("600");
  unmount();
  render(<Shows />);
  expect(screen.getByTestId("seconds")).toHaveTextContent("600");
});
