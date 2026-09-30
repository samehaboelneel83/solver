/**
 * Start a problem (simplification plan, phase 3): from a ready example, from
 * a spreadsheet, or from scratch -- each ends on the new problem's checklist.
 *
 * A spreadsheet is read first and what it would make is shown for the person
 * to correct: a kind of record per sheet, a field per column with the type
 * its values read as, and a link where a column holds another sheet's keys.
 * Nothing is written until they say so, and one bad cell writes nothing.
 */
import { useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { ApiError } from "../api/client";
import { formatApiError } from "../api/errors";
import {
  createProblem,
  importSpreadsheet,
  proposeSpreadsheet,
  useApplyTemplate,
  useTemplates,
  type AttrType,
  type Id,
  type SheetKind,
  type SheetProposal,
} from "../api/v1";
import { useCapabilities } from "../hooks/useCapability";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { exampleWords } from "../lib/examples";
import { parseRouteId } from "../lib/routeId";

type Way = "example" | "sheet" | "scratch";

const INPUT = "rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm text-slate-900";
const PRIMARY = "rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-50";
const CARD = "rounded-lg border border-slate-200 bg-white p-4";

const TYPE_WORDS: [AttrType, string][] = [
  ["integer", "a whole number"],
  ["number", "a number"],
  ["boolean", "yes or no"],
  ["date", "a date"],
  ["enum", "one of a list"],
  ["text", "text"],
];

/** The faults an import refused, or the error as one line. */
export function faultsOf(error: unknown): string[] {
  if (error instanceof ApiError && error.status === 422) {
    try {
      const detail = JSON.parse(error.message).detail;
      if (detail && Array.isArray(detail.faults)) {
        return [...detail.faults, ...(detail.more ? [`…and ${detail.more} more.`] : [])];
      }
    } catch {
      // not the import's own shape: fall through
    }
  }
  return [formatApiError(error)];
}

export default function StartProblem() {
  const { domainId: raw } = useParams();
  const domainId = parseRouteId(raw ?? null);
  useDocumentTitle("Start a problem");
  if (domainId === null) return <p role="alert">Choose a valid domain.</p>;
  return <Start domainId={domainId} />;
}

function Start({ domainId }: { domainId: Id }) {
  const [way, setWay] = useState<Way>("example");
  const [name, setName] = useState("");
  const navigate = useNavigate();
  const land = (problemId: Id) => navigate(`/domains/${domainId}/problems/${problemId}`);
  const ways: [Way, string, string][] = [
    ["example", "From a ready example", "A working problem with its data and model, to solve at once and change."],
    ["sheet", "From a spreadsheet", "Your own data from Excel or CSV: each sheet becomes a kind of record."],
    ["scratch", "From scratch", "An empty problem: add the data and say what to decide."],
  ];
  return (
    <div className="max-w-5xl space-y-6">
      <Link className="text-sm text-blue-700 underline" to={`/domains/${domainId}/problems`}>All problems</Link>
      <header>
        <h1 className="text-2xl font-semibold text-slate-900">Start a problem</h1>
        <p className="mt-1 text-sm text-slate-600">Choose where it starts from. You land on its checklist, which says what to do next.</p>
      </header>
      <label className="block text-sm text-slate-700">
        What is it called?{" "}
        <input className={`${INPUT} w-72`} value={name} onChange={(event) => setName(event.target.value)}
          placeholder={way === "example" ? "the example's name" : "Weekly rota"} />
      </label>
      <div role="radiogroup" aria-label="Start from" className="grid gap-3 md:grid-cols-3">
        {ways.map(([key, title, says]) => (
          <button key={key} type="button" role="radio" aria-checked={way === key} onClick={() => setWay(key)}
            className={`rounded-lg border p-4 text-left ${way === key ? "border-blue-600 bg-blue-50 ring-1 ring-blue-600" : "border-slate-200 bg-white hover:bg-slate-50"}`}>
            <span className="block font-semibold text-slate-900">{title}</span>
            <span className="mt-1 block text-sm text-slate-600">{says}</span>
          </button>
        ))}
      </div>
      {way === "example" && <FromExample domainId={domainId} name={name} onMade={land} />}
      {way === "sheet" && <FromSheet domainId={domainId} name={name} onMade={land} />}
      {way === "scratch" && <FromScratch domainId={domainId} name={name} onMade={land} />}
    </div>
  );
}

function Problems({ items }: { items: string[] }) {
  if (!items.length) return null;
  return (
    <div role="alert" className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-900">
      {items.length === 1 ? items[0] : <ul className="list-disc pl-5">{items.map((item) => <li key={item}>{item}</li>)}</ul>}
    </div>
  );
}

function FromExample({ domainId, name, onMade }: { domainId: Id; name: string; onMade: (id: Id) => void }) {
  const templates = useTemplates();
  const apply = useApplyTemplate();
  const { can } = useCapabilities();
  const [problems, setProblems] = useState<string[]>([]);
  if (templates.isLoading) return <p role="status" className="text-sm text-slate-600">Loading the examples…</p>;
  const items = templates.data?.items ?? [];
  if (!items.length) return <p className="text-sm text-slate-600">There are no ready examples here.</p>;
  return (
    <section aria-label="Ready examples" className="space-y-3">
      {!can("model.publish") && <p className="text-sm text-amber-800">An example comes with a model; this account may not publish one.</p>}
      <ul className="grid gap-3 md:grid-cols-2">
        {items.map((row) => {
          const words = exampleWords(row.name);
          return (
            <li key={String(row.id)} className={CARD}>
              <h2 className="font-semibold text-slate-900">{words.title}</h2>
              {words.says && <p className="mt-1 text-sm text-slate-600">{words.says}</p>}
              <button type="button" className={`${PRIMARY} mt-3`} disabled={apply.isPending || !can("model.publish")}
                onClick={() => {
                  setProblems([]);
                  apply.mutate({ id: row.id, body: { domain_id: domainId, name: name.trim() || words.title } }, {
                    onSuccess: (made) => onMade(made.problem_id),
                    onError: (error) => setProblems([formatApiError(error)]),
                  });
                }}>
                Use this example
              </button>
            </li>
          );
        })}
      </ul>
      {apply.isPending && <p role="status" className="text-sm text-slate-600">Making it…</p>}
      <Problems items={problems} />
    </section>
  );
}

function FromScratch({ domainId, name, onMade }: { domainId: Id; name: string; onMade: (id: Id) => void }) {
  const client = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [problems, setProblems] = useState<string[]>([]);
  return (
    <section aria-label="From scratch" className={CARD}>
      <p className="text-sm text-slate-600">The checklist then takes you through adding records and building the model.</p>
      <button type="button" className={`${PRIMARY} mt-3`} disabled={busy || !name.trim()}
        onClick={async () => {
          setBusy(true);
          setProblems([]);
          try {
            const made = await createProblem({ domain_id: domainId, name: name.trim() });
            await client.invalidateQueries();
            onMade(made.id);
          } catch (error) {
            setProblems([formatApiError(error)]);
          } finally {
            setBusy(false);
          }
        }}>
        Make the problem
      </button>
      {!name.trim() && <p className="mt-2 text-xs text-slate-500">Give it a name first.</p>}
      <div className="mt-3"><Problems items={problems} /></div>
    </section>
  );
}

function FromSheet({ domainId, name, onMade }: { domainId: Id; name: string; onMade: (id: Id) => void }) {
  const client = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [proposal, setProposal] = useState<SheetProposal | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const [made, setMade] = useState<string | null>(null);

  async function read(chosen: File) {
    setFile(chosen);
    setProposal(null);
    setProblems([]);
    setMade(null);
    setBusy("Reading the file…");
    try {
      setProposal(await proposeSpreadsheet(domainId, chosen));
    } catch (error) {
      setProblems(faultsOf(error));
    } finally {
      setBusy(null);
    }
  }

  function edit(index: number, change: (kind: SheetKind) => SheetKind) {
    setProposal((current) => current && { kinds: current.kinds.map((kind, i) => (i === index ? change(kind) : kind)) });
  }

  async function build() {
    if (!file || !proposal) return;
    setProblems([]);
    setBusy("Importing…");
    try {
      const { made: counts } = await importSpreadsheet(domainId, file, proposal);
      setMade(`Made ${counts.kinds} kinds of record, ${counts.fields} fields, ${counts.records} records and ${counts.links} links.`);
      const problem = await createProblem({ domain_id: domainId, name: name.trim() });
      await client.invalidateQueries();
      onMade(problem.id);
    } catch (error) {
      setProblems(faultsOf(error));
      await client.invalidateQueries();
    } finally {
      setBusy(null);
    }
  }

  const kinds = proposal?.kinds ?? [];
  return (
    <section aria-label="From a spreadsheet" className="space-y-4">
      <div className={CARD}>
        <label className="block text-sm text-slate-700">
          An Excel workbook (.xlsx) or a CSV file. The first row of each sheet names its columns.
          <input className="mt-2 block text-sm" type="file" accept=".xlsx,.csv,text/csv"
            onChange={(event) => { const chosen = event.target.files?.[0]; if (chosen) void read(chosen); }} />
        </label>
      </div>
      {kinds.length > 0 && (
        <>
          <p className="text-sm text-slate-700">This is what the file would make. Correct anything that is read wrongly, then import it.</p>
          {kinds.map((kind, index) => (
            <KindCard key={kind.sheet} kind={kind} names={kinds.filter((k) => !k.skip).map((k) => k.name)}
              onChange={(change) => edit(index, change)} />
          ))}
          <div className="flex flex-wrap items-center gap-3">
            <button type="button" className={PRIMARY} disabled={busy !== null || !name.trim() || kinds.every((k) => k.skip)} onClick={build}>
              Import and make the problem
            </button>
            {!name.trim() && <span className="text-xs text-slate-500">Give the problem a name first.</span>}
          </div>
        </>
      )}
      {busy && <p role="status" className="text-sm text-slate-600">{busy}</p>}
      {made && <p role="status" className="text-sm text-emerald-700">{made}</p>}
      <Problems items={problems} />
    </section>
  );
}

function Row({ children }: { children: ReactNode }) {
  return <tr className="border-t border-slate-100">{children}</tr>;
}

function KindCard({ kind, names, onChange }: { kind: SheetKind; names: string[]; onChange: (change: (kind: SheetKind) => SheetKind) => void }) {
  const columns = [...kind.fields.map((f) => f.column), ...kind.links.map((l) => l.column)];
  return (
    <article className={`${CARD} ${kind.skip ? "opacity-60" : ""}`} aria-label={`Sheet ${kind.sheet}`}>
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="font-semibold text-slate-900">Sheet “{kind.sheet}”</h2>
        <span className="text-sm text-slate-600">{kind.rows} {kind.rows === 1 ? "row" : "rows"}</span>
        <label className="ms-auto text-sm text-slate-700">
          <input type="checkbox" checked={!kind.skip} onChange={(event) => onChange((k) => ({ ...k, skip: !event.target.checked }))} /> import it
        </label>
      </div>
      {!kind.skip && (
        <>
          <div className="mt-2 flex flex-wrap gap-4 text-sm text-slate-700">
            <label>Each row is a{" "}
              <input aria-label={`Kind of record for ${kind.sheet}`} className={INPUT} value={kind.name}
                onChange={(event) => onChange((k) => ({ ...k, name: event.target.value }))} />
            </label>
            <label>told apart by{" "}
              <select aria-label={`Key column for ${kind.sheet}`} className={INPUT} value={kind.key ?? ""}
                onChange={(event) => onChange((k) => keyed(k, event.target.value || null))}>
                <option value="">its row number</option>
                {kind.key && <option value={kind.key}>{kind.key}</option>}
                {columns.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </label>
          </div>
          {kind.exists && <p className="mt-1 text-xs text-amber-800">{kind.name} already exists here: its fields are kept, new ones added, and a record whose key exists is left as it is.</p>}
          <table className="mt-3 w-full text-sm">
            <thead><tr className="text-left text-xs text-slate-500"><th className="py-1">Column</th><th>Becomes</th><th>Which is</th><th>For example</th><th>Import</th></tr></thead>
            <tbody>
              {kind.fields.map((field, i) => (
                <Row key={field.column}>
                  <td className="py-1 pr-2">{field.column}</td>
                  <td className="pr-2">
                    <input aria-label={`Field name for ${field.column}`} className={`${INPUT} w-40`} value={field.name}
                      onChange={(event) => onChange((k) => ({ ...k, fields: k.fields.map((f, j) => (j === i ? { ...f, name: event.target.value } : f)) }))} />
                  </td>
                  <td className="pr-2">
                    <select aria-label={`Type of ${field.column}`} className={INPUT} value={field.data_type}
                      onChange={(event) => onChange((k) => ({ ...k, fields: k.fields.map((f, j) => (j === i ? { ...f, data_type: event.target.value as AttrType } : f)) }))}>
                      {TYPE_WORDS.map(([value, words]) => <option key={value} value={value}>{words}</option>)}
                    </select>
                    {field.data_type === "enum" && (
                      <input aria-label={`Choices for ${field.column}`} className={`${INPUT} mt-1 block w-48`} value={(field.enum_values ?? []).join(", ")}
                        onChange={(event) => onChange((k) => ({ ...k, fields: k.fields.map((f, j) => (j === i
                          ? { ...f, enum_values: event.target.value.split(",").map((c) => c.trim()).filter(Boolean) } : f)) }))} />
                    )}
                  </td>
                  <td className="pr-2 text-slate-500">{field.samples.join(", ")}</td>
                  <td><input type="checkbox" aria-label={`Import ${field.column}`} checked={!field.skip}
                    onChange={(event) => onChange((k) => ({ ...k, fields: k.fields.map((f, j) => (j === i ? { ...f, skip: !event.target.checked } : f)) }))} /></td>
                </Row>
              ))}
              {kind.links.map((link, i) => (
                <Row key={link.column}>
                  <td className="py-1 pr-2">{link.column}</td>
                  <td className="pr-2">
                    <input aria-label={`Link name for ${link.column}`} className={`${INPUT} w-40`} value={link.name}
                      onChange={(event) => onChange((k) => ({ ...k, links: k.links.map((l, j) => (j === i ? { ...l, name: event.target.value } : l)) }))} />
                  </td>
                  <td className="pr-2" colSpan={2}>a link to a {names.includes(link.to) ? link.to : <em>{link.to} (not imported)</em>}</td>
                  <td><input type="checkbox" aria-label={`Import ${link.column}`} checked={!link.skip}
                    onChange={(event) => onChange((k) => ({ ...k, links: k.links.map((l, j) => (j === i ? { ...l, skip: !event.target.checked } : l)) }))} /></td>
                </Row>
              ))}
            </tbody>
          </table>
        </>
      )}
    </article>
  );
}

/** A new key column leaves the fields and links; the old key becomes a text field again. */
function keyed(kind: SheetKind, key: string | null): SheetKind {
  const fields = kind.fields.filter((f) => f.column !== key);
  const links = kind.links.filter((l) => l.column !== key);
  if (kind.key && kind.key !== key && !fields.some((f) => f.column === kind.key)) {
    fields.unshift({ column: kind.key, name: kind.key.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "") || "field",
      data_type: "text", enum_values: null, samples: [], skip: false });
  }
  return { ...kind, key, fields, links };
}
