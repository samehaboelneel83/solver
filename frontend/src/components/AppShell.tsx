import { MouseEvent, useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { setToken } from "../api/client";
import { useSchema } from "../api/meta";
import { UnsavedChangesProvider, useConfirmLeave } from "../hooks/useUnsavedChangesGuard";
import { tableLabelPlural } from "../lib/labels";
import type { TableMeta } from "../types/meta";

const navLinkClassName = ({ isActive }: { isActive: boolean }) =>
  `mb-4 block text-sm ${
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

function matchesFilter(table: TableMeta, filter: string): boolean {
  if (!filter) return true;
  const needle = filter.trim().toLowerCase();
  return (
    table.table.toLowerCase().includes(needle) ||
    tableLabelPlural(table).toLowerCase().includes(needle) ||
    table.schema.toLowerCase().includes(needle)
  );
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
  const { data: tables, isLoading, error } = useSchema();
  const navigate = useNavigate();
  const location = useLocation();
  const mainRef = useRef<HTMLElement>(null);
  const isFirstRender = useRef(true);
  const confirmLeave = useConfirmLeave();

  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>(() => loadOpenGroups());
  const [filterText, setFilterText] = useState("");
  // G-2/G-5: the sidebar used to be a fixed 256px at every viewport from
  // 375px to 1920px, eating 68.3% of a 375px screen. Below the `lg`
  // breakpoint it's now a drawer, hidden off-canvas until this opens it.
  const [drawerOpen, setDrawerOpen] = useState(false);

  const grouped: Record<string, TableMeta[]> = {};
  for (const t of tables ?? []) {
    (grouped[t.schema] ??= []).push(t);
  }

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

  function toggleGroup(schemaName: string) {
    setOpenGroups((current) => {
      const isOpen = current[schemaName] ?? true;
      const next = { ...current, [schemaName]: !isOpen };
      saveOpenGroups(next);
      return next;
    });
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
  }, [location.pathname]);

  // The drawer closes on every route change (a nav click already closes it via
  // handleNavClick, but this also covers programmatic navigation) and on Escape.
  useEffect(() => {
    setDrawerOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (!drawerOpen) return;
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setDrawerOpen(false);
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [drawerOpen]);

  return (
    <div className="flex h-screen">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2"
      >
        Skip to content
      </a>

      {/* G-2/G-5: backdrop behind the drawer on small screens, closing it on click. */}
      <div
        data-testid="sidebar-backdrop"
        aria-hidden="true"
        onClick={() => setDrawerOpen(false)}
        className={`fixed inset-0 z-30 bg-slate-900/50 lg:hidden ${drawerOpen ? "block" : "hidden"}`}
      />

      <aside
        id="sidebar-nav"
        className={`fixed inset-y-0 left-0 z-40 flex h-screen w-64 shrink-0 flex-col border-r border-slate-200 bg-white p-4 transition-transform duration-200 ease-in-out lg:static lg:translate-x-0 ${
          drawerOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="mb-4 flex items-center justify-between">
          <span className="font-semibold text-slate-900">Problem Solver</span>
          <button onClick={handleLogout} className="text-xs text-slate-500 hover:text-slate-900">
            Sign out
          </button>
        </div>
        <NavLink to="/" end className={navLinkClassName} onClick={handleNavClick}>
          Dashboard
        </NavLink>
        <NavLink to="/graph" className={navLinkClassName} onClick={handleNavClick}>
          Domain Graph
        </NavLink>

        <label className="mb-3 block">
          <span className="sr-only">Filter tables</span>
          <input
            type="search"
            value={filterText}
            onChange={(event) => setFilterText(event.target.value)}
            placeholder="Filter tables…"
            className="w-full rounded-md border border-slate-300 px-2 py-1 text-sm"
          />
        </label>

        {isLoading && <p className="text-sm text-slate-500">Loading navigation…</p>}
        {error && <p className="text-sm text-red-600">Failed to load navigation</p>}

        {/* A-4: this is the region that used to run 1120px tall with no scroll
            cue of its own -- it now scrolls independently of the rest of the
            shell instead of relying on the whole page to grow. */}
        <nav aria-label="Tables" className="min-h-0 flex-1 overflow-y-auto">
          {Object.entries(grouped).map(([schemaName, schemaTables]) => {
            const isOpen = openGroups[schemaName] ?? true;
            const visibleTables = schemaTables.filter((t) => matchesFilter(t, filterText));
            if (filterText && visibleTables.length === 0) return null;
            return (
              <div key={schemaName} className="mb-4">
                <button
                  type="button"
                  onClick={() => toggleGroup(schemaName)}
                  aria-expanded={isOpen}
                  className="mb-1 flex w-full items-center justify-between text-xs font-semibold uppercase tracking-wide text-slate-500 hover:text-slate-700"
                >
                  <span>{schemaName}</span>
                  <span aria-hidden="true">{isOpen ? "▾" : "▸"}</span>
                </button>
                {isOpen && (
                  <ul>
                    {visibleTables.map((t) => (
                      <li key={`${t.schema}.${t.table}`}>
                        <NavLink to={`/${t.schema}/${t.table}`} className={tableLinkClassName} onClick={handleNavClick}>
                          {tableLabelPlural(t)}
                        </NavLink>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            );
          })}
        </nav>
      </aside>

      <main id="main" tabIndex={-1} ref={mainRef} className="min-h-0 min-w-0 flex-1 overflow-y-auto bg-slate-50 p-6">
        {/* G-2/G-5: below `lg` the sidebar is a drawer, hidden until this
            toggles it -- always rendered (data-testid always present) so a
            small-screen user always has a way to open navigation, but hidden
            above the breakpoint via `lg:hidden` where the sidebar is static. */}
        <button
          type="button"
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
