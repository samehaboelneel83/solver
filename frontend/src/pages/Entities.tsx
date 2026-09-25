import { FormEvent, lazy, Suspense, useEffect, useId, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { formatAttrValue } from "../components/AttrsForm";
import { INPUT_CLASS } from "../components/attrTypes";
import OfflineNotice from "../components/OfflineNotice";
import Skeleton from "../components/Skeleton";
import { formatApiError } from "../api/errors";
import {
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
  useDocumentTitle("Entities");
  const { domainId } = useDomain();

  return (
    <div className="max-w-5xl">
      <h1 className="mb-4 text-lg font-semibold text-slate-900">Entities</h1>
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

  if (items.length === 0) {
    return (
      <div className="rounded-md border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
        <p>This domain has no entity types yet, and every entity belongs to one.</p>
        <p className="mt-1">
          <Link to="/entity-types" className="inline-block rounded py-1 text-blue-600 underline">
            Define an entity type first
          </Link>
          .
        </p>
      </div>
    );
  }

  return (
    <>
      <TypeChooser
        types={items}
        selected={selected}
        onSelect={(id) => setSearchParams({ type: String(id) }, { replace: true })}
      />
      {selected && (
        <EntityTable
          key={selected.id}
          type={selected}
          relationshipTypes={relationshipTypes.data?.items ?? []}
        />
      )}
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
  const id = useId();
  return (
    <div className="mb-4 flex flex-wrap items-end gap-4">
      <div>
        <label htmlFor={id} className="block text-sm font-medium text-slate-700">
          Entity type
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
          New entity
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
  const [searchParams, setSearchParams] = useSearchParams();
  const fromUrl = parseExprParam(searchParams.get("expr"));
  const qFromUrl = searchParams.get("q") ?? "";
  const [draft, setDraft] = useState(qFromUrl);
  const [q, setQ] = useState(qFromUrl);
  const [offset, setOffset] = useState(0);
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
            ? `No entities of this type match "${q}".`
            : "No entities of this type match these conditions."
          : "No entities of this type yet. Create the first one with “New entity” above."}
      </p>
    );
  } else {
    body = (
      <>
        <div className="overflow-x-auto rounded-md border border-slate-200 bg-white">
          <table className="w-full text-left text-sm" aria-label={`Entities of type ${type.name}`}>
            <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-600">
              <tr>
                <th scope="col" className="px-3 py-2 font-semibold">
                  Key
                </th>
                <th scope="col" className="px-3 py-2 font-semibold">
                  Label
                </th>
                <th scope="col" className="px-3 py-2 font-semibold">
                  Sort order
                </th>
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
                  <th scope="row" className="px-3 py-2 font-normal">
                    <Link to={`/entities/${entity.id}`} className="inline-block rounded py-1 font-mono text-blue-600 underline">
                      {entity.key}
                    </Link>
                  </th>
                  <td className="px-3 py-2 text-slate-700">{entity.label ?? "—"}</td>
                  <td className="px-3 py-2 text-slate-700">{entity.sort_order}</td>
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

  return (
    <>
      {search}
      {conditions}
      {body}
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
