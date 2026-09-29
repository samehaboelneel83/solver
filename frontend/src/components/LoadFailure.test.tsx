import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ApiError, NetworkError } from "../api/client";
import LoadFailure, { failureKind } from "./LoadFailure";

describe("a failed read says which kind of failure it is (Epic UX, U-1)", () => {
  it("tells no access, not found, offline and other failures apart", () => {
    expect(failureKind(new ApiError(403, "no"))).toBe("no-access");
    expect(failureKind(new ApiError(404, "gone"))).toBe("not-found");
    expect(failureKind(new NetworkError())).toBe("offline");
    expect(failureKind(new ApiError(500, "boom"))).toBe("failed");
  });

  it("no access: says who can fix it, and offers no Retry that cannot help", () => {
    render(<LoadFailure subject="The run" error={new ApiError(403, "no")} retry={vi.fn()} back={{ label: "Back to runs", to: "/runs" }} />);
    expect(screen.getByRole("alert")).toHaveTextContent("The run is not open to this account. Ask an administrator");
    expect(screen.queryByRole("button", { name: /Retry/ })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to runs" })).toHaveAttribute("href", "/runs");
  });

  it("not found: says the link is stale", () => {
    render(<LoadFailure subject="The run" error={new ApiError(404, "gone")} retry={vi.fn()} />);
    expect(screen.getByRole("alert")).toHaveTextContent("The run could not be found. It may have been deleted, or the link is mistyped.");
  });

  it("a failure that may pass is retried", () => {
    const retry = vi.fn();
    render(<LoadFailure subject="The run" error={new ApiError(500, "boom")} retry={retry} />);
    fireEvent.click(screen.getByRole("button", { name: "Retry loading the run" }));
    expect(retry).toHaveBeenCalledOnce();
  });
});
