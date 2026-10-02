import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { formatApiError } from "../api/errors";
import { getEntity, updateEntity, type Id } from "../api/v1";
import {
  usePlace,
  useProblems,
  useWorkbenchSchema,
  useWorkbenchSearch,
  type SearchHit,
  type TreeRecord,
} from "../api/workbench";
import { useToast } from "../components/ToastProvider";
import DetailPane from "../components/workbench/DetailPane";
import MasterPane, { type View } from "../components/workbench/MasterPane";
import WorkbenchTree, { groupNode, moveField, recordNode, rootNode, type TreeSelection } from "../components/workbench/WorkbenchTree";
import { useCapabilities } from "../hooks/useCapability";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { parseRouteId } from "../lib/routeId";

const VIEW_KEY = "solver_workbench_view";

function storedView(): View {
  try {
    const v = localStorage.getItem(VIEW_KEY);
    return v === "grid" || v === "map" ? v : "cards";
  } catch {
    return "cards";
  }
}

/** The tree branches to open so a record found by search is in view. */
export function pathNodes(hit: Pick<SearchHit, "path">, roots: Id[]): string[] {
  const nodes = roots.map(rootNode);
  for (const step of hit.path) nodes.push(recordNode(step.id), groupNode(step.child_group, step.id));
  return nodes;
}

function Search({ domainId, onPick }: { domainId: Id; onPick: (hit: SearchHit) => void }) {
  const [text, setText] = useState("");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setQ(text.trim()), 200);
    return () => clearTimeout(t);
  }, [text]);
  const found = useWorkbenchSearch(domainId, q);
  return (
    <div className="relative w-full max-w-md">
      <label htmlFor="wb-search" className="sr-only">
        Find any record
      </label>
      <input
        id="wb-search"
        role="combobox"
        aria-expanded={open && !!q}
        aria-controls="wb-search-results"
        className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
        placeholder="Find any record — key or name, any kind"
        value={text}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onChange={(e) => {
          setText(e.target.value);
          setOpen(true);
        }}
      />
      {open && q && (
        <ul id="wb-search-results" role="listbox" className="absolute z-30 mt-1 max-h-80 w-full overflow-auto rounded-md border border-slate-200 bg-white text-sm shadow-lg">
          {found.isLoading && <li className="px-3 py-2 text-slate-500">Searching…</li>}
          {found.data?.items.length === 0 && <li className="px-3 py-2 text-slate-500">Nothing matches “{q}”.</li>}
          {found.data?.items.map((hit) => (
            <li
              key={hit.id}
              role="option"
              aria-selected={false}
              className="cursor-pointer px-3 py-1.5 hover:bg-slate-100"
              onMouseDown={(e) => {
                e.preventDefault();
                onPick(hit);
                setText("");
                setOpen(false);
              }}
            >
              <span className="font-medium">{hit.label || hit.key}</span>{" "}
              <span className="text-xs text-slate-500">
                {hit.kind}
                {hit.path.length > 0 && ` · in ${hit.path.map((p) => p.label || p.key).join(" › ")}`}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * The data workbench (improvement plan, data entry): one page to enter and fix a domain's records.
 * Left, the records as a tree read from the model; middle, what sits under the selection, as cards
 * or an editable grid with the parent filled in; right, the selected record's form, links, values
 * and problems. The selection, tab and view live in the address, so a view can be shared.
 */
export default function Workbench() {
  const { domainId: rawDomain } = useParams();
  const domainId = parseRouteId(rawDomain);
  const [params, setParams] = useSearchParams();
  const schema = useWorkbenchSchema(domainId);
  const problems = useProblems(domainId);
  const toast = useToast();
  const queryClient = useQueryClient();
  const { can } = useCapabilities();
  useDocumentTitle("Data workbench");

  const selectedRecord = parseRouteId(params.get("record"));
  const selectedRoot = parseRouteId(params.get("kind"));
  const selection: TreeSelection | null =
    selectedRecord != null ? { kind: "record", id: selectedRecord } : selectedRoot != null ? { kind: "root", kindId: selectedRoot } : null;
  const tab = params.get("tab");
  const [view, setViewState] = useState<View>(storedView);
  const [showInactive, setShowInactive] = useState(true);
  const [onlyProblems, setOnlyProblems] = useState(false);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  // Root kinds start open: the top of the tree is what a person reads first.
  const roots = schema.data?.roots;
  useEffect(() => {
    if (roots) setExpanded((now) => new Set([...now, ...roots.map(rootNode)]));
  }, [roots]);
  // With nothing chosen, the first root kind is: never an empty page.
  // A record opened from a link: open the branches above it, so the tree shows where it is.
  const opened = usePlace(domainId, selectedRecord);
  const openedPath = opened.data?.path;
  useEffect(() => {
    if (openedPath && roots) setExpanded((now) => new Set([...now, ...pathNodes({ path: openedPath }, roots)]));
  }, [openedPath, roots]);
  const nothingChosen = selectedRecord == null && selectedRoot == null;
  useEffect(() => {
    if (nothingChosen && roots?.length) setParams({ kind: String(roots[0]) }, { replace: true });
  }, [nothingChosen, roots, setParams]);

  const setView = (v: View) => {
    setViewState(v);
    try {
      localStorage.setItem(VIEW_KEY, v);
    } catch {
      /* this page only */
    }
  };
  const select = (s: TreeSelection) =>
    setParams(s.kind === "record" ? { record: String(s.id) } : { kind: String(s.kindId) });
  const toggle = (node: string, open?: boolean) =>
    setExpanded((now) => {
      const next = new Set(now);
      if (open ?? !next.has(node)) next.add(node);
      else next.delete(node);
      return next;
    });

  async function move(moved: TreeRecord, onto: TreeRecord) {
    if (!schema.data || !can("domain.edit")) return;
    const field = moveField(schema.data, moved.entity_type_id, onto.entity_type_id);
    const kindName = (id: Id) => schema.data?.kinds.find((k) => k.id === id)?.name ?? "record";
    if (!field) {
      toast.error(`A ${kindName(moved.entity_type_id)} cannot be placed under a ${kindName(onto.entity_type_id)}.`);
      return;
    }
    if (!window.confirm(`Move ${moved.label || moved.key} under ${onto.label || onto.key} (${field} = ${onto.key})?`)) return;
    try {
      const fresh = await getEntity(moved.id);
      await updateEntity(moved.id, { attrs: { ...fresh.attrs, [field]: onto.key }, updated_at: fresh.updated_at });
      toast.success(`${moved.key} is now under ${onto.key}`);
      toggle(recordNode(onto.id), true);
      await queryClient.invalidateQueries({ queryKey: ["v1"] });
    } catch (err) {
      toast.error(formatApiError(err));
    }
  }

  const problemMap = problems.data?.records ?? {};
  const problemItems = problems.data?.items ?? [];
  const kinds = useMemo(() => schema.data?.kinds ?? [], [schema.data]);

  if (domainId === null) return <p className="text-sm">Choose a workspace first.</p>;
  if (schema.isError) return <p className="text-sm text-red-700">Could not read this domain: {formatApiError(schema.error)}</p>;
  if (!schema.data) return <p className="text-sm text-slate-500">Loading…</p>;
  if (kinds.length === 0) {
    return (
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold text-slate-900">Data workbench</h1>
        <p className="text-sm text-slate-600">
          This domain has no kinds of record yet.{" "}
          <Link className="underline" to={`/domains/${domainId}/data/records`}>
            Make the first one on the Records page
          </Link>
          .
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Data workbench</h1>
          <p className="text-sm text-slate-600">Pick a record in the tree; add what sits under it in the middle; edit it on the right.</p>
        </div>
        <Search
          domainId={domainId}
          onPick={(hit) => {
            setExpanded((now) => new Set([...now, ...pathNodes(hit, schema.data?.roots ?? [])]));
            select({ kind: "record", id: hit.id });
            setTimeout(() => document.getElementById(`wb-${hit.id}`)?.scrollIntoView({ block: "center" }), 300);
          }}
        />
      </header>
      <div className="flex flex-wrap items-center gap-4 text-sm text-slate-700">
        <label className="flex items-center gap-1">
          <input type="checkbox" checked={onlyProblems} onChange={(e) => setOnlyProblems(e.target.checked)} />
          Only records with problems{problemItems.length ? ` (${problemItems.length})` : ""}
        </label>
        <label className="flex items-center gap-1">
          <input type="checkbox" checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} />
          Show switched-off records
        </label>
      </div>
      <div className="grid gap-4 lg:grid-cols-[minmax(220px,280px)_1fr] xl:grid-cols-[minmax(220px,280px)_1fr_minmax(340px,420px)]">
        <aside className="max-h-[75vh] overflow-auto rounded-lg border border-slate-200 bg-white p-2">
          {onlyProblems ? (
            problemItems.length === 0 ? (
              <p className="p-2 text-sm text-emerald-800">No record has a problem.</p>
            ) : (
              <ul aria-label="Records with problems" className="space-y-0.5">
                {problemItems.map((p) => (
                  <li key={p.id}>
                    <button
                      type="button"
                      onClick={() => select({ kind: "record", id: p.id })}
                      className={`w-full rounded px-1 py-0.5 text-left text-sm hover:bg-slate-100 ${selectedRecord === p.id ? "bg-blue-100" : ""}`}
                    >
                      {p.label || p.key} <span className="text-xs text-slate-500">{p.kind}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )
          ) : (
            <WorkbenchTree
              domainId={domainId}
              schema={schema.data}
              problems={problemMap}
              selected={selection}
              onSelect={select}
              expanded={expanded}
              toggle={toggle}
              onMove={can("domain.edit") ? (a, b) => void move(a, b) : undefined}
              showInactive={showInactive}
            />
          )}
        </aside>
        <main className="min-w-0 rounded-lg border border-slate-200 bg-white p-4">
          <MasterPane
            domainId={domainId}
            schema={schema.data}
            selection={selection}
            tab={tab}
            setTab={(group) => setParams({ ...Object.fromEntries(params), tab: group })}
            view={view}
            setView={setView}
            problems={problemMap}
            onOpen={(id) => {
              // Opened from the list under the selection: open that branch too, so the tree shows where it is.
              if (selectedRecord != null) toggle(recordNode(selectedRecord), true);
              select({ kind: "record", id });
            }}
            showInactive={showInactive}
          />
        </main>
        <aside className="min-w-0 rounded-lg border border-slate-200 bg-white p-4 lg:col-span-2 xl:col-span-1">
          {selectedRecord != null ? (
            <DetailPane
              key={selectedRecord}
              entityId={selectedRecord}
              domainId={domainId}
              problems={problemMap[String(selectedRecord)] ?? []}
              onClosed={() => setParams(roots?.length ? { kind: String(roots[0]) } : {})}
            />
          ) : (
            <p className="text-sm text-slate-500">Choose a record to see and edit it here.</p>
          )}
        </aside>
      </div>
    </div>
  );
}
