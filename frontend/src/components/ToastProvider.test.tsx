import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider, useToast } from "./ToastProvider";

function TestConsumer() {
  const { success, error } = useToast();
  return (
    <div>
      <button type="button" onClick={() => success("Saved")}>
        trigger-success
      </button>
      <button type="button" onClick={() => error("Broken")}>
        trigger-error
      </button>
    </div>
  );
}

function renderWithProvider() {
  return render(
    <ToastProvider>
      <TestConsumer />
    </ToastProvider>
  );
}

describe("ToastProvider", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    act(() => {
      vi.runOnlyPendingTimers();
    });
    vi.useRealTimers();
  });

  it("renders a success toast inside a role=status, aria-live=polite region", () => {
    renderWithProvider();
    fireEvent.click(screen.getByText("trigger-success"));

    const status = screen.getByRole("status");
    expect(status).toHaveAttribute("aria-live", "polite");
    expect(status).toHaveTextContent("Saved");
  });

  it("renders an error toast inside a role=alert region", () => {
    renderWithProvider();
    fireEvent.click(screen.getByText("trigger-error"));

    expect(screen.getByRole("alert")).toHaveTextContent("Broken");
  });

  it("keeps both live regions mounted even with no toasts (so screen readers are already watching them)", () => {
    renderWithProvider();

    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("auto-dismisses a success toast after 4 seconds", () => {
    renderWithProvider();
    fireEvent.click(screen.getByText("trigger-success"));
    expect(screen.getByRole("status")).toHaveTextContent("Saved");

    act(() => {
      vi.advanceTimersByTime(3999);
    });
    expect(screen.getByRole("status")).toHaveTextContent("Saved");

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(screen.getByRole("status")).not.toHaveTextContent("Saved");
  });

  it("auto-dismisses an error toast after 8 seconds, not before", () => {
    renderWithProvider();
    fireEvent.click(screen.getByText("trigger-error"));

    act(() => {
      vi.advanceTimersByTime(7999);
    });
    expect(screen.getByRole("alert")).toHaveTextContent("Broken");

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(screen.getByRole("alert")).not.toHaveTextContent("Broken");
  });

  it("dismisses a toast immediately when its dismiss button is clicked", () => {
    renderWithProvider();
    fireEvent.click(screen.getByText("trigger-success"));
    fireEvent.click(screen.getByLabelText("Dismiss notification"));

    expect(screen.getByRole("status")).not.toHaveTextContent("Saved");
  });

  it("shows two toasts triggered back to back, one in each region", () => {
    renderWithProvider();
    fireEvent.click(screen.getByText("trigger-success"));
    fireEvent.click(screen.getByText("trigger-error"));

    expect(screen.getByRole("status")).toHaveTextContent("Saved");
    expect(screen.getByRole("alert")).toHaveTextContent("Broken");
  });

  it("caps visible toasts at 3, dropping the oldest", () => {
    renderWithProvider();
    const trigger = screen.getByText("trigger-success");
    fireEvent.click(trigger);
    fireEvent.click(trigger);
    fireEvent.click(trigger);
    fireEvent.click(trigger);

    expect(screen.getAllByText("Saved")).toHaveLength(3);
  });

  it("useToast() outside a ToastProvider returns working no-ops instead of throwing", () => {
    function Bare() {
      const { success, error } = useToast();
      return (
        <button type="button" onClick={() => { success("x"); error("y"); }}>
          trigger
        </button>
      );
    }
    expect(() => {
      render(<Bare />);
      fireEvent.click(screen.getByText("trigger"));
    }).not.toThrow();
  });
});
