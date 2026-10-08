import { useEffect, useId, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../api/client";
import { formatApiError } from "../api/errors";
import { useEntityTypes, useParameters, useRelationshipTypes, type EntityType, type ParameterDef, type RelationshipType } from "../api/v1";
import { uploadAgentFile } from "../api/agent";
import LoadFailure from "../components/LoadFailure";
import { useCapabilities } from "../hooks/useCapability";
import { useDocumentTitle } from "../hooks/useDocumentTitle";

/**
 * Sources & imports (Epic UX, U-4): set up a database source, run an extraction and
 * follow it, then -- in the import wizard -- preview the rows, map their columns onto
 * an entity type, a relationship type or a parameter, check every row, and load them
 * with their lineage recorded.
 */

type Connection = { id: number; name: string; enabled: boolean; config?: { schema?: string; table?: string; columns?: string[]; host?: string; url?: string; kind?: string; engine?: string; changed_column?: string } };
type TargetKind = "entity_type" | "relationship_type" | "parameter";
type Target = { kind: TargetKind; id: number; name: string };
type Load = {
  id: number; entity_type: string | null; target?: Target; rows_written: number; artifact_sha256: string; mapping_hash: string; created_at: string;
};

/** What one written row is, in each kind of target. */
const NOUN: Record<TargetKind, string> = { entity_type: "records", relationship_type: "links", parameter: "values" };

function loadedText(load: Load): string {
  const kind = load.target?.kind ?? "entity_type";
  const name = load.target?.name ?? load.entity_type ?? "";
  return `Loaded ${load.rows_written} ${name} ${NOUN[kind]}`;
}
export type Job = {
  id: number; state: "queued" | "running" | "extracted" | "failed" | "cancelled"; cancel_requested: boolean;
  created_at: string; finished_at: string | null; artifact_id: string | null; error_code: string | null; loads: Load[];
  incremental?: boolean;
};

const post = <T,>(path: string, body?: unknown) =>
  apiFetch<T>(path, { method: "POST", ...(body === undefined ? {} : { body: JSON.stringify(body) }) });

/** What a failed extraction's code means, and what to do about it. */
export const ERROR_TEXT: Record<string, string> = {
  extraction_failed: "The source could not be read. Check that the host is reachable from the import worker, that the credential is current, and that the table and columns exist.",
  deadline_exceeded: "The extraction ran past its time limit (about five minutes). Extract fewer columns, or a smaller table or view.",
  worker_lost: "The import worker stopped during the extraction. Run it again; nothing was changed.",
  authentication_failed: "The database refused the user name or password. Check the user exists on the source and replace the credential.",
  tls_failed: "The secure connection could not be verified. The source's certificate must be signed by the CA this server trusts and name the host you entered.",
  source_unreachable: "The database could not be reached from the import worker. Check the host name and port, and that the database is running and accepts connections.",
  network_not_allowed: "The database's address is outside the networks this server may connect to. An administrator can add its network to the integration policy.",
  source_missing: "The database, schema, table or one of the columns was not found on the source. Check the names (they are case-sensitive).",
  not_permitted: "The database user may not read this table or one of its columns. Grant it SELECT on them.",
  trust_unavailable: "This server has no trusted certificate for database connections. An administrator needs to install the CA file.",
  credential_unreadable: "The stored password cannot be decrypted with this server's keys (the keys changed). Replace the credential.",
  format_invalid: "The answer could not be read as the format chosen (JSON list, CSV or Excel), or the list is not where it was said to be.",
  limit_exceeded: "The table is larger than one extraction allows (100,000 rows or 20 MB). Extract fewer columns, or a smaller table or view.",
};

const STATE_TEXT: Record<Job["state"], string> = {
  queued: "Waiting for the import worker",
  running: "Extracting",
  extracted: "Extracted: ready to import",
  failed: "Failed",
  cancelled: "Cancelled",
};

type Binding = {
  id: number; connection_id: number | null; connection: string; file_name: string | null; file_version: number | null;
  kind: string; target: string; job_id: number | null; refreshed_at: string | null;
};
type KeptFile = { name: string; latest: number; versions: number; rows: number; updated_at: string };
type FieldChange = { field: string; before: unknown; after: unknown };
type BindingChange = {
  binding_id: number; connection_id: number | null; file_name?: string | null; source: string; kind: string; target: string;
  job_id: number | null; version?: number | null; from_version?: number | null; same_extraction: boolean;
  counts: { added: number; changed: number; removed: number; unchanged: number };
  added: { key?: string; label?: string; from?: string[]; to?: string[]; index?: string[]; value?: number; returning?: boolean }[];
  changed: { key?: string; fields?: FieldChange[]; index?: string[]; before?: number; after?: number }[];
  removed: { key?: string; from?: string; to?: string; index?: string[] }[];
};
type RunQueued = { scenario_id: number; scenario: string; problem_id: number; problem: string; run_id?: number;
  previous_objective?: number; error?: string };
type RefreshReport = { applied: boolean; changes: number; bindings: BindingChange[]; runs?: RunQueued[] };
const KIND_TEXT: Record<string, string> = { entities: "records", relationships: "links", parameter_values: "values" };

/** One change in words: "P1: profit 45 → 50", "+ n4 (Dee)", "− [n3]". */
export function changeLines(b: BindingChange): string[] {
  const name = (x: { key?: string; index?: string[]; from?: string | string[]; to?: string | string[] }) =>
    x.key ?? (x.index ? x.index.join(" · ") : `${[x.from].flat().join(":")} → ${[x.to].flat().join(":")}`);
  return [
    ...b.added.map(a => `+ ${name(a)}${a.label && a.label !== a.key ? ` (${a.label})` : ""}${a.value !== undefined ? ` = ${a.value}` : ""}${a.returning ? " (back again)" : ""}`),
    ...b.changed.map(c => c.fields
      ? `${name(c)}: ${c.fields.map(f => `${f.field} ${String(f.before ?? "—")} → ${String(f.after ?? "—")}`).join(", ")}`
      : `${name(c)}: ${String(c.before)} → ${String(c.after)}`),
    ...b.removed.map(r => `− ${name(r)}`),
  ];
}

/** Files kept in this workspace (by version): add next week's file as a new version, then check for changes. */
function KeptFiles({ domainId }: { domainId: string }) {
  const { can } = useCapabilities();
  const client = useQueryClient();
  const input = useId();
  const kept = useQuery({ queryKey: ["workspace-files", domainId],
    queryFn: () => apiFetch<{ items: KeptFile[] }>(`/api/v1/domains/${domainId}/files`) });
  const add = useMutation({
    mutationFn: async (file: File) => {
      const read = await uploadAgentFile(file, Number(domainId));
      return post<{ name: string; version: number; new: boolean }>(`/api/v1/domains/${domainId}/files`, { file: read });
    },
    onSuccess: () => void client.invalidateQueries({ queryKey: ["workspace-files", domainId] }),
  });
  if (!kept.data?.items.length) return null;
  return <section aria-labelledby="kept-files" className="rounded-xl border border-slate-200 bg-white p-4">
    <h2 id="kept-files" className="text-lg font-semibold">Files kept in this workspace</h2>
    <p className="text-sm text-slate-600">Files a problem was built from, every version kept. Add a newer copy under the same
      file name, then use <em>Check for changes</em> below to see and apply what it changes.</p>
    <ul className="my-2 text-sm">{kept.data.items.map(f => <li key={f.name}>
      <span className="font-medium">{f.name}</span> <span className="text-slate-500">· version {f.latest} of {f.versions} · {f.rows} rows · {new Date(f.updated_at).toLocaleString()}</span>
    </li>)}</ul>
    {can("domain.edit") && <>
      <label htmlFor={input} className="text-sm">Add a new version (same file name): </label>
      <input id={input} type="file" accept=".csv,.tsv,.xlsx,.xls,.json" className="text-sm" disabled={add.isPending}
        onChange={e => { const f = e.target.files?.[0]; if (f) add.mutate(f); e.target.value = ""; }} />
    </>}
    {add.isError && <p role="alert" className="mt-1 text-red-800">{formatApiError(add.error)}</p>}
    {add.data && <p role="status" className="mt-1 text-sm">{add.data.new ? `Kept as version ${add.data.version} of ${add.data.name}.`
      : `${add.data.name} is unchanged (same as version ${add.data.version}).`}</p>}
  </section>;
}

/** Its children only once something in the domain is bound to a source (shares the bindings query). */
function BoundOnly({ domainId, children }: { domainId: string; children: React.ReactNode }) {
  const bound = useQuery({ queryKey: ["source-bindings", domainId],
    queryFn: () => apiFetch<{ items: Binding[] }>(`/api/v1/domains/${domainId}/source-bindings`) });
  return bound.data?.items.length ? <>{children}</> : null;
}

const SETTLED = ["optimal", "feasible", "infeasible", "unbounded", "error", "cancelled", "timeout", "unknown"];

/** A queued run's state, followed until it settles: its answer beside the scenario's last one. */
function RunAnswer({ runId, previous }: { runId: number; previous?: number }) {
  const run = useQuery({ queryKey: ["run", runId], queryFn: () => apiFetch<{ status: string; objective: number | null }>(`/api/v1/runs/${runId}`),
    refetchInterval: (q) => (q.state.data && SETTLED.includes(q.state.data.status) ? false : 3000) });
  const before = previous !== undefined ? ` (was ${previous.toLocaleString()})` : "";
  if (!run.data || !SETTLED.includes(run.data.status)) return <span>solving…{before}</span>;
  return <span>{run.data.status}{run.data.objective != null ? `, ${run.data.objective.toLocaleString()}` : ""}{before}</span>;
}

/** The runs a refresh queued, each beside its scenario's last answer; or what to do when it queued none. */
function RunsQueued({ domainId, runs }: { domainId: string; runs?: RunQueued[] }) {
  if (!runs) return <p className="text-sm">Solve the problem&rsquo;s scenarios again to see what the new data changes.</p>;
  if (!runs.length) return <p className="text-sm">No scenario reads the data that changed.</p>;
  return <ul className="text-sm">{runs.map(r => <li key={r.scenario_id}>
    {r.problem} · {r.scenario}: {r.run_id
      ? <><Link className="text-blue-700 underline" to={`/domains/${domainId}/problems/${r.problem_id}/runs/${r.run_id}`}>run #{r.run_id}</Link>{" "}
        <RunAnswer runId={r.run_id} previous={r.previous_objective} /></>
      : <span className="text-red-800">not solved: {r.error}</span>}
  </li>)}</ul>;
}

type Schedule = { every_hours: number; mode: "report" | "apply"; solve: boolean; enabled: boolean; next_at: string; state: string;
  last_at: string | null; last_error: string | null; owner: string | null;
  last_report: (RefreshReport & { failed?: { connection_id: number; error_code: string }[] }) | null };

const EVERY: [number, string][] = [[1, "hour"], [6, "6 hours"], [24, "day"], [168, "week"], [720, "30 days"]];
/** The choices of how often, with a schedule's own interval when it is not one of them (set by the Assistant). */
export function everyOptions(current: number): [number, string][] {
  return EVERY.some(([h]) => h === current) ? EVERY : [...EVERY, [current, `${current} hours`]];
}

/** Refresh this domain from its sources on a schedule, and the last scheduled run's report. */
function ScheduledRefresh({ domainId }: { domainId: string }) {
  const { can } = useCapabilities();
  const client = useQueryClient();
  const key = ["refresh-schedule", domainId];
  const got = useQuery({ queryKey: key, queryFn: () => apiFetch<{ schedule: Schedule | null }>(`/api/v1/domains/${domainId}/refresh-schedule`) });
  const current = got.data?.schedule ?? null;
  const [form, setForm] = useState<{ every_hours: number; mode: "report" | "apply"; solve: boolean } | null>(null);
  const shown = form ?? { every_hours: current?.every_hours ?? 168, mode: current?.mode ?? "report", solve: current?.solve ?? false };
  const done = () => { setForm(null); void client.invalidateQueries({ queryKey: key }); };
  const save = useMutation({ mutationFn: (enabled: boolean) => apiFetch(`/api/v1/domains/${domainId}/refresh-schedule`,
    { method: "PUT", body: JSON.stringify({ ...shown, solve: shown.mode === "apply" && shown.solve, enabled }) }), onSuccess: done });
  const now = useMutation({ mutationFn: () => post(`/api/v1/domains/${domainId}/refresh-schedule/run-now`), onSuccess: done });
  const remove = useMutation({ mutationFn: () => apiFetch(`/api/v1/domains/${domainId}/refresh-schedule`, { method: "DELETE" }), onSuccess: done });
  const failed = save.error ?? now.error ?? remove.error;
  const report = current?.last_report;
  return <section aria-labelledby="scheduled-refresh" className="rounded-xl border border-slate-200 bg-white p-4">
    <h2 id="scheduled-refresh" className="text-lg font-semibold">Scheduled refresh</h2>
    {current
      ? <p className="text-sm">{current.enabled ? "On" : "Paused"}: every {current.every_hours === 24 ? "day" : current.every_hours === 168 ? "week" : `${current.every_hours} hours`},
          {current.mode === "apply" ? ` applying the changes${current.solve ? " and solving again" : ""}` : " keeping a report to apply"}; as {current.owner ?? "its owner"}.
          {current.enabled && ` Next: ${new Date(current.next_at).toLocaleString()}.`}{current.state === "extracting" ? " Reading the sources now…" : ""}</p>
      : <p className="text-sm text-slate-600">Not scheduled. The domain can read its sources again by itself, report what changed, or apply it and solve again.</p>}
    {current?.last_at && <div className="mt-2 text-sm" aria-live="polite">
      <p className="font-medium">Last run {new Date(current.last_at).toLocaleString()}: {current.last_error
        ? <span className="text-red-800">{current.last_error}</span>
        : report ? (report.applied ? `applied ${report.changes} change${report.changes === 1 ? "" : "s"}` : report.changes ? `${report.changes} change${report.changes === 1 ? "" : "s"} found, not applied — use Check for changes to apply` : "no changes") : "nothing to report"}</p>
      {report?.bindings?.filter(b => b.counts.added + b.counts.changed + b.counts.removed).map((b, i) => <div key={i}>
        <p>{b.source} → {KIND_TEXT[b.kind] ?? b.kind} {b.target}: {b.counts.added} added, {b.counts.changed} changed, {b.counts.removed} gone</p>
        <ul className="ml-4 list-none font-mono text-xs">{changeLines(b).map((line, j) => <li key={j}>{line}</li>)}</ul>
      </div>)}
      {report?.applied && <RunsQueued domainId={domainId} runs={report.runs ?? []} />}
    </div>}
    {can("domain.edit") && <div className="mt-3 flex flex-wrap items-end gap-3 text-sm">
      <label>Every <select className="ml-1 rounded border px-1 py-0.5" value={shown.every_hours}
        onChange={e => setForm({ ...shown, every_hours: Number(e.target.value) })}>
        {everyOptions(shown.every_hours).map(([h, t]) => <option key={h} value={h}>{t}</option>)}
      </select></label>
      <label><input type="radio" checked={shown.mode === "report"} onChange={() => setForm({ ...shown, mode: "report" })} /> Report what changed</label>
      <label><input type="radio" checked={shown.mode === "apply"} onChange={() => setForm({ ...shown, mode: "apply" })} /> Apply it</label>
      {shown.mode === "apply" && can("run.submit") && <label><input type="checkbox" checked={shown.solve}
        onChange={e => setForm({ ...shown, solve: e.target.checked })} /> and solve again</label>}
      <button type="button" className="rounded bg-blue-700 px-3 py-1.5 text-white" disabled={save.isPending}
        onClick={() => save.mutate(true)}>{current ? "Save schedule" : "Schedule"}</button>
      {current && <>
        {current.enabled && <button type="button" className="rounded border px-3 py-1.5" onClick={() => save.mutate(false)}>Pause</button>}
        <button type="button" className="rounded border px-3 py-1.5" disabled={now.isPending || current.state !== "idle"} onClick={() => now.mutate()}>Run now</button>
        <button type="button" className="rounded border px-3 py-1.5" onClick={() => remove.mutate()}>Remove</button>
      </>}
    </div>}
    {failed && <p role="alert" className="mt-2 text-red-800">{formatApiError(failed)}</p>}
  </section>;
}

/** What this domain was built from, and a refresh: what each source's latest extraction would change, then written on request. */
function BuiltFromSources({ domainId }: { domainId: string }) {
  const { can } = useCapabilities();
  const client = useQueryClient();
  const bound = useQuery({ queryKey: ["source-bindings", domainId],
    queryFn: () => apiFetch<{ items: Binding[] }>(`/api/v1/domains/${domainId}/source-bindings`) });
  const [report, setReport] = useState<RefreshReport | null>(null);
  const check = useMutation({ mutationFn: () => post<RefreshReport>(`/api/v1/domains/${domainId}/sources/refresh`, {}), onSuccess: setReport });
  const apply = useMutation({
    mutationFn: ({ r, solve }: { r: RefreshReport; solve: boolean }) => post<RefreshReport>(`/api/v1/domains/${domainId}/sources/refresh`, {
      apply: true, solve,
      jobs: Object.fromEntries(r.bindings.filter(b => b.connection_id != null).map(b => [b.connection_id, b.job_id])),
      files: Object.fromEntries(r.bindings.filter(b => b.file_name).map(b => [b.file_name, b.version])),
    }),
    onSuccess: (r) => { setReport(r); void client.invalidateQueries({ queryKey: ["source-bindings", domainId] }); },
  });
  if (!bound.data?.items.length) return null;
  return <section aria-labelledby="built-from" className="rounded-xl border border-slate-200 bg-white p-4">
    <h2 id="built-from" className="text-lg font-semibold">Built from these sources</h2>
    <p className="text-sm text-slate-600">Data loaded from a source when a problem was built. Check compares each source&rsquo;s latest
      extraction with what the domain holds; run an extraction first for today&rsquo;s data. Records a source no longer has are set inactive, not deleted.</p>
    <ul className="my-2 text-sm">{bound.data.items.map(b => <li key={b.id}>
      {b.file_name ? `File ${b.file_name}` : b.connection} → {KIND_TEXT[b.kind] ?? b.kind} <span className="font-medium">{b.target}</span>
      <span className="text-slate-500">{b.job_id ? ` · from extraction #${b.job_id}` : b.file_version ? ` · from version ${b.file_version}` : ""}{b.refreshed_at ? `, ${new Date(b.refreshed_at).toLocaleString()}` : ""}</span>
    </li>)}</ul>
    <button type="button" className="rounded border px-3 py-1.5 text-sm" disabled={check.isPending} onClick={() => check.mutate()}>
      {check.isPending ? "Checking…" : "Check for changes"}</button>
    {(check.error || apply.error) && <p role="alert" className="mt-2 text-red-800">{formatApiError(check.error ?? apply.error)}</p>}
    {report && <div className="mt-3 space-y-2" aria-live="polite">
      <p className="font-medium">{report.applied ? `Applied ${report.changes} change${report.changes === 1 ? "" : "s"}.`
        : report.changes ? `${report.changes} change${report.changes === 1 ? "" : "s"} found (nothing written yet).` : "No changes: the domain holds the sources' data."}</p>
      {report.bindings.filter(b => b.counts.added + b.counts.changed + b.counts.removed).map(b => <div key={b.binding_id}>
        <p className="text-sm">{b.source}{b.file_name ? ` (version ${b.from_version ?? "?"} → ${b.version ?? "?"})` : ""} → {KIND_TEXT[b.kind] ?? b.kind} {b.target}: {b.counts.added} added, {b.counts.changed} changed, {b.counts.removed} gone, {b.counts.unchanged} unchanged</p>
        <ul className="ml-4 list-none font-mono text-xs">{changeLines(b).map((line, i) => <li key={i}>{line}</li>)}</ul>
      </div>)}
      {!report.applied && report.changes > 0 && (can("domain.edit")
        ? <div className="flex flex-wrap gap-2">
            {can("run.submit") && <button type="button" className="rounded bg-blue-700 px-3 py-1.5 text-sm text-white" disabled={apply.isPending}
              onClick={() => apply.mutate({ r: report, solve: true })}>{apply.isPending ? "Applying…" : "Apply and solve again"}</button>}
            <button type="button" className="rounded border px-3 py-1.5 text-sm" disabled={apply.isPending}
              onClick={() => apply.mutate({ r: report, solve: false })}>Apply only</button>
          </div>
        : <p className="text-sm">Applying needs permission to edit this domain.</p>)}
      {report.applied && <RunsQueued domainId={domainId} runs={report.runs} />}
    </div>}
  </section>;
}

export function SourcesPage() {
  const { domainId } = useParams();
  const { can, known } = useCapabilities();
  useDocumentTitle("Sources");
  if (!known) return <p role="status">Checking access…</p>;
  if (!can("integration.run")) return <p role="alert">Your account does not have access to sources and imports.</p>;
  return <SourceList key={domainId} domainId={domainId!} canManage={can("integration.manage")} />;
}

function SourceList({ domainId, canManage }: { domainId: string; canManage: boolean }) {
  const [page, setPage] = useState(0);
  const [adding, setAdding] = useState(false);
  const [open, setOpen] = useState<number | null>(null);
  const client = useQueryClient();
  const sources = useQuery({
    queryKey: ["connections", domainId, page],
    queryFn: () => apiFetch<{ items: Connection[]; total: number }>(`/api/v1/connections?domain_id=${domainId}&limit=20&offset=${page * 20}`),
  });
  const refresh = () => client.invalidateQueries({ queryKey: ["connections", domainId] });
  return <div className="max-w-5xl space-y-5">
    <h1 className="text-2xl font-semibold">Sources</h1>
    <p className="text-sm text-slate-600">
      Where this domain&rsquo;s data comes from: database tables, web addresses and kept files. Run an extraction to copy a source&rsquo;s rows here, then import them: preview, map the columns
      onto a record type, check every row, and load.
    </p>
    {canManage && (adding
      ? <SourceForm domainId={domainId} onDone={(created) => { setAdding(false); if (created) void refresh(); }} />
      : <button type="button" className="rounded bg-blue-700 px-3 py-2 text-sm text-white" onClick={() => setAdding(true)}>Add a source</button>)}
    {sources.isError ? <LoadFailure subject="Sources" error={sources.error} retry={() => void sources.refetch()} />
      : sources.fetchStatus === "paused" ? <p role="status">Waiting for a connection to the server.</p>
      : sources.isLoading ? <p role="status">Loading sources…</p>
      : sources.data?.items.length ? <ul className="divide-y rounded-xl border border-slate-200 bg-white">{sources.data.items.map(source =>
        <li key={source.id} className="p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span>
              <span className="font-medium">{source.name}</span>
              {source.config?.table && <span className="ml-2 text-xs text-slate-500">
                {ENGINES.find(([value]) => value === (source.config?.engine ?? "postgres"))?.[1]} · {source.config.schema}.{source.config.table}</span>}
              {source.config?.url && <span className="ml-2 text-xs text-slate-500">{source.config.url}</span>}
            </span>
            <span className="flex items-center gap-3">
              <span>{source.enabled ? "Enabled" : "Disabled"}</span>
              <button type="button" className="rounded border px-2 py-1 text-sm" aria-expanded={open === source.id}
                onClick={() => setOpen(open === source.id ? null : source.id)}>Extractions</button>
            </span>
          </div>
          {open === source.id && <JobHistory domainId={domainId} source={source} canManage={canManage} onChanged={() => void refresh()} />}
        </li>)}</ul>
      : <p>No configured sources on this page.</p>}
    <KeptFiles domainId={domainId} />
    <BuiltFromSources domainId={domainId} />
    <BoundOnly domainId={domainId}><ScheduledRefresh domainId={domainId} /></BoundOnly>
    <nav aria-label="Source pages" className="flex items-center gap-4">
      <button className="p-2 disabled:opacity-50" disabled={page === 0 || sources.isLoading} onClick={() => setPage(page - 1)}>Previous</button>
      <span>Page {page + 1}</span>
      <button className="p-2 disabled:opacity-50" disabled={!sources.data || (page + 1) * 20 >= sources.data.total} onClick={() => setPage(page + 1)}>Next</button>
    </nav>
    <Link className="inline-block py-2 text-blue-700 underline" to="/help/api">Local API reference</Link>
  </div>;
}

/** The database engines a source may be (app/integrations/databases.py), each with its usual port and schema. */
const ENGINES: [string, string, string, string][] = [
  ["postgres", "PostgreSQL", "5432", "public"], ["mysql", "MySQL / MariaDB", "3306", ""],
  ["sqlserver", "SQL Server", "1433", "dbo"], ["oracle", "Oracle", "1521", ""],
];

export function engineDefaults(fields: { engine: string; port: string; schema: string }, engine: string) {
  const was = ENGINES.find(([value]) => value === fields.engine);
  const now = ENGINES.find(([value]) => value === engine);
  if (!now) return {};
  return {
    ...(!fields.port || fields.port === was?.[2] ? { port: now[2] } : {}),
    ...(!fields.schema || fields.schema === was?.[3] ? { schema: now[3] } : {}),
  };
}

function SourceForm({ domainId, onDone }: { domainId: string; onDone: (created: boolean) => void }) {
  const id = useId();
  const [kind, setKind] = useState<"postgres" | "http">("postgres");
  const [fields, setFields] = useState({ name: "", engine: "postgres", host: "", port: "5432", database: "", username: "", schema: "public", table: "", columns: "", password: "",
    url: "", format: "json", auth: "none", sheet: "", records_at: "", paging: "none", next_at: "", page_param: "", changed_column: "" });
  const columns = fields.columns.split(",").map((c) => c.trim()).filter(Boolean);
  const create = useMutation({
    mutationFn: () => post<{ id: number }>("/api/v1/connections", kind === "postgres" ? {
      domain_id: Number(domainId), name: fields.name.trim(), password: fields.password,
      source: { engine: fields.engine, host: fields.host.trim(), port: Number(fields.port), database: fields.database.trim(), username: fields.username.trim(),
        schema: fields.schema.trim() || (fields.engine === "mysql" ? fields.database.trim() : ""), table: fields.table.trim(), columns,
        ...(fields.changed_column.trim() ? { changed_column: fields.changed_column.trim() } : {}) },
    } : {
      domain_id: Number(domainId), name: fields.name.trim(), ...(fields.auth === "none" ? {} : { password: fields.password }),
      source: { kind: "http", url: fields.url.trim(), format: fields.format, auth: fields.auth, columns,
        ...(fields.auth === "basic" ? { username: fields.username.trim() } : {}),
        ...(fields.format === "xlsx" && fields.sheet.trim() ? { sheet: fields.sheet.trim() } : {}),
        ...(fields.format === "json" && fields.records_at.trim() ? { records_at: fields.records_at.trim() } : {}),
        // A REST answer in pages: every page is read, under the same rules as the first.
        ...(fields.format === "json" && fields.paging !== "none" ? { paging: fields.paging,
          ...(fields.paging === "next_link" ? { next_at: fields.next_at.trim() } : {}),
          ...(fields.paging === "page_number" ? { page_param: fields.page_param.trim() } : {}) } : {}) },
    }),
    onSuccess: () => onDone(true),
  });
  const field = (key: keyof typeof fields, label: string, type = "text") => (
    <label className="block text-sm" htmlFor={`${id}-${key}`}>{label}
      <input id={`${id}-${key}`} type={type} value={fields[key]} autoComplete={type === "password" ? "new-password" : "off"}
        onChange={(event) => setFields({ ...fields, [key]: event.target.value })} className="mt-1 w-full rounded border border-slate-300 px-2 py-1" />
    </label>
  );
  const choice = (key: "format" | "auth" | "engine" | "paging", label: string, options: [string, string][]) => (
    <label className="block text-sm" htmlFor={`${id}-${key}`}>{label}
      <select id={`${id}-${key}`} value={fields[key]} onChange={(event) => setFields({ ...fields, [key]: event.target.value,
        // A new engine brings its usual port and schema, unless the person typed their own.
        ...(key === "engine" ? engineDefaults(fields, event.target.value) : {}) })}
        className="mt-1 w-full rounded border border-slate-300 px-2 py-1">
        {options.map(([value, text]) => <option key={value} value={value}>{text}</option>)}
      </select>
    </label>
  );
  const needed: (keyof typeof fields)[] = kind === "postgres"
    ? ["name", "host", "database", "username", "table", "columns", "password", ...(fields.engine === "mysql" ? [] : ["schema" as const])]
    : ["name", "url", "columns", ...(fields.auth === "none" ? [] : ["password" as const]), ...(fields.auth === "basic" ? ["username" as const] : []),
       ...(fields.format === "json" && fields.paging === "next_link" ? ["next_at" as const] : []),
       ...(fields.format === "json" && fields.paging === "page_number" ? ["page_param" as const] : [])];
  const missing = needed.filter((k) => !fields[k].trim());
  return <form aria-label="Add a source" className="grid gap-3 rounded-lg border border-slate-200 bg-white p-4 sm:grid-cols-2"
    onSubmit={(event) => { event.preventDefault(); create.mutate(); }}>
    <fieldset className="flex gap-4 text-sm sm:col-span-2"><legend className="sr-only">Kind of source</legend>
      <label><input type="radio" name={`${id}-kind`} checked={kind === "postgres"} onChange={() => setKind("postgres")} /> Database table or view</label>
      <label><input type="radio" name={`${id}-kind`} checked={kind === "http"} onChange={() => setKind("http")} /> Web address (REST API, CSV or Excel over HTTPS)</label>
    </fieldset>
    {field("name", "Name")}
    {kind === "postgres" ? <>
      {choice("engine", "Database engine", ENGINES.map(([value, text]) => [value, text]))}
      {field("host", "Host")}
      {field("port", "Port")}
      {field("database", fields.engine === "oracle" ? "Service name" : "Database")}
      {field("username", "User name")}
      {field("password", "Password", "password")}
      {field("schema", fields.engine === "oracle" ? "Owner (schema)" : fields.engine === "mysql" ? "Database the table is in" : "Schema")}
      {field("table", "Table or view")}
      {field("changed_column", "Changed column, to read only what changed (an update time or version; optional)")}
    </> : <>
      <div className="sm:col-span-2">{field("url", "Address (https://…)")}</div>
      {choice("format", "What it answers", [["json", "JSON list of records"], ["csv", "CSV file"], ["xlsx", "Excel workbook"]])}
      {fields.format === "json" && field("records_at", "Where the list is (e.g. data.items; empty if the answer is the list)")}
      {fields.format === "json" && choice("paging", "Pages", [["none", "One answer, no pages"],
        ["next_link", "Next page's address in the answer"], ["link_header", "Next page in the Link header"],
        ["page_number", "Page number in the address"]])}
      {fields.format === "json" && fields.paging === "next_link" && field("next_at", "Where the next address is (e.g. next, links.next)")}
      {fields.format === "json" && fields.paging === "page_number" && field("page_param", "The address's page parameter (e.g. page)")}
      {fields.format === "xlsx" && field("sheet", "Sheet (empty for the first)")}
      {choice("auth", "Login", [["none", "None"], ["bearer", "Token (bearer)"], ["basic", "User name and password"]])}
      {fields.auth === "basic" && field("username", "User name")}
      {fields.auth !== "none" && field("password", fields.auth === "bearer" ? "Token" : "Password", "password")}
    </>}
    <div className="sm:col-span-2">{field("columns", "Columns to extract, separated by commas")}</div>
    <p className="text-xs text-slate-600 sm:col-span-2">
      A password or token is encrypted on the server and never shown again. Which networks a source may be on is set by the operator.
    </p>
    {create.isError && <p role="alert" className="text-sm text-red-700 sm:col-span-2">{formatApiError(create.error)}</p>}
    <div className="flex gap-2 sm:col-span-2">
      <button type="submit" disabled={missing.length > 0 || create.isPending} className="rounded bg-blue-700 px-3 py-2 text-sm text-white disabled:opacity-50">
        {create.isPending ? "Saving…" : "Save source"}
      </button>
      <button type="button" className="rounded border px-3 py-2 text-sm" onClick={() => onDone(false)}>Cancel</button>
      {missing.length > 0 && <span className="self-center text-xs text-slate-500">Still needed: {missing.join(", ")}.</span>}
    </div>
  </form>;
}

function JobHistory({ domainId, source, canManage, onChanged }: { domainId: string; source: Connection; canManage: boolean; onChanged: () => void }) {
  const client = useQueryClient();
  const jobs = useQuery({
    queryKey: ["ingestion-jobs", source.id],
    queryFn: () => apiFetch<{ items: Job[]; total: number }>(`/api/v1/connections/${source.id}/jobs?limit=10`),
  });
  const active = (jobs.data?.items ?? []).some((job) => job.state === "queued" || job.state === "running");
  // An extraction in flight is followed until it settles, then no longer asked about.
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => void jobs.refetch(), 2000);
    return () => clearInterval(timer);
  }, [active, jobs]);
  const refresh = () => client.invalidateQueries({ queryKey: ["ingestion-jobs", source.id] });
  // A source with a changed column may be read for only what changed since its last read (migration 0118).
  const run = useMutation({ mutationFn: (incremental: boolean) => post(`/api/v1/connections/${source.id}/jobs`, incremental ? { incremental } : undefined),
    onSuccess: () => void refresh() });
  const cancel = useMutation({ mutationFn: (job: number) => post(`/api/v1/ingestion-jobs/${job}/cancel`), onSuccess: () => void refresh() });
  const disable = useMutation({ mutationFn: () => post(`/api/v1/connections/${source.id}/disable`), onSuccess: () => { void refresh(); onChanged(); } });
  return <div className="mt-3 space-y-2 border-t border-slate-100 pt-3 text-sm">
    <div className="flex flex-wrap gap-2">
      <button type="button" className="rounded bg-blue-700 px-3 py-1.5 text-white disabled:opacity-50" disabled={!source.enabled || active || run.isPending}
        onClick={() => run.mutate(false)}>{active ? "An extraction is running" : "Run extraction"}</button>
      {source.config?.changed_column && <button type="button" className="rounded border border-blue-300 px-3 py-1.5 text-blue-800 disabled:opacity-50"
        disabled={!source.enabled || active || run.isPending} onClick={() => run.mutate(true)}
        title={`Only rows whose ${source.config.changed_column} is at least the highest the last read saw; a refresh from it adds and updates, and takes nothing away`}>
        Read only what changed</button>}
      {canManage && source.enabled && <button type="button" className="rounded border border-red-300 px-3 py-1.5 text-red-800" onClick={() => disable.mutate()}>Disable source</button>}
    </div>
    {run.isError && <p role="alert" className="text-red-700">{formatApiError(run.error)}</p>}
    {jobs.isError ? <LoadFailure subject="The extraction history" error={jobs.error} retry={() => void jobs.refetch()} />
      : jobs.isLoading ? <p role="status">Loading extractions…</p>
      : !jobs.data?.items.length ? <p className="text-slate-600">No extractions yet.</p>
      : <ul className="space-y-2" aria-label={`Extractions of ${source.name}`}>{jobs.data.items.map((job) => (
        <li key={job.id} className="rounded border border-slate-200 p-2">
          <div className="flex flex-wrap items-center gap-3">
            <span className="font-medium">Extraction {job.id}{job.incremental ? " · only what changed" : ""}</span>
            <span role="status">{STATE_TEXT[job.state]}{job.cancel_requested && job.state !== "cancelled" ? " (cancelling)" : ""}</span>
            <span className="text-xs text-slate-500">{new Date(job.created_at).toLocaleString()}</span>
            {(job.state === "queued" || job.state === "running") && !job.cancel_requested &&
              <button type="button" className="rounded border px-2 py-1" onClick={() => cancel.mutate(job.id)}>Cancel</button>}
            {job.state === "extracted" &&
              <Link className="rounded border border-blue-300 px-2 py-1 text-blue-800" to={`/domains/${domainId}/data/sources/${source.id}/jobs/${job.id}/import`}>Import…</Link>}
          </div>
          {job.state === "failed" && <p className="mt-1 text-red-800">{ERROR_TEXT[job.error_code ?? ""] ?? `The extraction failed (${job.error_code ?? "no reason recorded"}).`}</p>}
          {job.loads.map((load) => <p key={load.id} className="mt-1 text-slate-700">
            {loadedText(load)} (import {load.id}; rows {load.artifact_sha256.slice(0, 12)}…, mapping {load.mapping_hash.slice(0, 12)}…).
          </p>)}
        </li>
      ))}</ul>}
  </div>;
}

// -- the import wizard ---------------------------------------------------------------

type Preview = { columns: string[]; rows_total: number; rows: Record<string, unknown>[]; sha256: string; source_object: string | null };
type Fault = { row: number; column: string | null; message: string };
type Validation = {
  validation_id: number; ok: boolean; rows: number; would_write: number; faults: Fault[];
  /** Where a default fills an empty or unmapped value: not a fault, but not what the source said (F25). */
  defaults?: { column: string; rows: number; default: unknown; message: string }[];
  entity_type?: string; target?: Target; noun?: string; artifact_sha256: string; mapping_hash: string;
};

const STRUCTURAL = ["key", "label", "sort_order", "active"];
const LINK = ["from", "to", "valid_from", "valid_to"];

/** A parameter's index columns, named as its upload template names them: a type
 * that indexes twice (distance[site, site]) gets its position. */
export function parameterHeads(parameter: ParameterDef, types: EntityType[]): string[] {
  const names = parameter.index_type_ids.map((id) => types.find((t) => t.id === id)?.name ?? `type_${id}`);
  return names.map((name, i) => (names.filter((n) => n === name).length > 1 ? `${name}_${i + 1}` : name));
}

/** The target's template columns, and the ones a mapping must fill. */
function targetColumns(kind: TargetKind, chosen: EntityType | RelationshipType | ParameterDef | null, types: EntityType[]) {
  if (!chosen) return { columns: [] as string[], required: [] as string[] };
  if (kind === "entity_type") return { columns: [...STRUCTURAL, ...(chosen as EntityType).attributes.map((a) => a.name)], required: ["key"] };
  if (kind === "relationship_type") {
    return { columns: [...LINK, ...((chosen as RelationshipType).attributes ?? []).map((a) => a.name)], required: ["from", "to"] };
  }
  const heads = parameterHeads(chosen as ParameterDef, types);
  return { columns: [...heads, "value"], required: [...heads, "value"] };
}

const WHY_REQUIRED: Record<TargetKind, string> = {
  entity_type: "it is how each record is found again, so a second import updates rather than duplicates",
  relationship_type: "they are the keys of the two records each row links",
  parameter: "each row names its cell by one key per index, and the value to put in it",
};

/** A first guess at the mapping: a source column onto the target of the same name (or `id` onto `key`). */
export function guessMapping(sources: string[], targets: string[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const source of sources) {
    const name = source.toLowerCase();
    const target = targets.find((t) => t === name) ?? (["id", "code", "key"].includes(name) && targets.includes("key") ? "key" : undefined);
    if (target && !Object.values(out).includes(target)) out[source] = target;
  }
  return out;
}

export function ImportWizard() {
  const { domainId, jobId } = useParams();
  useDocumentTitle("Import an extraction");
  const preview = useQuery({ queryKey: ["import-preview", jobId], queryFn: () => apiFetch<Preview>(`/api/v1/ingestion-jobs/${jobId}/preview?limit=20`) });
  const types = useEntityTypes(Number(domainId), { limit: 500 });
  const relationships = useRelationshipTypes(Number(domainId), { limit: 500 });
  const parameters = useParameters(Number(domainId), { limit: 500 });
  const [kind, setKind] = useState<TargetKind>("entity_type");
  const [typeId, setTypeId] = useState<number | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [report, setReport] = useState<Validation | null>(null);
  const typeItems = types.data?.items ?? [];
  const options: (EntityType | RelationshipType | ParameterDef)[] = kind === "entity_type" ? typeItems.filter((t) => !t.is_abstract)
    : kind === "relationship_type" ? relationships.data?.items ?? [] : parameters.data?.items ?? [];
  const chosen = options.find((t) => t.id === typeId) ?? null;
  const { columns: targets, required } = targetColumns(kind, chosen, typeItems);
  const validate = useMutation({
    mutationFn: () => post<Validation>(`/api/v1/ingestion-jobs/${jobId}/validate`, { [`${kind}_id`]: typeId, columns: mapping }),
    onSuccess: setReport,
  });
  const load = useMutation({
    mutationFn: () => post<{ load_id: number; rows_written: number; entity_type?: string; target?: Target }>(
      `/api/v1/ingestion-jobs/${jobId}/load`, { validation_id: report?.validation_id }),
  });
  const noun = NOUN[kind];
  const back = `/domains/${domainId}/data/sources`;
  if (preview.isError) return <LoadFailure subject="The extracted rows" error={preview.error} retry={() => void preview.refetch()} back={{ label: "Back to sources", to: back }} />;
  if (!preview.data) return <p role="status">Loading the extracted rows…</p>;
  const columns = preview.data.columns;
  const missing = required.filter((column) => !Object.values(mapping).includes(column));
  return <div className="max-w-6xl space-y-6">
    <h1 className="text-2xl font-semibold">Import extraction {jobId}</h1>
    <Link to={back} className="text-sm text-blue-700 underline">Back to sources</Link>

    <section aria-labelledby="step-preview">
      <h2 id="step-preview" className="mb-2 text-lg font-semibold">1. Preview</h2>
      <p className="mb-2 text-sm text-slate-600">{preview.data.rows_total} rows from {preview.data.source_object ?? "the source"}; the first {preview.data.rows.length} below.</p>
      <div className="overflow-x-auto rounded border border-slate-200">
        <table className="w-full text-left text-sm" aria-label="Extracted rows">
          <thead className="bg-slate-50"><tr><th scope="col" className="px-2 py-1">Row</th>{columns.map((c) => <th key={c} scope="col" className="px-2 py-1">{c}</th>)}</tr></thead>
          <tbody>{preview.data.rows.map((row, i) => <tr key={i} className="border-t border-slate-100">
            <td className="px-2 py-1 text-slate-500">{i + 1}</td>
            {columns.map((c) => <td key={c} className="px-2 py-1 font-mono text-xs">{row[c] === null || row[c] === undefined ? "—" : String(row[c])}</td>)}
          </tr>)}</tbody>
        </table>
      </div>
    </section>

    <section aria-labelledby="step-map">
      <h2 id="step-map" className="mb-2 text-lg font-semibold">2. Map the columns</h2>
      <div className="flex flex-wrap items-center gap-3">
        <label className="block text-sm">What the rows become
          <select className="ml-2 rounded border border-slate-300 px-2 py-1" value={kind} onChange={(event) => {
            setKind(event.target.value as TargetKind);
            setTypeId(null);
            setMapping({});
            setReport(null);
          }}>
            <option value="entity_type">Records</option>
            <option value="relationship_type">Links between records</option>
            <option value="parameter">Values of a parameter</option>
          </select>
        </label>
        <label className="block text-sm">The rows become {noun} of
          <select className="ml-2 rounded border border-slate-300 px-2 py-1" value={typeId ?? ""} onChange={(event) => {
            const id = event.target.value ? Number(event.target.value) : null;
            setTypeId(id);
            setReport(null);
            const next = options.find((t) => t.id === id) ?? null;
            setMapping(next ? guessMapping(columns, targetColumns(kind, next, typeItems).columns) : {});
          }}>
            <option value="">{kind === "entity_type" ? "Choose a record type…" : kind === "relationship_type" ? "Choose a link type…" : "Choose a parameter…"}</option>
            {options.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
        </label>
      </div>
      {chosen && <table className="mt-3 text-sm" aria-label="Column mapping"><tbody>{columns.map((source) => (
        <tr key={source}>
          <th scope="row" className="py-1 pr-3 text-left font-mono font-normal">{source}</th>
          <td className="py-1 pr-2" aria-hidden>→</td>
          <td className="py-1"><select aria-label={`${source} becomes`} className="rounded border border-slate-300 px-2 py-1" value={mapping[source] ?? ""}
            onChange={(event) => {
              setReport(null);
              const next = { ...mapping };
              if (event.target.value) next[source] = event.target.value;
              else delete next[source];
              setMapping(next);
            }}>
            <option value="">— not imported</option>
            {targets.map((t) => <option key={t} value={t} disabled={Object.entries(mapping).some(([s, v]) => v === t && s !== source)}>{t}</option>)}
          </select></td>
        </tr>))}</tbody></table>}
      {chosen && missing.length > 0 && <p className="mt-2 text-sm text-amber-800">
        Map a column to {missing.map((column, i) => <span key={column}>{i > 0 ? (i === missing.length - 1 ? " and " : ", ") : ""}<code>{column}</code></span>)}: {WHY_REQUIRED[kind]}.
      </p>}
    </section>

    <section aria-labelledby="step-check">
      <h2 id="step-check" className="mb-2 text-lg font-semibold">3. Check every row</h2>
      <button type="button" className="rounded bg-blue-700 px-3 py-2 text-sm text-white disabled:opacity-50"
        disabled={!chosen || missing.length > 0 || validate.isPending} onClick={() => validate.mutate()}>
        {validate.isPending ? "Checking…" : "Check the rows"}
      </button>
      <span className="ml-2 text-sm text-slate-600">Nothing is written by a check.</span>
      {validate.isError && <p role="alert" className="mt-2 text-red-700">{formatApiError(validate.error)}</p>}
      {report && (report.ok
        ? <p role="status" className="mt-2 text-green-800">All {report.rows} rows are clean: {report.would_write} {report.target?.name ?? report.entity_type} {report.noun ?? "records"} would be written.</p>
        : <div role="alert" className="mt-2">
          <p className="text-red-800">{report.faults.length} {report.faults.length === 1 ? "problem" : "problems"} in {report.rows} rows; nothing can be loaded until they are fixed at the source (and extracted again) or the mapping is changed.</p>
          <table className="mt-2 text-sm" aria-label="Problems found"><thead><tr><th scope="col" className="pr-3 text-left">Row</th><th scope="col" className="pr-3 text-left">Column</th><th scope="col" className="text-left">Problem</th></tr></thead>
            <tbody>{report.faults.slice(0, 200).map((fault, i) => <tr key={i}>
              <td className="pr-3">{fault.row === 0 ? "mapping" : fault.row}</td><td className="pr-3 font-mono text-xs">{fault.column ?? "—"}</td><td>{fault.message}</td>
            </tr>)}</tbody></table>
        </div>)}
      {report && (report.defaults?.length ?? 0) > 0 && <div className="mt-2 rounded border border-amber-300 bg-amber-50 p-2 text-sm text-amber-900">
        <p>Defaults will fill in values the source does not give:</p>
        <ul aria-label="Defaults applied" className="list-disc pl-5">{report.defaults!.map((d) => <li key={d.column}>
          <span className="font-mono text-xs">{d.column}</span>: {d.message}</li>)}</ul>
      </div>}
    </section>

    <section aria-labelledby="step-load">
      <h2 id="step-load" className="mb-2 text-lg font-semibold">4. Load</h2>
      <button type="button" className="rounded bg-green-700 px-3 py-2 text-sm text-white disabled:opacity-50"
        disabled={!report?.ok || load.isPending || load.isSuccess} onClick={() => load.mutate()}>
        {load.isPending ? "Loading…" : report?.ok ? `Load ${report.would_write} ${report.noun ?? "records"}` : "Load"}
      </button>
      {load.isError && <p role="alert" className="mt-2 text-red-700">{formatApiError(load.error)}</p>}
      {load.isSuccess && report && <p role="status" className="mt-2 text-green-800">
        Loaded {load.data.rows_written} {load.data.target?.name ?? load.data.entity_type} {report.noun ?? "records"} (import {load.data.load_id}). They carry this extraction&rsquo;s fingerprint
        ({report.artifact_sha256.slice(0, 12)}…) and the mapping&rsquo;s ({report.mapping_hash.slice(0, 12)}…); the next run freezes them in its dataset.
      </p>}
    </section>
  </div>;
}
