import { useEffect, useId, useState, type ReactNode } from "react";
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
import { checkDeclaration, declarationSentence, DeclarationView, type DeclarationKind } from "./declarationViews";
import AddMenu from "../components/AddMenu";
import { useCardView, ViewToggle, type EquationView } from "./ViewToggle";
import { formatApiError } from "../api/errors";

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
  /** The workspace's trained predictors: a rule or goal calls one as `predict name(inputs...)`. */
  predictors?: { name: string; inputs: string[]; r2?: number | null }[];
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
  /** Make something new in the domain (a record type, a number on it, new data); absent where the account may not. */
  onCreateSet?: (name: string) => Promise<void>;
  onCreateAttribute?: (set: string, name: string, unit: string) => Promise<void>;
  onCreateParameter?: (parameter: { name: string; index: string[]; defaultValue: number; unit: string }) => Promise<void>;
  /** Simple: plain group names, cards closed to one line, and one “+ Add” per group. */
  simple?: boolean;
  /** Step by step: show this group only. */
  onlyGroup?: "sets" | "data" | "decisions";
  /** Open this declaration's card (a “go to it” from the list of things to fix); `seq` changes each time. */
  opening?: { name: string; seq: number } | null;
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
  onCreateSet,
  onCreateAttribute,
  onCreateParameter,
  simple = false,
  onlyGroup,
  opening = null,
  predictors = [],
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
        <Group hidden={onlyGroup !== undefined && onlyGroup !== "sets"} title={simple ? "Things involved" : "Sets"} hint="The kinds of thing the rules range over.">
          {sets.map((name) => (
            <DeclarationCard key={name} kind="set" name={name} openSignal={opening?.name === name ? opening.seq : undefined} heading={name} view={view} simple={simple}
              summary={declarationSentence("set", name, null, attributes[name] ?? [], undefined)}
              foldDetails
              details={onCreateAttribute ? <NewAttribute set={name} taken={(attributes[name] ?? []).map((a) => a.name)} onCreate={onCreateAttribute} /> : undefined}
              onStop={() => refuseIfStranding("set", name, () => apply({ sets: sets.filter((s) => s !== name) }))}>
              {(shown, setShown) => (
                <DeclarationView kind="set" name={name} spec={null} view={shown} sets={sets} attributes={attributes[name] ?? []}
                  usedBy={usedBy("set", name)} onBoxes={() => setShown("boxes")} />
              )}
            </DeclarationCard>
          ))}
          {simple ? (
            <AddMenu label="Add a set">{() => (
              <>
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
          {onCreateSet && (
            <NewRecordType taken={entityTypeNames} onCreate={async (name) => {
              await onCreateSet(name);
              apply({ sets: [...sets, name] });
            }} />
          )}
              </>
            )}</AddMenu>
          ) : (
            <>
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
          {onCreateSet && (
            <NewRecordType taken={entityTypeNames} onCreate={async (name) => {
              await onCreateSet(name);
              apply({ sets: [...sets, name] });
            }} />
          )}
            </>
          )}
        </Group>

        <Group hidden={onlyGroup !== undefined && onlyGroup !== "data"} title={simple ? "Data" : "Parameters"} hint="Numbers the domain already holds, read by the rules.">
          {predictors.length > 0 && (
            // Benchmark, October 2026: a trained model could not be used -- nothing here named it.
            <section aria-label="Trained predictors" className="mb-2 rounded border border-violet-200 bg-violet-50 p-2 text-sm">
              <p className="font-medium text-violet-900">Trained predictors a rule or goal can use</p>
              <ul className="mt-1 space-y-0.5">
                {predictors.map((p) => (
                  <li key={p.name}>
                    <code className="font-mono text-xs">predict {p.name}({p.inputs.join(", ")})</code>
                    {typeof p.r2 === "number" && <span className="ml-1 text-xs text-slate-600">· R² {p.r2.toFixed(2)}</span>}
                  </li>
                ))}
              </ul>
              <p className="mt-1 text-xs text-slate-600">
                Write it in a rule or goal with its inputs in this order, e.g. from fields of the records a rule runs over;
                the model declares it when it is published.
              </p>
            </section>
          )}
          {Object.entries(parameters).map(([name, spec]) => (
            <DeclarationCard key={name} kind="parameter" name={name} openSignal={opening?.name === name ? opening.seq : undefined} heading={`${name}[${spec.index.join(", ")}]`} view={view} simple={simple}
              summary={declarationSentence("parameter", name, spec, [], units[name])}
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
          {simple ? (
            <AddMenu label="Add data">{() => (
              <>
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
          {onCreateParameter && (
            <NewData sets={sets} taken={[...parameterOptions.map((o) => o.name), ...Object.keys(variables)]} onCreate={async (made) => {
              await onCreateParameter(made);
              apply({ parameters: { ...parameters, [made.name]: { index: made.index } } });
            }} />
          )}
              </>
            )}</AddMenu>
          ) : (
            <>
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
          {onCreateParameter && (
            <NewData sets={sets} taken={[...parameterOptions.map((o) => o.name), ...Object.keys(variables)]} onCreate={async (made) => {
              await onCreateParameter(made);
              apply({ parameters: { ...parameters, [made.name]: { index: made.index } } });
            }} />
          )}
            </>
          )}
        </Group>

        <Group hidden={onlyGroup !== undefined && onlyGroup !== "decisions"} title={simple ? "Decisions" : "Variables"} hint="What the solver decides.">
          {Object.entries(variables).map(([name, spec]) => (
            <DeclarationCard key={name} kind="variable" name={name} openSignal={opening?.name === name ? opening.seq : undefined} heading={`${name}[${spec.index.join(", ")}]`} view={view} simple={simple}
              summary={declarationSentence("variable", name, spec, [], undefined)} problems={checkDeclaration("variable", spec, sets).length}
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
          {simple ? (
            <AddMenu label="Add a decision">{() => (
              <>
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
              </>
            )}</AddMenu>
          ) : (
            <>
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
            </>
          )}
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
function Group({ title, hint, hidden = false, children }: { title: string; hint: string; hidden?: boolean; children: ReactNode }) {
  return (
    // A named group, because "day" appears both as a set and as an index of a
    // variable being built: without the grouping the two are one ambiguous
    // control to anyone navigating by name.
    <div role="group" aria-label={title} className="space-y-1" hidden={hidden}>
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
function DeclarationCard({ kind, name, heading, view, details, foldDetails = false, onRemove, onStop, simple = false, summary, problems = 0, openSignal, children }: {
  kind: DeclarationKind;
  name: string;
  heading: string;
  view: EquationView;
  details?: ReactNode;
  /** Keep the details behind “More options” in every view, the equation's too. */
  foldDetails?: boolean;
  onRemove?: () => void;
  onStop?: () => void;
  /** Simple: closed to one line (its sentence) until opened. */
  simple?: boolean;
  summary?: string;
  problems?: number;
  openSignal?: number;
  children: (shown: EquationView, setShown: (next: EquationView) => void) => ReactNode;
}) {
  const [shown, setShown] = useCardView(view);
  const [more, setMore] = useState(false);
  const [open, setOpen] = useState(!simple);
  useEffect(() => {
    if (openSignal !== undefined) setOpen(true);
  }, [openSignal]);
  const tag = KIND_TAG[kind];
  if (simple && !open) {
    return (
      <button type="button" data-testid={`${kind}-card`} onClick={() => setOpen(true)}
        className="flex w-full min-w-0 items-center gap-2 rounded-md border border-slate-200 bg-white px-3 py-2 text-left text-sm hover:border-blue-300">
        <span aria-hidden="true" className={problems ? "text-rose-600" : "text-emerald-600"}>{problems ? "●" : "✓"}</span>
        <span className="shrink-0 font-mono text-xs text-slate-500">{heading}</span>
        <span className={`shrink-0 rounded px-1.5 py-0.5 text-xs font-semibold ${tag.style}`}>{tag.text}</span>
        <span className="min-w-0 truncate text-slate-900" title={summary}>{summary}</span>
      </button>
    );
  }
  return (
    <article id={`${kind}-card-${name}`} className="rounded-md border border-slate-200 bg-white p-2" data-testid={`${kind}-card`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs">{heading}</span>
        <span className={`rounded px-1.5 py-0.5 text-xs font-semibold ${tag.style}`}>{tag.text}</span>
        <span className="ml-auto flex gap-1">
          {simple && (
            <button type="button" className="rounded px-2 py-1 text-xs text-slate-600 underline" onClick={() => setOpen(false)}>
              Close
            </button>
          )}
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
      {details && (shown === "equation" && !foldDetails ? (
        <div className="mt-1">{details}</div>
      ) : (
        <>
          <button type="button" aria-expanded={more} aria-label={`${more ? "Fewer" : "More"} options for ${name}`}
            className="mt-1 rounded py-1 text-xs font-medium text-blue-700 underline" onClick={() => setMore((open) => !open)}>
            {more ? "Fewer options" : "More options"}
          </button>
          {more && <div className="mt-1">{details}</div>}
        </>
      ))}
    </article>
  );
}

const NAME = /^[a-z][a-z0-9_]*$/;
const FORM_INPUT = "rounded-md border border-slate-300 bg-white px-2 py-1 text-sm text-slate-900";

/** A name the database takes, and not one already used; or why not. */
function nameProblem(name: string, taken: string[]): string | null {
  if (!name) return null;
  if (!NAME.test(name)) return "Use lower-case letters, digits and underscores, starting with a letter.";
  if (taken.includes(name)) return `There is already something called ${name}.`;
  return null;
}

/** A creation form's shell: its fields, its button, and what came of it. */
function CreateForm({ title, button, ready, onSubmit, children }: {
  title: string;
  button: string;
  ready: boolean;
  onSubmit: () => Promise<string>;
  children: ReactNode;
}) {
  const [busy, setBusy] = useState(false);
  const [said, setSaid] = useState<{ error: boolean; text: string } | null>(null);
  return (
    <form aria-label={title} className="space-y-2 rounded-md border border-dashed border-slate-300 bg-white px-3 py-2"
      onSubmit={async (event) => {
        event.preventDefault();
        if (!ready || busy) return;
        setBusy(true);
        setSaid(null);
        try {
          setSaid({ error: false, text: await onSubmit() });
        } catch (error) {
          setSaid({ error: true, text: formatApiError(error) });
        } finally {
          setBusy(false);
        }
      }}>
      <p className="text-xs font-medium text-slate-700">{title}</p>
      <div className="flex flex-wrap items-end gap-2">
        {children}
        <button type="submit" disabled={!ready || busy} className="rounded bg-blue-600 px-3 py-1.5 text-sm text-white disabled:opacity-50">
          {busy ? "Creating…" : button}
        </button>
      </div>
      {said && <p role={said.error ? "alert" : "status"} className={`text-xs ${said.error ? "text-red-700" : "text-emerald-800"}`}>{said.text}</p>}
    </form>
  );
}

/** A new record type in the domain, used as a set of this model at once. */
function NewRecordType({ taken, onCreate }: { taken: string[]; onCreate: (name: string) => Promise<void> }) {
  const [name, setName] = useState("");
  const problem = nameProblem(name, taken);
  return (
    <CreateForm title="Create a new record type" button="Create record type" ready={!!name && !problem}
      onSubmit={async () => {
        await onCreate(name);
        const made = name;
        setName("");
        return `${made} is a record type of this domain now, and a set of this model. Add its records under Data.`;
      }}>
      <label className="text-xs text-slate-600">Name
        <input className={`${FORM_INPUT} ml-1 w-40 font-mono`} value={name} placeholder="warehouse" onChange={(e) => setName(e.target.value.trim())} />
      </label>
      {problem && <p className="w-full text-xs text-red-700">{problem}</p>}
    </CreateForm>
  );
}

/** A number every record of a set carries (an attribute), for rules to read as “data of each”. */
function NewAttribute({ set, taken, onCreate }: { set: string; taken: string[]; onCreate: (set: string, name: string, unit: string) => Promise<void> }) {
  const [name, setName] = useState("");
  const [unit, setUnit] = useState("");
  const problem = nameProblem(name, taken);
  return (
    <CreateForm title={`Add a number to each ${set}`} button="Add number" ready={!!name && !problem}
      onSubmit={async () => {
        await onCreate(set, name, unit.trim());
        const made = name;
        setName("");
        setUnit("");
        return `Each ${set} has ${made} now; fill it in on its records.`;
      }}>
      <label className="text-xs text-slate-600">Name
        <input aria-label={`New number of each ${set}`} className={`${FORM_INPUT} ml-1 w-36 font-mono`} value={name} placeholder="capacity"
          onChange={(e) => setName(e.target.value.trim())} />
      </label>
      <label className="text-xs text-slate-600">Unit
        <input aria-label={`Unit of the new number of each ${set}`} className={`${FORM_INPUT} ml-1 w-24`} value={unit} placeholder="optional"
          onChange={(e) => setUnit(e.target.value)} />
      </label>
      {problem && <p className="w-full text-xs text-red-700">{problem}</p>}
    </CreateForm>
  );
}

/** New data in the domain -- one number per item of the sets chosen -- read by this model at once. */
function NewData({ sets, taken, onCreate }: {
  sets: string[];
  taken: string[];
  onCreate: (made: { name: string; index: string[]; defaultValue: number; unit: string }) => Promise<void>;
}) {
  const [name, setName] = useState("");
  const [index, setIndex] = useState<string[]>([]);
  const [fallback, setFallback] = useState("0");
  const [unit, setUnit] = useState("");
  const problem = nameProblem(name, taken);
  const number = Number(fallback);
  const ready = !!name && !problem && index.length > 0 && fallback.trim() !== "" && Number.isFinite(number);
  return (
    <CreateForm title="Create new data" button="Create data" ready={ready}
      onSubmit={async () => {
        await onCreate({ name, index, defaultValue: number, unit: unit.trim() });
        const made = name;
        setName("");
        setIndex([]);
        return `${made} is data of this domain now, read by this model. Fill in its values under Data › Parameters.`;
      }}>
      <label className="text-xs text-slate-600">Name
        <input aria-label="New data name" className={`${FORM_INPUT} ml-1 w-36 font-mono`} value={name} placeholder="demand"
          onChange={(e) => setName(e.target.value.trim())} />
      </label>
      <fieldset className="text-xs text-slate-600">
        <legend>One number for every</legend>
        {sets.length === 0 && <span>Choose a set first.</span>}
        {sets.map((set) => (
          <label key={set} className="mr-2 inline-flex items-center gap-1">
            <input type="checkbox" checked={index.includes(set)}
              onChange={(e) => setIndex((current) => (e.target.checked ? [...current, set] : current.filter((s) => s !== set)))} />
            <span className="font-mono">{set}</span>
          </label>
        ))}
      </fieldset>
      <label className="text-xs text-slate-600">Where none is given
        <input aria-label="New data default" inputMode="numeric" className={`${FORM_INPUT} ml-1 w-20 font-mono`} value={fallback}
          onChange={(e) => setFallback(e.target.value)} />
      </label>
      <label className="text-xs text-slate-600">Unit
        <input aria-label="New data unit" className={`${FORM_INPUT} ml-1 w-24`} value={unit} placeholder="optional" onChange={(e) => setUnit(e.target.value)} />
      </label>
      {problem && <p className="w-full text-xs text-red-700">{problem}</p>}
      {name && !problem && index.length === 0 && <p className="w-full text-xs text-slate-600">Choose which sets it has one number for.</p>}
      <p className="w-full text-xs text-slate-500">
        Places with a shape? Distances, travel times, “within reach” and counts can be computed from the map instead of
        typed: Data › Parameters › Compute from the map.
      </p>
    </CreateForm>
  );
}
