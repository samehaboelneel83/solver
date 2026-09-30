/**
 * Is the platform working? (simplification plan, phase 5) Each part --
 * database, its version, the worker, the analytics store -- in a word, and
 * for a part that is down the command that brings it back. The rebuild
 * script ends here; no sign-in is needed, so it also answers "is it me or
 * the server?" from the login page. Checks again every few seconds.
 */
import { Link } from "react-router-dom";
import { useHealthDetails, type HealthCheck } from "../api/health";
import { useDocumentTitle } from "../hooks/useDocumentTitle";

function Row({ check }: { check: HealthCheck }) {
  const tone = check.ok ? "border-emerald-200 bg-emerald-50" : check.needed ? "border-red-300 bg-red-50" : "border-amber-300 bg-amber-50";
  const mark = check.ok ? "Working" : check.needed ? "Down" : "Not working";
  return (
    <li className={`rounded-md border p-3 ${tone}`}>
      <div className="flex flex-wrap items-baseline gap-2">
        <h2 className="font-semibold text-slate-900">{check.name}</h2>
        <span className={`text-xs font-semibold uppercase ${check.ok ? "text-emerald-800" : check.needed ? "text-red-800" : "text-amber-800"}`}>{mark}</span>
      </div>
      <p className="mt-1 text-sm text-slate-800">{check.says}</p>
      {check.fix && <p className="mt-1 text-sm text-slate-900"><span className="font-medium">To fix: </span><code className="whitespace-pre-wrap">{check.fix}</code></p>}
    </li>
  );
}

export default function Health() {
  useDocumentTitle("Health");
  const details = useHealthDetails();
  const checks = details.data?.checks ?? [];
  const down = checks.filter((c) => !c.ok && c.needed);
  const warn = checks.filter((c) => !c.ok && !c.needed);
  return (
    <main className="mx-auto max-w-3xl space-y-4 p-6">
      <h1 className="text-2xl font-semibold text-slate-900">Is the platform working?</h1>
      {details.isLoading && <p role="status" className="text-sm text-slate-600">Checking…</p>}
      {details.isError && !details.data && (
        <p role="alert" className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-900">
          The server does not answer. Start it with <code>docker compose up -d backend</code>, or run <code>scripts\rebuild.cmd</code>;
          this page checks again by itself.
        </p>
      )}
      {details.data && (
        <p role="status" className="text-sm font-medium text-slate-900">
          {down.length ? `${down.length} ${down.length === 1 ? "part is" : "parts are"} down: planning needs ${down.length === 1 ? "it" : "them"}.`
            : warn.length ? "Planning works. One extra is not working; see below."
              : "Everything is working."}
        </p>
      )}
      <ul className="space-y-2">{checks.map((check) => <Row key={check.name} check={check} />)}</ul>
      <p className="text-sm text-slate-600">Checked every few seconds. <Link className="text-blue-700 underline" to="/">Open the platform</Link></p>
    </main>
  );
}
