import { useId, useState, type ReactNode } from "react";
import RangePicture from "./RangePicture";
import { INPUT_CLASS } from "../components/attrTypes";
import { VARIABLE_DOMAINS, type VariableDomain } from "../ir/contract";
import {
  parameterIsUsable,
  strandedBy,
  variableNameProblem,
  withDomain,
  withStage,
  type ParameterDeclaration,
  type VariableDeclaration,
  type VariableSpec,
  type ParameterSpec,
  type Uncertainty,
} from "./declarations";
import type { Constraint, ObjectiveTerm } from "./terms";
import { DeclarationView, type DeclarationKind } from "./declarationViews";
import { useCardView, ViewToggle, type EquationView } from "./ViewToggle";

/**
 * What a model declares: its sets, the domain parameters it reads, and the
 * variables a solver decides.
 *
 * Sets and parameters are **chosen, not typed**: both must exist in the
 * domain for a dataset to be frozen against them, and a parameter's index
 * order comes from its `parameter_def` — typing it would be an invitation to
 * write `demand[shift, day]`, which type-checks by arity and silently means a
 * different model.
 *
 * Removing a declaration that rules still use is refused here, naming them.
 * The server refuses it too, but by then the person has lost the edit and
 * been told about a document rather than about their rule.
 */

export type DeclarationsEditorProps = {
  sets: string[];
  parameters: Record<string, ParameterSpec>;
  variables: Record<string, VariableSpec>;
  /** Every entity type of the domain, whether declared as a set or not. */
  entityTypeNames: string[];
  /** The domain's parameters, indexes already read back as set names. */
  parameterOptions: ParameterDeclaration[];
  constraints: Constraint[];
  objectiveTerms: ObjectiveTerm[];
  onChange: (next: {
    sets: string[];
    parameters: Record<string, ParameterSpec>;
    variables: Record<string, VariableSpec>;
  }) => void;
  /** How each declaration is shown (the page's switch); this editor keeps its own without one. */
  view?: EquationView;
  onView?: (next: EquationView) => void;
  /** Set name -> its attributes, for the Sets' views. */
  attributes?: Record<string, { name: string; data_type: string }[]>;
  /** Parameter name -> its unit, for the Parameters' views. */
  units?: Record<string, string | null | undefined>;
};

export default function DeclarationsEditor({
  sets,
  parameters,
  variables,
  entityTypeNames,
  parameterOptions,
  constraints,
  objectiveTerms,
  onChange,
  view: pageView,
  onView,
  attributes = {},
  units = {},
}: DeclarationsEditorProps) {
  const [refusal, setRefusal] = useState<string | null>(null);
  const [ownView, setOwnView] = useState<EquationView>("equation");
  const view = pageView ?? ownView;
  const setView = onView ?? setOwnView;

  function apply(next: Partial<Parameters<DeclarationsEditorProps["onChange"]>[0]>) {
    setRefusal(null);
    onChange({ sets, parameters, variables, ...next });
  }

  function refuseIfStranding(
    kind: "set" | "parameter" | "variable",
    name: string,
    then: () => void
  ) {
    const broken = strandedBy({ kind, name }, constraints, objectiveTerms, variables);
    if (broken.length > 0) {
      setRefusal(
        `${name} is used by ${broken.join(", ")}. Change ${
          broken.length > 1 ? "those" : "that"
        } first, then remove it.`
      );
      return;
    }
    then();
  }

  const usedBy = (kind: "set" | "parameter" | "variable", name: string) =>
    strandedBy({ kind, name }, constraints, objectiveTerms, variables);

  /** A variable's own fields: what it decides, when, and its bounds -- or an interval's parts. */
  const variableDetails = (name: string, spec: VariableSpec) => (
    <>
    {spec.domain === "interval" ? (
      <IntervalFields
        name={name}
        spec={spec}
        variables={variables}
        parameters={parameters}
        onChange={(next) => apply({ variables: { ...variables, [name]: next } })}
      />
    ) : (
    <>
    <div className="mt-1">
      <label className="block text-xs text-slate-600" htmlFor={`var-domain-${name}`}>
        {name} decides
      </label>
      <select
        id={`var-domain-${name}`}
        className={`${INPUT_CLASS} mt-0.5 w-auto text-xs`}
        value={spec.domain}
        onChange={(event) =>
          apply({
            variables: {
              ...variables,
              [name]: withStage(
                withDomain(spec, event.target.value as VariableDomain),
                spec.stage
              ),
            },
          })
        }
      >
        {SETTABLE_DOMAINS.map((option) => (
          <option key={option} value={option}>
            {domainPhrase(option)}
          </option>
        ))}
      </select>
    </div>
    <div className="mt-1">
      <label className="block text-xs text-slate-600" htmlFor={`var-stage-${name}`}>
        {name} is decided
      </label>
      <select
        id={`var-stage-${name}`}
        className={`${INPUT_CLASS} mt-0.5 w-auto text-xs`}
        value={spec.stage === undefined ? "" : String(spec.stage)}
        onChange={(event) =>
          apply({
            variables: {
              ...variables,
              [name]: withStage(spec, event.target.value === "" ? undefined : (Number(event.target.value) as 1 | 2)),
            },
          })
        }
        title="For a two-stage stochastic solve: what is decided now, and what waits until the uncertain data is known"
      >
        <option value="">whenever (one stage)</option>
        <option value="1">now, before the data is known</option>
        <option value="2">once the uncertain data is known</option>
      </select>
    </div>
    {spec.domain !== "binary" && (
      <div className="mt-2">
        <div className="flex flex-wrap items-end gap-2">
          <BoundField
            id={`var-lower-${name}`}
            label={`${name} no less than`}
            value={spec.lower}
            integer={spec.domain === "integer"}
            onChange={(lower) =>
              apply({
                variables: {
                  ...variables,
                  [name]: boundPatch(spec, "lower", lower),
                },
              })
            }
          />
          <BoundField
            id={`var-upper-${name}`}
            label={`${name} no more than`}
            value={spec.upper}
            integer={spec.domain === "integer"}
            onChange={(upper) =>
              apply({
                variables: {
                  ...variables,
                  [name]: boundPatch(spec, "upper", upper),
                },
              })
            }
          />
        </div>
        {spec.lower !== undefined &&
          spec.upper !== undefined &&
          spec.lower > spec.upper && (
            <p role="alert" className="mt-1 text-xs text-red-600">
              {name}: no less than {spec.lower} is above no more than {spec.upper}, so
              it has no admissible value.
            </p>
          )}
      </div>
    )}
    </>
    )}
    </>
  );

  /** A parameter's own fields: whether its values are exact. */
  const parameterDetails = (name: string) => {
    const option = parameterOptions.find((o) => o.name === name) ?? { name, index: parameters[name].index };
    return (
      <UncertaintyFields
        name={option.name}
        parameterId={option.id}
        value={parameters[option.name].uncertainty}
        onChange={(uncertainty) => {
          const { uncertainty: _was, ...rest } = parameters[option.name];
          apply({
            parameters: {
              ...parameters,
              [option.name]: uncertainty ? { ...rest, uncertainty } : rest,
            },
          });
        }}
      />
    );
  };

  return (
    <section aria-labelledby="declarations-heading" className="mb-6">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h2 id="declarations-heading" className="text-base font-semibold text-slate-900">
          What this model is about
        </h2>
        <ViewToggle value={view} onChange={setView} name="all declarations" />
      </div>

      {refusal && (
        <p role="alert" className="mb-3 text-sm text-red-600">
          {refusal}
        </p>
      )}

      <div className="space-y-4">
        <Group title="Sets" hint="The kinds of thing the rules range over.">
          {sets.map((name) => (
            <DeclarationCard key={name} kind="set" name={name} heading={name} view={view}
              onStop={() => refuseIfStranding("set", name, () => apply({ sets: sets.filter((s) => s !== name) }))}>
              {(shown, setShown) => (
                <DeclarationView kind="set" name={name} spec={null} view={shown} sets={sets} attributes={attributes[name] ?? []}
                  usedBy={usedBy("set", name)} onBoxes={() => setShown("boxes")} />
              )}
            </DeclarationCard>
          ))}
          <Chooser label="Record types this model uses">
          {entityTypeNames.length === 0 && <Muted>This domain has no entity types yet.</Muted>}
          {entityTypeNames.map((name) => {
            const checked = sets.includes(name);
            return (
              <label key={name} className="flex items-center gap-2 py-1 text-sm">
                <input
                  type="checkbox"
                  className="h-4 w-4"
                  checked={checked}
                  onChange={() => {
                    if (checked) {
                      refuseIfStranding("set", name, () =>
                        apply({ sets: sets.filter((s) => s !== name) })
                      );
                    } else {
                      apply({ sets: [...sets, name] });
                    }
                  }}
                />
                <span className="font-mono text-xs">{name}</span>
              </label>
            );
          })}
          </Chooser>
        </Group>

        <Group title="Parameters" hint="Numbers the domain already holds, read by the rules.">
          {Object.entries(parameters).map(([name, spec]) => (
            <DeclarationCard key={name} kind="parameter" name={name} heading={`${name}[${spec.index.join(", ")}]`} view={view}
              details={parameterDetails(name)}
              onStop={() => refuseIfStranding("parameter", name, () => {
                const next = { ...parameters };
                delete next[name];
                apply({ parameters: next });
              })}>
              {(shown, setShown) => (
                <DeclarationView kind="parameter" name={name} spec={spec} view={shown} sets={sets} unit={units[name]}
                  usedBy={usedBy("parameter", name)} onBoxes={() => setShown("boxes")} />
              )}
            </DeclarationCard>
          ))}
          <Chooser label="Data this model reads">
          {parameterOptions.length === 0 && <Muted>This domain defines no parameters.</Muted>}
          {parameterOptions.map((option) => {
            const declared = option.name in parameters;
            const { usable, reason } = parameterIsUsable(option, sets);
            return (
              <div key={option.name} className="py-1">
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    className="h-4 w-4"
                    checked={declared}
                    disabled={!declared && !usable}
                    onChange={() => {
                      if (declared) {
                        refuseIfStranding("parameter", option.name, () => {
                          const next = { ...parameters };
                          delete next[option.name];
                          apply({ parameters: next });
                        });
                      } else {
                        apply({
                          parameters: {
                            ...parameters,
                            [option.name]: { index: option.index, ...(option.entity ? { entity: option.entity } : {}) },
                          },
                        });
                      }
                    }}
                  />
                  <span className="font-mono text-xs">
                    {option.name}[{option.index.join(", ")}]
                  </span>
                </label>
                {!declared && !usable && <Muted>{reason}</Muted>}
              </div>
            );
          })}
          </Chooser>
        </Group>

        <Group title="Variables" hint="What the solver decides.">
          {Object.entries(variables).map(([name, spec]) => (
            <DeclarationCard key={name} kind="variable" name={name} heading={`${name}[${spec.index.join(", ")}]`} view={view}
              details={variableDetails(name, spec)}
              onRemove={() =>
                refuseIfStranding("variable", name, () => {
                  const next = { ...variables };
                  delete next[name];
                  apply({ variables: next });
                })
              }>
              {(shown, setShown) => (
                <DeclarationView kind="variable" name={name} spec={spec} view={shown} sets={sets}
                  usedBy={usedBy("variable", name)} onBoxes={() => setShown("boxes")}
                  onChange={(next) => apply({ variables: { ...variables, [name]: next } })} />
              )}
            </DeclarationCard>
          ))}
          <div className="rounded-md border border-dashed border-slate-300 bg-white px-3 py-2">
            <p className="mb-1 text-xs font-medium text-slate-700">Add a variable</p>
          <AddVariable
            sets={sets}
            taken={[...Object.keys(variables), ...Object.keys(parameters)]}
            onAdd={(variable) => {
              if (variable.domain !== "interval") {
                apply({
                  variables: { ...variables, [variable.name]: { index: variable.index, domain: variable.domain } },
                });
                return;
              }
              // An interval is a start and an end: make them with it, so the
              // new declaration is whole from the first render.
              const taken = new Set([...Object.keys(variables), ...Object.keys(parameters), variable.name]);
              const free = (stem: string) => {
                let candidate = stem;
                for (let n = 2; taken.has(candidate); n += 1) candidate = `${stem}_${n}`;
                taken.add(candidate);
                return candidate;
              };
              const start = free(`${variable.name}_start`);
              const end = free(`${variable.name}_end`);
              const part = { index: variable.index, domain: "integer" as const, lower: 0 };
              apply({
                variables: {
                  ...variables,
                  [start]: part,
                  [end]: part,
                  [variable.name]: { index: variable.index, domain: "interval", start, end, size: 1 },
                },
              });
            }}
          />
          </div>
        </Group>
      </div>
    </section>
  );
}

/** What an existing number or yes-or-no variable can be changed into. Not an
 * interval: that is a different kind of declaration, made new with its start
 * and end (`AddVariable`). */
const SETTABLE_DOMAINS = VARIABLE_DOMAINS.filter((domain) => domain !== "interval");

const sameIndex = (a: readonly string[] | undefined, b: readonly string[]) =>
  a !== undefined && a.length === b.length && a.every((set, i) => set === b[i]);

/**
 * An interval's parts: its start and end (whole-number variables), its size
 * (a whole number, or a parameter), and, optionally, the yes-or-no that says
 * whether it happens. Each offered only where declared over the interval's
 * own sets, as the contract asks.
 */
function IntervalFields({
  name,
  spec,
  variables,
  parameters,
  onChange,
}: {
  name: string;
  spec: VariableSpec;
  variables: Record<string, VariableSpec>;
  parameters: Record<string, ParameterSpec>;
  onChange: (next: VariableSpec) => void;
}) {
  const ids = { start: useId(), end: useId(), size: useId(), presence: useId(), number: useId() };
  const of = (domain: string) =>
    Object.entries(variables)
      .filter(([other, v]) => other !== name && v.domain === domain && sameIndex(v.index, spec.index))
      .map(([other]) => other);
  const integers = of("integer");
  const switches = of("binary");
  const sizes = Object.entries(parameters)
    .filter(([, p]) => sameIndex(p.index, spec.index))
    .map(([parameter]) => parameter);
  const bySize = typeof spec.size === "string";
  const choice = (id: string, label: string, value: string, options: string[], set: (v: string) => void, blank?: string) => (
    <div>
      <label htmlFor={id} className="block text-xs text-slate-600">
        {label}
      </label>
      <select id={id} className={`${INPUT_CLASS} mt-0.5 w-auto text-xs`} value={value} onChange={(e) => set(e.target.value)}>
        {blank !== undefined && <option value="">{blank}</option>}
        {blank === undefined && !options.includes(value) && <option value={value}>{value || "choose…"}</option>}
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </div>
  );

  return (
    <div className="mt-1 space-y-2">
      <p className="text-xs text-slate-600">
        {name} is a span of time: from {spec.start} to {spec.end}, lasting {spec.size}
        {spec.presence ? `, and only if ${spec.presence}` : ""}.
      </p>
      <div className="flex flex-wrap items-end gap-2">
        {choice(ids.start, `${name} starts at`, spec.start ?? "", integers, (start) => onChange({ ...spec, start }))}
        {choice(ids.end, `${name} ends at`, spec.end ?? "", integers, (end) => onChange({ ...spec, end }))}
      </div>
      <div className="flex flex-wrap items-end gap-2">
        {choice(
          ids.size,
          `${name} lasts`,
          bySize ? String(spec.size) : "",
          sizes,
          (size) => onChange({ ...spec, size: size === "" ? 1 : size }),
          "a fixed number"
        )}
        {!bySize && (
          <div>
            <label htmlFor={ids.number} className="block text-xs text-slate-600">
              {name} length
            </label>
            <input
              id={ids.number}
              inputMode="numeric"
              className={`${INPUT_CLASS} mt-0.5 w-20 text-xs`}
              value={String(spec.size ?? 0)}
              onChange={(event) => {
                // A size is a non-negative whole number (interval_size_invalid).
                if (!/^\d*$/.test(event.target.value)) return;
                onChange({ ...spec, size: event.target.value === "" ? 0 : Number(event.target.value) });
              }}
            />
          </div>
        )}
      </div>
      {choice(
        ids.presence,
        `${name} happens`,
        spec.presence ?? "",
        switches,
        (presence) => {
          if (presence === "") {
            const { presence: _always, ...rest } = spec;
            onChange(rest);
            return;
          }
          onChange({ ...spec, presence });
        },
        "always"
      )}
    </div>
  );
}

/**
 * How a declared parameter's values may be wrong (IR version 2). Exact is
 * the default and writes nothing; a range is typed as a percentage and
 * kept as a fraction, with an optional cap on how many of a rule's values
 * may be off at once.
 */
function UncertaintyFields({
  name,
  parameterId,
  value,
  onChange,
}: {
  name: string;
  /** The domain's parameter, so its values can be drawn as ranges (queue R17d). */
  parameterId?: number | string;
  value: Uncertainty | undefined;
  onChange: (next: Uncertainty | undefined) => void;
}) {
  const ids = { kind: useId(), share: useId(), gamma: useId() };
  const kind = value?.kind ?? "exact";
  const range = value?.kind === "interval" ? value : null;
  const [shareDraft, setShareDraft] = useState(range ? String(Number((range.deviation * 100).toPrecision(6))) : "10");
  const [gammaDraft, setGammaDraft] = useState(range?.gamma !== undefined ? String(range.gamma) : "");
  return (
    <div className="ml-6 mt-1 space-y-1">
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor={ids.kind} className="text-xs text-slate-600">
          {name}&rsquo;s values are
        </label>
        <select
          id={ids.kind}
          className={`${INPUT_CLASS} w-auto text-xs`}
          value={kind}
          onChange={(event) => {
            const next = event.target.value;
            if (next === "exact") onChange(undefined);
            else if (next === "scenarios")
              onChange({
                kind: "scenarios",
                futures: [
                  { label: "low", factor: 0.8 },
                  { label: "high", factor: 1.2 },
                ],
              });
            else onChange({ kind: "interval", deviation: Number(shareDraft) / 100 || 0.1 });
          }}
        >
          <option value="exact">exact</option>
          <option value="interval">within a range of each value</option>
          <option value="scenarios">named futures (scaled)</option>
        </select>
      </div>
      {value?.kind === "scenarios" && (
        <div className="space-y-1 rounded border border-slate-200 bg-slate-50 p-2">
          <p className="text-xs text-slate-600">
            Each future scales every cell of {name} by its factor (1 keeps the stored value).
          </p>
          {value.futures.map((future, index) => (
            <div key={index} className="flex flex-wrap items-end gap-2">
              <div>
                <label className="block text-xs text-slate-600" htmlFor={`${parameterId ?? name}-sc-label-${index}`}>
                  Label
                </label>
                <input
                  id={`${parameterId ?? name}-sc-label-${index}`}
                  className={`${INPUT_CLASS} w-28 text-xs`}
                  value={future.label ?? ""}
                  onChange={(event) => {
                    const futures = value.futures.map((row, i) =>
                      i === index ? { ...row, label: event.target.value || undefined } : row,
                    );
                    onChange({ kind: "scenarios", futures });
                  }}
                />
              </div>
              <div>
                <label className="block text-xs text-slate-600" htmlFor={`${parameterId ?? name}-sc-factor-${index}`}>
                  Factor
                </label>
                <input
                  id={`${parameterId ?? name}-sc-factor-${index}`}
                  inputMode="decimal"
                  className={`${INPUT_CLASS} w-20 text-xs`}
                  value={String(future.factor)}
                  onChange={(event) => {
                    const raw = event.target.value;
                    if (!/^\d*\.?\d*$/.test(raw)) return;
                    const factor = Number(raw);
                    if (!Number.isFinite(factor) || !(factor > 0)) return;
                    const futures = value.futures.map((row, i) => (i === index ? { ...row, factor } : row));
                    onChange({ kind: "scenarios", futures });
                  }}
                />
              </div>
              <button
                type="button"
                className="text-xs text-slate-600 hover:text-red-700"
                disabled={value.futures.length <= 1}
                onClick={() =>
                  onChange({
                    kind: "scenarios",
                    futures: value.futures.filter((_, i) => i !== index),
                  })
                }
              >
                Remove
              </button>
            </div>
          ))}
          <button
            type="button"
            className="text-xs font-medium text-blue-800"
            onClick={() =>
              onChange({
                kind: "scenarios",
                futures: [...value.futures, { label: `future ${value.futures.length + 1}`, factor: 1 }],
              })
            }
          >
            Add a future
          </button>
        </div>
      )}
      {range && (
        <div className="flex flex-wrap items-end gap-2">
          <div>
            <label htmlFor={ids.share} className="block text-xs text-slate-600">
              {name} may be off by up to (%)
            </label>
            <input
              id={ids.share}
              inputMode="decimal"
              className={`${INPUT_CLASS} w-20 text-xs`}
              value={shareDraft}
              onChange={(event) => {
                const raw = event.target.value;
                if (!/^\d*\.?\d*$/.test(raw)) return;
                setShareDraft(raw);
                if (raw !== "" && Number.isFinite(Number(raw))) onChange({ ...range, deviation: Number(raw) / 100 });
              }}
            />
          </div>
          <div>
            <label htmlFor={ids.gamma} className="block text-xs text-slate-600">
              at most this many of a rule&rsquo;s {name} values at once (blank: all)
            </label>
            <input
              id={ids.gamma}
              inputMode="decimal"
              className={`${INPUT_CLASS} w-20 text-xs`}
              value={gammaDraft}
              onChange={(event) => {
                const raw = event.target.value;
                if (!/^\d*\.?\d*$/.test(raw)) return;
                setGammaDraft(raw);
                if (raw === "") {
                  const { gamma: _all, ...rest } = range;
                  onChange(rest);
                } else if (Number.isFinite(Number(raw))) {
                  onChange({ ...range, gamma: Number(raw) });
                }
              }}
            />
          </div>
        </div>
      )}
      {range && parameterId !== undefined && (
        <RangePicture parameterId={Number(parameterId)} deviation={range.deviation} name={name} />
      )}
    </div>
  );
}

/** Planner language for a variable domain — not the contract token. */
function domainPhrase(domain: string): string {
  if (domain === "binary") return "yes or no";
  if (domain === "continuous") return "any number";
  if (domain === "interval") return "a span of time";
  return "a whole number";
}

function boundPatch(
  spec: VariableSpec,
  key: "lower" | "upper",
  value: number | undefined
): VariableSpec {
  const next = { ...spec };
  if (value === undefined) {
    delete next[key];
  } else {
    next[key] = value;
  }
  return next;
}

function BoundField({
  id,
  label,
  value,
  integer,
  onChange,
}: {
  id: string;
  label: string;
  value: number | undefined;
  integer: boolean;
  onChange: (next: number | undefined) => void;
}) {
  return (
    <div>
      <label htmlFor={id} className="block text-xs text-slate-600">
        {label}
      </label>
      <input
        id={id}
        inputMode={integer ? "numeric" : "decimal"}
        className={`${INPUT_CLASS} mt-0.5 w-24 text-xs`}
        value={value === undefined ? "" : String(value)}
        placeholder="optional"
        onChange={(event) => {
          const raw = event.target.value.trim();
          if (raw === "") {
            onChange(undefined);
            return;
          }
          if (integer) {
            if (!/^[+-]?\d+$/.test(raw)) return;
            const next = Number(raw);
            if (Number.isSafeInteger(next)) onChange(next);
            return;
          }
          if (!/^[+-]?(\d+(\.\d*)?|\.\d+)$/.test(raw)) return;
          const next = Number(raw);
          if (Number.isFinite(next)) onChange(next);
        }}
      />
    </div>
  );
}

function AddVariable({
  sets,
  taken,
  onAdd,
}: {
  sets: string[];
  taken: string[];
  onAdd: (variable: VariableDeclaration) => void;
}) {
  const nameId = useId();
  const domainId = useId();
  const [name, setName] = useState("");
  const [domain, setDomain] = useState<VariableDomain>("binary");
  const [index, setIndex] = useState<string[]>([]);
  const problem = name === "" ? null : variableNameProblem(name, taken);

  return (
    <div className="mt-2 border-t border-slate-200 pt-2">
      <div className="flex flex-wrap items-end gap-2">
        <div>
          <label htmlFor={nameId} className="block text-xs text-slate-600">
            New variable
          </label>
          <input
            id={nameId}
            className={`${INPUT_CLASS} w-32 text-xs`}
            value={name}
            aria-invalid={problem ? "true" : undefined}
            onChange={(event) => setName(event.target.value)}
          />
        </div>
        <div>
          <label htmlFor={domainId} className="block text-xs text-slate-600">
            Decides
          </label>
          <select
            id={domainId}
            className={`${INPUT_CLASS} w-auto text-xs`}
            value={domain}
            onChange={(event) => setDomain(event.target.value as VariableDomain)}
          >
            {VARIABLE_DOMAINS.map((option) => (
              <option key={option} value={option}>
                {domainPhrase(option)}
              </option>
            ))}
          </select>
        </div>
      </div>

      {sets.length > 0 && (
        <fieldset className="mt-2">
          <legend className="text-xs text-slate-600">One for every…</legend>
          <div className="flex flex-wrap gap-2">
            {sets.map((set) => {
              const position = index.indexOf(set);
              return (
                <label key={set} className="flex items-center gap-1 text-xs">
                  <input
                    type="checkbox"
                    className="h-4 w-4"
                    checked={position >= 0}
                    onChange={() =>
                      setIndex(position >= 0 ? index.filter((s) => s !== set) : [...index, set])
                    }
                  />
                  <span className="font-mono">{set}</span>
                  {position >= 0 && <span className="text-slate-400">#{position + 1}</span>}
                </label>
              );
            })}
          </div>
        </fieldset>
      )}

      {problem && (
        <p role="alert" className="mt-1 text-xs text-red-600">
          {problem}
        </p>
      )}

      <button
        type="button"
        disabled={name === "" || problem !== null || index.length === 0}
        className="mt-2 rounded border border-slate-300 px-2 py-1 text-xs text-slate-700 disabled:opacity-50"
        onClick={() => {
          onAdd({ name, index, domain });
          setName("");
          setIndex([]);
        }}
      >
        Add variable
      </button>
      {index.length === 0 && name !== "" && !problem && (
        <p className="mt-1 text-xs text-slate-500">
          Choose at least one set: a variable with no index is a single number, which this platform
          does not express yet.
        </p>
      )}
    </div>
  );
}


function Muted({ children }: { children: React.ReactNode }) {
  return <p className="text-xs text-slate-500">{children}</p>;
}

/** One of the three groups -- Sets, Parameters, Variables -- as a named group of cards. */
function Group({ title, hint, children }: { title: string; hint: string; children: ReactNode }) {
  return (
    // A named group, because "day" appears both as a set and as an index of a
    // variable being built: without the grouping the two are one ambiguous
    // control to anyone navigating by name.
    <div role="group" aria-label={title} className="space-y-1">
      <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
      <p className="mb-1 text-xs text-slate-500">{hint}</p>
      {children}
    </div>
  );
}

/** What the domain offers, ticked for what the model uses. */
function Chooser({ label, children }: { label: string; children: ReactNode }) {
  return (
    <details className="rounded-md border border-dashed border-slate-300 bg-white px-3 py-2" open>
      <summary className="cursor-pointer text-xs font-medium text-slate-700">{label}</summary>
      <div className="mt-1">{children}</div>
    </details>
  );
}

const KIND_TAG: Record<DeclarationKind, { text: string; style: string }> = {
  set: { text: "set", style: "bg-teal-100 text-teal-800" },
  parameter: { text: "data", style: "bg-emerald-100 text-emerald-800" },
  variable: { text: "decision", style: "bg-sky-100 text-sky-800" },
};

/**
 * One declaration as a card, as rules and goals are: its name, its own view
 * switch, the view, and its fields -- shown with the equation, behind “More
 * options” with the simpler views.
 */
function DeclarationCard({ kind, name, heading, view, details, onRemove, onStop, children }: {
  kind: DeclarationKind;
  name: string;
  heading: string;
  view: EquationView;
  details?: ReactNode;
  onRemove?: () => void;
  onStop?: () => void;
  children: (shown: EquationView, setShown: (next: EquationView) => void) => ReactNode;
}) {
  const [shown, setShown] = useCardView(view);
  const [more, setMore] = useState(false);
  const tag = KIND_TAG[kind];
  return (
    <article className="rounded-md border border-slate-200 bg-white p-2" data-testid={`${kind}-card`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs">{heading}</span>
        <span className={`rounded px-1.5 py-0.5 text-xs font-semibold ${tag.style}`}>{tag.text}</span>
        <span className="ml-auto flex gap-1">
          {onStop && (
            <button type="button" className="rounded px-2 py-1 text-xs text-red-700 underline" onClick={onStop}>
              Stop using {name}
            </button>
          )}
          {onRemove && (
            <button type="button" className="rounded px-2 py-1 text-xs text-red-700 underline" onClick={onRemove}>
              Remove
            </button>
          )}
        </span>
      </div>
      <div className="mt-1 space-y-1">
        <ViewToggle value={shown} onChange={setShown} name={name} size="xs" />
        {children(shown, setShown)}
      </div>
      {details && (shown === "equation" ? (
        <div className="mt-1">{details}</div>
      ) : (
        <>
          <button type="button" aria-expanded={more} className="mt-1 rounded py-1 text-xs font-medium text-blue-700 underline"
            onClick={() => setMore((open) => !open)}>
            {more ? "Fewer options" : "More options"}
          </button>
          {more && <div className="mt-1">{details}</div>}
        </>
      ))}
    </article>
  );
}
