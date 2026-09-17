import { render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import App from "./App";
import { setToken } from "./api/client";

function LocationDisplay() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname + location.search}</div>;
}

describe("RequireAuth", () => {
  beforeEach(() => {
    setToken(null);
  });

  it("redirects to /login with next=<current path> and no reason when there is no token", () => {
    render(
      <MemoryRouter initialEntries={["/finance/invoice?tab=details"]}>
        <LocationDisplay />
        <App />
      </MemoryRouter>
    );

    expect(screen.getByTestId("location").textContent).toBe(
      "/login?next=" + encodeURIComponent("/finance/invoice?tab=details")
    );
  });
});
