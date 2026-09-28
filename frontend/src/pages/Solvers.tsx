import { useState } from "react";
import { Link } from "react-router-dom";
import OfflineNotice from "../components/OfflineNotice";
import Skeleton from "../components/Skeleton";
import { useToast } from "../components/ToastProvider";
import { formatApiError } from "../api/errors";
import {
  useRemoveSolverLicence,
  useRunConformance,
  useSetSolverLicence,
  useSolverLicences,
  useSolvers,
  type ConformanceReport,
  type SolverInfo,
  type SolverLicence,
} from "../api/v1";
import { useDocumentTitle } from "../hooks/useDocumentTitle";

/**
 * Solvers (queue R44): every solver this platform can use -- the built-ins, and any added from a
 * manifest (docs/solver-adapters.md) -- with whether it is here, whether the rules may choose it
 * unasked, its conformance report and, for one that needs it, this organization's licence.
 *
 * A licence is write-only: this page sends it and never shows it again, only whether one is set,
 * when, by whom, and a fingerprint that tells two apart. Running the conformance kit is an
 * operator's act: passing makes a solver eligible to be chosen unasked for every organization.
 */

function when(value: string | undefined | null): string {
  return value ? new Date(value).toLocaleString() : "—";
}

function Conformance({ solver }: { solver: SolverInfo }) {
  if (solver.origin !== "adapter") return <span className="text-slate-500">built in</span>;
  const report = solver.conformance;
  if (!report) return <span className="text-slate-600">not run</span>;
  if (!report.current) return <span className="text-amber-800">run on {report.version}, not this version</span>;
  if (!report.passed)
    return <span className="text-red-700" title={report.failed.join(", ")}>failed: {report.failed.join(", ")}</span>;
  return (
    <span className="text-green-800" title={report.notes.join("\n")}>
      passed {when(report.ran_at)}
      {report.notes.length > 0 ? ` (${report.notes.length} note${report.notes.length > 1 ? "s" : ""})` : ""}
    </span>
  );
}

function LicenceForm({ licence, onDone }: { licence: SolverLicence; onDone: () => void }) {
  const toast = useToast();
  const save = useSetSolverLicence();
  const [values, setValues] = useState<Record<string, string>>({});
  const [file, setFile] = useState("");
  const [failure, setFailure] = useState<string | null>(null);

  function submit(event: React.FormEvent) {
    event.preventDefault();
    setFailure(null);
    const env = Object.fromEntries(Object.entries(values).filter(([, v]) => v !== ""));
    save.mutate(
      { adapter: licence.adapter, licence: { ...(Object.keys(env).length ? { env } : {}), ...(file ? { file } : {}) } },
      {
        onSuccess: (done) => {
          // Forget what was typed: the page never holds a licence longer than the request.
          setValues({});
          setFile("");
          toast.success(`Licence for ${licence.adapter} set (${done.fingerprint})`);
          onDone();
        },
        onError: (error) => setFailure(formatApiError(error)),
      }
    );
  }

  return (
    <form onSubmit={submit} aria-label={`Licence for ${licence.adapter}`} className="mt-2 rounded-md border border-slate-200 bg-slate-50 p-3">
      <p className="mb-2 text-xs text-slate-600">
        Sent once and stored encrypted. It is never shown again -- only that it is set, and its fingerprint.
      </p>
      {licence.env.map((name) => (
        <label key={name} className="mb-2 flex flex-col text-sm text-slate-700">
          <code>{name}</code>
          <input
            type="password"
            autoComplete="off"
            value={values[name] ?? ""}
            onChange={(event) => setValues({ ...values, [name]: event.target.value })}
            className="mt-1 w-96 max-w-full rounded-md border border-slate-300 px-2 py-1"
          />
        </label>
      ))}
      {licence.file && (
        <label className="mb-2 flex flex-col text-sm text-slate-700">
          Licence file
          <textarea
            value={file}
            onChange={(event) => setFile(event.target.value)}
            rows={4}
            spellCheck={false}
            className="mt-1 w-96 max-w-full rounded-md border border-slate-300 px-2 py-1 font-mono text-xs"
          />
        </label>
      )}
      {failure && (
        <p role="alert" className="mb-2 text-sm text-red-700">
          {failure}
        </p>
      )}
      <div className="flex gap-2">
        <button type="submit" disabled={save.isPending} className="rounded-md bg-blue-700 px-3 py-1 text-sm text-white disabled:opacity-60">
          {save.isPending ? "Saving…" : "Save licence"}
        </button>
        <button type="button" onClick={onDone} className="px-2 py-1 text-sm text-slate-600 underline">
          Cancel
        </button>
      </div>
    </form>
  );
}

function Report({ report }: { report: ConformanceReport }) {
  return (
    <div role="status" aria-label="Conformance report" className={`mt-2 rounded-md border p-3 text-sm ${report.passed ? "border-green-300 bg-green-50" : "border-red-300 bg-red-50"}`}>
      <p className="font-medium">
        {report.adapter} {report.version}: {report.passed ? "passed -- it may now be chosen unasked" : "failed -- it runs only when named"}
      </p>
      <ul className="mt-1 space-y-0.5 text-xs">
        {report.checks.map((c) => (
          <li key={c.check}>
            <span className={c.result === "fail" ? "text-red-700" : c.result === "note" ? "text-amber-800" : "text-slate-700"}>
              {c.result}
            </span>{" "}
            <code>{c.check}</code> {c.detail}
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function Solvers() {
  useDocumentTitle("Solvers");
  const toast = useToast();
  const solvers = useSolvers();
  const licences = useSolverLicences();
  const remove = useRemoveSolverLicence();
  const conformance = useRunConformance();
  const [editing, setEditing] = useState<string | null>(null);
  const [report, setReport] = useState<ConformanceReport | null>(null);
  const licenceOf = new Map((licences.data?.items ?? []).map((l) => [l.adapter, l]));
  const skipped = solvers.data?.skipped ?? [];

  function runKit(name: string) {
    setReport(null);
    conformance.mutate(name, {
      onSuccess: (done) => setReport(done),
      onError: (error) => toast.error(formatApiError(error)),
    });
  }

  return (
    <div className="max-w-6xl">
      <h1 className="mb-1 text-lg font-semibold text-slate-900">Solvers</h1>
      <section aria-label="Worker availability" className="mb-4 rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm">
        <h2 className="font-semibold">Worker availability</h2>
        <p className="mt-1">Per-worker heartbeat status is not available on this screen. Review queue activity to investigate waiting or running solves.</p>
        <Link className="mt-2 inline-block py-2 text-blue-700 underline" to="/ops/queue">Open runs & queues</Link>
      </section>
      <p className="mb-4 max-w-3xl text-sm text-slate-600">
        The built-in solvers, and any added from a manifest -- Gurobi, Xpress, CPLEX or your own, with your licence
        (see <code className="rounded bg-slate-100 px-1">docs/solver-adapters.md</code>). An added solver runs only when
        named until its current version passes the conformance kit. Which solvers may run at all is set on{" "}
        <Link to="/settings" className="underline">Settings</Link> (<code>solve.allowed_solvers</code>,{" "}
        <code>solve.denied_solvers</code>).
      </p>
      <OfflineNotice />

      {skipped.length > 0 && (
        <section role="alert" className="mb-4 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm" aria-label="Manifests not loaded">
          <h2 className="font-medium text-amber-900">Manifests not loaded</h2>
          <ul className="mt-1 list-disc pl-5 text-amber-900">
            {skipped.map((s) => (
              <li key={s.folder}>
                <code>{s.folder}</code>: {s.reason}
              </li>
            ))}
          </ul>
        </section>
      )}

      {report && <Report report={report} />}

      {solvers.isLoading ? (
        <Skeleton rows={5} cols={7} />
      ) : (
        <div className="mt-2 overflow-x-auto">
          <table className="w-full table-auto border-collapse text-sm">
            <caption className="sr-only">Solvers</caption>
            <thead>
              <tr className="border-b border-slate-200 text-left text-slate-600">
                <th scope="col" className="py-2 pr-3 font-medium">Solver</th>
                <th scope="col" className="py-2 pr-3 font-medium">Where from</th>
                <th scope="col" className="py-2 pr-3 font-medium">Solves</th>
                <th scope="col" className="py-2 pr-3 font-medium">Here</th>
                <th scope="col" className="py-2 pr-3 font-medium">Chosen unasked</th>
                <th scope="col" className="py-2 pr-3 font-medium">Conformance</th>
                <th scope="col" className="py-2 pr-3 font-medium">Licence</th>
                <th scope="col" className="py-2 font-medium"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {(solvers.data?.items ?? []).map((s) => {
                const licence = licenceOf.get(s.name);
                return (
                  <tr key={s.name} className="border-b border-slate-100 align-top" data-testid={`solver-${s.name}`}>
                    <td className="py-2 pr-3">
                      <div className="font-medium text-slate-900">{s.name}</div>
                      <div className="text-xs text-slate-500">{s.note}</div>
                    </td>
                    <td className="py-2 pr-3 text-xs">
                      {s.origin === "adapter" ? `added (${s.kind} ${s.version})` : "built in"}
                    </td>
                    <td className="py-2 pr-3 text-xs">{s.classes.join(", ")}</td>
                    <td className="py-2 pr-3">{s.available ? "yes" : <span className="text-amber-800">not installed</span>}</td>
                    <td className="py-2 pr-3">{s.automatic ? "yes" : <span className="text-slate-600">only when named</span>}</td>
                    <td className="py-2 pr-3 text-xs"><Conformance solver={s} /></td>
                    <td className="py-2 pr-3 text-xs">
                      {s.licence === "set" ? (
                        <span className="text-green-800" title={`set by ${licence?.set_by ?? "?"}, ${when(licence?.set_at)}`}>
                          set ({licence?.fingerprint})
                        </span>
                      ) : s.licence === "missing" ? (
                        <span className="text-red-700">needed, not set</span>
                      ) : (
                        <span className="text-slate-500">not needed</span>
                      )}
                      {licence && editing === s.name && <LicenceForm licence={licence} onDone={() => setEditing(null)} />}
                    </td>
                    <td className="py-2">
                      <div className="flex flex-col items-start gap-1">
                        {licence && editing !== s.name && (
                          <button type="button" onClick={() => setEditing(s.name)} className="whitespace-nowrap text-sm text-blue-700 underline">
                            {licence.set ? "Replace licence" : "Set licence"}
                          </button>
                        )}
                        {licence?.set && (
                          <button
                            type="button"
                            onClick={() => {
                              if (!window.confirm(`Remove the licence for ${s.name}? Its runs will stop until one is set again.`)) return;
                              remove.mutate(s.name, {
                                onSuccess: () => toast.success(`Licence for ${s.name} removed`),
                                onError: (error) => toast.error(formatApiError(error)),
                              });
                            }}
                            className="whitespace-nowrap text-sm text-red-700 underline"
                          >
                            Remove licence
                          </button>
                        )}
                        {s.origin === "adapter" && s.available && (
                          <button
                            type="button"
                            disabled={conformance.isPending}
                            onClick={() => runKit(s.name)}
                            className="whitespace-nowrap text-sm text-blue-700 underline disabled:opacity-60"
                          >
                            {conformance.isPending && conformance.variables === s.name ? "Running the kit…" : "Run conformance kit"}
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
