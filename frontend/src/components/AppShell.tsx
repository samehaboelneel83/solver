import { Link, Outlet, useNavigate } from "react-router-dom";
import { setToken } from "../api/client";
import { useSchema } from "../api/meta";
import type { TableMeta } from "../types/meta";

export default function AppShell() {
  const { data: tables, isLoading, error } = useSchema();
  const navigate = useNavigate();

  const grouped: Record<string, TableMeta[]> = {};
  for (const t of tables ?? []) {
    (grouped[t.schema] ??= []).push(t);
  }

  function handleLogout() {
    setToken(null);
    navigate("/login");
  }

  return (
    <div className="flex min-h-screen">
      <aside className="w-64 shrink-0 border-r border-slate-200 bg-white p-4">
        <div className="mb-4 flex items-center justify-between">
          <span className="font-semibold text-slate-900">Problem Solver</span>
          <button onClick={handleLogout} className="text-xs text-slate-500 hover:text-slate-900">
            Sign out
          </button>
        </div>
        <Link to="/" className="mb-4 block text-sm text-slate-600 hover:text-slate-900">
          Dashboard
        </Link>
        <Link to="/graph" className="mb-4 block text-sm text-slate-600 hover:text-slate-900">
          Domain Graph
        </Link>
        {isLoading && <p className="text-sm text-slate-400">Loading navigation…</p>}
        {error && <p className="text-sm text-red-600">Failed to load navigation</p>}
        {Object.entries(grouped).map(([schemaName, schemaTables]) => (
          <div key={schemaName} className="mb-4">
            <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
              {schemaName}
            </div>
            <ul>
              {schemaTables.map((t) => (
                <li key={`${t.schema}.${t.table}`}>
                  <Link
                    to={`/${t.schema}/${t.table}`}
                    className="block rounded px-2 py-1 text-sm text-slate-700 hover:bg-slate-100"
                  >
                    {t.table}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </aside>
      <main className="flex-1 bg-slate-50 p-6">
        <Outlet />
      </main>
    </div>
  );
}
