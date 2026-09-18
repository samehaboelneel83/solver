import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Login from "./Login";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, login: vi.fn() };
});

import { login } from "../api/client";

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/domain/entity" element={<div>Entity page</div>} />
        <Route path="/" element={<div>Home page</div>} />
      </Routes>
    </MemoryRouter>
  );
}

function submitLoginForm() {
  fireEvent.change(screen.getByTestId("username"), { target: { value: "admin" } });
  fireEvent.change(screen.getByTestId("password"), { target: { value: "secret" } });
  fireEvent.click(screen.getByText("Sign in"));
}

describe("Login page", () => {
  beforeEach(() => {
    (login as any).mockResolvedValue("fake-token");
  });

  it("calls login with the entered credentials on submit", async () => {
    renderAt("/login");

    submitLoginForm();

    await waitFor(() => {
      expect(login).toHaveBeenCalledWith("admin", "secret");
    });
  });

  it("shows a session-expired message when redirected with reason=expired", () => {
    renderAt("/login?reason=expired");

    expect(screen.getByText("Your session expired — please sign in again")).toBeInTheDocument();
  });

  it("does not show the session-expired message otherwise", () => {
    renderAt("/login");

    expect(screen.queryByText("Your session expired — please sign in again")).not.toBeInTheDocument();
  });

  it("navigates to the next path after a successful login", async () => {
    renderAt("/login?reason=expired&next=%2Fdomain%2Fentity");

    submitLoginForm();

    await waitFor(() => {
      expect(screen.getByText("Entity page")).toBeInTheDocument();
    });
  });

  it("navigates to / after a successful login when there is no next param", async () => {
    renderAt("/login");

    submitLoginForm();

    await waitFor(() => {
      expect(screen.getByText("Home page")).toBeInTheDocument();
    });
  });

  it("navigates to / when next is not a safe relative path", async () => {
    renderAt("/login?next=" + encodeURIComponent("//evil.example.com"));

    submitLoginForm();

    await waitFor(() => {
      expect(screen.getByText("Home page")).toBeInTheDocument();
    });
  });

  it("navigates to the next path (with query string) after a successful login", async () => {
    renderAt("/login?next=" + encodeURIComponent("/domain/entity?offset=20"));

    submitLoginForm();

    await waitFor(() => {
      expect(screen.getByText("Entity page")).toBeInTheDocument();
    });
  });

  const unsafeNextValues: Array<[string, string]> = [
    ["a tab-smuggled protocol-relative URL", "/\t/evil.com"],
    ["a protocol-relative URL", "//evil.example.com"],
    ["an absolute URL to another origin", "https://evil.example.com"],
    ["a backslash-smuggled URL", "/\\evil.com"],
  ];

  it.each(unsafeNextValues)(
    "does not leave the app's origin when next is %s",
    async (_label, unsafeNext) => {
      renderAt("/login?next=" + encodeURIComponent(unsafeNext));

      submitLoginForm();

      // None of these should land on a page other than the app's own "/" —
      // in particular they must never produce a cross-origin navigation.
      await waitFor(() => {
        expect(screen.getByText("Home page")).toBeInTheDocument();
      });
      expect(window.location.origin).toBe("http://localhost:3000");
    }
  );
});

describe("Login accessible fields (H-8)", () => {
  it("associates each <label> with its input via htmlFor/id, findable by getByLabelText", () => {
    renderAt("/login");

    expect(screen.getByLabelText("Username")).toBe(screen.getByTestId("username"));
    expect(screen.getByLabelText("Password")).toBe(screen.getByTestId("password"));
  });

  it("gives each input a name and the right autocomplete token so a password manager can fill them", () => {
    renderAt("/login");

    const usernameField = screen.getByTestId("username");
    expect(usernameField).toHaveAttribute("name", "username");
    expect(usernameField).toHaveAttribute("autocomplete", "username");

    const passwordField = screen.getByTestId("password");
    expect(passwordField).toHaveAttribute("name", "password");
    expect(passwordField).toHaveAttribute("autocomplete", "current-password");
  });
});
