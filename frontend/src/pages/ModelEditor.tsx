import { useEffect, useId, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import OfflineNotice from "../components/OfflineNotice";
import Skeleton from "../components/Skeleton";
import { INPUT_CLASS } from "../components/attrTypes";
import { useToast } from "../components/ToastProvider";
import { useEntityList } from "../api/entities";
import { formatApiError } from "../api/errors";
import {
  useCreateVersion,
  useEntityTypes,
  useParameters,
  useRelationshipTypes,
  useVersion,
  useVersions,
  type Id,
} from "../api/v1";
import { checkIrShape } from "../ir";
import { RELATIONS, SENSES, SEVERITIES } from "../ir/contract";
import TermBuilder, { BindingsEditor } from "../model/TermBuilder";
import DeclarationsEditor from "../model/DeclarationsEditor";
import { parameterOptions } from "../model/declarations";
import {
  declaredRelationships,
  describeTerm,
  freeIndexName,
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
  version: 1,
  sets: [],
  parameters: {},
  variables: {},
  constraints: [],
  objective: { sense: "minimize", terms: [] },
} as const;

type Draft = {
  sets: string[];
  parameters: Record<string, { index: string[] }>;
  variables: Record<string, { index: string[]; domain: string }>;
  constraints: Constraint[];
  objective: { sense: string; terms: ObjectiveTerm[] };
};

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
          .
        </p>
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
  const [failure, setFailure] = useState<string | null>(null);

  const ir = (scratch ? EMPTY_MODEL : latest.data?.ir) as Record<string, unknown> | undefined;

  useEffect(() => {
    if (!ir || draft) return;
    setDraft({
      sets: [...((ir.sets as string[]) ?? [])],
      parameters: { ...((ir.parameters as Draft["parameters"]) ?? {}) },
      variables: { ...((ir.variables as Draft["variables"]) ?? {}) },
      constraints: ((ir.constraints as Constraint[]) ?? []).map((c) => ({ ...c })),
      objective: {
        sense: ((ir.objective as { sense?: string })?.sense as string) ?? "minimize",
        terms: (((ir.objective as { terms?: ObjectiveTerm[] })?.terms ?? []) as ObjectiveTerm[]).map(
          (t) => ({ ...t })
        ),
      },
    });
  }, [ir, draft]);

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
            setDraft({
              sets: [],
              parameters: {},
              variables: {},
              constraints: [],
              objective: { sense: "minimize", terms: [] },
            });
          }}
        >
          Start a model
        </button>
      </Note>
    );
  }
  if (!draft || !context || !ir) return <Skeleton rows={4} cols={3} />;

  // An objective with no terms is refused by the contract -- "omit the
  // objective otherwise" -- because an empty one and an absent one would
  // otherwise be two spellings of "optimise nothing". A model with only
  // rules is legitimate: it asks for any answer that satisfies them.
  const { objective: _previous, relationships: _edges, ...withoutObjective } = ir;
  const walked = declaredRelationships(draft.constraints, draft.objective.terms);
  const nextIr = {
    ...withoutObjective,
    sets: draft.sets,
    // Derived from the walks, not declared by hand. `sets` is declared
    // because a set may legitimately be carried and never used -- for
    // display, or for a later version (contract 3.1). A relationship has no
    // such use: you declare one to walk it. Deriving it removes the only
    // way this screen could build a `binding_via_rel_not_declared`.
    ...(walked.length > 0 ? { relationships: walked } : {}),
    parameters: draft.parameters,
    variables: draft.variables,
    constraints: draft.constraints,
    ...(draft.objective.terms.length > 0
      ? { objective: { sense: draft.objective.sense, terms: draft.objective.terms } }
      : {}),
  };
  // `checkIrShape` answers with the refusal itself, or null when the
  // document is shaped right. The server judges it again -- this is the
  // half that can be answered without the domain.
  const refusal = checkIrShape(nextIr);

  function publish() {
    setFailure(null);
    createVersion.mutate(
      { problemId, body: { ir: nextIr, note: "edited in the model editor" } },
      {
        onSuccess: (created: { id: Id; version: number }) => {
          toast.success(`Published version ${created.version}`);
          setDraft(null);
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
              setDraft(null);
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
        onChange={(next) => setDraft({ ...draft, ...next })}
      />

      <section aria-labelledby="constraints-heading" className="mb-6">
        <h2 id="constraints-heading" className="mb-2 text-base font-semibold text-slate-900">
          Rules
        </h2>
        <div className="space-y-4">
          {draft.constraints.map((constraint, position) => (
            <ConstraintCard
              key={position}
              constraint={constraint}
              context={context}
              onChange={(next) =>
                setDraft({
                  ...draft,
                  constraints: draft.constraints.map((c, i) => (i === position ? next : c)),
                })
              }
              onRemove={() =>
                setDraft({
                  ...draft,
                  constraints: draft.constraints.filter((_, i) => i !== position),
                })
              }
            />
          ))}
        </div>
        <button
          type="button"
          className="mt-3 rounded border border-slate-300 px-3 py-2 text-sm text-slate-700"
          onClick={() =>
            setDraft({
              ...draft,
              constraints: [
                ...draft.constraints,
                {
                  id: `c_${draft.constraints.length + 1}`,
                  forall: [{ index: freeIndexName([]), set: context.sets[0] ?? "" }],
                  left: { const: 0 },
                  relation: "<=",
                  right: { const: 0 },
                  severity: "hard",
                } as Constraint,
              ],
            })
          }
        >
          Add a rule
        </button>
      </section>

      <section aria-labelledby="objective-heading" className="mb-6">
        <h2 id="objective-heading" className="mb-2 text-base font-semibold text-slate-900">
          Objective
        </h2>
        <ObjectiveEditor
          objective={draft.objective}
          context={context}
          onChange={(objective) => setDraft({ ...draft, objective })}
        />
      </section>

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
  context,
  onChange,
  onRemove,
}: {
  constraint: Constraint;
  context: ModelContext;
  onChange: (next: Constraint) => void;
  onRemove: () => void;
}) {
  const idField = useId();
  const noteField = useId();
  const bound: Binding[] = constraint.forall ?? [];

  return (
    <article className="rounded-md border border-slate-200 bg-white p-4">
      <div className="mb-3 flex flex-wrap items-end gap-3">
        <div>
          <label htmlFor={idField} className="block text-xs text-slate-600">
            Name
          </label>
          <input
            id={idField}
            className={`${INPUT_CLASS} w-48 text-sm`}
            value={constraint.id}
            onChange={(event) => onChange({ ...constraint, id: event.target.value })}
          />
        </div>
        <div className="flex-1">
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
        <button type="button" onClick={onRemove} className="rounded px-2 py-2 text-sm text-red-700 underline">
          Remove
        </button>
      </div>

      <p className="mb-2 font-mono text-xs text-slate-500">
        {describeTerm(constraint.left)} {constraint.relation} {describeTerm(constraint.right)}
      </p>

      <div className="space-y-3">
        <BindingsEditor
          bindings={bound}
          onChange={(forall) => onChange({ ...constraint, forall })}
          context={context}
          outer={[]}
          legend="For every"
        />

        <TermBuilder
          value={constraint.left}
          onChange={(left) => onChange({ ...constraint, left })}
          context={context}
          bound={bound}
          label="This"
        />

        <div className="flex flex-wrap items-end gap-3">
          <Choice
            label="Must be"
            value={constraint.relation}
            options={RELATIONS.map((r) => ({ value: r, label: relationLabel(r) }))}
            onChange={(relation) => onChange({ ...constraint, relation: relation as Constraint["relation"] })}
          />
          <Choice
            label="Strength"
            value={constraint.severity}
            options={SEVERITIES.map((s) => ({
              value: s,
              label: s === "hard" ? "must hold" : "can bend, at a cost",
            }))}
            onChange={(severity) =>
              onChange({ ...constraint, severity: severity as Constraint["severity"] })
            }
          />
          {constraint.severity === "soft" && (
            <div>
              <label className="block text-xs text-slate-600" htmlFor={`${idField}-penalty`}>
                Cost per unit broken
              </label>
              <input
                id={`${idField}-penalty`}
                inputMode="numeric"
                className={`${INPUT_CLASS} w-28 text-sm`}
                value={String(constraint.penalty ?? 1)}
                onChange={(event) => {
                  const next = Number(event.target.value);
                  if (/^\d*$/.test(event.target.value) && Number.isSafeInteger(next)) {
                    onChange({ ...constraint, penalty: next });
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
      </div>
    </article>
  );
}

function ObjectiveEditor({
  objective,
  context,
  onChange,
}: {
  objective: { sense: string; terms: ObjectiveTerm[] };
  context: ModelContext;
  onChange: (next: { sense: string; terms: ObjectiveTerm[] }) => void;
}) {
  return (
    <div className="rounded-md border border-slate-200 bg-white p-4">
      <Choice
        label="The solver should"
        value={objective.sense}
        options={SENSES.map((s) => ({ value: s, label: s === "minimize" ? "make it as small as possible" : "make it as large as possible" }))}
        onChange={(sense) => onChange({ ...objective, sense })}
      />

      <div className="mt-3 space-y-4">
        {objective.terms.map((term, position) => (
          <div key={position} className="rounded border border-slate-200 p-3">
            <div className="mb-2 flex flex-wrap items-end gap-3">
              <div>
                <label className="block text-xs text-slate-600" htmlFor={`obj-${position}-id`}>
                  Name
                </label>
                <input
                  id={`obj-${position}-id`}
                  className={`${INPUT_CLASS} w-48 text-sm`}
                  value={term.id}
                  onChange={(event) =>
                    onChange({
                      ...objective,
                      terms: objective.terms.map((t, i) =>
                        i === position ? { ...t, id: event.target.value } : t
                      ),
                    })
                  }
                />
              </div>
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
              <button
                type="button"
                className="rounded px-2 py-2 text-sm text-red-700 underline"
                onClick={() =>
                  onChange({ ...objective, terms: objective.terms.filter((_, i) => i !== position) })
                }
              >
                Remove
              </button>
            </div>
            <TermBuilder
              value={term.expression}
              onChange={(expression) =>
                onChange({
                  ...objective,
                  terms: objective.terms.map((t, i) => (i === position ? { ...t, expression } : t)),
                })
              }
              context={context}
              bound={[]}
              label="Count"
            />
          </div>
        ))}
      </div>

      <button
        type="button"
        className="mt-3 rounded border border-slate-300 px-3 py-2 text-sm text-slate-700"
        onClick={() =>
          onChange({
            ...objective,
            terms: [
              ...objective.terms,
              { id: `o_${objective.terms.length + 1}`, weight: 1, expression: { const: 0 } as Term },
            ],
          })
        }
      >
        Add something to count
      </button>
    </div>
  );
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
