import { useId, useState } from "react";
import { INPUT_CLASS } from "../components/attrTypes";
import { VARIABLE_DOMAINS } from "../ir/contract";
import {
  parameterIsUsable,
  strandedBy,
  variableNameProblem,
  type ParameterDeclaration,
  type VariableDeclaration,
} from "./declarations";
import type { Constraint, ObjectiveTerm } from "./terms";

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
  parameters: Record<string, { index: string[] }>;
  variables: Record<string, { index: string[]; domain: string }>;
  /** Every entity type of the domain, whether declared as a set or not. */
  entityTypeNames: string[];
  /** The domain's parameters, indexes already read back as set names. */
  parameterOptions: ParameterDeclaration[];
  constraints: Constraint[];
  objectiveTerms: ObjectiveTerm[];
  onChange: (next: {
    sets: string[];
    parameters: Record<string, { index: string[] }>;
    variables: Record<string, { index: string[]; domain: string }>;
  }) => void;
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
}: DeclarationsEditorProps) {
  const [refusal, setRefusal] = useState<string | null>(null);

  function apply(next: Partial<Parameters<DeclarationsEditorProps["onChange"]>[0]>) {
    setRefusal(null);
    onChange({ sets, parameters, variables, ...next });
  }

  function refuseIfStranding(
    kind: "set" | "parameter" | "variable",
    name: string,
    then: () => void
  ) {
    const broken = strandedBy({ kind, name }, constraints, objectiveTerms);
    if (broken.length > 0) {
      setRefusal(
        `${name} is used by ${broken.join(", ")}. Change ${
          broken.length > 1 ? "those rules" : "that rule"
        } first, then remove it.`
      );
      return;
    }
    then();
  }

  return (
    <section aria-labelledby="declarations-heading" className="mb-6">
      <h2 id="declarations-heading" className="mb-2 text-base font-semibold text-slate-900">
        What this model is about
      </h2>

      {refusal && (
        <p role="alert" className="mb-3 text-sm text-red-600">
          {refusal}
        </p>
      )}

      <div className="grid gap-4 md:grid-cols-3">
        <Card title="Sets" hint="The kinds of thing the rules range over.">
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
        </Card>

        <Card title="Parameters" hint="Numbers the domain already holds, read by the rules.">
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
                          parameters: { ...parameters, [option.name]: { index: option.index } },
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
        </Card>

        <Card title="Variables" hint="What the solver decides.">
          {Object.entries(variables).map(([name, spec]) => (
            <div key={name} className="mb-2 rounded border border-slate-200 p-2">
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-xs">
                  {name}[{spec.index.join(", ")}]
                </span>
                <button
                  type="button"
                  className="rounded px-2 py-1 text-xs text-red-700 underline"
                  onClick={() =>
                    refuseIfStranding("variable", name, () => {
                      const next = { ...variables };
                      delete next[name];
                      apply({ variables: next });
                    })
                  }
                >
                  Remove
                </button>
              </div>
              <p className="text-xs text-slate-500">
                {spec.domain === "binary" ? "yes or no for each" : "a whole number for each"}
              </p>
            </div>
          ))}
          <AddVariable
            sets={sets}
            taken={[...Object.keys(variables), ...Object.keys(parameters)]}
            onAdd={(variable) =>
              apply({
                variables: {
                  ...variables,
                  [variable.name]: { index: variable.index, domain: variable.domain },
                },
              })
            }
          />
        </Card>
      </div>
    </section>
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
  const [domain, setDomain] = useState<"binary" | "integer">("binary");
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
            onChange={(event) => setDomain(event.target.value as "binary" | "integer")}
          >
            {VARIABLE_DOMAINS.map((option) => (
              <option key={option} value={option}>
                {option === "binary" ? "yes or no" : "a whole number"}
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

function Card({ title, hint, children }: { title: string; hint: string; children: React.ReactNode }) {
  return (
    // A named group, because "day" appears both as a set and as an index of a
    // variable being built: without the grouping the two are one ambiguous
    // control to anyone navigating by name.
    <div role="group" aria-label={title} className="rounded-md border border-slate-200 bg-white p-3">
      <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
      <p className="mb-2 text-xs text-slate-500">{hint}</p>
      {children}
    </div>
  );
}

function Muted({ children }: { children: React.ReactNode }) {
  return <p className="text-xs text-slate-500">{children}</p>;
}
