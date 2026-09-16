import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Login from "./Login";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, login: vi.fn() };
});

import { login } from "../api/client";

describe("Login page", () => {
  beforeEach(() => {
    (login as any).mockResolvedValue("fake-token");
  });

  it("calls login with the entered credentials on submit", async () => {
    render(
      <MemoryRouter>
        <Login />
      </MemoryRouter>
    );

    fireEvent.change(screen.getByTestId("username"), { target: { value: "admin" } });
    fireEvent.change(screen.getByTestId("password"), { target: { value: "secret" } });
    fireEvent.click(screen.getByText("Sign in"));

    await waitFor(() => {
      expect(login).toHaveBeenCalledWith("admin", "secret");
    });
  });
});
