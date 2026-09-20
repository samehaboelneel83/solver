import { MouseEvent, useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { setToken } from "../api/client";
import { UnsavedChangesProvider, useConfirmLeave } from "../hooks/useUnsavedChangesGuard";
import DomainSelector from "./DomainSelector";

// H-9: a full app-wide target-size sweep (beyond the three controls the finding named) turned
// up these two links themselves at 223x20px -- text-sm's 20px line-height with no padding,
// still under the 24px floor even after Sign out/the group toggles/Show identifiers were fixed.
// py-1 brings them to 28px without disturbing the sidebar's own vertical rhythm (mb-4 is
// unchanged, so the gap between links stays the same).
const navLinkClassName = ({ isActive }: { isActive: boolean }) =>
  `mb-4 block rounded py-1 text-sm ${
    isActive ? "font-medium text-slate-900" : "text-slate-600 hover:text-slate-900"
  }`;

const tableLinkClassName = ({ isActive }: { isActive: boolean }) =>
  `block rounded px-2 py-1 text-sm ${
    isActive ? "bg-slate-100 font-medium text-slate-900" : "text-slate-700 hover:bg-slate-100"
  }`;

// A-4: the nav used to be 31 tables in one flat, un-collapsible list -- about
// 30% of it (the whole problem.* group) sat below the fold on a laptop
// viewport with no scroll cue and no way to narrow it down. Groups now
// collapse (state persisted here so it survives a reload) and a filter box
// narrows the visible tables.
const OPEN_GROUPS_STORAGE_KEY = "solver_nav_open_groups";

function loadOpenGroups(): Record<string, boolean> {
  try {
    const raw = localStorage.getItem(OPEN_GROUPS_STORAGE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function saveOpenGroups(state: Record<string, boolean>) {
  try {
    localStorage.setItem(OPEN_GROUPS_STORAGE_KEY, JSON.stringify(state));
  } catch {
    // localStorage unavailable (private mode, etc.) -- the collapse state
    // just won't survive a reload.
  }
}

type NavItem = { to: string; label: string };
type NavGroup = {
  /** Stable key for the collapse state in localStorage. */
  key: string;
  label: string;
  items: NavItem[];
  /** Shown instead of links when a group has none yet. */
  emptyNote?: string;
};

/**
 * The sidebar, as a static map (Task 10). It used to be built from
 * `/api/meta/schema`, one group per Postgres schema; schema v1 moved every
 * table into `public`, so the schema no longer says anything about where a
 * page belongs. Grouped instead the way a planner works: model the domain,
 * pose a problem, look at runs.
 *
 * Tasks 11-13 add their pages here (entity types, entities, parameters,
 * model versions) alongside their routes in `App.tsx` -- a link to a route
 * that doesn't exist yet would only lead to the not-found page. Task 14f
 * adds relationship types beside entity types: the two halves of a
 * domain's schema, before the rows that fill it in.
 *
 * `/public/<table>` is the generic list route for the three flat v1 tables;
 * `public` is the schema name `/api/meta/schema` reports for them.
 */
export const NAV_GROUPS: NavGroup[] = [
  {
    key: "domain",
    label: "Domain",
    items: [
      { to: "/public/domain", label: "Domains" },
      { to: "/entity-types", label: "Entity types" },
      { to: "/relationship-types", label: "Relationship types" },
      { to: "/relationships", label: "Relationships" },
      { to: "/entities", label: "Entities" },
      { to: "/parameters", label: "Parameters" },
    ],
  },
  {
    key: "problem",
    label: "Problem",
    items: [
      { to: "/public/problem", label: "Problems" },
      { to: "/versions", label: "Model versions" },
      { to: "/public/template", label: "Templates" },
    ],
  },
  {
    key: "runs",
    label: "Runs",
    items: [],
    // The RUN tables exist but are deliberately not wired (plan, Global Constraints).
    emptyNote: "No run screens yet: runs appear here once a solver is connected.",
  },
  {
    // Not one of the three workflow groups -- user and role administration,
    // kept reachable rather than dropped with the schema-driven nav.
    key: "access",
    label: "Access",
    items: [
      { to: "/iam/organization", label: "Organizations" },
      { to: "/iam/user_account", label: "Users" },
      { to: "/iam/role", label: "Roles" },
      { to: "/iam/user_role", label: "User roles" },
    ],
  },
];

/** The items of `group` that match `filter`: all of them when the group's
 * own name matches, otherwise those whose label does. */
function visibleItems(group: NavGroup, filter: string): NavItem[] {
  const needle = filter.trim().toLowerCase();
  if (!needle || group.label.toLowerCase().includes(needle)) return group.items;
  return group.items.filter((item) => item.label.toLowerCase().includes(needle));
}

// Matches the `lg` breakpoint in tailwind.config.js (also em-based, for the
// same reflow reasons -- see that file). Written in em here too so this JS
// check tracks the CSS one even when the root font size changes, instead of
// silently diverging from it at a raw pixel value.
//
// This and tailwind.config.js's `lg` value are two independent string
// literals -- nothing at build time ties them together, since the Tailwind
// config is loaded by Node/PostCSS outside the app's own TS/Vite pipeline
// and can't cleanly import from `src`. Exported so AppShell.breakpoint.test.tsx
// can read tailwind.config.js's own source and assert the two values still
// agree; that test is the actual guard against drift, not this comment.
export const DESKTOP_QUERY = "(min-width: 64em)";

function getIsDesktop(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
  return window.matchMedia(DESKTOP_QUERY).matches;
}

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** Every element inside `root` that a keyboard user could Tab to, in order. */
function focusableElements(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
}

export default function AppShell() {
  // Wraps the whole shell (nav + <Outlet />) in one shared "does the
  // currently-open form have unsaved changes?" guard (C-3): a routed page's
  // form registers itself via useUnsavedChangesGuard, and this component's
  // own nav links below consult it via useConfirmLeave before navigating.
  return (
    <UnsavedChangesProvider>
      <AppShellContent />
    </UnsavedChangesProvider>
  );
}

function AppShellContent() {
  const navigate = useNavigate();
  const location = useLocation();
  const mainRef = useRef<HTMLElement>(null);
  const asideRef = useRef<HTMLElement>(null);
  const menuToggleRef = useRef<HTMLButtonElement>(null);
  const drawerHeadingRef = useRef<HTMLHeadingElement>(null);
  const isFirstRender = useRef(true);
  const confirmLeave = useConfirmLeave();

  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>(() => loadOpenGroups());
  const [filterText, setFilterText] = useState("");
  // G-2/G-5: the sidebar used to be a fixed 256px at every viewport from
  // 375px to 1920px, eating 68.3% of a 375px screen. Below the `lg`
  // breakpoint it's now a drawer, hidden off-canvas until this opens it.
  const [drawerOpen, setDrawerOpen] = useState(false);
  // G-2 fix round 1: whether the sidebar is currently the static, always-
  // reachable desktop one (`lg`+) or the off-canvas drawer. Needed in JS
  // (not just CSS) because the two states have different accessibility
  // requirements below -- a *closed* drawer must be unreachable by keyboard/
  // AT, but the *static* sidebar must never be, regardless of `drawerOpen`.
  const [isDesktop, setIsDesktop] = useState(getIsDesktop);

  function handleLogout() {
    setToken(null);
    navigate("/login");
  }

  // C-3: a click on any sidebar link first asks the active form (if any)
  // whether it's OK to leave a dirty edit behind.
  function handleNavClick(event: MouseEvent) {
    if (!confirmLeave()) {
      event.preventDefault();
      return;
    }
    setDrawerOpen(false);
  }

  function toggleGroup(groupKey: string) {
    setOpenGroups((current) => {
      const isOpen = current[groupKey] ?? true;
      const next = { ...current, [groupKey]: !isOpen };
      saveOpenGroups(next);
      return next;
    });
  }

  // G-2 fix round 1: closing the drawer via Escape or the backdrop (as
  // opposed to a nav-link click, which navigates -- the existing H-11 effect
  // below already sends focus to <main> for that case) leaves focus with
  // nowhere sensible to land unless we send it back to the control that
  // opened the drawer.
  function closeDrawer() {
    setDrawerOpen(false);
    menuToggleRef.current?.focus();
  }

  // Move focus to the main content region on every route change so keyboard/screen-reader
  // users land somewhere sensible instead of focus falling back to <body> (H-11). Skipped on
  // first mount so loading the app doesn't yank focus away from wherever the browser put it.
  useEffect(() => {
    if (isFirstRender.current) {
      isFirstRender.current = false;
      return;
    }
    mainRef.current?.focus();
    // Same fix as the skip link's own handler below (see its comment): focus()
    // alone scrolls *ancestors* of the focused element into view, not main's
    // own internal scrollTop. Without this, navigating away from a scrolled
    // list opened the new route mid-content instead of at the top.
    if (mainRef.current) {
      mainRef.current.scrollTop = 0;
    }
  }, [location.pathname]);

  // The drawer closes on every route change (a nav click already closes it via
  // handleNavClick, but this also covers programmatic navigation) and on Escape.
  useEffect(() => {
    setDrawerOpen(false);
  }, [location.pathname]);

  // G-2 fix round 2: Escape closes the drawer as before; Tab/Shift+Tab are
  // now trapped within it while it's open *and* off-canvas (below `lg`) --
  // measured at 375px, tabbing forward from the drawer used to walk out
  // onto the Menu button, which the open drawer's own backdrop visually
  // covers (a real mouse click there hits the backdrop, not the button --
  // confirmed with elementFromPoint -- so keyboard and pointer disagreed
  // about what was reachable), and past it onto page content behind the
  // backdrop entirely. The static `lg`+ sidebar is not a modal and must
  // never trap Tab, hence the `isDesktop` guard -- matches `drawerInert`
  // below in spirit (that gate is JS-tracked for the same reason).
  useEffect(() => {
    if (!drawerOpen) return;
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        closeDrawer();
        return;
      }
      if (event.key !== "Tab" || isDesktop || !asideRef.current) return;
      const focusable = focusableElements(asideRef.current);
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drawerOpen, isDesktop]);

  // G-2 fix round 1: track the `lg` breakpoint in JS so the drawer's
  // accessibility state (below) can tell "closed drawer, below lg" (must be
  // unreachable) apart from "static sidebar, lg+" (must always be reachable,
  // independent of `drawerOpen`).
  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const mql = window.matchMedia(DESKTOP_QUERY);
    function handleChange(event: MediaQueryListEvent) {
      setIsDesktop(event.matches);
    }
    setIsDesktop(mql.matches);
    mql.addEventListener?.("change", handleChange);
    return () => mql.removeEventListener?.("change", handleChange);
  }, []);

  // G-2 fix round 1: below `lg`, a *closed* drawer used to stay fully in the
  // tab order and the accessibility tree while only translated off-screen --
  // measured at 375px, 11 of the first 12 tab stops were off-screen controls
  // (Sign out, Dashboard, Domain Graph, the filter input, every group
  // heading...) before a keyboard user ever reached page content. `inert`
  // removes the whole subtree from both while it applies.
  const drawerInert = !isDesktop && !drawerOpen;

  // ...and the reverse direction: when the drawer opens, move focus into it
  // (previously Tab from the Menu button went straight into the page content
  // behind the backdrop -- focus never entered the drawer at all). Targets
  // the drawer's own (non-interactive, tabindex=-1) heading rather than the
  // first focusable control -- fix round 2: that used to be "Sign out",
  // which is merely first in DOM order, leaving a user one Enter press from
  // logging out the moment the drawer opened. Tab from here still reaches
  // Sign out next, same as before -- this only changes what receives focus
  // *before* the user has pressed anything.
  useEffect(() => {
    if (isDesktop || !drawerOpen) return;
    drawerHeadingRef.current?.focus();
  }, [drawerOpen, isDesktop]);

  // A-11/skip-link fix round 1: `<main>` is now the scroll container (see
  // the h-screen/overflow-y-auto shell below), so the browser's native
  // href="#main" jump -- which scrolls the target's *ancestors* into view --
  // finds main already filling the viewport and leaves its own internal
  // scrollTop untouched. Handling the click directly resets that scroll
  // position as well as moving focus, instead of just the latter.
  function handleSkipLinkClick(event: MouseEvent<HTMLAnchorElement>) {
    event.preventDefault();
    mainRef.current?.focus();
    if (mainRef.current) {
      mainRef.current.scrollTop = 0;
    }
  }

  return (
    // G-4/WCAG 1.4.10 Reflow, fix round 1: the actual page-level
    // horizontal-scroll backstop lives in index.css (`html { overflow-x:
    // hidden }`) -- see that file's comment for why it has to be on <html>
    // specifically, not a class here or on <main>/the table's own wrapper.
    <div className="flex h-screen">
      <a
        href="#main"
        onClick={handleSkipLinkClick}
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2"
      >
        Skip to content
      </a>

      {/* G-2/G-5: backdrop behind the drawer on small screens, closing it on
          click. A real (if unusual) button rather than a div+onClick (fix
          round 1) -- `tabIndex={-1}` keeps it out of the normal Tab
          sequence (it's not meant to be tabbed to, just clicked/tapped),
          while still being a genuine interactive element with its own
          accessible name instead of a non-interactive node with a click
          handler bolted on. */}
      <button
        type="button"
        data-testid="sidebar-backdrop"
        tabIndex={-1}
        aria-label="Close navigation menu"
        onClick={closeDrawer}
        className={`fixed inset-0 z-30 cursor-default bg-slate-900/50 lg:hidden ${drawerOpen ? "block" : "hidden"}`}
      />

      <aside
        id="sidebar-nav"
        ref={asideRef}
        inert={drawerInert ? "" : undefined}
        className={`fixed inset-y-0 left-0 z-40 flex h-screen w-64 shrink-0 flex-col border-r border-slate-200 bg-white p-4 transition-transform duration-200 ease-in-out lg:static lg:translate-x-0 ${
          drawerOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="mb-4 flex items-center justify-between">
          {/* fix round 2: focus target when the drawer opens (see the effect
              above) -- non-interactive and `tabIndex={-1}` on purpose, so it
              never joins the normal Tab sequence itself, it's just somewhere
              safe to land focus before the user has pressed anything. */}
          <h2 ref={drawerHeadingRef} tabIndex={-1} className="font-semibold text-slate-900">
            Problem Solver
          </h2>
          {/* H-9: was text with no padding at all (44x16px) -- under the WCAG 2.2 24x24
              Target Size minimum. py-2 brings it to a full 32px tall without changing its
              position in the header row (items-center keeps it aligned with the heading). */}
          <button
            onClick={handleLogout}
            className="rounded px-2 py-2 text-xs text-slate-500 hover:text-slate-900"
          >
            Sign out
          </button>
        </div>
        <DomainSelector />
        <NavLink to="/" end className={navLinkClassName} onClick={handleNavClick}>
          Dashboard
        </NavLink>
        <NavLink to="/graph" className={navLinkClassName} onClick={handleNavClick}>
          Domain Graph
        </NavLink>

        <label className="mb-3 block">
          <span className="sr-only">Filter navigation</span>
          <input
            type="search"
            value={filterText}
            onChange={(event) => setFilterText(event.target.value)}
            placeholder="Filter pages…"
            className="w-full rounded-md border border-slate-300 px-2 py-1 text-sm"
          />
        </label>

        {/* A-4: scrolls independently of the rest of the sidebar, instead of
            relying on the whole page to grow. */}
        <nav aria-label="Main" className="min-h-0 flex-1 overflow-y-auto">
          {NAV_GROUPS.map((group) => {
            const isOpen = openGroups[group.key] ?? true;
            const items = visibleItems(group, filterText);
            if (filterText.trim() && items.length === 0) return null;
            return (
              <div key={group.key} className="mb-4">
                {/* H-9: py-2 keeps the toggle above the 24px Target Size floor. */}
                <button
                  type="button"
                  onClick={() => toggleGroup(group.key)}
                  aria-expanded={isOpen}
                  className="mb-1 flex w-full items-center justify-between rounded px-1 py-2 text-xs font-semibold uppercase tracking-wide text-slate-500 hover:text-slate-700"
                >
                  <span>{group.label}</span>
                  <span aria-hidden="true">{isOpen ? "▾" : "▸"}</span>
                </button>
                {isOpen &&
                  (items.length > 0 ? (
                    <ul>
                      {items.map((item) => (
                        <li key={item.to}>
                          <NavLink to={item.to} className={tableLinkClassName} onClick={handleNavClick}>
                            {item.label}
                          </NavLink>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    group.emptyNote && <p className="px-2 text-sm text-slate-500">{group.emptyNote}</p>
                  ))}
              </div>
            );
          })}
        </nav>
      </aside>

      <main
        id="main"
        tabIndex={-1}
        ref={mainRef}
        // G-4/WCAG 1.4.10 Reflow, fix round 1: `contain-layout` (CSS
        // `contain: layout`) is the confirmed real fix for a wide table
        // (DataTable.tsx's own `overflow-x-auto` wrapper) inflating the
        // *document's* scrollWidth at a 150% root font size -- verified in
        // a real browser that this stops it and that neither `overflow-y-
        // auto` above nor forcing `overflow: hidden` on this element or the
        // table's wrapper (even with !important) did. Containment makes
        // `main` a genuinely independent formatting context, so its
        // internal content categorically cannot affect an ancestor's
        // layout or scrolling area -- see index.css for the accompanying
        // `html { overflow-x: hidden }` backstop.
        // fix round 2: `contain: layout` is not *only* an overflow fix --
        // per spec it also makes this element a containing block for any
        // `position: fixed`/`absolute` descendant and a new stacking
        // context. That's safe today only because nothing inside `<main>`
        // is fixed-positioned; the first one added later (a modal, a
        // sticky toolbar) will silently size/position itself relative to
        // `<main>` instead of the viewport, with no error to flag it.
        // (DataTable.tsx's own row-actions menu portals to `document.body`
        // specifically to stay outside this containing block.)
        className="min-h-0 min-w-0 flex-1 overflow-y-auto contain-layout bg-slate-50 p-6"
      >
        {/* G-2/G-5: below `lg` the sidebar is a drawer, hidden until this
            toggles it -- always rendered (data-testid always present) so a
            small-screen user always has a way to open navigation, but hidden
            above the breakpoint via `lg:hidden` where the sidebar is static. */}
        <button
          type="button"
          ref={menuToggleRef}
          data-testid="menu-toggle"
          aria-expanded={drawerOpen}
          aria-controls="sidebar-nav"
          onClick={() => setDrawerOpen((open) => !open)}
          className="mb-4 inline-flex items-center gap-2 rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-white lg:hidden"
        >
          <span aria-hidden="true">☰</span> Menu
        </button>
        <Outlet />
      </main>
    </div>
  );
}
