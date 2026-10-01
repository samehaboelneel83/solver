import { useEffect, useId, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../api/client";
import { formatApiError } from "../api/errors";
import { useEntityTypes, useParameters, useRelationshipTypes, type EntityType, type ParameterDef, type RelationshipType } from "../api/v1";
import LoadFailure from "../components/LoadFailure";
import { useCapabilities } from "../hooks/useCapability";
import { useDocumentTitle } from "../hooks/useDocumentTitle";

/**
 * Sources & imports (Epic UX, U-4): set up a database source, run an extraction and
 * follow it, then -- in the import wizard -- preview the rows, map their columns onto
 * an entity type, a relationship type or a parameter, check every row, and load them
 * with their lineage recorded.
 */

type Connection = { id: number; name: string; enabled: boolean; config?: { schema?: string; table?: string; columns?: string[]; host?: string } };
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
};

const post = <T,>(path: string, body?: unknown) =>
  apiFetch<T>(path, { method: "POST", ...(body === undefined ? {} : { body: JSON.stringify(body) }) });

/** What a failed extraction's code means, and what to do about it. */
export const ERROR_TEXT: Record<string, string> = {
  extraction_failed: "The source could not be read. Check that the host is reachable from the import worker, that the credential is current, and that the table and columns exist.",
  deadline_exceeded: "The extraction ran past its time limit (about five minutes). Extract fewer columns, or a smaller table or view.",
  worker_lost: "The import worker stopped during the extraction. Run it again; nothing was changed.",
};

const STATE_TEXT: Record<Job["state"], string> = {
  queued: "Waiting for the import worker",
  running: "Extracting",
  extracted: "Extracted: ready to import",
  failed: "Failed",
  cancelled: "Cancelled",
};

export function SourcesPage() {
  const { domainId } = useParams();
  const { can, known } = useCapabilities();
  useDocumentTitle("Database connections");
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
    <h1 className="text-2xl font-semibold">Database connections</h1>
    <p className="text-sm text-slate-600">
      Database sources for this domain. Run an extraction to copy a table&rsquo;s rows here, then import them: preview, map the columns
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
              {source.config?.table && <span className="ml-2 text-xs text-slate-500">{source.config.schema}.{source.config.table}</span>}
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
    <nav aria-label="Source pages" className="flex items-center gap-4">
      <button className="p-2 disabled:opacity-50" disabled={page === 0 || sources.isLoading} onClick={() => setPage(page - 1)}>Previous</button>
      <span>Page {page + 1}</span>
      <button className="p-2 disabled:opacity-50" disabled={!sources.data || (page + 1) * 20 >= sources.data.total} onClick={() => setPage(page + 1)}>Next</button>
    </nav>
    <Link className="inline-block py-2 text-blue-700 underline" to="/help/api">Local API reference</Link>
  </div>;
}

function SourceForm({ domainId, onDone }: { domainId: string; onDone: (created: boolean) => void }) {
  const id = useId();
  const [fields, setFields] = useState({ name: "", host: "", port: "5432", database: "", username: "", schema: "public", table: "", columns: "", password: "" });
  const create = useMutation({
    mutationFn: () => post<{ id: number }>("/api/v1/connections", {
      domain_id: Number(domainId), name: fields.name.trim(), password: fields.password,
      source: { host: fields.host.trim(), port: Number(fields.port), database: fields.database.trim(), username: fields.username.trim(),
        schema: fields.schema.trim(), table: fields.table.trim(), columns: fields.columns.split(",").map((c) => c.trim()).filter(Boolean) },
    }),
    onSuccess: () => onDone(true),
  });
  const field = (key: keyof typeof fields, label: string, type = "text") => (
    <label className="block text-sm" htmlFor={`${id}-${key}`}>{label}
      <input id={`${id}-${key}`} type={type} value={fields[key]} autoComplete={type === "password" ? "new-password" : "off"}
        onChange={(event) => setFields({ ...fields, [key]: event.target.value })} className="mt-1 w-full rounded border border-slate-300 px-2 py-1" />
    </label>
  );
  const missing = (["name", "host", "database", "username", "table", "columns", "password"] as const).filter((k) => !fields[k].trim());
  return <form aria-label="Add a source" className="grid gap-3 rounded-lg border border-slate-200 bg-white p-4 sm:grid-cols-2"
    onSubmit={(event) => { event.preventDefault(); create.mutate(); }}>
    {field("name", "Name")}
    {field("host", "Host")}
    {field("port", "Port")}
    {field("database", "Database")}
    {field("username", "User name")}
    {field("password", "Password", "password")}
    {field("schema", "Schema")}
    {field("table", "Table or view")}
    <div className="sm:col-span-2">{field("columns", "Columns to extract, separated by commas")}</div>
    <p className="text-xs text-slate-600 sm:col-span-2">
      The password is encrypted on the server and never shown again. Which networks a source may be on is set by the operator.
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
  const run = useMutation({ mutationFn: () => post(`/api/v1/connections/${source.id}/jobs`), onSuccess: () => void refresh() });
  const cancel = useMutation({ mutationFn: (job: number) => post(`/api/v1/ingestion-jobs/${job}/cancel`), onSuccess: () => void refresh() });
  const disable = useMutation({ mutationFn: () => post(`/api/v1/connections/${source.id}/disable`), onSuccess: () => { void refresh(); onChanged(); } });
  return <div className="mt-3 space-y-2 border-t border-slate-100 pt-3 text-sm">
    <div className="flex flex-wrap gap-2">
      <button type="button" className="rounded bg-blue-700 px-3 py-1.5 text-white disabled:opacity-50" disabled={!source.enabled || active || run.isPending}
        onClick={() => run.mutate()}>{active ? "An extraction is running" : "Run extraction"}</button>
      {canManage && source.enabled && <button type="button" className="rounded border border-red-300 px-3 py-1.5 text-red-800" onClick={() => disable.mutate()}>Disable source</button>}
    </div>
    {run.isError && <p role="alert" className="text-red-700">{formatApiError(run.error)}</p>}
    {jobs.isError ? <LoadFailure subject="The extraction history" error={jobs.error} retry={() => void jobs.refetch()} />
      : jobs.isLoading ? <p role="status">Loading extractions…</p>
      : !jobs.data?.items.length ? <p className="text-slate-600">No extractions yet.</p>
      : <ul className="space-y-2" aria-label={`Extractions of ${source.name}`}>{jobs.data.items.map((job) => (
        <li key={job.id} className="rounded border border-slate-200 p-2">
          <div className="flex flex-wrap items-center gap-3">
            <span className="font-medium">Extraction {job.id}</span>
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
