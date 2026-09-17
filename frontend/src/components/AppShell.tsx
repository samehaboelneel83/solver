import { useEffect, useRef } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { setToken } from "../api/client";
import { useSchema } from "../api/meta";
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

export default function AppShell() {
  const { data: tables, isLoading, error } = useSchema();
  const navigate = useNavigate();
  const location = useLocation();
  const mainRef = useRef<HTMLElement>(null);
  const isFirstRender = useRef(true);

  const grouped: Record<string, TableMeta[]> = {};
  for (const t of tables ?? []) {
    (grouped[t.schema] ??= []).push(t);
  }

  function handleLogout() {
    setToken(null);
    navigate("/login");
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

  return (
    <div className="flex min-h-screen">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2"
      >
        Skip to content
      </a>
      <aside className="w-64 shrink-0 border-r border-slate-200 bg-white p-4">
        <div className="mb-4 flex items-center justify-between">
          <span className="font-semibold text-slate-900">Problem Solver</span>
          <button onClick={handleLogout} className="text-xs text-slate-500 hover:text-slate-900">
            Sign out
          </button>
        </div>
        <NavLink to="/" end className={navLinkClassName}>
          Dashboard
        </NavLink>
        <NavLink to="/graph" className={navLinkClassName}>
          Domain Graph
        </NavLink>
        {isLoading && <p className="text-sm text-slate-500">Loading navigation…</p>}
        {error && <p className="text-sm text-red-600">Failed to load navigation</p>}
        {Object.entries(grouped).map(([schemaName, schemaTables]) => (
          <div key={schemaName} className="mb-4">
            <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
              {schemaName}
            </div>
            <ul>
              {schemaTables.map((t) => (
                <li key={`${t.schema}.${t.table}`}>
                  <NavLink to={`/${t.schema}/${t.table}`} className={tableLinkClassName}>
                    {tableLabelPlural(t)}
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </aside>
      <main id="main" tabIndex={-1} ref={mainRef} className="flex-1 min-w-0 bg-slate-50 p-6">
        <Outlet />
      </main>
    </div>
  );
}
