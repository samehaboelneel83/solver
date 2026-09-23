import { useEffect, useId, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import OfflineNotice from "../components/OfflineNotice";
import Skeleton from "../components/Skeleton";
import { INPUT_CLASS } from "../components/attrTypes";
import { useToast } from "../components/ToastProvider";
import { useEntityList } from "../api/entities";
import { formatApiError } from "../api/errors";
import { useCapabilities } from "../hooks/useCapability";
import {
  useApplyTemplate,
  useCreateVersion,
  useClassify,
  useEntityTypes,
  useParameters,
  useRelationshipTypes,
  useTemplates,
  useVersion,
  useVersions,
  type ApplyTemplateResult,
  type EmptyRange,
  type Id,
} from "../api/v1";
import { checkIrShape } from "../ir";
import { isName, RELATIONS, SENSES, SEVERITIES } from "../ir/contract";
import TermBuilder, { BindingsEditor } from "../model/TermBuilder";
import DeclarationsEditor from "../model/DeclarationsEditor";
import { TreeItem, TreeView } from "../components/ui/tree-view";
import { parameterOptions, cleanVariable, type VariableSpec } from "../model/declarations";
import {
  cleanBinding,
  cleanTerm,
  declaredRelationships,
  describeBinding,
  describeSchedule,
  describeTerm,
  freeNumberedId,
  nextBinding,
  type Binding,
  type Constraint,
  type ModelContext,
  type ObjectiveTerm,
  type Term,
} from "../model/terms";
import { useDomain } from "../hooks/useDomain";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { parseRouteId } from "../lib/routeId";

/**
 * Writing a model: its constraints and its objective.
 *
 * **Where react-querybuilder sits.** Every binding's filter — "only the
 * weekend days", "only senior employees" — is edited with it, because a
 * filter is a boolean condition tree and that is what the library builds.
 * The arithmetic around the filters (`8 * sum(assign) <= hours_per_week`)
 * is not a condition tree, so `TermBuilder` handles that; `terms.ts`
 * explains why in full.
 *
 * **Versions are immutable, so this publishes rather than saves.** Editing
 * starts from the latest version's model and writes a new one, which is
 * what keeps a run's answer attributable to an exact model for ever. The
 * server validates against the IR contract and refuses with the offending
 * path, so a model this screen builds wrongly is named, not stored.
 *
 * Sets, parameters and variables are shown read-only: they are declared by
 * the domain and by the previous version, and changing them is a different
 * job from writing a rule.
 */

/** A model with nothing in it: what "start from scratch" means. The keys are
 * all present because the contract requires every top-level key, including
 * the empty ones -- a missing `constraints` is a different document from an
 * empty one, and only one of them is valid. */
const EMPTY_MODEL = {
  version: 2,
  sets: [],
  parameters: {},
  variables: {},
  constraints: [],
  objective: { sense: "minimize", mode: "weighted", terms: [] },
} as const;

type Draft = {
  sets: string[];
  parameters: Record<string, { index: string[] }>;
  variables: Record<string, VariableSpec>;
  constraints: Constraint[];
  objective: { sense: string; mode: string; terms: ObjectiveTerm[] };
};

function emptyRangeWhere(item: EmptyRange): string {
  const keys = Object.values(item.index);
  if (keys.length === 0) return "";
  return ` at ${keys.join(" · ")}`;
}

export default function ModelEditor() {
  useDocumentTitle("Model editor");
  const { domainId } = useDomain();

  return (
    <div className="max-w-5xl">
      <h1 className="mb-1 text-lg font-semibold text-slate-900">Model editor</h1>
      <p className="mb-4 text-sm text-slate-500">
        The rules a solver must respect, and what it should make as small or as large as it can.
        Publishing writes a new version: the old one keeps working, and every run stays attributable
        to the exact model that produced it.
      </p>
      {domainId === null ? (
        <div className="rounded-md border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
          <p>Choose a domain in the sidebar&rsquo;s Domain selector (under Menu on a small screen).</p>
        </div>
      ) : (
        <ForDomain domainId={domainId} />
      )}
    </div>
  );
}

function ForDomain({ domainId }: { domainId: Id }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const chooserId = useId();
  const problems = useEntityList("public", "problem", {
    limit: 500,
    offset: 0,
    orderBy: "name",
    order: "asc",
    filters: { domain_id: String(domainId) },
  });

  if (problems.fetchStatus === "paused" && !problems.data) return <OfflineNotice subject="The problem list" />;
  if (problems.isLoading) return <Skeleton rows={3} cols={4} />;

  const items = problems.data?.items ?? [];
  if (items.length === 0) {
    return (
      <Note>
        <p>This domain has no problems yet, and a model belongs to one.</p>
        <p className="mt-1">
          Create one on the{" "}
          <Link to="/public/problem" className="inline-block rounded py-1 text-blue-600 underline">
            Problems page
          </Link>
          , or start from a template. Missing types are created from its seed.
        </p>
        <StartFromTemplates
          domainId={domainId}
          onApplied={(result) => setSearchParams({ problem: String(result.problem_id) }, { replace: true })}
        />
      </Note>
    );
  }

  const requested = parseRouteId(searchParams.get("problem"));
  const problem = items.find((row) => Number(row.id) === requested) ?? items[0];
  const problemId = Number(problem.id);

  return (
    <>
      <div className="mb-4">
        <label htmlFor={chooserId} className="block text-sm font-medium text-slate-700">
          Problem
        </label>
        <select
          id={chooserId}
          className={`${INPUT_CLASS} max-w-sm`}
          value={String(problemId)}
          onChange={(event) => setSearchParams({ problem: event.target.value }, { replace: true })}
        >
          {items.map((row) => (
            <option key={String(row.id)} value={String(row.id)}>
              {String(row.name ?? row.id)}
            </option>
          ))}
        </select>
      </div>
      <Editor key={problemId} problemId={problemId} domainId={domainId} />
    </>
  );
}

function Editor({ problemId, domainId }: { problemId: Id; domainId: Id }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const versions = useVersions(problemId, { limit: 50, offset: 0 });
  const versionItems = versions.data?.items ?? [];
  // Editing an older version is not editing it: publishing always writes a
  // new latest, because a version a run points at can never change. So this
  // chooses a *starting point*, which is why the label says so.
  const requestedVersion = parseRouteId(searchParams.get("version"));
  const base = versionItems.find((row) => row.id === requestedVersion) ?? versionItems[0] ?? null;
  const baseId = base?.id ?? null;
  const latest = useVersion(baseId);
  const [scratch, setScratch] = useState(false);
  const entityTypes = useEntityTypes(domainId, { limit: 500, offset: 0 });
  const relationshipTypes = useRelationshipTypes(domainId, { limit: 500, offset: 0 });
  const parameters = useParameters(domainId, { limit: 500, offset: 0 });
  const createVersion = useCreateVersion();
  const toast = useToast();

  const [draft, setDraft] = useState<Draft | null>(null);
  // What the draft was seeded from: a version id, or "scratch". The draft is
  // re-seeded exactly when this stops matching what the page shows.
  //
  // It used to be "seed when the draft is empty", with every change of
  // starting point clearing the draft and moving the URL in one handler. If
  // the URL move landed a render after the clear -- it can -- the effect saw
  // an empty draft beside the OLD version and seeded from it; by the time the
  // URL caught up the draft was no longer empty, so it was never re-seeded.
  // The page then said "starting from version 1" over version 2's rules, and
  // publishing would have built on the wrong one.
  const [seededFrom, setSeededFrom] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  const ir = (scratch ? EMPTY_MODEL : latest.data?.ir) as Record<string, unknown> | undefined;
  const seedKey = scratch ? "scratch" : baseId === null ? null : `version-${baseId}`;

  useEffect(() => {
    if (!ir || seedKey === null || (draft && seededFrom === seedKey)) return;
    setSeededFrom(seedKey);
    setDraft({
      sets: [...((ir.sets as string[]) ?? [])],
      parameters: { ...((ir.parameters as Draft["parameters"]) ?? {}) },
      variables: { ...((ir.variables as Draft["variables"]) ?? {}) },
      constraints: ((ir.constraints as Constraint[]) ?? []).map((c) => ({ ...c })),
      objective: {
        sense: ((ir.objective as { sense?: string })?.sense as string) ?? "minimize",
        mode: ((ir.objective as { mode?: string })?.mode as string) === "lex" ? "lex" : "weighted",
        terms: (((ir.objective as { terms?: ObjectiveTerm[] })?.terms ?? []) as ObjectiveTerm[]).map(
          (t) => ({ ...t })
        ),
      },
    });
    // `draft` is read only to ask "is there one yet"; listing it would re-run
    // this on every keystroke for nothing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ir, seedKey, seededFrom]);

  const context: ModelContext | null = useMemo(() => {
    if (!ir || !draft) return null;
    const types = entityTypes.data?.items ?? [];
    // From the **draft**, not the stored version: a set or variable declared
    // a moment ago has to be offered by the term editor immediately, or the
    // two halves of this page disagree about what the model is.
    const sets = draft.sets;
    return {
      sets,
      setIds: Object.fromEntries(
        sets.map((name) => [name, Number(types.find((t) => t.name === name)?.id ?? 0)])
      ),
      attributes: Object.fromEntries(
        sets.map((name) => [
          name,
          (types.find((t) => t.name === name)?.attributes ?? []).map((a) => ({
            name: a.name,
            data_type: a.data_type,
          })),
        ])
      ),
      variables: draft.variables as ModelContext["variables"],
      parameters: draft.parameters as ModelContext["parameters"],
      // Every relationship type of the domain whose BOTH ends are sets this
      // model declares. An edge to a type the model does not carry could not
      // bind an index to anything, so offering it would only produce a
      // refusal. Which of these the IR declares is decided on save, from the
      // walks actually written -- see `declaredRelationships`.
      relationships: (relationshipTypes.data?.items ?? [])
        .map((rel) => ({
          name: rel.name,
          from: types.find((t) => t.id === rel.from_type_id)?.name ?? "",
          to: types.find((t) => t.id === rel.to_type_id)?.name ?? "",
        }))
        .filter((rel) => sets.includes(rel.from) && sets.includes(rel.to)),
    };
  }, [ir, draft, entityTypes.data, relationshipTypes.data]);

  const nextIr = useMemo(() => {
    if (!ir || !draft) return null;
    // An objective with no terms is refused by the contract -- "omit the
    // objective otherwise" -- because an empty one and an absent one would
    // otherwise be two spellings of "optimise nothing". A model with only
    // rules is legitimate: it asks for any answer that satisfies them.
    const { objective: _previous, relationships: _edges, ...withoutObjective } = ir;
    const walked = declaredRelationships(draft.constraints, draft.objective.terms);
    return {
      ...withoutObjective,
      sets: draft.sets,
      // Derived from the walks, not declared by hand. `sets` is declared
      // because a set may legitimately be carried and never used -- for
      // display, or for a later version (contract 3.1). A relationship has no
      // such use: you declare one to walk it. Deriving it removes the only
      // way this screen could build a `binding_via_rel_not_declared`.
      ...(walked.length > 0 ? { relationships: walked } : {}),
      parameters: draft.parameters,
      variables: Object.fromEntries(
        Object.entries(draft.variables).map(([name, spec]) => [name, cleanVariable(spec)])
      ),
      constraints: draft.constraints.map((constraint) => {
        // A hard rule must not carry a weight (contract §3.4); a soft one
        // must. The Strength control keeps the draft honest, and this
        // strips a leftover weight so Publish is not blocked by a key
        // the person can no longer see.
        let next: Constraint =
          constraint.severity === "soft"
            ? {
                ...constraint,
                weight: constraint.weight && constraint.weight >= 1 ? constraint.weight : 1,
              }
            : (() => {
                const { weight: _dropped, ...rest } = constraint;
                return rest;
              })();
        // A blank "What it means" is not prose — omit the key rather than
        // publish an empty string.
        if (!next.note?.trim()) {
          const { note: _blank, ...rest } = next;
          next = rest;
        }
        // An empty forall is refused; omit it the same way the editor does
        // when the last index is removed.
        if (Array.isArray(next.forall) && next.forall.length === 0) {
          const { forall: _empty, ...rest } = next;
          next = rest;
        }
        // Drop empty where arrays and any UI-only `problems` left on a
        // binding after a filter was refused then fixed.
        if (next.forall) {
          next = { ...next, forall: next.forall.map(cleanBinding) };
        }
        if (next.left) next = { ...next, left: cleanTerm(next.left) };
        if (next.right) next = { ...next, right: cleanTerm(next.right) };
        return next;
      }),
      ...(draft.objective.terms.length > 0
        ? {
            objective: {
              sense: draft.objective.sense,
              ...(draft.objective.mode === "lex" ? { mode: "lex" } : {}),
              terms: draft.objective.terms.map((term) => ({
                ...term,
                expression: term.expression ? cleanTerm(term.expression) : term.expression,
              })),
            },
          }
        : {}),
    };
  }, [ir, draft]);
  // `checkIrShape` answers with the refusal itself, or null when the
  // document is shaped right. The server judges it again -- this is the
  // half that can be answered without the domain.
  const refusal = nextIr ? checkIrShape(nextIr) : null;
  const classification = useClassify(
    nextIr !== null && refusal === null ? (nextIr as Record<string, unknown>) : null,
    problemId
  );

  if (versions.isLoading || (baseId !== null && latest.isLoading) || entityTypes.isLoading) {
    return <Skeleton rows={4} cols={3} />;
  }
  if (baseId === null && !scratch) {
    return (
      <Note>
        <p>This problem has no model yet.</p>
        <p className="mt-1">
          Starting one declares what it is about — which sets it ranges over, which of the
          domain&rsquo;s parameters it reads — and then its rules.
        </p>
        <button
          type="button"
          className="mt-3 rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700"
          onClick={() => {
            setScratch(true);
            setSeededFrom("scratch");
            setDraft({
              sets: [],
              parameters: {},
              variables: {},
              constraints: [],
              objective: { sense: "minimize", mode: "weighted", terms: [] },
            });
          }}
        >
          Start a model
        </button>
        <StartFromTemplates
          domainId={domainId}
          problemId={problemId}
          onApplied={() => {
            versions.refetch();
          }}
        />
      </Note>
    );
  }
  if (!draft || !context || !ir || nextIr === null) return <Skeleton rows={4} cols={3} />;
  const toPublish = nextIr as Record<string, unknown>;

  function publish() {
    setFailure(null);
    createVersion.mutate(
      { problemId, body: { ir: toPublish, note: "edited in the model editor" } },
      {
        onSuccess: (created: { id: Id; version: number }) => {
          toast.success(`Published version ${created.version}`);
          setScratch(false);
          setSearchParams(
            { problem: String(problemId), version: String(created.id) },
            { replace: true }
          );
          versions.refetch();
        },
        onError: (error: unknown) => setFailure(formatApiError(error)),
      }
    );
  }

  return (
    <>
      {versionItems.length > 0 && !scratch ? (
        <div className="mb-4">
          <label htmlFor="model-base" className="block text-sm font-medium text-slate-700">
            Starting from
          </label>
          <select
            id="model-base"
            className={`${INPUT_CLASS} max-w-sm`}
            value={String(baseId ?? "")}
            onChange={(event) => {
              setSearchParams(
                { problem: String(problemId), version: event.target.value },
                { replace: true }
              );
            }}
          >
            {versionItems.map((row) => (
              <option key={String(row.id)} value={String(row.id)}>
                version {row.version}
                {row.note ? ` — ${row.note}` : ""}
              </option>
            ))}
          </select>
          <p className="mt-1 text-xs text-slate-500">
            Publishing writes a new version either way: an older one is a starting point, never
            something this overwrites.
          </p>
        </div>
      ) : (
        <p className="mb-4 text-sm text-slate-600">Starting a model from nothing.</p>
      )}

      <DeclarationsEditor
        sets={draft.sets}
        parameters={draft.parameters}
        variables={draft.variables}
        entityTypeNames={(entityTypes.data?.items ?? []).map((type) => type.name)}
        parameterOptions={parameterOptions(
          parameters.data?.items ?? [],
          entityTypes.data?.items ?? []
        )}
        constraints={draft.constraints}
        objectiveTerms={draft.objective.terms}
        onChange={(next) => setDraft((current) => current && { ...current, ...next })}
      />

      <section aria-labelledby="constraints-heading" className="mb-6">
        <h2 id="constraints-heading" className="mb-2 text-base font-semibold text-slate-900">
          What must be true
        </h2>
        {draft.constraints.length === 0 && (
          <p className="mb-2 text-sm text-slate-600">No rules yet. Add one that must hold.</p>
        )}
        <div className="space-y-1">
          {draft.constraints.map((constraint, position) => (
            <ConstraintCard
              key={position}
              constraint={constraint}
              otherIds={draft.constraints
                .filter((_, i) => i !== position)
                .map((c) => c.id)}
              context={context}
              onChange={(next) =>
                setDraft((current) =>
                  current && {
                    ...current,
                    constraints: current.constraints.map((c, i) => (i === position ? next : c)),
                  }
                )
              }
              onRemove={() =>
                setDraft((current) =>
                  current && {
                    ...current,
                    constraints: current.constraints.filter((_, i) => i !== position),
                  }
                )
              }
            />
          ))}
        </div>
        <button
          type="button"
          className="mt-3 rounded border border-slate-300 px-3 py-2 text-sm text-slate-700"
          onClick={() =>
            setDraft((current) =>
              current && {
                ...current,
                constraints: [
                  ...current.constraints,
                {
                  id: freeNumberedId(
                    "c_",
                    current.constraints.map((constraint) => constraint.id)
                  ),
                  // No set yet → a global rule (omit forall). Naming an
                  // empty set would publish a binding the contract refuses.
                  ...(context.sets.length > 0
                    ? { forall: [nextBinding([], context)] }
                    : {}),
                  left: { const: 0 },
                  relation: "<=",
                  right: { const: 0 },
                  severity: "hard",
                } as Constraint,
                ],
              }
            )
          }
        >
          Add a rule
        </button>
      </section>

      <section aria-labelledby="objective-heading" className="mb-6">
        <h2 id="objective-heading" className="mb-2 text-base font-semibold text-slate-900">
          What to make best
        </h2>
        <ObjectiveEditor
          objective={draft.objective}
          context={context}
          onChange={(objective) => setDraft((current) => current && { ...current, objective })}
        />
      </section>

      {refusal === null && classification.data && (
        <aside aria-label="What this model is" className="mb-4 rounded-md border border-slate-200 bg-slate-50 p-3">
          <h2 className="mb-1 text-sm font-semibold text-slate-900">What this model is</h2>
          {classification.data.planner.length > 0 && (
            <ul className="list-disc space-y-1 pl-5 text-sm text-slate-700">
              {classification.data.planner.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          )}
          {classification.data.would_solve ? (
            <p className={`text-sm text-slate-700 ${classification.data.planner.length > 0 ? "mt-2" : ""}`}>
              {classification.data.would_solve}
            </p>
          ) : (
            <p
              className={`text-sm text-amber-800 ${classification.data.planner.length > 0 ? "mt-2" : ""}`}
            >
              No solver this platform has can take this model.
            </p>
          )}
        </aside>
      )}

      {refusal === null && (classification.data?.empty_ranges.length ?? 0) > 0 && (
        <aside
          aria-label="Rules that ranged over nobody"
          className="mb-4 rounded-md border border-slate-200 bg-slate-50 p-3"
        >
          <h2 className="mb-1 text-sm font-semibold text-slate-900">Rules that ranged over nobody</h2>
          <p className="mb-2 text-sm text-slate-700">
            A rule that matches nobody never constrains anyone. Check the filter, or the data it ranges
            over.
          </p>
          <ul className="space-y-1 text-sm text-slate-800">
            {classification.data?.empty_ranges.map((item) => (
              <li key={`${item.constraint_id}:${item.kind}:${Object.values(item.index).join(",")}`}>
                <span className="font-mono">{item.constraint_id}</span>
                {item.kind === "forall"
                  ? " never applied to anyone"
                  : ` counted nobody${emptyRangeWhere(item)}`}
              </li>
            ))}
          </ul>
        </aside>
      )}

      {refusal && (
        <p role="alert" className="mb-3 text-sm text-red-600">
          {refusal.message}
        </p>
      )}
      {failure && (
        <p role="alert" className="mb-3 whitespace-pre-line text-sm text-red-600">
          {failure}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={publish}
          disabled={createVersion.isPending || refusal !== null}
          className="rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
        >
          {createVersion.isPending ? "Publishing…" : "Publish a new version"}
        </button>
        <span className="text-sm text-slate-500">
          The version you started from is untouched, and any run of it keeps its answer.
        </span>
      </div>
    </>
  );
}

function ConstraintCard({
  constraint,
  otherIds,
  context,
  onChange,
  onRemove,
}: {
  constraint: Constraint;
  otherIds: string[];
  context: ModelContext;
  onChange: (next: Constraint) => void;
  onRemove: () => void;
}) {
  const idField = useId();
  const noteField = useId();
  const bound: Binding[] = constraint.forall ?? [];
  const idProblem = !constraint.id
    ? "A rule needs a name."
    : !isName(constraint.id)
      ? "A name starts with a letter and uses lower-case letters, digits and underscores."
      : otherIds.includes(constraint.id)
        ? `Another rule is already called ${constraint.id}.`
        : null;

  return (
    <article className="rounded-md border border-slate-200 bg-white p-2">
    <TreeItem
      name={constraint.id || "rule"}
      header={
        <div className="flex min-w-0 flex-1 flex-wrap items-end gap-3">
          <div>
            <label htmlFor={idField} className="block text-xs text-slate-600">
              Name
            </label>
            <input
              id={idField}
              className={`${INPUT_CLASS} w-48 text-sm`}
              value={constraint.id}
              aria-invalid={idProblem ? "true" : undefined}
              aria-describedby={idProblem ? `${idField}-problem` : undefined}
              onChange={(event) => onChange({ ...constraint, id: event.target.value })}
            />
            {idProblem && (
              <p id={`${idField}-problem`} role="alert" className="mt-1 text-xs text-red-600">
                {idProblem}
              </p>
            )}
          </div>
          <div className="min-w-0 flex-1">
            <label htmlFor={noteField} className="block text-xs text-slate-600">
              What it means
            </label>
            <input
              id={noteField}
              className={`${INPUT_CLASS} text-sm`}
              value={constraint.note ?? ""}
              onChange={(event) => onChange({ ...constraint, note: event.target.value })}
            />
          </div>
        </div>
      }
      actions={
        <button type="button" onClick={onRemove} className="rounded px-2 py-1 text-sm text-red-700 underline">
          Remove
        </button>
      }
    >
      {describeSchedule(constraint) !== null ? (
        <div className="rounded border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">
          <p className="font-mono text-xs">
            {constraint.forall?.length ? `for every ${constraint.forall.map(describeBinding).join(", ")}: ` : ""}
            {describeSchedule(constraint)}
          </p>
          <p className="mt-1">
            A scheduling rule, always required. Kept as published; it cannot be edited here yet.
          </p>
        </div>
      ) : constraint.left == null || constraint.right == null ? (
        <div className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          <p>
            This rule is named but not expressed — a leftover of versions that
            predate the contract. There is nothing here to edit, and publishing
            it as-is is refused.
          </p>
          <button
            type="button"
            className="mt-2 rounded px-2 py-1 text-sm text-amber-950 underline"
            onClick={() =>
              onChange({
                ...constraint,
                left: { const: 0 },
                relation: constraint.relation ?? "<=",
                right: { const: 0 },
                severity: constraint.severity ?? "hard",
              })
            }
          >
            Start expressing it
          </button>
        </div>
      ) : (
        <TreeView>
          <p className="mb-1 px-2 font-mono text-xs text-slate-500">
            {describeTerm(constraint.left)} {constraint.relation} {describeTerm(constraint.right)}
          </p>

          <BindingsEditor
            bindings={bound}
            onChange={(forall) => {
              // Omit the key when there is nothing to range over — an empty
              // array is refused (contract §3.4).
              if (forall.length === 0) {
                const { forall: _dropped, ...rest } = constraint;
                onChange(rest);
                return;
              }
              onChange({ ...constraint, forall });
            }}
            context={context}
            outer={[]}
            legend="For every"
            minBindings={0}
          />

          <TermBuilder
            value={constraint.left}
            onChange={(left) => onChange({ ...constraint, left })}
            context={context}
            bound={bound}
            label="This"
          />

          <div className="flex flex-wrap items-end gap-3 px-2 py-1">
            <Choice
              label="Must be"
              value={constraint.relation ?? "<="}
              options={RELATIONS.map((r) => ({ value: r, label: relationLabel(r) }))}
              onChange={(relation) =>
                onChange({ ...constraint, relation: relation as Constraint["relation"] })
              }
            />
            <Choice
              label="Strength"
              value={constraint.severity ?? "hard"}
              options={SEVERITIES.map((s) => ({
                value: s,
                label: s === "hard" ? "required" : "preferred",
              }))}
              onChange={(severity) => {
                const next = severity as Constraint["severity"];
                if (next === "soft") {
                  onChange({
                    ...constraint,
                    severity: next,
                    weight: constraint.weight && constraint.weight >= 1 ? constraint.weight : 1,
                  });
                  return;
                }
                const { weight: _dropped, ...rest } = constraint;
                onChange({ ...rest, severity: next });
              }}
            />
            {constraint.severity === "soft" && (
              <div>
                <label className="block text-xs text-slate-600" htmlFor={`${idField}-weight`}>
                  How much it matters
                </label>
                <input
                  id={`${idField}-weight`}
                  inputMode="numeric"
                  className={`${INPUT_CLASS} w-28 text-sm`}
                  value={String(constraint.weight ?? 1)}
                  onChange={(event) => {
                    // A soft cost must be a positive integer (contract §3.4).
                    // Rejecting 0 here keeps the field honest — Publish used
                    // to coerce it silently while the box still showed 0.
                    const raw = event.target.value;
                    if (!/^\d*$/.test(raw)) return;
                    if (raw === "") {
                      onChange({ ...constraint, weight: 1 });
                      return;
                    }
                    const next = Number(raw);
                    if (Number.isSafeInteger(next) && next >= 1) {
                      onChange({ ...constraint, weight: next });
                    }
                  }}
                />
              </div>
            )}
          </div>

          <TermBuilder
            value={constraint.right}
            onChange={(right) => onChange({ ...constraint, right })}
            context={context}
            bound={bound}
            label="That"
          />
        </TreeView>
      )}
    </TreeItem>
    </article>
  );
}

function ObjectiveEditor({
  objective,
  context,
  onChange,
}: {
  objective: { sense: string; mode: string; terms: ObjectiveTerm[] };
  context: ModelContext;
  onChange: (next: { sense: string; mode: string; terms: ObjectiveTerm[] }) => void;
}) {
  const lex = objective.mode === "lex";

  function moveTerm(from: number, to: number) {
    if (to < 0 || to >= objective.terms.length) return;
    const terms = [...objective.terms];
    const [moved] = terms.splice(from, 1);
    terms.splice(to, 0, moved);
    onChange({ ...objective, terms });
  }

  return (
    <div className="rounded-md border border-slate-200 bg-white p-4">
      <Choice
        label="The solver should"
        value={objective.sense}
        options={SENSES.map((s) => ({ value: s, label: s === "minimize" ? "make it as small as possible" : "make it as large as possible" }))}
        onChange={(sense) => onChange({ ...objective, sense })}
      />
      <Choice
        label="When there is more than one goal"
        value={objective.mode}
        options={[
          { value: "weighted", label: "mix them by weight" },
          { value: "lex", label: "this order: first goal, then the next" },
        ]}
        onChange={(mode) => onChange({ ...objective, mode })}
      />

      <div className="mt-3 space-y-1">
        {objective.terms.length === 0 && (
          <p className="text-sm text-slate-600">
            No goals yet. Leave it empty for a feasibility problem, or add one.
          </p>
        )}
        {objective.terms.map((term, position) => {
          const otherIds = objective.terms
            .filter((_, i) => i !== position)
            .map((t) => t.id);
          const idProblem = !term.id
            ? "A goal needs a name."
            : !isName(term.id)
              ? "A name starts with a letter and uses lower-case letters, digits and underscores."
              : otherIds.includes(term.id)
                ? `Another goal is already called ${term.id}.`
                : null;
          return (
          <TreeItem
            key={position}
            name={term.id || "objective term"}
            header={
              <div className="flex flex-wrap items-end gap-3">
                <div>
                  <label className="block text-xs text-slate-600" htmlFor={`obj-${position}-id`}>
                    Name
                  </label>
                  <input
                    id={`obj-${position}-id`}
                    className={`${INPUT_CLASS} w-48 text-sm`}
                    value={term.id}
                    aria-invalid={idProblem ? "true" : undefined}
                    aria-describedby={idProblem ? `obj-${position}-id-problem` : undefined}
                    onChange={(event) =>
                      onChange({
                        ...objective,
                        terms: objective.terms.map((t, i) =>
                          i === position ? { ...t, id: event.target.value } : t
                        ),
                      })
                    }
                  />
                  {idProblem && (
                    <p
                      id={`obj-${position}-id-problem`}
                      role="alert"
                      className="mt-1 text-xs text-red-600"
                    >
                      {idProblem}
                    </p>
                  )}
                </div>
                {lex ? (
                  <div>
                    <span className="block text-xs text-slate-600">Goal order</span>
                    <p className="mt-1 font-mono text-sm text-slate-900" data-testid={`goal-order-${position}`}>
                      {ordinal(position + 1)}
                    </p>
                  </div>
                ) : (
                  <div>
                    <label className="block text-xs text-slate-600" htmlFor={`obj-${position}-weight`}>
                      Weight
                    </label>
                    <input
                      id={`obj-${position}-weight`}
                      inputMode="numeric"
                      className={`${INPUT_CLASS} w-24 text-sm`}
                      value={String(term.weight)}
                      onChange={(event) => {
                        const next = Number(event.target.value);
                        if (/^[+-]?\d*$/.test(event.target.value) && Number.isSafeInteger(next)) {
                          onChange({
                            ...objective,
                            terms: objective.terms.map((t, i) =>
                              i === position ? { ...t, weight: next } : t
                            ),
                          });
                        }
                      }}
                    />
                  </div>
                )}
              </div>
            }
            actions={
              <span className="flex flex-wrap items-center gap-1">
                {lex && position > 0 && (
                  <button
                    type="button"
                    className="rounded px-2 py-1 text-sm text-slate-700 underline"
                    onClick={() => moveTerm(position, position - 1)}
                    aria-label={`Make ${term.id || "goal"} earlier`}
                  >
                    Earlier
                  </button>
                )}
                {lex && position < objective.terms.length - 1 && (
                  <button
                    type="button"
                    className="rounded px-2 py-1 text-sm text-slate-700 underline"
                    onClick={() => moveTerm(position, position + 1)}
                    aria-label={`Make ${term.id || "goal"} later`}
                  >
                    Later
                  </button>
                )}
                <button
                  type="button"
                  className="rounded px-2 py-1 text-sm text-red-700 underline"
                  onClick={() =>
                    onChange({ ...objective, terms: objective.terms.filter((_, i) => i !== position) })
                  }
                >
                  Remove
                </button>
              </span>
            }
          >
            {term.expression == null ? (
              <div className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                <p>This term is named but has nothing to count.</p>
                <button
                  type="button"
                  className="mt-2 rounded px-2 py-1 text-sm text-amber-950 underline"
                  onClick={() =>
                    onChange({
                      ...objective,
                      terms: objective.terms.map((t, i) =>
                        i === position ? { ...t, expression: { const: 0 } } : t
                      ),
                    })
                  }
                >
                  Start expressing it
                </button>
              </div>
            ) : (
              <TermBuilder
                value={term.expression}
                onChange={(expression) =>
                  onChange({
                    ...objective,
                    terms: objective.terms.map((t, i) =>
                      i === position ? { ...t, expression } : t
                    ),
                  })
                }
                context={context}
                bound={[]}
                label="Count"
              />
            )}
          </TreeItem>
          );
        })}
      </div>

      <button
        type="button"
        className="mt-3 rounded border border-slate-300 px-3 py-2 text-sm text-slate-700"
        onClick={() =>
          onChange({
            ...objective,
            terms: [
              ...objective.terms,
              {
                id: freeNumberedId(
                  "o_",
                  objective.terms.map((term) => term.id)
                ),
                weight: 1,
                expression: { const: 0 } as Term,
              },
            ],
          })
        }
      >
        Add something to count
      </button>
    </div>
  );
}

/** 1 → 1st, 2 → 2nd, 11 → 11th — the place a lex goal takes in the order. */
function ordinal(n: number): string {
  const mod100 = n % 100;
  if (mod100 >= 11 && mod100 <= 13) return `${n}th`;
  switch (n % 10) {
    case 1:
      return `${n}st`;
    case 2:
      return `${n}nd`;
    case 3:
      return `${n}rd`;
    default:
      return `${n}th`;
  }
}

function relationLabel(relation: string): string {
  if (relation === "<=") return "at most";
  if (relation === ">=") return "at least";
  return "exactly";
}

function Choice({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
}) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="block text-xs text-slate-600">
        {label}
      </label>
      <select
        id={id}
        className={`${INPUT_CLASS} w-auto text-sm`}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}

function Note({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">{children}</div>
  );
}

function StartFromTemplates({
  domainId,
  problemId,
  onApplied,
}: {
  domainId: Id;
  problemId?: Id;
  onApplied: (result: ApplyTemplateResult) => void;
}) {
  const { can } = useCapabilities();
  const templates = useTemplates();
  const apply = useApplyTemplate();
  const [failure, setFailure] = useState<string | null>(null);
  if (!can("model.publish")) return null;
  const items = templates.data?.items ?? [];
  if (items.length === 0) return null;
  return (
    <div className="mt-3">
      {items.map((row) => (
        <button
          key={String(row.id)}
          type="button"
          disabled={apply.isPending}
          className="mr-2 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-60"
          onClick={() => {
            setFailure(null);
            apply.mutate(
              {
                id: row.id,
                body: problemId
                  ? { problem_id: problemId, domain_id: domainId }
                  : { domain_id: domainId },
              },
              {
                onSuccess: onApplied,
                onError: (error: unknown) => setFailure(formatApiError(error)),
              }
            );
          }}
        >
          {apply.isPending ? "Starting…" : `Start from ${row.name}`}
        </button>
      ))}
      {failure && (
        <p role="alert" className="mt-2 text-sm text-red-600">
          {failure}
        </p>
      )}
    </div>
  );
}
