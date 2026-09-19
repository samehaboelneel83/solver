import { onlineManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
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

const DOMAINS = [
  { id: 7, name: "alpha", created_at: "2026-09-19T10:00:00Z" },
  { id: 3, name: "beta", created_at: "2026-09-19T09:00:00Z" },
];

/** Waits for the domain selector's list to arrive, so no state update lands
 * after a test has finished (the nav itself is static and renders at once). */
async function settled() {
  await screen.findByRole("option", { name: "alpha" });
}

describe("AppShell", () => {
  beforeEach(() => {
    localStorage.clear();
    (apiFetch as any).mockImplementation((path: string) => {
      if (path.startsWith("/api/domain/")) return Promise.resolve({ items: DOMAINS, total: DOMAINS.length });
      return Promise.reject(new Error(`unexpected path ${path}`));
    });
  });

  describe("static navigation (Task 10)", () => {
    it("renders the three workflow groups -- Domain, Problem, Runs -- in that order", async () => {
      renderWithProviders();
      await settled();

      const nav = screen.getByRole("navigation", { name: "Main" });
      const headings = within(nav)
        .getAllByRole("button", { expanded: true })
        .map((b) => b.textContent?.replace(/[▾▸]/g, "").trim());
      expect(headings.slice(0, 3)).toEqual(["Domain", "Problem", "Runs"]);
    });

    it("links each group's pages from a static map", async () => {
      renderWithProviders();
      await settled();

      expect(screen.getByRole("link", { name: "Domains" })).toHaveAttribute("href", "/public/domain");
      expect(screen.getByRole("link", { name: "Problems" })).toHaveAttribute("href", "/public/problem");
      expect(screen.getByRole("link", { name: "Templates" })).toHaveAttribute("href", "/public/template");
      // Access administration stays reachable, in its own group after the three.
      expect(screen.getByRole("link", { name: "Organizations" })).toHaveAttribute("href", "/iam/organization");
      expect(screen.getByRole("link", { name: "Users" })).toHaveAttribute("href", "/iam/user_account");
    });

    it("says plainly that runs have no screens yet, rather than rendering an empty group", async () => {
      renderWithProviders();
      await settled();
      expect(screen.getByText(/no run screens yet/i)).toBeInTheDocument();
    });

    it("does not build the nav from /api/meta/schema", async () => {
      renderWithProviders();
      await settled();
      const paths = (apiFetch as any).mock.calls.map((call: unknown[]) => call[0]);
      expect(paths.some((path: string) => path.startsWith("/api/meta"))).toBe(false);
    });

    it("renders the domain selector in the sidebar, above the page links", async () => {
      renderWithProviders();
      await settled();
      const aside = document.getElementById("sidebar-nav") as HTMLElement;
      const select = within(aside).getByRole("combobox", { name: "Domain" });
      const firstNavLink = within(aside).getByRole("link", { name: "Dashboard" });
      expect(select.compareDocumentPosition(firstNavLink) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    });
  });

  it("renders a 'Skip to content' link as the first focusable element, targeting #main", async () => {
    renderWithProviders();
    await settled();

    const links = screen.getAllByRole("link");
    expect(links[0]).toHaveTextContent("Skip to content");
    expect(links[0]).toHaveAttribute("href", "#main");
  });

  it("marks the nav link for the current route as active and leaves the others plain", async () => {
    renderWithProviders(["/public/domain"]);
    await settled();
    const activeLink = screen.getByRole("link", { name: "Domains" });
    const otherLink = screen.getByRole("link", { name: "Problems" });

    expect(activeLink).toHaveAttribute("aria-current", "page");
    expect(activeLink.className).not.toBe(otherLink.className);
    expect(otherLink).not.toHaveAttribute("aria-current");
  });

  it("renders <main> as a shrinkable flex child with id=main", async () => {
    renderWithProviders();
    await settled();

    const main = document.getElementById("main");
    expect(main).not.toBeNull();
    expect(main?.className.split(/\s+/)).toContain("min-w-0");
  });

  describe("collapsible groups (A-4)", () => {
    it("hides a group's pages when its heading is clicked, and shows them again on a second click", async () => {
      renderWithProviders();
      await settled();

      const heading = screen.getByRole("button", { name: "Problem" });
      expect(screen.getByRole("link", { name: "Problems" })).toBeInTheDocument();

      fireEvent.click(heading);
      expect(heading).toHaveAttribute("aria-expanded", "false");
      expect(screen.queryByRole("link", { name: "Problems" })).not.toBeInTheDocument();
      // The other groups are untouched.
      expect(screen.getByRole("link", { name: "Domains" })).toBeInTheDocument();

      fireEvent.click(heading);
      expect(screen.getByRole("link", { name: "Problems" })).toBeInTheDocument();
    });

    it("persists a collapsed group's state in localStorage and restores it on the next mount", async () => {
      const { unmount } = renderWithProviders();
      await settled();

      fireEvent.click(screen.getByRole("button", { name: "Problem" }));
      expect(screen.queryByRole("link", { name: "Problems" })).not.toBeInTheDocument();

      const stored = JSON.parse(localStorage.getItem("solver_nav_open_groups") ?? "{}");
      expect(stored.problem).toBe(false);

      unmount();

      renderWithProviders();
      await settled();
      // Restored collapsed -- the page link stays hidden without clicking again.
      expect(screen.queryByRole("link", { name: "Problems" })).not.toBeInTheDocument();
      expect(screen.getByRole("link", { name: "Domains" })).toBeInTheDocument();
    });
  });

  it("narrows the visible pages via the filter box, hiding groups with no match", async () => {
    renderWithProviders();
    await settled();

    fireEvent.change(screen.getByPlaceholderText("Filter pages…"), { target: { value: "templ" } });

    expect(screen.getByRole("link", { name: "Templates" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Problems" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Domains" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Domain" })).not.toBeInTheDocument();
  });

  it("matches the filter against the group name too", async () => {
    renderWithProviders();
    await settled();

    fireEvent.change(screen.getByPlaceholderText("Filter pages…"), { target: { value: "access" } });

    expect(screen.getByRole("link", { name: "Organizations" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Domains" })).not.toBeInTheDocument();
  });

  it("scrolls the nav region independently of the rest of the sidebar", async () => {
    renderWithProviders();
    await settled();

    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(nav.className).toContain("overflow-y-auto");
  });

  describe("drawer below the lg breakpoint (G-2/G-5)", () => {
    it("always renders a menu toggle button, hidden above the drawer breakpoint via a responsive class", async () => {
      renderWithProviders();
      await settled();

      const toggle = screen.getByTestId("menu-toggle");
      expect(toggle).toBeInTheDocument();
      expect(toggle.className).toContain("lg:hidden");
    });

    it("opens the sidebar via the menu button and closes it again on Escape", async () => {
      renderWithProviders();
      await settled();

      const toggle = screen.getByTestId("menu-toggle");
      expect(toggle).toHaveAttribute("aria-expanded", "false");

      fireEvent.click(toggle);
      expect(toggle).toHaveAttribute("aria-expanded", "true");

      fireEvent.keyDown(document, { key: "Escape" });
      expect(toggle).toHaveAttribute("aria-expanded", "false");
    });

    it("closes the drawer on route change", async () => {
      renderWithProviders();
      await settled();

      const toggle = screen.getByTestId("menu-toggle");
      fireEvent.click(toggle);
      expect(toggle).toHaveAttribute("aria-expanded", "true");

      fireEvent.click(screen.getByRole("link", { name: "Problems" }));
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
        await settled();

        // The default jsdom matchMedia stub reports "not desktop".
        const aside = document.getElementById("sidebar-nav");
        expect(aside).toHaveAttribute("inert");
      });

      it("removes inert and moves focus into the drawer when it opens", async () => {
        renderWithProviders();
        await settled();

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
        await settled();

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
        await settled();

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
          await settled();

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
      await settled();

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
        await settled();
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
        await settled();
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
          await settled();
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
    await settled();

    const main = document.getElementById("main") as HTMLElement;
    main.scrollTop = 305;
    expect(main.scrollTop).toBe(305);

    fireEvent.click(screen.getByRole("link", { name: "Skip to content" }));

    expect(main).toHaveFocus();
    expect(main.scrollTop).toBe(0);
  });

  // Twin of the skip-link fix above, for the other place focus moves to
  // <main>: the route-change effect used to call mainRef.current?.focus()
  // alone, which (per the skip-link comment) scrolls *ancestors* into view,
  // not main's own internal scrollTop -- so navigating away from a scrolled
  // list opened the destination route mid-content instead of at the top.
  it("resets main's own scroll position (not just focus) on a route change", async () => {
    renderWithProviders(["/iam/organization"]);
    await settled();

    const main = document.getElementById("main") as HTMLElement;
    main.scrollTop = 240;
    expect(main.scrollTop).toBe(240);

    fireEvent.click(screen.getByRole("link", { name: "Problems" }));

    expect(main).toHaveFocus();
    expect(main.scrollTop).toBe(0);
  });

  // H-9: both controls used to be text with zero vertical padding (Sign out 44x16px, each nav
  // group toggle 223x16px) -- under the WCAG 2.2 24x24 Target Size minimum. jsdom has no layout,
  // so real pixel measurement happens in the Playwright harness (fw_h9_target_sizes.js); this
  // guards the regression at the class level so a future edit can't silently drop the padding.
  it("gives Sign out and the nav group toggles enough vertical padding to clear the 24px Target Size floor", async () => {
    renderWithProviders();
    await settled();

    const signOut = screen.getByRole("button", { name: "Sign out" });
    expect(signOut.className).toMatch(/py-2/);

    const groupToggle = screen.getByRole("button", { name: "Domain" });
    expect(groupToggle.className).toMatch(/py-2/);
  });

  describe("sidebar goes offline (D-7)", () => {
    afterEach(() => {
      onlineManager.setOnline(true);
    });

    it("keeps the static nav usable and shows the offline notice for the domain list when its query is paused", async () => {
      // React Query's default networkMode ("online") pauses a query -- rather than running its
      // queryFn and failing -- whenever the shared onlineManager reports offline. Drive that
      // directly instead of faking fetchStatus, so this exercises the real pause path.
      onlineManager.setOnline(false);
      (apiFetch as any).mockImplementation(() => new Promise(() => {}));

      renderWithProviders();

      expect(await screen.findByTestId("offline-notice")).toHaveTextContent(/offline/i);
      // The nav no longer depends on any request, so it is all still there.
      expect(screen.getByRole("link", { name: "Domains" })).toBeInTheDocument();
      expect(screen.queryByText("Loading navigation…")).not.toBeInTheDocument();
    });
  });
});
