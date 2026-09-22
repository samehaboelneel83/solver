import { useEffect, useId, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import OfflineNotice from "../components/OfflineNotice";
import Skeleton from "../components/Skeleton";
import { INPUT_CLASS } from "../components/attrTypes";
import { useToast } from "../components/ToastProvider";
import { useEntityList } from "../api/entities";
import { formatApiError } from "../api/errors";
import {
  useCreateScenario,
  useDeleteScenario,
  useScenarios,
  useUpdateScenario,
  useVersion,
  useVersions,
  type Id,
  type Scenario,
  type ScenarioPatch,
} from "../api/v1";
import { useCapabilities } from "../hooks/useCapability";
import { useDomain } from "../hooks/useDomain";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { parseRouteId } from "../lib/routeId";

/**
 * Scenarios: the same model, asked a different question.
 *
 * A scenario is a **patch over one version** — disable a rule, harden a soft
 * one, or soften a hard one at a price. That is what makes an
 * over-subscribed model answerable: the shipped demo cannot cover 57
 * shift-slots with five people, and softening coverage is the difference
 * between "no answer" and "here is the best you can do, and here is what it
 * costs".
 *
 * The patch is edited **against the version's own rules**, one choice per
 * rule, rather than as a document of ids. A patch naming a rule the version
 * does not declare is refused by the server (Task 9's gap, closed in Phase
 * 0); offering the rules means it cannot be written in the first place.
 *
 * Changing the version a scenario points at is allowed, but the patch is
 * then checked again — a rule in one version may not exist in another, which
 * is why the choices are re-read whenever the version changes.
 */

type Choice = "as_is" | "disable" | "harden" | "soften";

export default function Scenarios() {
  useDocumentTitle("Scenarios");
  const { domainId } = useDomain();

  return (
    <div className="max-w-5xl">
      <h1 className="mb-1 text-lg font-semibold text-slate-900">Scenarios</h1>
      <p className="mb-4 text-sm text-slate-500">
        A what-if over one version of a model: leave the rules alone, or relax the ones that make it
        impossible and see what that costs. Solving a scenario is what produces a run.
      </p>
      {domainId === null ? (
        <Note>
          <p>Choose a domain in the sidebar&rsquo;s Domain selector (under Menu on a small screen).</p>
        </Note>
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
        <p>This domain has no problems yet, and a scenario belongs to one.</p>
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
      <ForProblem key={problemId} problemId={problemId} />
    </>
  );
}

function ForProblem({ problemId }: { problemId: Id }) {
  const { can } = useCapabilities();
  const canPublish = can("model.publish");
  const scenarios = useScenarios(problemId, { limit: 500, offset: 0 });
  const versions = useVersions(problemId, { limit: 50, offset: 0 });
  const [editing, setEditing] = useState<Scenario | "new" | null>(null);

  if (scenarios.isLoading || versions.isLoading) return <Skeleton rows={3} cols={3} />;

  const versionItems = versions.data?.items ?? [];
  if (versionItems.length === 0) {
    return (
      <Note>
        <p>This problem has no model version, and a scenario patches one.</p>
        <p className="mt-1">
          Write a model on the{" "}
          <Link to={`/model?problem=${problemId}`} className="inline-block rounded py-1 text-blue-600 underline">
            Model editor
          </Link>
          .
        </p>
      </Note>
    );
  }

  const items = scenarios.data?.items ?? [];

  return (
    <>
      {items.length === 0 ? (
        <Note>
          <p>No scenarios yet. One that changes nothing still works: it asks the model as written.</p>
        </Note>
      ) : (
        <ul className="mb-4 space-y-2">
          {items.map((scenario) => (
            <li
              key={String(scenario.id)}
              className="flex flex-wrap items-center gap-3 rounded-md border border-slate-200 bg-white px-3 py-2 text-sm"
            >
              <span className="font-medium text-slate-900">{scenario.name}</span>
              <span className="text-xs text-slate-500">
                version {versionItems.find((v) => v.id === scenario.model_version_id)?.version ?? "?"}
              </span>
              <span className="text-xs text-slate-600">{describePatch(scenario.patch)}</span>
              <span className="ml-auto flex gap-2">
                {canPublish && (
                  <button
                    type="button"
                    className="rounded px-2 py-1 text-blue-700 underline"
                    onClick={() => setEditing(scenario)}
                  >
                    Edit
                  </button>
                )}
                <Link to={`/runs?problem=${problemId}&scenario=${scenario.id}`} className="rounded px-2 py-1 text-blue-700 underline">
                  Solve
                </Link>
              </span>
            </li>
          ))}
        </ul>
      )}

      {editing === null ? (
        canPublish ? (
          <button
            type="button"
            className="rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700"
            onClick={() => setEditing("new")}
          >
            New scenario
          </button>
        ) : null
      ) : (
        <ScenarioForm
          problemId={problemId}
          scenario={editing === "new" ? null : editing}
          versions={versionItems}
          onDone={() => {
            setEditing(null);
            scenarios.refetch();
          }}
        />
      )}
    </>
  );
}

function ScenarioForm({
  problemId,
  scenario,
  versions,
  onDone,
}: {
  problemId: Id;
  scenario: Scenario | null;
  versions: { id: Id; version: number; note: string | null }[];
  onDone: () => void;
}) {
  const nameId = useId();
  const versionId = useId();
  const toast = useToast();
  const create = useCreateScenario();
  const update = useUpdateScenario();
  const remove = useDeleteScenario();

  const [name, setName] = useState(scenario?.name ?? "");
  const [modelVersionId, setModelVersionId] = useState<Id>(
    scenario?.model_version_id ?? versions[0].id
  );
  const [choices, setChoices] = useState<Record<string, { choice: Choice; weight: number }>>(() =>
    fromPatch(scenario?.patch ?? {})
  );
  const [failure, setFailure] = useState<string | null>(null);

  const version = useVersion(modelVersionId);
  const constraints = (
    version.data?.ir as { constraints?: { id: string; note?: string; severity?: string }[] } | undefined
  )?.constraints;

  useEffect(() => {
    // A rule chosen in one version may not exist in another, and a patch
    // naming an unknown rule is refused. Dropping the choices that no longer
    // apply is better than sending a patch the server will reject.
    if (!version.data) return;
    const known = new Set((constraints ?? []).map((c) => c.id));
    setChoices((current) => {
      const kept = Object.fromEntries(Object.entries(current).filter(([id]) => known.has(id)));
      return Object.keys(kept).length === Object.keys(current).length ? current : kept;
    });
  }, [version.data, constraints]);

  function save() {
    setFailure(null);
    const body = { name, model_version_id: modelVersionId, patch: toPatch(choices) };
    const onError = (error: unknown) => setFailure(formatApiError(error));
    if (scenario) {
      update.mutate(
        { id: scenario.id, body },
        { onSuccess: () => { toast.success(`Saved ${name}`); onDone(); }, onError }
      );
    } else {
      create.mutate(
        { problem_id: problemId, ...body },
        { onSuccess: () => { toast.success(`Created ${name}`); onDone(); }, onError }
      );
    }
  }

  return (
    <section aria-labelledby="scenario-form-heading" className="rounded-md border border-slate-200 bg-white p-4">
      <h2 id="scenario-form-heading" className="mb-3 text-base font-semibold text-slate-900">
        {scenario ? `Edit ${scenario.name}` : "New scenario"}
      </h2>

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div>
          <label htmlFor={nameId} className="block text-xs text-slate-600">
            Name
          </label>
          <input
            id={nameId}
            className={`${INPUT_CLASS} w-56 text-sm`}
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </div>
        <div>
          <label htmlFor={versionId} className="block text-xs text-slate-600">
            Of version
          </label>
          <select
            id={versionId}
            className={`${INPUT_CLASS} w-auto text-sm`}
            value={String(modelVersionId)}
            onChange={(event) => setModelVersionId(Number(event.target.value))}
          >
            {versions.map((row) => (
              <option key={String(row.id)} value={String(row.id)}>
                version {row.version}
                {row.note ? ` — ${row.note}` : ""}
              </option>
            ))}
          </select>
        </div>
      </div>

      {version.isLoading ? (
        <Skeleton rows={3} cols={2} />
      ) : (constraints ?? []).length === 0 ? (
        <p className="text-sm text-slate-600">
          This version has no rules to change, so a scenario of it asks the model as written.
        </p>
      ) : (
        <ul className="space-y-2">
          {(constraints ?? []).map((constraint) => {
            const current = choices[constraint.id]?.choice ?? "as_is";
            return (
              <li key={constraint.id} className="rounded border border-slate-200 p-2">
                <div className="flex flex-wrap items-center gap-3">
                  <span className="font-mono text-xs text-slate-900">{constraint.id}</span>
                  <span className="text-xs text-slate-500">
                    {constraint.severity === "soft" ? "can bend" : "must hold"}
                  </span>
                  <label className="ml-auto flex items-center gap-2 text-xs">
                    <span className="sr-only">{`What to do with ${constraint.id}`}</span>
                    <select
                      aria-label={`What to do with ${constraint.id}`}
                      className={`${INPUT_CLASS} w-auto text-xs`}
                      value={current}
                      onChange={(event) =>
                        setChoices({
                          ...choices,
                          [constraint.id]: {
                            choice: event.target.value as Choice,
                            weight: choices[constraint.id]?.weight ?? 100,
                          },
                        })
                      }
                    >
                      <option value="as_is">leave as it is</option>
                      <option value="disable">ignore it</option>
                      <option value="harden">insist on it</option>
                      <option value="soften">let it bend, at a cost</option>
                    </select>
                  </label>
                  {current === "soften" && (
                    <label className="flex items-center gap-1 text-xs">
                      cost
                      <input
                        aria-label={`Cost of bending ${constraint.id}`}
                        inputMode="numeric"
                        className={`${INPUT_CLASS} w-20 text-xs`}
                        value={String(choices[constraint.id]?.weight ?? 100)}
                        onChange={(event) => {
                          const next = Number(event.target.value);
                          if (/^\d*$/.test(event.target.value) && Number.isSafeInteger(next)) {
                            setChoices({
                              ...choices,
                              [constraint.id]: { choice: "soften", weight: next },
                            });
                          }
                        }}
                      />
                    </label>
                  )}
                </div>
                {constraint.note && <p className="mt-1 text-xs text-slate-500">{constraint.note}</p>}
              </li>
            );
          })}
        </ul>
      )}

      {failure && (
        <p role="alert" className="mt-3 whitespace-pre-line text-sm text-red-600">
          {failure}
        </p>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={save}
          disabled={name.trim() === "" || create.isPending || update.isPending}
          className="rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
        >
          {scenario ? "Save" : "Create"}
        </button>
        <button type="button" onClick={onDone} className="rounded px-2 py-2 text-sm text-slate-700 underline">
          Cancel
        </button>
        {scenario && (
          <button
            type="button"
            className="ml-auto rounded px-2 py-2 text-sm text-red-700 underline"
            onClick={() => {
              if (!window.confirm(`Delete "${scenario.name}"? Its runs are deleted with it.`)) return;
              remove.mutate(scenario.id, {
                onSuccess: () => { toast.success(`Deleted ${scenario.name}`); onDone(); },
                onError: (error: unknown) => setFailure(formatApiError(error)),
              });
            }}
          >
            Delete
          </button>
        )}
      </div>
    </section>
  );
}

export function fromPatch(patch: ScenarioPatch): Record<string, { choice: Choice; weight: number }> {
  const choices: Record<string, { choice: Choice; weight: number }> = {};
  (patch.disable ?? []).forEach((id) => (choices[id] = { choice: "disable", weight: 100 }));
  (patch.harden ?? []).forEach((id) => (choices[id] = { choice: "harden", weight: 100 }));
  Object.entries(patch.soften ?? {}).forEach(([id, weight]) => {
    choices[id] = { choice: "soften", weight };
  });
  return choices;
}

export function toPatch(choices: Record<string, { choice: Choice; weight: number }>): ScenarioPatch {
  const patch: ScenarioPatch = {};
  for (const [id, { choice, weight }] of Object.entries(choices)) {
    if (choice === "disable") (patch.disable ??= []).push(id);
    if (choice === "harden") (patch.harden ??= []).push(id);
    if (choice === "soften") (patch.soften ??= {})[id] = weight;
  }
  return patch;
}

export function describePatch(patch: ScenarioPatch): string {
  const parts: string[] = [];
  if (patch.disable?.length) parts.push(`ignores ${patch.disable.join(", ")}`);
  if (patch.harden?.length) parts.push(`insists on ${patch.harden.join(", ")}`);
  const soften = Object.entries(patch.soften ?? {});
  if (soften.length) parts.push(soften.map(([id, w]) => `bends ${id} at ${w}`).join(", "));
  return parts.length > 0 ? parts.join("; ") : "asks the model as written";
}

function Note({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">{children}</div>
  );
}
