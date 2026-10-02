import { useEffect, useId, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import OfflineNotice from "../components/OfflineNotice";
import Skeleton from "../components/Skeleton";
import { INPUT_CLASS } from "../components/attrTypes";
import { useToast } from "../components/ToastProvider";
import ProblemPicker from "../components/ProblemPicker";
import LoadFailure from "../components/LoadFailure";
import Pager from "../components/Pager";
import SearchBox, { NoMatches } from "../components/SearchBox";

/** Scenarios shown at once; the rest are paged and searched on the server (Epic UX, U-1). */
const SCENARIO_PAGE = 50;
import { useDomainProblem } from "../hooks/useDomainProblem";
import { formatApiError } from "../api/errors";
import RecordPicker from "../components/RecordPicker";
import LimitSweep from "../components/LimitSweep";
import { ruleLimit, type RuleSides } from "../model/ruleLimit";
export { ruleLimit };
import {
  solveProblem,
  useCreateRun,
  useEntityTypes,
  useParameters,
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
import ContextMismatch from "../components/ContextMismatch";
import { useSolveSeconds } from "../components/SolveEffort";

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
  const found = useDomainProblem(domainId, searchParams.get("problem"));

  if (found.state === "offline") return <OfflineNotice subject="The problem list" />;
  if (found.state === "loading") return <Skeleton rows={3} cols={4} />;
  if (found.state === "failed") return <LoadFailure subject={found.subject} error={found.error} retry={found.retry} />;
  if (found.state === "empty") {
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
  if (found.state === "mismatch") {
    return (
      <ContextMismatch
        title="This problem is not available here"
        detail="The link asked for a problem that is missing or belongs to another domain. Nothing was substituted."
        parentHref="/public/problem"
        parentLabel="Open problems in this domain"
      />
    );
  }
  const { problem, firstPage, total } = found;
  const problemId = Number(problem.id);

  return (
    <>
      <ProblemPicker
        domainId={domainId}
        current={problem}
        firstPage={firstPage}
        total={total}
        onChoose={(id) => setSearchParams({ problem: id }, { replace: true })}
      />
      <ForProblem key={problemId} problemId={problemId} />
    </>
  );
}

function ForProblem({ problemId }: { problemId: Id }) {
  const { can } = useCapabilities();
  const canPublish = can("model.publish");
  const canSolve = can("run.submit");
  const createRun = useCreateRun();
  const navigate = useNavigate();
  const toast = useToast();
  const [solving, setSolving] = useState<Id | null>(null);
  const [solvingBase, setSolvingBase] = useState(false);
  const [seconds] = useSolveSeconds();
  const runsOf = (scenarioId: Id, runId?: Id) =>
    `/runs?problem=${problemId}&scenario=${scenarioId}${runId === undefined ? "" : `&run=${runId}`}`;
  // One click: the run starts here, and the runs page follows it (user trial: "Solve" only opened that page).
  function solve(scenarioId: Id) {
    setSolving(scenarioId);
    createRun.mutate(
      { scenarioId, body: { time_limit_s: seconds } },
      {
        onSuccess: (run) => navigate(runsOf(scenarioId, run.id)),
        onError: (error: unknown) => {
          toast.error(formatApiError(error));
          navigate(runsOf(scenarioId));
        },
        onSettled: () => setSolving(null),
      }
    );
  }
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const scenarios = useScenarios(problemId, { limit: SCENARIO_PAGE, offset, q });
  const versions = useVersions(problemId, { limit: 50, offset: 0 });
  const [editing, setEditing] = useState<Scenario | "new" | null>(null);

  if (scenarios.isError) return <LoadFailure subject="The scenario list" error={scenarios.error} retry={() => void scenarios.refetch()} />;
  if (versions.isError) return <LoadFailure subject="The model versions" error={versions.error} retry={() => void versions.refetch()} />;
  if ((scenarios.isLoading && !scenarios.data) || versions.isLoading) return <Skeleton rows={3} cols={3} />;

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
  const total = scenarios.data?.total ?? items.length;

  return (
    <>
      {(q || total > SCENARIO_PAGE) && (
        <div className="mb-3">
          <SearchBox label="scenarios" initial={q} onSearch={(text) => { setQ(text); setOffset(0); }} />
        </div>
      )}
      {items.length === 0 && q ? (
        <NoMatches label="scenarios" q={q} />
      ) : items.length === 0 ? (
        <Note>
          <p>No scenarios yet. One that changes nothing still works: it asks the model as written.</p>
          {canSolve && versionItems.length > 0 && (
            <button
              type="button"
              className="mt-2 rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-60"
              disabled={solvingBase}
              onClick={() => {
                setSolvingBase(true);
                solveProblem(problemId, seconds)
                  .then((run) => navigate(runsOf(run.scenario_id, run.id)))
                  .catch((error: unknown) => toast.error(formatApiError(error)))
                  .finally(() => setSolvingBase(false));
              }}
            >
              {solvingBase ? "Starting…" : "Solve the model as written (Base)"}
            </button>
          )}
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
                {canSolve && (
                  <button
                    type="button"
                    className="rounded bg-blue-600 px-2 py-1 text-white disabled:opacity-60"
                    disabled={solving !== null}
                    onClick={() => solve(scenario.id)}
                  >
                    {solving === scenario.id ? "Starting…" : "Solve"}
                  </button>
                )}
                <Link to={runsOf(scenario.id)} className="rounded px-2 py-1 text-blue-700 underline">
                  Runs
                </Link>
              </span>
            </li>
          ))}
        </ul>
      )}
      <Pager label="Scenario" offset={offset} size={SCENARIO_PAGE} total={total} onOffset={setOffset} />
      {canSolve && canPublish && versionItems.length > 0 && (
        <LimitSweep problemId={problemId} versionId={versionItems[0].id} scenarioHref={(scenarioId, runId) => runsOf(scenarioId, runId)} />
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
  // A rule's limit, as typed: "80000" puts that number where the version has 60000.
  const [limits, setLimits] = useState<Record<string, string>>(() =>
    Object.fromEntries(Object.entries(scenario?.patch?.set_limit ?? {}).map(([id, v]) => [id, String(v)]))
  );
  // Data what-ifs (improvement plan 3.3): kept beside the rule choices, sent with them.
  const [dataChanges, setDataChanges] = useState<ScenarioPatch>(() => dataOf(scenario?.patch ?? {}));

  const version = useVersion(modelVersionId);
  const constraints = (
    version.data?.ir as { constraints?: RuleSides[] } | undefined
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
    // Locks and stay-close a scenario was made with are kept; the form edits rules and data.
    const kept = { ...(scenario?.patch?.lock ? { lock: scenario.patch.lock } : {}),
      ...(scenario?.patch?.stay_close ? { stay_close: scenario.patch.stay_close } : {}) };
    const setLimit = limitsOf(limits, constraints ?? []);
    const body = { name, model_version_id: modelVersionId,
      patch: { ...kept, ...toPatch(choices), ...dataChanges, ...(Object.keys(setLimit).length ? { set_limit: setLimit } : {}) } };
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
                {ruleLimit(constraint) !== null && current !== "disable" && (
                  <label className="mt-1 flex items-center gap-1 text-xs text-slate-600">
                    its limit, {ruleLimit(constraint)!.toLocaleString("en-US")} in the model, here
                    <input
                      aria-label={`New limit for ${constraint.id}`}
                      inputMode="decimal"
                      className={`${INPUT_CLASS} w-28 text-xs`}
                      placeholder={String(ruleLimit(constraint))}
                      value={limits[constraint.id] ?? ""}
                      onChange={(event) => setLimits({ ...limits, [constraint.id]: event.target.value })}
                    />
                  </label>
                )}
                {constraint.note && <p className="mt-1 text-xs text-slate-500">{constraint.note}</p>}
              </li>
            );
          })}
        </ul>
      )}

      <DataWhatIf ir={version.data?.ir as WhatIfIr | undefined} value={dataChanges} onChange={setDataChanges} />

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



/** The limits typed that are numbers and differ from the model's own. */
export function limitsOf(typed: Record<string, string>, rules: RuleSides[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const rule of rules) {
    const text = (typed[rule.id] ?? "").trim().replace(/,/g, "");
    const was = ruleLimit(rule);
    if (text === "" || was === null) continue;
    const value = Number(text);
    if (Number.isFinite(value) && value !== was) out[rule.id] = value;
  }
  return out;
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

type WhatIfIr = { sets?: string[]; parameters?: Record<string, { index?: string[]; entity?: string }> };

/** The data keys of a patch, and nothing else. */
export function dataOf(patch: ScenarioPatch): ScenarioPatch {
  const out: ScenarioPatch = {};
  if (patch.remove && Object.keys(patch.remove).length) out.remove = patch.remove;
  if (patch.scale_param && Object.keys(patch.scale_param).length) out.scale_param = patch.scale_param;
  if (patch.set_param?.length) out.set_param = patch.set_param;
  if (patch.set_attr?.length) out.set_attr = patch.set_attr;
  if (patch.scale_attr?.length) out.scale_attr = patch.scale_attr;
  if (patch.rederive?.length) out.rederive = patch.rederive;
  return out;
}

type Made = { name: string; index_type_ids: unknown[]; source?: Record<string, unknown> | null };

/** The 0/1 "within" data made from the same places and measure as `param`, made again from it once it is
 * scaled -- in its units (benchmark re-test, October 2026: a sandstorm scaled travel times +40% and the
 * "within 30 minutes" data, and so coverage, stayed as it was). */
export function rederivesFor(param: string, made: Made[], ir?: WhatIfIr): NonNullable<ScenarioPatch["rederive"]> {
  const from = made.find((m) => m.name === param);
  const src = from?.source as { kind?: string; metric?: string; from?: string; to?: string; unit?: string } | null | undefined;
  if (!src || src.kind === "within") return [];
  const same = (a: unknown[], b: unknown[]) => a.length === b.length && a.every((x, i) => x === b[i]);
  return made.flatMap((w) => {
    const ws = w.source as { kind?: string; metric?: string; from?: string; to?: string; request?: { max_min?: number; max_m?: number } } | null | undefined;
    if (!ws || ws.kind !== "within" || ws.metric !== src.metric || ws.from !== src.from || ws.to !== src.to) return [];
    if (!same(w.index_type_ids, from!.index_type_ids) || (ir?.parameters && !ir.parameters[w.name])) return [];
    const r = ws.request ?? {};
    const limit = r.max_min != null ? (src.unit === "s" ? r.max_min * 60 : src.unit === "min" ? r.max_min : null)
      : r.max_m != null ? (src.unit === "km" ? r.max_m / 1000 : src.unit === "m" ? r.max_m : null) : null;
    return limit == null ? [] : [{ param: w.name, source: param, op: "<=" as const, limit }];
  });
}

/**
 * "What if the data were different?" (improvement plan 3.3): leave records out,
 * scale a parameter, or change one value -- on a copy of the frozen data, so the
 * stored data never changes and the scenarios can be compared run by run.
 */
function DataWhatIf({ ir, value, onChange }: { ir?: WhatIfIr; value: ScenarioPatch; onChange: (next: ScenarioPatch) => void }) {
  const { domainId } = useDomain();
  const made = (useParameters(domainId, { limit: 500 }).data?.items ?? []) as Made[];
  const sets = ir?.sets ?? [];
  const kinds = useEntityTypes(domainId, { limit: 500 });
  const kindOf = (set: string) => kinds.data?.items.find((k) => k.name === set) ?? null;
  const [fieldSet, setFieldSet] = useState("");
  const [fieldKey, setFieldKey] = useState("");
  const [fieldName, setFieldName] = useState("");
  const [fieldValue, setFieldValue] = useState("");
  const fields = (kindOf(fieldSet)?.attributes ?? []).filter((a) => ["integer", "number", "boolean", "text", "enum"].includes(a.data_type));
  const numbers = Object.entries(ir?.parameters ?? {}).filter(([, spec]) => !spec.entity).map(([name]) => name);
  const [removeSet, setRemoveSet] = useState("");
  const [removeKeys, setRemoveKeys] = useState("");
  const [scaleParam, setScaleParam] = useState("");
  const [factor, setFactor] = useState("1.3");
  const [cellParam, setCellParam] = useState("");
  const [cellKeys, setCellKeys] = useState("");
  const [cellValue, setCellValue] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [scaleSet, setScaleSet] = useState("");
  const [scaleField, setScaleField] = useState("");
  const [scaleBy, setScaleBy] = useState("1.3");
  if (!sets.length) return null;
  const said = describeData(value);
  const keysOf = (text: string) => text.split(",").map((k) => k.trim()).filter(Boolean);
  const input = "rounded border border-slate-300 px-2 py-1 text-sm";
  return (
    <fieldset className="mt-4 rounded-md border border-slate-200 p-3">
      <legend className="px-1 text-sm font-semibold text-slate-900">What if the data were different?</legend>
      <p className="mb-2 text-xs text-slate-600">
        Changes made to a copy of the data when this scenario is solved — the records themselves are not touched.
      </p>
      {said.length > 0 && (
        <ul className="mb-2 flex flex-wrap gap-2 text-xs">
          {said.map((text) => <li key={text} className="rounded bg-amber-50 px-2 py-1 text-amber-900">{text}</li>)}
          <li><button type="button" className="text-xs text-red-700 underline" onClick={() => onChange({})}>Clear the data changes</button></li>
        </ul>
      )}
      <div className="flex flex-wrap items-end gap-2 text-xs text-slate-600">
        <label>Leave out
          <select aria-label="Leave out records of" className={`${input} ml-1`} value={removeSet} onChange={(e) => setRemoveSet(e.target.value)}>
            <option value="">kind…</option>
            {sets.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        {removeSet && kindOf(removeSet) ? (
          // Found by typing a key or a name, like any link (user trial: keys had to be typed from memory).
          <div className="w-64">
            <RecordPicker typeId={kindOf(removeSet)!.id} value="" aria-label="Record to leave out" kindName={removeSet}
              placeholder={`find a ${removeSet}…`}
              onChange={(key) => {
                if (!key) return;
                setProblem(null);
                onChange({ ...value, remove: { ...(value.remove ?? {}), [removeSet]: [...new Set([...(value.remove?.[removeSet] ?? []), key])] } });
              }} />
          </div>
        ) : (
          <>
            <input aria-label="Keys to leave out" className={`${input} w-40 font-mono`} placeholder="Y3, Y5" value={removeKeys} onChange={(e) => setRemoveKeys(e.target.value)} />
            <button type="button" className="rounded border border-slate-300 px-2 py-1 text-slate-800 hover:bg-slate-50"
              onClick={() => {
                if (!removeSet || !keysOf(removeKeys).length) return setProblem("Choose a kind and the keys to leave out.");
                setProblem(null);
                onChange({ ...value, remove: { ...(value.remove ?? {}), [removeSet]: [...new Set([...(value.remove?.[removeSet] ?? []), ...keysOf(removeKeys)])] } });
                setRemoveKeys("");
              }}>Add</button>
          </>
        )}
      </div>
      <div className="mt-2 flex flex-wrap items-end gap-2 text-xs text-slate-600">
        <label>Change
          <select aria-label="Change a field of" className={`${input} ml-1`} value={fieldSet}
            onChange={(e) => { setFieldSet(e.target.value); setFieldKey(""); setFieldName(""); }}>
            <option value="">kind…</option>
            {sets.filter((s) => kindOf(s)).map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        {fieldSet && kindOf(fieldSet) && (
          <>
            <div className="w-56">
              <RecordPicker typeId={kindOf(fieldSet)!.id} value={fieldKey} aria-label="Record to change" kindName={fieldSet}
                placeholder={`find a ${fieldSet}…`} onChange={setFieldKey} />
            </div>
            <label>its
              <select aria-label="Field to change" className={`${input} ml-1`} value={fieldName} onChange={(e) => setFieldName(e.target.value)}>
                <option value="">field…</option>
                {fields.map((f) => <option key={f.name} value={f.name}>{f.name}</option>)}
              </select>
            </label>
            <label>to
              <input aria-label="New field value" className={`${input} ml-1 w-24`} value={fieldValue} onChange={(e) => setFieldValue(e.target.value)} />
            </label>
            <button type="button" className="rounded border border-slate-300 px-2 py-1 text-slate-800 hover:bg-slate-50"
              onClick={() => {
                const field = fields.find((f) => f.name === fieldName);
                if (!fieldKey || !field || fieldValue.trim() === "") return setProblem("Choose a record, its field and the new value.");
                let v: unknown = fieldValue.trim();
                if (field.data_type === "integer" || field.data_type === "number") {
                  v = Number(String(v).replace(/,/g, ""));
                  if (!Number.isFinite(v as number)) return setProblem(`${field.name} is a number.`);
                } else if (field.data_type === "boolean") {
                  const word = String(v).toLowerCase();
                  if (!["yes", "no", "true", "false"].includes(word)) return setProblem(`${field.name} is yes or no.`);
                  v = word === "yes" || word === "true";
                }
                setProblem(null);
                onChange({ ...value, set_attr: [...(value.set_attr ?? []).filter((c) => !(c.set === fieldSet && c.key === fieldKey && c.attr === field.name)),
                  { set: fieldSet, key: fieldKey, attr: field.name, value: v }] });
                setFieldValue("");
              }}>Add</button>
          </>
        )}
      </div>
      <div className="mt-2 flex flex-wrap items-end gap-2 text-xs text-slate-600">
        {/* Benchmark, October 2026: "demand +30% everywhere" was one record at a time. */}
        <label>Scale
          <select aria-label="Scale a field of" className={`${input} ml-1`} value={scaleSet}
            onChange={(e) => { setScaleSet(e.target.value); setScaleField(""); }}>
            <option value="">kind…</option>
            {sets.filter((s) => kindOf(s)).map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        {scaleSet && (
          <>
            <label>’s
              <select aria-label="Field to scale" className={`${input} ml-1`} value={scaleField} onChange={(e) => setScaleField(e.target.value)}>
                <option value="">field…</option>
                {(kindOf(scaleSet)?.attributes ?? []).filter((a) => a.data_type === "integer" || a.data_type === "number")
                  .map((a) => <option key={a.name} value={a.name}>{a.name}</option>)}
              </select>
            </label>
            <label>for every record, by ×
              <input aria-label="Field scale factor" inputMode="decimal" className={`${input} ml-1 w-20`} value={scaleBy} onChange={(e) => setScaleBy(e.target.value)} />
            </label>
            <button type="button" className="rounded border border-slate-300 px-2 py-1 text-slate-800 hover:bg-slate-50"
              onClick={() => {
                const f = Number(scaleBy);
                if (!scaleField || !(f >= 0)) return setProblem("Choose a field and a factor of 0 or more (1.3 for +30%).");
                setProblem(null);
                onChange({ ...value, scale_attr: [...(value.scale_attr ?? []).filter((c) => !(c.set === scaleSet && c.attr === scaleField)),
                  { set: scaleSet, attr: scaleField, factor: f }] });
              }}>Add</button>
          </>
        )}
      </div>
      {numbers.length > 0 && (
        <>
          <div className="mt-2 flex flex-wrap items-end gap-2 text-xs text-slate-600">
            <label>Scale
              <select aria-label="Parameter to scale" className={`${input} ml-1`} value={scaleParam} onChange={(e) => setScaleParam(e.target.value)}>
                <option value="">data…</option>
                {numbers.map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
            </label>
            <label>by ×
              <input aria-label="Scale factor" inputMode="decimal" className={`${input} ml-1 w-20`} value={factor} onChange={(e) => setFactor(e.target.value)} />
            </label>
            <button type="button" className="rounded border border-slate-300 px-2 py-1 text-slate-800 hover:bg-slate-50"
              onClick={() => {
                const f = Number(factor);
                if (!scaleParam || !(f >= 0)) return setProblem("Choose data to scale and a factor of 0 or more.");
                setProblem(null);
                const again = rederivesFor(scaleParam, made, ir);
                onChange({ ...value, scale_param: { ...(value.scale_param ?? {}), [scaleParam]: f },
                  ...(again.length ? { rederive: [...(value.rederive ?? []).filter((c) => !again.some((a) => a.param === c.param)), ...again] } : {}) });
              }}>Add</button>
          </div>
          <div className="mt-2 flex flex-wrap items-end gap-2 text-xs text-slate-600">
            <label>Set
              <select aria-label="Parameter to change" className={`${input} ml-1`} value={cellParam} onChange={(e) => setCellParam(e.target.value)}>
                <option value="">data…</option>
                {numbers.map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
            </label>
            <input aria-label="Keys of the value" className={`${input} w-36 font-mono`}
              placeholder={(ir?.parameters?.[cellParam]?.index ?? ["key"]).join(", ")} value={cellKeys} onChange={(e) => setCellKeys(e.target.value)} />
            <label>to
              <input aria-label="New value" inputMode="decimal" className={`${input} ml-1 w-20`} value={cellValue} onChange={(e) => setCellValue(e.target.value)} />
            </label>
            <button type="button" className="rounded border border-slate-300 px-2 py-1 text-slate-800 hover:bg-slate-50"
              onClick={() => {
                const arity = ir?.parameters?.[cellParam]?.index?.length ?? 0;
                const keys = keysOf(cellKeys);
                const v = Number(cellValue);
                if (!cellParam || keys.length !== arity || cellValue.trim() === "" || Number.isNaN(v)) {
                  return setProblem(`Choose data, ${arity || "its"} key${arity === 1 ? "" : "s"} and a number.`);
                }
                setProblem(null);
                onChange({ ...value, set_param: [...(value.set_param ?? []), { param: cellParam, index: keys, value: v }] });
                setCellKeys("");
                setCellValue("");
              }}>Add</button>
          </div>
        </>
      )}
      {problem && <p role="alert" className="mt-2 text-xs text-red-700">{problem}</p>}
    </fieldset>
  );
}

export function describeData(patch: ScenarioPatch): string[] {
  const said: string[] = [];
  for (const [set, keys] of Object.entries(patch.remove ?? {})) said.push(`without ${set} ${keys.join(", ")}`);
  for (const [param, f] of Object.entries(patch.scale_param ?? {})) said.push(`${param} × ${f}`);
  for (const c of patch.rederive ?? []) said.push(`${c.param} made again: 1 where ${c.source} ${c.op === "<=" ? "≤" : "≥"} ${c.limit}`);
  for (const c of patch.set_param ?? []) said.push(`${c.param}[${c.index.join(", ")}] = ${c.value}`);
  for (const c of patch.set_attr ?? []) said.push(`${c.set} ${c.key}: ${c.attr} = ${String(c.value)}`);
  for (const c of patch.scale_attr ?? []) said.push(`${c.attr} × ${c.factor} for every ${c.set}`);
  return said;
}

export function describePatch(patch: ScenarioPatch): string {
  const parts: string[] = [...describeData(patch)];
  if (patch.disable?.length) parts.push(`ignores ${patch.disable.join(", ")}`);
  if (patch.harden?.length) parts.push(`insists on ${patch.harden.join(", ")}`);
  const soften = Object.entries(patch.soften ?? {});
  if (soften.length) parts.push(soften.map(([id, w]) => `bends ${id} at ${w}`).join(", "));
  const limits = Object.entries(patch.set_limit ?? {});
  if (limits.length) parts.push(limits.map(([id, v]) => `${id} limit ${v.toLocaleString("en-US")}`).join(", "));
  return parts.length > 0 ? parts.join("; ") : "asks the model as written";
}

function Note({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">{children}</div>
  );
}
