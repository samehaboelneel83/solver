import { useId, useState } from "react";
import type { FormDraft } from "./draftIr";
import { applyGuidedCommand, type GuidedCommand, type ParameterUse } from "./guidedCommands";
import { printRule, printTerm } from "./formula";
import type { Constraint, Term } from "./terms";
import { INPUT_CLASS } from "../components/attrTypes";
import PatternForm, { UnitCheck } from "./PatternForm";
import type { PatternCommand } from "./patterns";

type Props = {
  draft: FormDraft;
  availableSets: string[];
  onApply: (command: GuidedCommand) => void;
  /** The scheduling and routing patterns (Epic UX, U-3); without it they are not offered. */
  onPattern?: (command: PatternCommand) => void;
  relationships?: { name: string; from: string; to: string }[];
  /** Parameter name -> its unit from the domain. */
  units?: Record<string, string | null | undefined>;
};

export default function GuidedCreation({ draft, availableSets, onApply, onPattern, relationships = [], units = {} }: Props) {
  const prefix = useId();
  const [kind, setKind] = useState<GuidedCommand["kind"]>("variable");
  const [name, setName] = useState("");
  const [domain, setDomain] = useState<"binary" | "integer" | "continuous">("binary");
  const [index, setIndex] = useState<string[]>([]);
  const [lower, setLower] = useState("0");
  const [upper, setUpper] = useState("");
  const [decision, setDecision] = useState("");
  const [separate, setSeparate] = useState<number[]>([]);
  const [relation, setRelation] = useState<"<=" | "=" | ">=">("<=");
  const [limit, setLimit] = useState("");
  const [limitSource, setLimitSource] = useState<"number" | "parameter">("number");
  const [limitParameter, setLimitParameter] = useState<ParameterUse>({ name: "", dimensions: [] });
  const [coefficient, setCoefficient] = useState<ParameterUse>({ name: "", dimensions: [] });
  const [preference, setPreference] = useState(false);
  const [penalty, setPenalty] = useState("1");
  const [note, setNote] = useState("");
  const [sense, setSense] = useState<"minimize" | "maximize">("minimize");
  const [weight, setWeight] = useState("1");
  const [feedback, setFeedback] = useState<{ error: boolean; text: string } | null>(null);
  const choices = Object.entries(draft.variables).filter(([, spec]) => spec.domain !== "interval");
  const chosen = draft.variables[decision];
  const actualSense = draft.objective.terms.length ? draft.objective.sense as "minimize" | "maximize" : sense;
  const command: GuidedCommand = kind === "variable"
    ? { kind, name: name.trim(), domain, index, lower, upper }
    : kind === "rule" ? { kind, name: name.trim(), decision, separate, relation, limit, preference, penalty, note,
      ...(limitSource === "parameter" ? { limitParameter } : {}), ...(coefficient.name ? { coefficient } : {}) }
    : { kind, name: name.trim(), decision, sense: actualSense, weight, ...(coefficient.name ? { coefficient } : {}) };
  let preview: unknown;
  let issue: string | null = null;
  try {
    const next = applyGuidedCommand(draft, command, availableSets);
    preview = kind === "variable" ? next.variables[command.name] : kind === "rule" ? next.constraints[next.constraints.length - 1] : next.objective;
  } catch (error) { issue = (error as Error).message; }
  const input = `${INPUT_CLASS} mt-1 w-full`;
  const field = (label: string, value: string, update: (value: string) => void, numeric = false) => <label className="block text-sm font-medium">{label}
    <input className={input} value={value} onChange={event => update(event.target.value)} inputMode={numeric ? "decimal" : "text"} />
  </label>;
  return <section aria-labelledby={`${prefix}-title`} className="mb-6 rounded-xl border border-blue-200 bg-white p-5">
    <h2 id={`${prefix}-title`} className="text-lg font-semibold">Create with guided forms</h2>
    <p className="mt-1 text-sm text-slate-600">Define a decision, add limits, then choose what to optimize. These forms add to your draft; review and edit the resulting items below before publishing.</p>
    <div className="my-4 flex flex-wrap gap-2" role="group" aria-label="Choose what to create">
      {(["variable", "rule", "objective"] as const).map(item => <button key={item} type="button" aria-pressed={kind === item}
        className={`rounded-lg border px-3 py-2 text-sm ${kind === item ? "bg-blue-700 text-white" : "bg-white text-slate-700"}`}
        onClick={() => { setKind(item); setName(""); setFeedback(null); }}>
        {{ variable: "1. Decision variable", rule: "2. Rule", objective: "3. Objective" }[item]}
      </button>)}
    </div>
    <form onSubmit={event => {
      event.preventDefault();
      try {
        onApply(command);
        setFeedback({ error: false, text: `${kind === "objective" ? "Objective term" : kind === "rule" ? "Rule" : "Decision variable"} ${command.name} added to the draft.` });
        // A fresh form for the next one: a kept tick put the next decision over the last one's sets
        // without anyone seeing it (benchmark, October 2026).
        setName(""); setDomain("binary"); setIndex([]); setLower("0"); setUpper("");
        setSeparate([]); setLimit(""); setLimitSource("number"); setLimitParameter({ name: "", dimensions: [] });
        setCoefficient({ name: "", dimensions: [] }); setPreference(false); setPenalty("1"); setNote(""); setWeight("1");
      } catch (error) { setFeedback({ error: true, text: (error as Error).message }); }
    }}>
      <div className="grid gap-4 sm:grid-cols-2">
        <div>{field(kind === "variable" ? "Decision name" : kind === "rule" ? "Rule name" : "Objective term name", name, setName)}
          <p className="mt-1 text-xs text-slate-500">Use a short identifier, for example staff_count or daily_capacity.</p></div>
        {kind === "variable" ? <>
          <label className="block text-sm font-medium">What kind of decision?
            <select className={input} value={domain} onChange={event => setDomain(event.target.value as typeof domain)}>
              <option value="binary">Yes or no (0 or 1)</option><option value="integer">Whole number (for example, number of people)</option><option value="continuous">Decimal amount (for example, quantity produced)</option>
            </select></label>
          <fieldset className="sm:col-span-2"><legend className="text-sm font-medium">Create one decision for each combination of</legend>
            <p className="text-xs text-slate-500">Leave all unchecked for one overall decision. Selected order: {index.join(" → ") || "one overall value"}.</p>
            <div className="mt-2 flex flex-wrap gap-4">{availableSets.map(set => <label key={set} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={index.includes(set)} onChange={event => setIndex(event.target.checked ? [...index, set] : index.filter(item => item !== set))} />{set}</label>)}</div>
            {!availableSets.length && <p className="mt-2 text-sm">No record types yet. You can create an overall decision now, or define record types in Domain data.</p>}
          </fieldset>
          {domain !== "binary" && <>{field("Minimum (0 if blank)", lower, setLower, true)}{field("Maximum (optional)", upper, setUpper, true)}<p className="text-xs text-slate-600 sm:col-span-2">A blank minimum is 0; a blank maximum is no bound, which can make a goal unbounded.</p></>}
        </> : <>
          <label className="block text-sm font-medium">Decision to use
            <select className={input} value={decision} onChange={event => { setDecision(event.target.value); setSeparate([]); setCoefficient({ name: "", dimensions: [] }); setLimitParameter({ name: "", dimensions: [] }); }}>
              <option value="">Choose a decision</option>{choices.map(([key, spec]) => <option key={key} value={key}>{key}{spec.index.length ? ` — by ${spec.index.join(", ")}` : " — overall"}</option>)}
            </select></label>
          {!choices.length && <p className="text-sm text-slate-600 sm:col-span-2">Create a decision variable first. Interval scheduling uses the advanced forms below.</p>}
          <ParameterFields label="Multiply each decision by" draft={draft} decision={decision} units={units}
            allowed={(chosen?.index ?? []).map((_, i) => i)} value={coefficient} onChange={setCoefficient} optional />
          {kind === "rule" ? <>
            {!!chosen?.index.length && <fieldset className="sm:col-span-2"><legend className="text-sm font-medium">Apply this limit separately for each</legend>
              <p className="text-xs text-slate-500">Unchecked dimensions are added together. Leave all unchecked to limit the overall total.</p>
              <div className="mt-2 flex flex-wrap gap-4">{chosen.index.map((set, i) => <label key={i} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={separate.includes(i)} onChange={event => setSeparate(event.target.checked ? [...separate, i] : separate.filter(item => item !== i))} />{set} (dimension {i + 1})</label>)}</div>
            </fieldset>}
            <label className="block text-sm font-medium">The value must be
              <select className={input} value={relation} onChange={event => setRelation(event.target.value as typeof relation)}><option value="<=">At most</option><option value="=">Exactly</option><option value=">=">At least</option></select></label>
            <label className="block text-sm font-medium">Limit source
              <select className={input} value={limitSource} onChange={event => setLimitSource(event.target.value as typeof limitSource)}>
                <option value="number">Fixed number</option><option value="parameter">Domain parameter (capacity, demand, …)</option>
              </select>
            </label>
            {limitSource === "number" ? field("Limit", limit, setLimit, true)
              : <ParameterFields label="Limit parameter" draft={draft} decision={decision} units={units} allowed={separate} value={limitParameter} onChange={setLimitParameter} />}
            <UnitCheck units={units} a={coefficient.name || null} b={limitSource === "parameter" ? limitParameter.name || null : null} />
            <label className="block text-sm font-medium">How strict is this rule?
              <select className={input} value={preference ? "preference" : "required"} onChange={event => setPreference(event.target.value === "preference")}><option value="required">Required — every acceptable solution must obey it</option><option value="preference">Preference — may be violated at a cost</option></select></label>
            {preference && field("Penalty for violating this preference", penalty, setPenalty, true)}
            {field("Business explanation (optional)", note, setNote)}
          </> : <>
            <label className="block text-sm font-medium">Optimization direction
              <select className={input} value={actualSense} disabled={draft.objective.terms.length > 0} onChange={event => setSense(event.target.value as typeof sense)}><option value="minimize">Minimize — make the total smaller</option><option value="maximize">Maximize — make the total larger</option></select></label>
            {field("Objective weight", weight, setWeight, true)}
            <p className="text-sm text-slate-600 sm:col-span-2">Adds the total of the chosen decision, optionally multiplied by a parameter such as unit cost. Existing terms and their combination mode are preserved. Change the overall direction or build more complex expressions in “What to make best” below.</p>
          </>}
        </>}
      </div>
      <div className="my-4 rounded-lg bg-slate-50 p-3 text-sm" aria-label="Creation summary">
        {kind === "variable" ? `Create ${name || "a decision"}: ${domain === "binary" ? "yes/no" : domain === "integer" ? "whole numbers" : "decimal amounts"}, ${index.length ? `for each combination of ${index.join(" and ")}` : "one overall value"}.`
          : kind === "rule" ? `${preference ? "Prefer" : "Require"} ${coefficient.name ? `${coefficient.name} × ` : ""}${decision || "the selected decision"}${chosen?.index.some((_, i) => !separate.includes(i)) ? " summed over unchecked dimensions" : ""} ${relation} ${limitSource === "parameter" ? limitParameter.name || "a parameter" : limit || "a limit"}${separate.length ? `, separately by ${separate.map(i => chosen?.index[i]).join(", ")}` : " overall"}.`
          : `${actualSense} the total of ${coefficient.name ? `${coefficient.name} × ` : ""}${decision || "the selected decision"} with weight ${weight || "to be supplied"}.`}
      </div>
      {!issue && kind === "rule" && preview !== undefined && (
        <p className="-mt-2 mb-4 overflow-x-auto whitespace-nowrap rounded bg-slate-50 px-3 py-2 font-mono text-xs text-slate-700" aria-label="Equation">
          {printRule(preview as Constraint)}
        </p>
      )}
      {!issue && kind === "objective" && (preview as { terms?: { expression?: Term }[] } | undefined)?.terms?.length ? (
        <p className="-mt-2 mb-4 overflow-x-auto whitespace-nowrap rounded bg-slate-50 px-3 py-2 font-mono text-xs text-slate-700" aria-label="Equation">
          {(() => {
            const terms = (preview as { terms: { expression?: Term }[] }).terms;
            const last = terms[terms.length - 1]?.expression;
            return last ? printTerm(last) : "";
          })()}
        </p>
      ) : null}
      {issue && <p id={`${prefix}-issue`} className="mb-3 text-sm text-slate-600">{issue}</p>}
      {!issue && <details className="mb-3"><summary className="cursor-pointer py-2 text-sm">Preview exact model representation</summary><pre className="max-h-64 overflow-auto bg-slate-50 p-3 text-xs">{JSON.stringify(preview, null, 2)}</pre></details>}
      <button type="submit" disabled={issue !== null} aria-describedby={issue ? `${prefix}-issue` : undefined} className="rounded-lg bg-blue-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">{kind === "variable" ? "Create decision variable" : kind === "rule" ? "Create rule" : "Add objective term"}</button>
      {feedback && <p role={feedback.error ? "alert" : "status"} className={`mt-3 text-sm ${feedback.error ? "text-red-700" : "text-green-800"}`}>{feedback.text}</p>}
    </form>
    {onPattern && <PatternForm draft={draft} availableSets={availableSets} relationships={relationships} units={units} onApply={onPattern} />}
  </section>;
}

function ParameterFields({ label, draft, decision, allowed, value, onChange, optional = false, units = {} }: {
  label: string; draft: FormDraft; decision: string; allowed: number[]; value: ParameterUse;
  onChange: (value: ParameterUse) => void; optional?: boolean; units?: Record<string, string | null | undefined>;
}) {
  const dimensions = draft.variables[decision]?.index ?? [];
  const options = Object.entries(draft.parameters).filter(([, spec]) => !("entity" in spec));
  const spec = draft.parameters[value.name];
  return <fieldset className="rounded-lg border border-slate-200 p-3 sm:col-span-2">
    <legend className="px-1 text-sm font-medium">{label}</legend>
    <label className="block text-sm">{label}: parameter
      <select className={`${INPUT_CLASS} mt-1 w-full`} value={value.name} onChange={event => {
        const name = event.target.value;
        const mapped = (draft.parameters[name]?.index ?? []).map(set => {
          const candidates = allowed.filter(i => dimensions[i] === set);
          return candidates.length === 1 ? candidates[0] : -1;
        });
        onChange({ name, dimensions: mapped });
      }}>
        <option value="">{optional ? "No multiplier — count the decision" : "Choose a parameter"}</option>
        {options.map(([name, parameter]) => <option key={name} value={name}>{name}{parameter.index.length ? ` [${parameter.index.join(", ")}]` : " [overall]"}{units[name] ? ` in ${units[name]}` : ""}</option>)}
      </select>
    </label>
    {!options.length && <p className="mt-2 text-xs text-slate-600">No numeric parameters selected. Choose sets and parameters in “What this model is about” below, or add domain parameters from Inputs.</p>}
    {spec?.index.map((set, position) => <label key={position} className="mt-3 block text-sm">
      {label}: {set} (parameter dimension {position + 1})
      <select className={`${INPUT_CLASS} mt-1 w-full`} value={allowed.includes(value.dimensions[position]) && dimensions[value.dimensions[position]] === set ? value.dimensions[position] : -1}
        onChange={event => onChange({ ...value, dimensions: spec.index.map((_, i) => i === position ? Number(event.target.value) : value.dimensions[i] ?? -1) })}>
        <option value={-1}>Choose a matching dimension</option>
        {allowed.filter(i => dimensions[i] === set).map(i => <option key={i} value={i}>{set} (decision dimension {i + 1})</option>)}
      </select>
    </label>)}
    {value.name && spec && <MappingPreview name={value.name} parameterIndex={spec.index} dimensions={value.dimensions}
      decision={decision} decisionIndex={dimensions} allowed={allowed} unit={units[value.name] ?? null} />}
  </fieldset>;
}

/**
 * The mapping, said plainly (Epic UX, U-3): `cost[nurse ← staff's nurse, shift ← staff's shift]`,
 * and for each dimension not yet mapped, why -- rather than a refusal after the fact.
 */
export function MappingPreview({ name, parameterIndex, dimensions, decision, decisionIndex, allowed, unit }: {
  name: string; parameterIndex: string[]; dimensions: number[]; decision: string; decisionIndex: string[];
  allowed: number[]; unit: string | null;
}) {
  const parts = parameterIndex.map((set, i) => {
    const d = dimensions[i];
    return d !== undefined && d >= 0 && decisionIndex[d] === set ? `${set} ← ${decision || "the decision"}'s ${set}` : `${set} ← ?`;
  });
  const problems = parameterIndex.flatMap((set, i) => {
    const d = dimensions[i];
    if (d !== undefined && d >= 0 && decisionIndex[d] === set) return [];
    const matching = decisionIndex.map((s, j) => (s === set ? j : -1)).filter((j) => j >= 0);
    if (matching.length === 0) return [`${decision || "The decision"} has no ${set} dimension, so ${name}'s ${set} cannot follow it.`];
    if (!matching.some((j) => allowed.includes(j))) return [`${decision || "The decision"}'s ${set} is added together here; a limit can only follow a dimension kept separate. Tick ${set} under "Apply this limit separately for each".`];
    return [`Choose which of ${decision || "the decision"}'s ${set} dimensions ${name}'s ${set} follows.`];
  });
  return <div className="mt-2 text-xs text-slate-700" aria-label={`Mapping of ${name}`}>
    <p className="font-mono">{name}[{parts.join(", ")}]{unit ? ` in ${unit}` : ""}</p>
    {problems.map((problem) => <p key={problem} className="text-amber-800">{problem}</p>)}
  </div>;
}
