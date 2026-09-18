import { onlineManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AppShell from "./AppShell";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { apiFetch } from "../api/client";

function renderWithProviders(initialEntries: string[] = ["/"]) {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={initialEntries}>
        <AppShell />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("AppShell", () => {
  beforeEach(() => {
    localStorage.clear();
    (apiFetch as any).mockResolvedValue([
      { schema: "iam", table: "organization", fields: [] },
      { schema: "domain", table: "entity", fields: [] },
    ]);
  });

  it("renders a nav group per schema with a link per table", async () => {
    renderWithProviders();

    expect(await screen.findByText("organization")).toBeInTheDocument();
    expect(screen.getByText("entity")).toBeInTheDocument();
    // B-1: the group heading is a human label ("Access"/"Domain model"), not the raw
    // postgres schema name -- see the dedicated describe block below for direct coverage.
    expect(screen.getByText("Access")).toBeInTheDocument();
    expect(screen.getByText("Domain model")).toBeInTheDocument();
    expect(screen.queryByText("iam")).not.toBeInTheDocument();
    expect(screen.queryByText("domain")).not.toBeInTheDocument();
  });

  it("renders a 'Skip to content' link as the first focusable element, targeting #main", async () => {
    renderWithProviders();
    await screen.findByText("organization");

    const links = screen.getAllByRole("link");
    expect(links[0]).toHaveTextContent("Skip to content");
    expect(links[0]).toHaveAttribute("href", "#main");
  });

  it("marks the nav link for the current route as active and leaves the others plain", async () => {
    renderWithProviders(["/iam/organization"]);
    const activeLink = await screen.findByRole("link", { name: "organization" });
    const otherLink = screen.getByRole("link", { name: "entity" });

    expect(activeLink).toHaveAttribute("aria-current", "page");
    expect(activeLink.className).not.toBe(otherLink.className);
    expect(otherLink).not.toHaveAttribute("aria-current");
  });

  it("renders <main> as a shrinkable flex child with id=main", async () => {
    renderWithProviders();
    await screen.findByText("organization");

    const main = document.getElementById("main");
    expect(main).not.toBeNull();
    expect(main?.className.split(/\s+/)).toContain("min-w-0");
  });

  it("lists the plural human label (e.g. 'Entity types') instead of the raw table name when the backend sends one (B-1)", async () => {
    (apiFetch as any).mockResolvedValue([
      { schema: "domain", table: "entity_type", label: "Entity type", label_plural: "Entity types", fields: [] },
    ]);
    renderWithProviders();

    expect(await screen.findByText("Entity types")).toBeInTheDocument();
    expect(screen.queryByText("entity_type")).not.toBeInTheDocument();
  });

  describe("nav group headings are human labels, not raw schema names (B-1)", () => {
    it("maps known schemas to their human label and falls back to a capitalised name for an unknown one", async () => {
      (apiFetch as any).mockResolvedValue([
        { schema: "iam", table: "organization", fields: [] },
        { schema: "domain", table: "entity", fields: [] },
        { schema: "problem", table: "problem", fields: [] },
        { schema: "scratch", table: "widget", fields: [] },
      ]);
      renderWithProviders();

      expect(await screen.findByText("Access")).toBeInTheDocument();
      expect(screen.getByText("Domain model")).toBeInTheDocument();
      expect(screen.getByText("Problem")).toBeInTheDocument();
      // Unmapped schema: falls back to a capitalised raw name, not a crash or blank heading.
      expect(screen.getByText("Scratch")).toBeInTheDocument();
    });

    it("still filters by the raw schema name even though it's no longer shown", async () => {
      renderWithProviders();
      await screen.findByText("organization");

      fireEvent.change(screen.getByPlaceholderText("Filter tables…"), { target: { value: "iam" } });

      expect(screen.getByRole("link", { name: "organization" })).toBeInTheDocument();
      expect(screen.queryByRole("link", { name: "entity" })).not.toBeInTheDocument();
    });
  });

  describe("collapsible groups (A-4)", () => {
    it("hides a group's tables when its heading is clicked, and shows them again on a second click", async () => {
      renderWithProviders();
      await screen.findByText("organization");

      const heading = screen.getByRole("button", { name: "Access" });
      expect(screen.getByRole("link", { name: "organization" })).toBeInTheDocument();

      fireEvent.click(heading);
      expect(screen.queryByRole("link", { name: "organization" })).not.toBeInTheDocument();
      // The other group is untouched.
      expect(screen.getByRole("link", { name: "entity" })).toBeInTheDocument();

      fireEvent.click(heading);
      expect(screen.getByRole("link", { name: "organization" })).toBeInTheDocument();
    });

    it("persists a collapsed group's state in localStorage and restores it on the next mount", async () => {
      const { unmount } = renderWithProviders();
      await screen.findByText("organization");

      fireEvent.click(screen.getByRole("button", { name: "Access" }));
      expect(screen.queryByRole("link", { name: "organization" })).not.toBeInTheDocument();

      const stored = JSON.parse(localStorage.getItem("solver_nav_open_groups") ?? "{}");
      expect(stored.iam).toBe(false);

      unmount();

      renderWithProviders();
      await screen.findByText("entity");
      // Restored collapsed -- the table link stays hidden without clicking again.
      expect(screen.queryByRole("link", { name: "organization" })).not.toBeInTheDocument();
    });
  });

  it("narrows the visible tables via the filter box", async () => {
    renderWithProviders();
    await screen.findByText("organization");

    fireEvent.change(screen.getByPlaceholderText("Filter tables…"), { target: { value: "entity" } });

    expect(screen.getByRole("link", { name: "entity" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "organization" })).not.toBeInTheDocument();
  });

  it("scrolls the table nav region independently of the rest of the sidebar", async () => {
    renderWithProviders();
    await screen.findByText("organization");

    const nav = screen.getByRole("navigation", { name: "Tables" });
    expect(nav.className).toContain("overflow-y-auto");
  });

  describe("drawer below the lg breakpoint (G-2/G-5)", () => {
    it("always renders a menu toggle button, hidden above the drawer breakpoint via a responsive class", async () => {
      renderWithProviders();
      await screen.findByText("organization");

      const toggle = screen.getByTestId("menu-toggle");
      expect(toggle).toBeInTheDocument();
      expect(toggle.className).toContain("lg:hidden");
    });

    it("opens the sidebar via the menu button and closes it again on Escape", async () => {
      renderWithProviders();
      await screen.findByText("organization");

      const toggle = screen.getByTestId("menu-toggle");
      expect(toggle).toHaveAttribute("aria-expanded", "false");

      fireEvent.click(toggle);
      expect(toggle).toHaveAttribute("aria-expanded", "true");

      fireEvent.keyDown(document, { key: "Escape" });
      expect(toggle).toHaveAttribute("aria-expanded", "false");
    });

    it("closes the drawer on route change", async () => {
      renderWithProviders();
      await screen.findByText("organization");

      const toggle = screen.getByTestId("menu-toggle");
      fireEvent.click(toggle);
      expect(toggle).toHaveAttribute("aria-expanded", "true");

      fireEvent.click(screen.getByRole("link", { name: "entity" }));
      expect(toggle).toHaveAttribute("aria-expanded", "false");
    });

    // fix round 1: a closed drawer used to stay fully in the tab order and
    // the accessibility tree while only translated off-screen -- measured
    // in a real browser at 375px, 11 of the first 12 tab stops were
    // off-screen sidebar controls before a keyboard user ever reached page
    // content. `axe` doesn't catch this (nothing here is an axe violation on
    // its own), so this has to be asserted directly rather than left to an
    // automated scan.
    describe("keyboard/AT reachability (fix round 1)", () => {
      it("makes the closed drawer's contents inert below the lg breakpoint", async () => {
        renderWithProviders();
        await screen.findByText("organization");

        // The default jsdom matchMedia stub reports "not desktop".
        const aside = document.getElementById("sidebar-nav");
        expect(aside).toHaveAttribute("inert");
      });

      it("removes inert and moves focus into the drawer when it opens", async () => {
        renderWithProviders();
        await screen.findByText("organization");

        const aside = document.getElementById("sidebar-nav") as HTMLElement;
        fireEvent.click(screen.getByTestId("menu-toggle"));

        expect(aside).not.toHaveAttribute("inert");
        // Focus lands on the drawer's own (non-interactive) heading, not on
        // "Sign out" (fix round 2) -- it used to be first in DOM order,
        // which left a user one Enter press from logging out the instant
        // the drawer opened.
        expect(screen.getByRole("heading", { name: "Problem Solver" })).toHaveFocus();
      });

      it("restores inert and returns focus to the Menu button when the drawer closes via Escape", async () => {
        renderWithProviders();
        await screen.findByText("organization");

        const aside = document.getElementById("sidebar-nav") as HTMLElement;
        const toggle = screen.getByTestId("menu-toggle");
        fireEvent.click(toggle);
        expect(aside).not.toHaveAttribute("inert");

        fireEvent.keyDown(document, { key: "Escape" });

        expect(aside).toHaveAttribute("inert");
        expect(toggle).toHaveFocus();
      });

      it("restores inert and returns focus to the Menu button when the backdrop is clicked", async () => {
        renderWithProviders();
        await screen.findByText("organization");

        const aside = document.getElementById("sidebar-nav") as HTMLElement;
        const toggle = screen.getByTestId("menu-toggle");
        fireEvent.click(toggle);
        expect(aside).not.toHaveAttribute("inert");

        fireEvent.click(screen.getByTestId("sidebar-backdrop"));

        expect(aside).toHaveAttribute("inert");
        expect(toggle).toHaveFocus();
      });

      it("keeps the sidebar reachable (never inert) at the lg breakpoint regardless of drawer state", async () => {
        const originalMatchMedia = window.matchMedia;
        window.matchMedia = ((query: string) =>
          ({
            matches: true,
            media: query,
            onchange: null,
            addListener: () => {},
            removeListener: () => {},
            addEventListener: () => {},
            removeEventListener: () => {},
            dispatchEvent: () => false,
          }) as unknown as MediaQueryList) as typeof window.matchMedia;

        try {
          renderWithProviders();
          await screen.findByText("organization");

          // The drawer is "closed" (never opened), but at the desktop
          // breakpoint the sidebar is the static one and must stay reachable.
          const aside = document.getElementById("sidebar-nav");
          expect(aside).not.toHaveAttribute("inert");
        } finally {
          window.matchMedia = originalMatchMedia;
        }
      });
    });

    it("the backdrop is a real interactive element with an accessible name, not a div with an onClick (fix round 1)", async () => {
      renderWithProviders();
      await screen.findByText("organization");

      const backdrop = screen.getByTestId("sidebar-backdrop");
      expect(backdrop.tagName).toBe("BUTTON");
      expect(backdrop).toHaveAccessibleName("Close navigation menu");
      // Not a stop on the normal Tab sequence -- it's meant to be
      // clicked/tapped, not tabbed to.
      expect(backdrop).toHaveAttribute("tabIndex", "-1");
    });

    // fix round 2: opening the drawer moved focus in (fix round 1), but
    // nothing stopped Tab from walking back *out* of it -- measured at
    // 375px, tabbing forward from the drawer landed on the Menu button,
    // which the open drawer's own backdrop visually covers (a real click
    // there hits the backdrop, not the button), and past it onto page
    // content entirely. `axe` doesn't catch this either direction, so it's
    // asserted directly rather than left to an automated scan.
    describe("focus trap while open and off-canvas (fix round 2)", () => {
      function lastFocusable(aside: HTMLElement): HTMLElement {
        const all = aside.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        );
        return all[all.length - 1];
      }

      it("wraps Tab forward from the drawer's last focusable control back to its first", async () => {
        renderWithProviders();
        await screen.findByText("organization");
        fireEvent.click(screen.getByTestId("menu-toggle"));

        const aside = document.getElementById("sidebar-nav") as HTMLElement;
        const last = lastFocusable(aside);
        last.focus();
        expect(last).toHaveFocus();

        fireEvent.keyDown(document, { key: "Tab" });

        // First tabbable control in the drawer (the heading itself is
        // tabindex=-1 and not part of the normal sequence).
        expect(screen.getByRole("button", { name: "Sign out" })).toHaveFocus();
      });

      it("wraps Shift+Tab backward from the drawer's first focusable control to its last", async () => {
        renderWithProviders();
        await screen.findByText("organization");
        fireEvent.click(screen.getByTestId("menu-toggle"));

        const aside = document.getElementById("sidebar-nav") as HTMLElement;
        const signOut = screen.getByRole("button", { name: "Sign out" });
        signOut.focus();
        expect(signOut).toHaveFocus();

        fireEvent.keyDown(document, { key: "Tab", shiftKey: true });

        expect(lastFocusable(aside)).toHaveFocus();
      });

      it("does not trap Tab at the lg breakpoint, even if drawerOpen is somehow true", async () => {
        const originalMatchMedia = window.matchMedia;
        window.matchMedia = ((query: string) =>
          ({
            matches: true,
            media: query,
            onchange: null,
            addListener: () => {},
            removeListener: () => {},
            addEventListener: () => {},
            removeEventListener: () => {},
            dispatchEvent: () => false,
          }) as unknown as MediaQueryList) as typeof window.matchMedia;

        try {
          renderWithProviders();
          await screen.findByText("organization");
          // The toggle button is only visually hidden (lg:hidden) at this
          // breakpoint, not removed -- clicking it still flips drawerOpen.
          fireEvent.click(screen.getByTestId("menu-toggle"));

          const aside = document.getElementById("sidebar-nav") as HTMLElement;
          const last = lastFocusable(aside);
          last.focus();

          fireEvent.keyDown(document, { key: "Tab" });

          // Not wrapped -- the static sidebar is never a focus trap.
          expect(last).toHaveFocus();
        } finally {
          window.matchMedia = originalMatchMedia;
        }
      });
    });
  });

  // fix round 1: <main> is now the shell's own scroll container (see the
  // h-screen/overflow-y-auto layout above), so the browser's native
  // href="#main" jump -- which scrolls the target's ancestors into view --
  // found main already filling the viewport and left its internal
  // scrollTop untouched, even though focus landed correctly.
  it("resets main's own scroll position (not just focus) when the skip link is activated", async () => {
    renderWithProviders();
    await screen.findByText("organization");

    const main = document.getElementById("main") as HTMLElement;
    main.scrollTop = 305;
    expect(main.scrollTop).toBe(305);

    fireEvent.click(screen.getByRole("link", { name: "Skip to content" }));

    expect(main).toHaveFocus();
    expect(main.scrollTop).toBe(0);
  });

  // H-9: both controls used to be text with zero vertical padding (Sign out 44x16px, each nav
  // group toggle 223x16px) -- under the WCAG 2.2 24x24 Target Size minimum. jsdom has no layout,
  // so real pixel measurement happens in the Playwright harness (fw_h9_target_sizes.js); this
  // guards the regression at the class level so a future edit can't silently drop the padding.
  it("gives Sign out and the nav group toggles enough vertical padding to clear the 24px Target Size floor", async () => {
    renderWithProviders();
    await screen.findByText("organization");

    const signOut = screen.getByRole("button", { name: "Sign out" });
    expect(signOut.className).toMatch(/py-2/);

    const groupToggle = screen.getByRole("button", { name: "Access" });
    expect(groupToggle.className).toMatch(/py-2/);
  });

  describe("nav goes offline (D-7)", () => {
    afterEach(() => {
      onlineManager.setOnline(true);
    });

    it("shows an offline notice instead of an indefinite 'Loading navigation…' when the schema query is paused", async () => {
      // React Query's default networkMode ("online") pauses a query -- rather than running its
      // queryFn and failing -- whenever the shared onlineManager reports offline (which, in a
      // real browser, tracks the window 'online'/'offline' events driven by navigator.onLine).
      // Drive that directly instead of faking fetchStatus, so this exercises the real pause path.
      onlineManager.setOnline(false);
      // Never resolves -- a genuinely paused query never calls queryFn at all, so this would
      // never resolve for real offline either; the mock just has to not resolve on its own.
      (apiFetch as any).mockImplementation(() => new Promise(() => {}));

      renderWithProviders();

      expect(await screen.findByTestId("offline-notice")).toHaveTextContent(/offline/i);
      expect(screen.queryByText("Loading navigation…")).not.toBeInTheDocument();
    });
  });
});
