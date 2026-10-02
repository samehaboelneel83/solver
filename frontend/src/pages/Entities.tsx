import { FormEvent, lazy, Suspense, useEffect, useId, useMemo, useState } from "react";
import RecordsMap, { geometryFields } from "../components/map/RecordsMap";
import BulkPanel from "../components/BulkPanel";
import RecordGrid from "../components/RecordGrid";

import QuickStructure, { NewKindForm } from "../components/QuickStructure";
import EntityPicture from "../components/EntityPicture";
import { Link, useSearchParams } from "react-router-dom";
import { formatAttrValue } from "../components/AttrsForm";
import { INPUT_CLASS } from "../components/attrTypes";
import OfflineNotice from "../components/OfflineNotice";
import Skeleton from "../components/Skeleton";
import { formatApiError } from "../api/errors";
import {
  useDeleteEntities,
  useEntities,
  useEntityTypes,
  useRelationshipTypes,
  type EntityType,
  type Id,
  type RelationshipType,
} from "../api/v1";
import {
  buildFieldCatalogue,
  countRules,
  isEmptyDocument,
  validateExpression,
  withoutUntouchedRules,
  type ExpressionDocument,
} from "../expressions";
import { serverExpressionProblems } from "../expressions/serverProblems";
import { useCapabilities } from "../hooks/useCapability";
import { useDomain } from "../hooks/useDomain";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { parseRouteId } from "../lib/routeId";
import { useWords } from "../lib/words";
import { useEditorLevel } from "../model/editorLevel";
import FormulaField from "../components/FormulaField";
import LinkedTotalField from "../components/LinkedTotalField";
import LinkByField from "../components/LinkByField";

// Lazy, like the graph's filter bar. The builder is the only module that
// imports react-querybuilder, which Task 14c measured at +47.6 kB gz on a
// chunk that already warns; importing it here eagerly would undo that split
// for everyone who opens the Entities page, including the people who never
// open the panel. The two `lazy()` calls name the same module, so they
// share one chunk and one download.
const ExpressionBuilder = lazy(() => import("../expressions/ExpressionBuilder"));

/**
 * The selected domain's entities, one entity type at a time.
 *
 * The type chooser is not a convenience: `GET /api/v1/entities` has no
 * `domain_id` filter (Task 10's finding), only `entity_type_id`, and a
 * domain-wide list would have to fan out one request per type and merge
 * them -- with no way to page the result. A type also decides which
 * columns the table has, since they are its `attribute_def` rows.
 *
 * The chosen type, the search box and the condition document live in the
 * query string so a filtered list can be linked to and survives a reload,
 * and so the "New entity" link can carry the type.
 *
 * Conditions (Task 14d)
 * ---------------------
 * The same builder the graph uses, over the same catalogue, but the
 * filtering happens on the SERVER: the graph has its whole payload in
 * memory and this list has a page of fifty rows out of however many exist,
 * so a client-side filter here would hide rows from the current page and
 * silently miss every row on the others. The document goes to
 * `GET /api/v1/entities?expr=`, which compiles it to SQL.
 *
 * The catalogue offered here is the SELECTED type's attributes (plus the
 * entity's four columns and `count()` over the domain's relationship
 * types), not every type's. The list is one type's; a rule about another
 * type's attribute would be legal, compile, and match nothing -- the
 * "mixed entity types" shape `validate.ts` warns about. Not offering it is
 * better than warning about it after the fact.
 */

const PAGE_SIZE = 50;

/** How long the builder stays quiet before the document is sent. Every
 * keystroke in a value box changes the document, and unlike the graph's
 * filter each change here is a request. */
const APPLY_DELAY_MS = 400;

export default function Entities() {
  useDocumentTitle("Records");
  const { domainId } = useDomain();

  return (
    <div className="max-w-5xl">
      <h1 className="mb-4 text-lg font-semibold text-slate-900">Records</h1>
      {domainId === null ? (
        <div className="rounded-md border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
          <p>
            Choose a domain in the sidebar&rsquo;s Domain selector (under Menu on a small screen) to see its
            entities.
          </p>
          <p className="mt-1">
            No domain yet?{" "}
            <Link to="/public/domain" className="inline-block rounded py-1 text-blue-600 underline">
              Create one on the Domains page
            </Link>
            .
          </p>
        </div>
      ) : (
        <ForDomain domainId={domainId} />
      )}
    </div>
  );
}

function ForDomain({ domainId }: { domainId: Id }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const { can } = useCapabilities();
  const types = useEntityTypes(domainId, { limit: 500 });
  // For `count(<relationship type>, direction)`. Its failure is not this
  // page's failure: without it the builder simply offers no counts, which
  // is what `?? []` says.
  const relationshipTypes = useRelationshipTypes(domainId, { limit: 500 });
  const items = types.data?.items ?? [];

  const requested = parseRouteId(searchParams.get("type"));
  const selected = items.find((type) => type.id === requested) ?? items[0] ?? null;

  if (types.fetchStatus === "paused" && !types.data) return <OfflineNotice subject="The entity list" />;
  if (types.isLoading) return <Skeleton rows={3} cols={4} />;
  if (types.isError && !types.data) {
    return <Failed error={types.error} onRetry={() => types.refetch()} />;
  }

  const select = (id: Id) => setSearchParams({ type: String(id) }, { replace: true });

  if (items.length === 0) {
    return (
      <div className="rounded-md border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
        <p>This domain has no kinds of record yet, and every record is of one kind.</p>
        {can("domain.edit") ? (
          <div className="mt-2"><NewKindForm domainId={domainId} onMade={(made) => select(made.id)} /></div>
        ) : (
          <p className="mt-1">Someone who may edit this domain can add one.</p>
        )}
      </div>
    );
  }

  return (
    <>
      <TypeChooser
        types={items}
        selected={selected}
        onSelect={select}
      />
      {/* Data and structure together: a new kind of record, or a field, without leaving the records. */}
      {can("domain.edit") && <QuickStructure domainId={domainId} type={selected} onMade={(made) => select(made.id)} />}
      {selected && (
        <EntityTable
          key={selected.id}
          type={selected}
          relationshipTypes={relationshipTypes.data?.items ?? []}
        />
      )}
      {/* Queue R17b: the type's numbers and places as a picture. */}
      {selected && <EntityPicture key={`picture-${selected.id}`} type={selected} />}
    </>
  );
}

function TypeChooser({
  types,
  selected,
  onSelect,
}: {
  types: EntityType[];
  selected: EntityType | null;
  onSelect: (id: Id) => void;
}) {
  const { can } = useCapabilities();
  const w = useWords();
  const id = useId();
  return (
    <div className="mb-4 flex flex-wrap items-end gap-4">
      <div>
        <label htmlFor={id} className="block text-sm font-medium text-slate-700">
          {w("Entity type")}
        </label>
        <select
          id={id}
          className={`${INPUT_CLASS} font-mono`}
          value={selected ? String(selected.id) : ""}
          onChange={(event) => onSelect(Number(event.target.value))}
        >
          {types.map((type) => (
            <option key={type.id} value={type.id}>
              {type.name}
            </option>
          ))}
        </select>
      </div>
      {selected?.is_abstract && (
        <p className="text-sm text-slate-600">
          <span className="font-mono">{selected.name}</span> is abstract: its entities are those of the types that inherit from it.
        </p>
      )}
      {selected && !selected.is_abstract && can("domain.edit") && (
        <Link
          to={`/entities/new?type=${selected.id}`}
          className="rounded-md border border-slate-300 px-3 py-2 text-sm font-medium text-slate-800 hover:bg-slate-50"
        >
          {w("New entity")}
        </Link>
      )}
    </div>
  );
}

function Failed({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  return (
    <div className="mb-6 flex flex-wrap items-center gap-3">
      <p className="text-sm text-red-600">{formatApiError(error)}</p>
      <button
        type="button"
        onClick={onRetry}
        className="rounded-md border border-red-300 px-2 py-1 text-xs font-medium text-red-700 hover:bg-red-50"
      >
        Retry
      </button>
    </div>
  );
}


/**
 * The conditions panel: the builder, behind a toggle that says how many
 * conditions are set.
 *
 * Not a popover, for the reason Task 14c recorded on the graph: the
 * builder is as tall as the expression in it, and an anchored panel that
 * tall reaches out from under the page's own content. It expands the page
 * downwards instead, which also needs no clamping at 375px.
 */
function Conditions({
  type,
  relationshipTypes,
  value,
  onChange,
  serverProblems,
}: {
  type: EntityType;
  relationshipTypes: RelationshipType[];
  value: ExpressionDocument | null;
  onChange: (document: ExpressionDocument | null) => void;
  serverProblems: readonly { path: number[]; message: string }[];
}) {
  const [open, setOpen] = useState(() => countRules(value) > 0);
  const panelId = useId();
  const catalogue = useMemo(
    () => buildFieldCatalogue({ entityTypes: [type], relationshipTypes }),
    [type, relationshipTypes]
  );
  const count = countRules(value);

  // A refusal the user cannot see is a refusal they cannot fix, so the
  // panel opens itself when the server rejects what it sent.
  useEffect(() => {
    if (serverProblems.length > 0) setOpen(true);
  }, [serverProblems.length]);

  return (
    <div className="mb-4">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={panelId}
        title="Build a filter over this type's attributes"
        className="rounded-md border border-slate-300 px-3 py-2 text-sm font-medium text-slate-800 hover:bg-slate-50"
        data-testid="entities-conditions-toggle"
      >
        {count === 0 ? "No conditions" : count === 1 ? "1 condition" : `${count} conditions`}
      </button>

      {open && (
        <div
          id={panelId}
          className="mt-2 max-h-96 overflow-auto rounded-md border border-slate-200 bg-white p-2"
          data-testid="entities-conditions-panel"
        >
          <Suspense fallback={<p className="text-xs text-slate-500">Loading the condition builder…</p>}>
            <ExpressionBuilder
              catalogue={catalogue}
              value={value}
              onChange={onChange}
              extraProblems={serverProblems}
            />
          </Suspense>
          <button
            type="button"
            onClick={() => onChange(null)}
            className="mt-2 rounded-md border border-slate-300 px-2 py-1 text-xs"
            style={{ minWidth: 28, minHeight: 28 }}
            data-testid="entities-conditions-clear"
          >
            Clear conditions
          </button>
        </div>
      )}
    </div>
  );
}

function EntityTable({
  type,
  relationshipTypes,
}: {
  type: EntityType;
  relationshipTypes: RelationshipType[];
}) {
  const [level] = useEditorLevel();
  // Simple shows what a planner reads: the order records are listed in is a setting for Expert.
  const simple = level === "simple";
  const [searchParams, setSearchParams] = useSearchParams();
  const fromUrl = parseExprParam(searchParams.get("expr"));
  const qFromUrl = searchParams.get("q") ?? "";
  const [draft, setDraft] = useState(qFromUrl);
  const [q, setQ] = useState(qFromUrl);
  const [offset, setOffset] = useState(0);
  const { can } = useCapabilities();
  // Editing a page of records in place, spreadsheet-style.
  const [grid, setGrid] = useState(false);
  const [expression, setExpression] = useState<ExpressionDocument | null>(fromUrl);
  const [applied, setApplied] = useState<ExpressionDocument | null>(fromUrl);
  const searchId = useId();

  const catalogue = useMemo(
    () => buildFieldCatalogue({ entityTypes: [type], relationshipTypes }),
    [type, relationshipTypes]
  );

  /**
   * What is worth sending: a document that is neither empty nor invalid,
   * once the rules nobody has touched yet are taken out of it.
   *
   * An INVALID document means "no constraint", not "match nothing" -- the
   * same rule the graph applies. A half-written condition must not blank
   * the table, and it must never be sent: the server would answer 422 for
   * something the user is still in the middle of typing, and the builder
   * is already saying what is wrong.
   *
   * An UNTOUCHED one is the emptiest half of all, and it used to be sent
   * the instant "+ Condition" was pressed -- 5 rows to 0 before the person
   * had typed a character, which is the exact opposite of what the
   * paragraph above says this does. `withoutUntouchedRules` removes them
   * here rather than in the builder, which must keep rendering the row the
   * person is about to fill in.
   */
  const sendable = useMemo(() => {
    const pruned = withoutUntouchedRules(expression, catalogue);
    if (pruned === null || isEmptyDocument(pruned)) return null;
    return validateExpression(pruned, catalogue).valid ? pruned : null;
  }, [expression, catalogue]);
  const sendableKey = sendable === null ? "" : JSON.stringify(sendable);

  useEffect(() => {
    const timer = setTimeout(() => setApplied(sendableKey === "" ? null : JSON.parse(sendableKey)), APPLY_DELAY_MS);
    return () => clearTimeout(timer);
  }, [sendableKey]);

  // The type was already in the URL; the expression and the search were
  // not, so a filtered list could not be shared or survive a reload.
  useEffect(() => {
    const next = new URLSearchParams(searchParams);
    next.set("type", String(type.id));
    if (q) next.set("q", q);
    else next.delete("q");
    if (applied) next.set("expr", JSON.stringify(applied));
    else next.delete("expr");
    if (next.toString() === searchParams.toString()) return;
    setSearchParams(next, { replace: true });
  }, [applied, q, type.id, searchParams, setSearchParams]);

  // Records with a shape can be seen where they are (improvement plan 1.4).
  const [view, setView] = useState<"table" | "map">("table");
  const { data, error, isError, isLoading, refetch, fetchStatus } = useEntities(type.id, {
    q: q || undefined,
    expression: applied,
    limit: PAGE_SIZE,
    offset,
  });

  // A narrower search or condition can leave the current page past the end
  // of the result.
  useEffect(() => setOffset(0), [q, applied]);

  const serverProblems = useMemo(() => serverExpressionProblems(error), [error]);

  const rows = data?.items ?? [];
  const total = data?.total ?? 0;
  const filtered = Boolean(q) || applied !== null;
  // Records ticked to delete together: an import gone wrong is undone in one step (benchmark, October 2026).
  const [picked, setPicked] = useState<Set<Id>>(() => new Set());
  const removeMany = useDeleteEntities();
  const [removal, setRemoval] = useState<{ error: boolean; text: string } | null>(null);
  const canDelete = can("domain.edit");
  useEffect(() => setPicked(new Set()), [type.id, q, applied, offset]);
  const allPicked = rows.length > 0 && rows.every((e) => picked.has(e.id));
  function deletePicked() {
    const ids = [...picked];
    if (!ids.length || !window.confirm(`Delete ${ids.length} ${type.name} record${ids.length === 1 ? "" : "s"}? Their links and values go with them. This cannot be undone.`)) return;
    removeMany.mutate(ids, {
      onSuccess: (done) => { setPicked(new Set()); setRemoval({ error: false, text: `${done.deleted} records deleted.` }); },
      onError: (e) => setRemoval({ error: true, text: formatApiError(e) }),
    });
  }

  const conditions = (
    <Conditions
      type={type}
      relationshipTypes={relationshipTypes}
      value={expression}
      onChange={setExpression}
      serverProblems={serverProblems}
    />
  );

  const search = (
    <form
      className="mb-4 flex flex-wrap items-end gap-2"
      onSubmit={(event: FormEvent) => {
        event.preventDefault();
        setQ(draft.trim());
      }}
    >
      <div>
        <label htmlFor={searchId} className="block text-sm font-medium text-slate-700">
          Search
        </label>
        <input
          id={searchId}
          type="search"
          autoComplete="off"
          className={INPUT_CLASS}
          placeholder="key or label"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
        />
      </div>
      <button
        type="submit"
        className="rounded-md border border-slate-300 px-3 py-2 text-sm font-medium text-slate-800 hover:bg-slate-50"
      >
        Search
      </button>
    </form>
  );

  // The search box and the conditions panel are rendered whatever the
  // query is doing, so a refusal can be corrected in the control that
  // caused it. Only the result below them changes.
  let body: JSX.Element;
  if (fetchStatus === "paused" && !data) {
    body = <OfflineNotice subject="The entity list" />;
  } else if (isLoading) {
    body = <Skeleton rows={4} cols={4} />;
  } else if (serverProblems.length > 0 && !data) {
    // The builder is already showing the message against the rule it is
    // about; repeating it here would say the same thing twice.
    body = (
      <p className="text-sm text-red-600" data-testid="entities-expression-refused">
        The server could not use these conditions. See the condition list above.
      </p>
    );
  } else if (isError && !data) {
    body = <Failed error={error} onRetry={() => refetch()} />;
  } else if (rows.length === 0) {
    body = (
      <p className="text-sm text-slate-600">
        {filtered
          ? q
            ? simple ? `No ${type.name} records match "${q}".` : `No entities of this type match "${q}".`
            : simple ? `No ${type.name} records match these conditions.` : "No entities of this type match these conditions."
          : simple
            ? `No ${type.name} records yet. Add the first with “New record” above.`
            : "No entities of this type yet. Create the first one with “New entity” above."}
      </p>
    );
  } else {
    body = (
      <>
        {canDelete && picked.size > 0 && (
          <div className="mb-2 flex flex-wrap items-center gap-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm">
            <span>{picked.size} selected</span>
            <button type="button" disabled={removeMany.isPending} onClick={deletePicked}
              className="rounded-md bg-red-600 px-3 py-1 text-white disabled:opacity-60">
              {removeMany.isPending ? "Deleting…" : `Delete ${picked.size} selected`}
            </button>
            <button type="button" className="underline" onClick={() => setPicked(new Set())}>Clear</button>
          </div>
        )}
        {removal && <p role={removal.error ? "alert" : "status"} className={`mb-2 text-sm ${removal.error ? "text-red-700" : "text-green-800"}`}>{removal.text}</p>}
        <div className="overflow-x-auto rounded-md border border-slate-200 bg-white">
          <table className="w-full text-left text-sm" aria-label={`Entities of type ${type.name}`}>
            <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-600">
              <tr>
                {canDelete && (
                  <th scope="col" className="w-8 px-3 py-2">
                    <input type="checkbox" aria-label="Select every record on this page" checked={allPicked}
                      onChange={(e) => setPicked(e.target.checked ? new Set(rows.map((r) => r.id)) : new Set())} />
                  </th>
                )}
                <th scope="col" className="px-3 py-2 font-semibold">
                  Key
                </th>
                <th scope="col" className="px-3 py-2 font-semibold">
                  Label
                </th>
                {!simple && (
                  <th scope="col" className="px-3 py-2 font-semibold">
                    Sort order
                  </th>
                )}
                <th scope="col" className="px-3 py-2 font-semibold">
                  Active
                </th>
                {type.attributes.map((attribute) => (
                  <th key={attribute.id} scope="col" className="px-3 py-2 font-mono font-semibold normal-case">
                    {attribute.name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((entity) => (
                <tr key={entity.id} className="border-b border-slate-100 last:border-0">
                  {canDelete && (
                    <td className="px-3 py-2">
                      <input type="checkbox" aria-label={`Select ${entity.key}`} checked={picked.has(entity.id)}
                        onChange={(e) => setPicked((now) => {
                          const next = new Set(now);
                          if (e.target.checked) next.add(entity.id);
                          else next.delete(entity.id);
                          return next;
                        })} />
                    </td>
                  )}
                  <th scope="row" className="px-3 py-2 font-normal">
                    <Link to={`/entities/${entity.id}`} className="inline-block rounded py-1 font-mono text-blue-600 underline">
                      {entity.key}
                    </Link>
                  </th>
                  <td className="px-3 py-2 text-slate-700">{entity.label ?? "—"}</td>
                  {!simple && <td className="px-3 py-2 text-slate-700">{entity.sort_order}</td>}
                  <td className="px-3 py-2 text-slate-700">{entity.active ? "Yes" : "No"}</td>
                  {type.attributes.map((attribute) => (
                    <td key={attribute.id} className="px-3 py-2 text-slate-700">
                      {formatAttrValue(entity.attrs?.[attribute.name])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {total > PAGE_SIZE && (
          <div className="mt-3 flex flex-wrap items-center gap-3 text-sm text-slate-600">
            <span>
              {offset + 1}&ndash;{Math.min(offset + rows.length, total)} of {total}
            </span>
            <button
              type="button"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              className="rounded-md border border-slate-300 px-3 py-2 text-sm font-medium text-slate-800 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Previous
            </button>
            <button
              type="button"
              disabled={offset + rows.length >= total}
              onClick={() => setOffset(offset + PAGE_SIZE)}
              className="rounded-md border border-slate-300 px-3 py-2 text-sm font-medium text-slate-800 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Next
            </button>
          </div>
        )}
      </>
    );
  }

  const placed = geometryFields(type).length > 0;
  return (
    <>
      {/* Ratios and travel times as data, in Simple as in Expert (benchmark, October 2026); joins named in
          the title, where testers looked for them (re-test, October 2026). */}
      <details className="mb-4 rounded-md border border-slate-200 bg-white px-3 py-2">
        <summary className="cursor-pointer select-none text-sm font-medium text-slate-800">
          Compute and join: a field from others, link by a code (a join), totals of linked records
        </summary>
        <div className="mt-2"><FormulaField kind={type} /><LinkByField kind={type} /><LinkedTotalField kind={type} /></div>
        <p className="mt-3 text-xs text-slate-600">
          A value for each pair of records — a parcel&apos;s suitability for each crop read through its soil, 1 or 0 by a
          comparison — is made under{" "}
          <Link className="text-blue-700 underline" to={`/domains/${type.domain_id}/data/parameters`}>Data values → A data value computed from the records</Link>.
        </p>
      </details>
      {/* One door for bringing records in (improvement plan 4.5): a file of rows, or the features of a map layer. */}
      <details className="mb-4 rounded-md border border-slate-200 bg-white px-3 py-2">
        <summary className="cursor-pointer select-none text-sm font-medium text-slate-800">
          Import {type.name} records — from Excel / CSV, or from the map
        </summary>
        <div className="mt-2 space-y-2">
          <BulkPanel base={`/api/v1/entity-types/${type.id}`} what={`${type.name} records`} />
          <p className="text-xs text-slate-600">
            Places drawn in CAD or GIS? Import the file under{" "}
            <Link className="underline" to={`/domains/${type.domain_id}/map-data`}>Map data</Link>, then use its
            layers here (“Use in models”). A sheet with longitude and latitude columns becomes places on its own.
          </p>
        </div>
      </details>
      {search}
      {conditions}
      {placed && (
        <div role="tablist" aria-label="Show the records as" className="mb-3 inline-flex overflow-hidden rounded-md border border-slate-300 text-sm">
          {(["table", "map"] as const).map((v) => (
            <button key={v} role="tab" type="button" aria-selected={view === v} onClick={() => setView(v)}
              className={`px-3 py-1.5 ${view === v ? "bg-blue-600 text-white" : "bg-white text-slate-700 hover:bg-slate-50"}`}>
              {v === "table" ? "Table" : "Map"}
            </button>
          ))}
        </div>
      )}
      {can("domain.edit") && !(placed && view === "map") && (
        <div className="mb-3">
          <button
            type="button"
            aria-pressed={grid}
            onClick={() => setGrid(!grid)}
            className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50"
          >
            {grid ? "Back to the list" : "Edit as grid"}
          </button>
        </div>
      )}
      {placed && view === "map" ? (
        <RecordsMap type={type} />
      ) : grid && can("domain.edit") && data ? (
        <RecordGrid key={`${type.id}-${offset}`} type={type} records={rows} onDone={() => setGrid(false)} />
      ) : (
        body
      )}
    </>
  );
}

function parseExprParam(raw: string | null): ExpressionDocument | null {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (
      parsed !== null &&
      typeof parsed === "object" &&
      (parsed as ExpressionDocument).version === 1 &&
      typeof (parsed as ExpressionDocument).query === "object" &&
      (parsed as ExpressionDocument).query !== null
    ) {
      return parsed as ExpressionDocument;
    }
  } catch {
    // A broken link is no filter, not a crashed page.
  }
  return null;
}
