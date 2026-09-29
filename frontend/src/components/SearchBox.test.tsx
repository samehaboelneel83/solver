import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import SearchBox from "./SearchBox";

describe("the search box (Epic UX, U-1)", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("sends what was typed once the planner pauses, trimmed, and clears on Escape", () => {
    const onSearch = vi.fn();
    render(<SearchBox label="scenarios" onSearch={onSearch} delay={200} />);
    const box = screen.getByRole("searchbox", { name: "Search scenarios" });
    fireEvent.change(box, { target: { value: " win" } });
    fireEvent.change(box, { target: { value: " winter " } });
    act(() => { vi.advanceTimersByTime(250); });
    expect(onSearch).toHaveBeenLastCalledWith("winter");
    expect(onSearch).not.toHaveBeenCalledWith("win");
    fireEvent.keyDown(box, { key: "Escape" });
    act(() => { vi.advanceTimersByTime(250); });
    expect(onSearch).toHaveBeenLastCalledWith("");
  });
});
