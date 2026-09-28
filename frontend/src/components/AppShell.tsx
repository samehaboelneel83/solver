import { MouseEvent, useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import {
  Activity, Archive, Bell, BookOpen, Boxes, ChevronDown, ChevronLeft, ChevronRight, CircleHelp, Database, FileStack, FlaskConical, FolderTree,
  GitBranch, Home, Cpu,
  KeyRound, Languages, LayoutTemplate, LogOut, Menu, Moon, Network, Play, ScrollText, Search, Settings,
  ShieldCheck, SlidersHorizontal, Sun, Table2, UserCog, Users, Waypoints, Workflow, type LucideIcon,
} from "lucide-react";
import { setToken } from "../api/client";
import { applyDirection, applyTheme, isDark, storedDirection, storedTheme, type ThemeChoice } from "../lib/theme";
import CommandPalette from "./CommandPalette";
import RecentRuns from "./RecentRuns";
import ContextHeader from "./ContextHeader";
import ReachabilityBanner from "./ReachabilityBanner";
import { useCapabilities } from "../hooks/useCapability";
import { UnsavedChangesProvider, useConfirmLeave } from "../hooks/useUnsavedChangesGuard";
import DomainSelector from "./DomainSelector";
import { buildNavGroups, buildSidebarGroups, destinationForPath, stripDomainPrefix } from "../nav/registry";
import { DomainRouteProvider, useDomain } from "../hooks/useDomain";
import { parseRouteId } from "../lib/routeId";

// H-9: a full app-wide target-size sweep (beyond the three controls the finding named) turned
// up these two links themselves at 223x20px -- text-sm's 20px line-height with no padding,
// still under the 24px floor even after Sign out/the group toggles/Show identifiers were fixed.
// py-1 brings them to 28px without disturbing the sidebar's own vertical rhythm (mb-4 is
// unchanged, so the gap between links stays the same).
// R22: every link the same shape -- an icon, the label, the active page in the accent's
// soft green with a bar on the start edge (the screenshot's look), hover a quiet grey.
const linkBase = "relative flex items-center gap-3 rounded-lg px-2.5 py-1.5 text-sm transition-colors";
const activeLink = "bg-blue-50 font-semibold text-blue-800 before:absolute before:inset-y-1 before:start-0 before:w-0.5 before:rounded-full before:bg-blue-600";
const idleLink = "text-slate-600 hover:bg-slate-100 hover:text-slate-900";

const tableLinkClassName = ({ isActive }: { isActive: boolean }) => `${linkBase} ${isActive ? activeLink : idleLink}`;

/** Each page's icon (lucide), by its route. */
const ICONS: Record<string, LucideIcon> = {
  "/": Home,
  "/home": Home,
  "/graph": Network,
  "/public/domain": FolderTree,
  "/domains": FolderTree,
  "/entity-types": Boxes,
  "/relationship-types": Waypoints,
  "/relationships": GitBranch,
  "/entities": Database,
  "/parameters": SlidersHorizontal,
  "/public/problem": FlaskConical,
  "/model": Workflow,
  "/versions": FileStack,
  "/scenarios": BookOpen,
  "/public/template": LayoutTemplate,
  "/templates": LayoutTemplate,
  "/runs": Play,
  "/workspace": Table2,
  "/settings": Settings,
  "/solvers": Cpu,
  "/ops/queue": Activity,
  "/ops/audit": ScrollText,
  "/ops/backups": Archive,
  "/help/getting-started": CircleHelp,
  "/help/modeling": BookOpen,
  "/help/coverage": FileStack,
  "/help/api": BookOpen,
  "/help/release-notes": ScrollText,
  "/help/install": Archive,
  "/api-keys": KeyRound,
  "/iam/organization": Users,
  "/iam/user_account": UserCog,
  "/iam/role": ShieldCheck,
  "/iam/user_role": ShieldCheck,
  "/iam/role_capability": ShieldCheck,
  "/iam/capability": ShieldCheck,
};

function NavIcon({ to }: { to: string }) {
  const legacy = stripDomainPrefix(to.split("?")[0] ?? to);
  const Icon = ICONS[legacy] ?? ICONS[to] ?? Table2;
  return <Icon className="h-4 w-4 shrink-0" aria-hidden />;
}

const COLLAPSED_STORAGE_KEY = "solver_nav_collapsed";

type NavItem = { to: string; label: string; id?: string; /** Hide unless `GET /me` lists this. */ capability?: string };
type NavGroup = {
  /** Stable key for the collapse state in localStorage. */
  key: string;
  label: string;
  items: NavItem[];
  /** Shown instead of links when a group has none yet. */
  emptyNote?: string;
  footer?: boolean;
};

/**
 * Sidebar groups from `nav/registry` (OAAS N01): planner-centred labels,
 * Administration separated. Paths become domain-scoped when a domain is selected.
 */
export const NAV_GROUPS: NavGroup[] = buildNavGroups();

/** The page the breadcrumb names: its group and label, or Home. */
export function whereAmI(pathname: string): { group: string | null; page: string; purpose?: string } {
  const dest = destinationForPath(pathname);
  if (dest) {
    const group = NAV_GROUPS.find((g) => g.items.some((i) => i.id === dest.id || i.to === dest.path));
    return { group: group?.label ?? null, page: dest.label, purpose: dest.purpose };
  }
  if (pathname === "/" || pathname === "/home") return { group: null, page: "Home" };
  return { group: null, page: "Page" };
}

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

/** The items of `group` that match `filter`: all of them when the group's
 * own name matches, otherwise those whose label does. */
function visibleItems(
  group: NavGroup,
  filter: string,
  can: (capability: string) => boolean
): NavItem[] {
  const allowed = group.items.filter((item) => !item.capability || can(item.capability));
  const needle = filter.trim().toLowerCase();
  if (!needle || group.label.toLowerCase().includes(needle)) return allowed;
  return allowed.filter((item) => item.label.toLowerCase().includes(needle));
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
    <DomainRouteProvider><UnsavedChangesProvider>
      <AppShellContent />
    </UnsavedChangesProvider></DomainRouteProvider>
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
  const { can } = useCapabilities();
  const { domainId } = useDomain();
  const [searchParams] = useSearchParams();
  const pathProblem = location.pathname.match(/^\/domains\/\d+\/problems\/(\d+)/);
  const problemId =
    parseRouteId(pathProblem?.[1] ?? null) ?? parseRouteId(searchParams.get("problem"));
  const navGroups = buildSidebarGroups(location.pathname, { domainId, problemId });

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
  // R22: the desktop sidebar can shrink to its icons; the choice is remembered.
  const [collapsedChoice, setCollapsedChoice] = useState<boolean>(() => {
    try {
      return localStorage.getItem(COLLAPSED_STORAGE_KEY) === "1";
    } catch {
      return false;
    }
  });
  const collapsed = collapsedChoice && isDesktop;
  const [theme, setTheme] = useState<ThemeChoice>(storedTheme);
  const [direction, setDirection] = useState(storedDirection);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [openMenu, setOpenMenu] = useState<null | "user" | "runs">(null);
  const { username } = useCapabilities();
  const where = whereAmI(location.pathname);

  function toggleCollapsed() {
    setCollapsedChoice((current) => {
      try {
        localStorage.setItem(COLLAPSED_STORAGE_KEY, current ? "0" : "1");
      } catch {
        // not remembered; still applies now
      }
      return !current;
    });
  }

  function toggleTheme() {
    const next: ThemeChoice = isDark(theme) ? "light" : "dark";
    applyTheme(next);
    setTheme(next);
  }

  function toggleDirection() {
    const next = direction === "rtl" ? "ltr" : "rtl";
    applyDirection(next);
    setDirection(next);
  }

  // Ctrl+K (or Cmd+K) opens the command search from anywhere.
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen(true);
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  // A menu closes on the next route change.
  useEffect(() => setOpenMenu(null), [location.pathname]);

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
    <div className="flex h-screen bg-slate-50">
      <a
        href="#main"
        onClick={handleSkipLinkClick}
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded-shell focus:bg-white focus:px-3 focus:py-2 focus:shadow-panel"
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
        className={`fixed inset-y-0 start-0 z-40 flex h-screen shrink-0 flex-col border-e border-slate-200/80 bg-white px-3 py-shell shadow-shell transition-[transform,width] duration-200 ease-in-out lg:static lg:translate-x-0 ${
          collapsed ? "w-16" : "w-64"
        } ${drawerOpen ? "translate-x-0" : "-translate-x-full rtl:translate-x-full lg:rtl:translate-x-0"}`}
      >
        <div className={`mb-shell flex items-center gap-2 ${collapsed ? "flex-col" : ""}`}>
          <span aria-hidden="true" className="grid h-8 w-8 shrink-0 place-items-center rounded-shell bg-blue-600 text-sm font-bold tracking-tight text-white shadow-sm">PS</span>
          {/* fix round 2: focus target when the drawer opens (see the effect
              above) -- non-interactive and `tabIndex={-1}` on purpose, so it
              never joins the normal Tab sequence itself, it's just somewhere
              safe to land focus before the user has pressed anything. */}
          <h2 ref={drawerHeadingRef} tabIndex={-1} className={`flex-1 whitespace-nowrap font-serif text-[15px] font-semibold tracking-tight text-slate-900 ${collapsed ? "sr-only" : ""}`}>
            Problem Solver
          </h2>
          {/* H-9: was text with no padding at all (44x16px) -- under the WCAG 2.2 24x24
              Target Size minimum. py-2 brings it to a full 32px tall without changing its
              position in the header row (items-center keeps it aligned with the heading). */}
          <button
            onClick={handleLogout}
            title="Sign out"
            className="inline-flex items-center rounded px-2 py-2 text-slate-500 hover:bg-slate-100 hover:text-slate-900"
          >
            <LogOut className="h-4 w-4" aria-hidden />
            <span className="sr-only">Sign out</span>
          </button>
          {isDesktop && (
            <button
              type="button"
              onClick={toggleCollapsed}
              aria-label={collapsed ? "Expand the sidebar" : "Collapse the sidebar"}
              className="rounded p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-900"
            >
              {collapsed === (direction === "rtl") ? <ChevronLeft className="h-4 w-4" aria-hidden /> : <ChevronRight className="h-4 w-4" aria-hidden />}
            </button>
          )}
        </div>
        {!collapsed && <DomainSelector />}

        {!collapsed && (
          <label className="mb-3 mt-2 block">
            <span className="sr-only">Filter navigation</span>
            <input
              type="search"
              value={filterText}
              onChange={(event) => setFilterText(event.target.value)}
              placeholder="Filter pages…"
              className="w-full rounded-shell border border-slate-300 bg-white px-2.5 py-1.5 text-sm shadow-sm"
            />
          </label>
        )}

        {/* A-4: scrolls independently of the rest of the sidebar, instead of
            relying on the whole page to grow. */}
        <nav aria-label="Main" className="min-h-0 flex-1 overflow-y-auto">
          {navGroups.map((group) => {
            const isOpen = openGroups[group.key] ?? true;
            const items = visibleItems(group, filterText, can);
            if (items.length === 0 && (filterText.trim() || !group.emptyNote)) return null;
            return (
              <div key={group.key} className="mb-4">
                {/* H-9: py-2 keeps the toggle above the 24px Target Size floor. */}
                <button
                  type="button"
                  onClick={() => toggleGroup(group.key)}
                  aria-expanded={isOpen}
                  className={`mb-1 flex w-full items-center justify-between rounded px-1 py-2 text-[11px] font-semibold uppercase tracking-wider text-slate-500 hover:text-slate-700 ${collapsed ? "sr-only" : ""}`}
                >
                  <span>{group.label}</span>
                  <ChevronDown aria-hidden className={`h-3.5 w-3.5 transition-transform ${isOpen ? "" : "-rotate-90 rtl:rotate-90"}`} />
                </button>
                {isOpen &&
                  (items.length > 0 ? (
                    <ul>
                      {items.map((item) => (
                        <li key={item.to}>
                          <NavLink
                            to={item.to}
                            end={item.to === "/" || ["problems", "data-records", "data-structure"].includes(item.id ?? "")}
                            className={tableLinkClassName}
                            onClick={handleNavClick}
                            title={item.label}
                          >
                            <NavIcon to={item.to} />
                            <span className={collapsed ? "sr-only" : ""}>{item.label}</span>
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
        <button
          type="button"
          onClick={toggleDirection}
          title={direction === "rtl" ? "Left to right" : "Right to left"}
          className="mt-2 flex items-center gap-3 rounded-md px-2.5 py-1.5 text-sm text-slate-600 hover:bg-slate-100 hover:text-slate-900"
        >
          <Languages className="h-4 w-4 shrink-0" aria-hidden />
          <span className={collapsed ? "sr-only" : ""}>{direction === "rtl" ? "Left to right" : "Right to left"}</span>
        </button>
      </aside>

      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      <header className="flex h-14 shrink-0 items-center gap-3 border-b border-slate-200/80 bg-white px-shell shadow-sm">
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
          className="inline-flex items-center gap-2 rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-100 lg:hidden"
        >
          <Menu className="h-4 w-4" aria-hidden /> Menu
        </button>
        <nav aria-label="Breadcrumb" className="min-w-0 flex-1 truncate text-sm">
          <ol className="flex items-center gap-1.5">
            {where.group && where.group !== where.page && (
              <>
                <li className="text-slate-500">{where.group}</li>
                <li aria-hidden="true" className="text-slate-400">
                  <ChevronRight className="h-3.5 w-3.5 rtl:rotate-180" />
                </li>
              </>
            )}
            <li aria-current="page" className="font-semibold text-slate-900">{where.page}</li>
          </ol>
          {where.purpose && (
            <p className="mt-0.5 truncate text-xs font-normal text-slate-500">{where.purpose}</p>
          )}
        </nav>
        <ContextHeader />
        <button
          type="button"
          onClick={() => setPaletteOpen(true)}
          className="hidden items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-3 py-1.5 text-sm text-slate-500 hover:border-slate-300 sm:inline-flex"
        >
          <Search className="h-4 w-4" aria-hidden />
          <span className="w-32 text-start">Go to page…</span>
          <kbd className="rounded border border-slate-300 bg-white px-1.5 font-sans text-[11px] text-slate-500">Ctrl K</kbd>
        </button>
        <span title="The platform is in English" className="hidden items-center gap-1 rounded px-2 py-1.5 text-xs font-semibold text-slate-600 md:inline-flex">
          <Languages className="h-4 w-4" aria-hidden /> EN
        </span>
        <button
          type="button"
          onClick={toggleTheme}
          aria-label={isDark(theme) ? "Switch to the light theme" : "Switch to the dark theme"}
          className="rounded-md p-2 text-slate-600 hover:bg-slate-100 hover:text-slate-900"
        >
          {isDark(theme) ? <Sun className="h-4 w-4" aria-hidden /> : <Moon className="h-4 w-4" aria-hidden />}
        </button>
        <div className="relative">
          <button
            type="button"
            aria-label="Recent runs"
            aria-expanded={openMenu === "runs"}
            onClick={() => setOpenMenu((m) => (m === "runs" ? null : "runs"))}
            className="rounded-md p-2 text-slate-600 hover:bg-slate-100 hover:text-slate-900"
          >
            <Bell className="h-4 w-4" aria-hidden />
          </button>
          {openMenu === "runs" && <RecentRuns onClose={() => setOpenMenu(null)} />}
        </div>
        <div className="relative">
          <button
            type="button"
            aria-label="Account"
            aria-expanded={openMenu === "user"}
            onClick={() => setOpenMenu((m) => (m === "user" ? null : "user"))}
            className="flex items-center gap-2 rounded-md px-1.5 py-1 text-sm text-slate-700 hover:bg-slate-100"
          >
            <span aria-hidden="true" className="grid h-7 w-7 place-items-center rounded-full bg-blue-600 text-xs font-semibold uppercase text-white">
              {(username ?? "?").slice(0, 1)}
            </span>
            <span className="hidden font-medium md:inline">{username ?? ""}</span>
            <ChevronDown className="h-3.5 w-3.5 text-slate-400" aria-hidden />
          </button>
          {openMenu === "user" && (
            <div role="menu" className="absolute end-0 z-50 mt-1 w-44 rounded-md border border-slate-200 bg-white py-1 text-sm shadow-lg">
              <p className="truncate px-3 py-1.5 text-xs text-slate-500">Signed in as {username}</p>
              <button type="button" role="menuitem" onClick={() => navigate("/settings")} className="flex w-full items-center gap-2 px-3 py-1.5 text-start text-slate-700 hover:bg-slate-100">
                <Settings className="h-4 w-4" aria-hidden /> Settings
              </button>
              <button type="button" role="menuitem" onClick={handleLogout} className="flex w-full items-center gap-2 px-3 py-1.5 text-start text-slate-700 hover:bg-slate-100">
                <LogOut className="h-4 w-4" aria-hidden /> Sign out of {username ?? "this account"}
              </button>
            </div>
          )}
        </div>
      </header>
      <ReachabilityBanner />
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
        className="min-h-0 min-w-0 flex-1 overflow-y-auto contain-layout bg-slate-50 px-shell py-shell-lg focus:outline-none sm:px-shell-lg"
      >
        <Outlet />
      </main>
      </div>
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} can={can} />
    </div>
  );
}
