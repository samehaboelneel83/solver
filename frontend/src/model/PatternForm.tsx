import { useId, useState } from "react";
import { INPUT_CLASS } from "../components/attrTypes";
import type { FormDraft } from "./draftIr";
import { applyPattern, PATTERNS, tasksOf, type Amount, type PatternCommand, type PatternKind } from "./patterns";
import { describeConnected, describeRoute, describeSchedule } from "./terms";

type Relationship = { name: string; from: string; to: string };

/**
 * The scheduling and routing patterns (Epic UX, U-3): pick one, fill in a few
 * planner-level fields, see in words what it adds, and add it whole.
 */
export default function PatternForm({ draft, availableSets, relationships, units, onApply }: {
  draft: FormDraft;
  availableSets: string[];
  relationships: Relationship[];
  /** Parameter name -> its unit from the domain, where it has one. */
  units: Record<string, string | null | undefined>;
  onApply: (command: PatternCommand) => void;
}) {
  const prefix = useId();
  const [kind, setKind] = useState<PatternKind>("task");
  const [name, setName] = useState("");
  const [index, setIndex] = useState<string[]>([]);
  const [size, setSize] = useState<Amount>({ const: 1 });
  const [horizon, setHorizon] = useState("100");
  const [optional, setOptional] = useState(false);
  const tasks = tasksOf(draft);
  const [task, setTask] = useState("");
  const [resource, setResource] = useState<number[]>([]);
  const [demand, setDemand] = useState<Amount>({ const: 1 });
  const [capacity, setCapacity] = useState<Amount>({ const: 1 });
  const [vehicles, setVehicles] = useState("");
  const [stops, setStops] = useState("");
  const [depot, setDepot] = useState("");
  const [loadDemand, setLoadDemand] = useState("");
  const [loadCapacity, setLoadCapacity] = useState("");
  const [travel, setTravel] = useState("");
  const [unitsSet, setUnitsSet] = useState("");
  const [groups, setGroups] = useState("");
  const [via, setVia] = useState("");
  const [everyUnitOnce, setEveryUnitOnce] = useState(true);
  const [allowEmpty, setAllowEmpty] = useState(false);
  const [feedback, setFeedback] = useState<{ error: boolean; text: string } | null>(null);

  const chosenTask = draft.variables[task || tasks[0]?.name || ""];
  const taskName = task || tasks[0]?.name || "";
  const command: PatternCommand =
    kind === "task" ? { kind, name: name.trim(), index, size, horizon: Number(horizon), optional }
      : kind === "one_at_a_time" ? { kind, name: name.trim(), task: taskName, resource }
        : kind === "shared_capacity" ? { kind, name: name.trim(), task: taskName, resource, demand, capacity }
          : kind === "routes" ? { kind, name: name.trim(), vehicles, stops, depot,
              ...(loadDemand && loadCapacity ? { load: { demand: loadDemand, capacity: loadCapacity } } : {}),
              ...(travel ? { travel } : {}) }
            : { kind, name: name.trim(), units: unitsSet, groups, via, everyUnitOnce, allowEmpty };

  let issue: string | null = null;
  let summary = "";
  try {
    const next = applyPattern(draft, command, availableSets);
    summary = describeAdded(draft, next);
  } catch (error) {
    issue = (error as Error).message;
  }
  const input = `${INPUT_CLASS} mt-1 w-full`;
  const setChoice = (label: string, value: string, update: (v: string) => void, options: string[]) => (
    <label className="block text-sm font-medium">{label}
      <select className={input} value={value} onChange={(event) => update(event.target.value)}>
        <option value="">Choose…</option>
        {options.map((option) => <option key={option} value={option}>{option}</option>)}
      </select>
    </label>
  );
  const parametersIndexedBy = (sets: string[]) =>
    Object.entries(draft.parameters).filter(([, spec]) => spec.index.join("|") === sets.join("|")).map(([n]) => n);
  const amountField = (label: string, value: Amount, update: (a: Amount) => void, sets: string[]) => (
    <AmountField label={label} value={value} onChange={update} options={parametersIndexedBy(sets)} units={units}
      shape={sets.length ? `one number for each ${sets.join(" and ")}` : "one number"} />
  );

  return (
    <div className="mt-4 rounded-lg border border-slate-200 p-4">
      <h3 id={`${prefix}-title`} className="text-base font-semibold">Scheduling and routing patterns</h3>
      <div className="my-3 flex flex-wrap gap-2" role="group" aria-label="Choose a pattern">
        {PATTERNS.map((pattern) => (
          <button key={pattern.kind} type="button" aria-pressed={kind === pattern.kind}
            className={`rounded-lg border px-3 py-2 text-sm ${kind === pattern.kind ? "bg-blue-700 text-white" : "bg-white text-slate-700"}`}
            onClick={() => { setKind(pattern.kind); setName(""); setFeedback(null); }}>
            {pattern.label}
          </button>
        ))}
      </div>
      <p className="mb-3 text-sm text-slate-600">{PATTERNS.find((p) => p.kind === kind)?.says}</p>
      <form aria-labelledby={`${prefix}-title`} onSubmit={(event) => {
        event.preventDefault();
        try {
          onApply(command);
          setFeedback({ error: false, text: `${PATTERNS.find((p) => p.kind === kind)?.label} ${command.name} added to the draft.` });
          setName("");
        } catch (error) {
          setFeedback({ error: true, text: (error as Error).message });
        }
      }}>
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block text-sm font-medium">{kind === "task" ? "Task name" : "Rule name"}
            <input className={input} value={name} onChange={(event) => setName(event.target.value)} />
          </label>
          {kind === "task" && <>
            <fieldset className="sm:col-span-2"><legend className="text-sm font-medium">One task for each combination of</legend>
              <div className="mt-2 flex flex-wrap gap-4">{availableSets.map((set) => <label key={set} className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={index.includes(set)} onChange={(event) => setIndex(event.target.checked ? [...index, set] : index.filter((s) => s !== set))} />{set}
              </label>)}</div>
            </fieldset>
            {amountField("Duration", size, setSize, index)}
            <label className="block text-sm font-medium">Horizon (latest end, in time steps)
              <input className={input} value={horizon} inputMode="numeric" onChange={(event) => setHorizon(event.target.value)} />
            </label>
            <label className="flex items-center gap-2 text-sm sm:col-span-2">
              <input type="checkbox" checked={optional} onChange={(event) => setOptional(event.target.checked)} />
              A task may be left undone (the model decides whether each one happens)
            </label>
          </>}
          {(kind === "one_at_a_time" || kind === "shared_capacity") && <>
            {tasks.length === 0 ? <p className="text-sm text-slate-600 sm:col-span-2">Add a task first, with the Task with a duration pattern.</p> : <>
              {setChoice("Task", taskName, (v) => { setTask(v); setResource([]); }, tasks.map((t) => t.name))}
              <fieldset className="sm:col-span-2"><legend className="text-sm font-medium">The resource is each</legend>
                <p className="text-xs text-slate-500">The other dimensions are the tasks that share it.</p>
                <div className="mt-2 flex flex-wrap gap-4">{(chosenTask?.index ?? []).map((set, i) => <label key={i} className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={resource.includes(i)} onChange={(event) => setResource(event.target.checked ? [...resource, i] : resource.filter((r) => r !== i))} />{set}
                </label>)}</div>
              </fieldset>
              {kind === "shared_capacity" && <>
                {amountField("Each task uses", demand, setDemand, chosenTask?.index ?? [])}
                {amountField("The resource has", capacity, setCapacity, resource.map((i) => chosenTask?.index[i] ?? ""))}
                <UnitCheck units={units} a={"parameter" in demand ? demand.parameter : null} b={"parameter" in capacity ? capacity.parameter : null} />
              </>}
            </>}
          </>}
          {kind === "routes" && <>
            {setChoice("Vehicles", vehicles, setVehicles, availableSets)}
            {setChoice("Stops", stops, setStops, availableSets)}
            <label className="block text-sm font-medium">Depot (the key of the stop they start from)
              <input className={input} value={depot} onChange={(event) => setDepot(event.target.value)} />
            </label>
            {setChoice("Travel cost to minimise (optional)", travel, setTravel, parametersIndexedBy([stops, stops]))}
            <label className="block text-sm font-medium">Stop demand attribute (optional)
              <input className={input} value={loadDemand} onChange={(event) => setLoadDemand(event.target.value)} />
            </label>
            <label className="block text-sm font-medium">Vehicle capacity attribute (optional)
              <input className={input} value={loadCapacity} onChange={(event) => setLoadCapacity(event.target.value)} />
            </label>
            {Boolean(loadDemand) !== Boolean(loadCapacity) && <p className="text-xs text-amber-800 sm:col-span-2">Name both the demand and the capacity, or neither.</p>}
          </>}
          {kind === "regions" && <>
            {setChoice("Units (what is grouped)", unitsSet, (v) => { setUnitsSet(v); setVia(""); }, availableSets)}
            {setChoice("Groups", groups, setGroups, availableSets)}
            {setChoice(`Next to each other by`, via, setVia, relationships.filter((r) => r.from === unitsSet && r.to === unitsSet).map((r) => r.name))}
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={everyUnitOnce} onChange={(event) => setEveryUnitOnce(event.target.checked)} />Every unit in exactly one group</label>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={allowEmpty} onChange={(event) => setAllowEmpty(event.target.checked)} />A group may be left empty</label>
          </>}
        </div>
        <div className="my-4 rounded-lg bg-slate-50 p-3 text-sm" aria-label="Pattern summary">{issue ?? summary}</div>
        <button type="submit" disabled={issue !== null} className="rounded-lg bg-blue-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
          Add {PATTERNS.find((p) => p.kind === kind)?.label.toLowerCase()}
        </button>
        {feedback && <p role={feedback.error ? "alert" : "status"} className={`mt-3 text-sm ${feedback.error ? "text-red-700" : "text-green-800"}`}>{feedback.text}</p>}
      </form>
    </div>
  );
}

/** What a pattern adds, in words: the new declarations and rules. */
export function describeAdded(before: FormDraft, after: FormDraft): string {
  const added: string[] = [];
  for (const [name, spec] of Object.entries(after.variables)) {
    if (before.variables[name]) continue;
    added.push(spec.domain === "interval"
      ? `the task ${name}${spec.index.length ? ` for each ${spec.index.join(" and ")}` : ""}, lasting ${String(spec.size)}${spec.presence ? `, done only if ${spec.presence}` : ""}`
      : `the decision ${name} (${spec.domain === "binary" ? "yes or no" : spec.domain === "integer" ? "whole number" : "any number"})`);
  }
  for (const rule of after.constraints.slice(before.constraints.length)) {
    added.push(`the rule ${rule.id}: ${describeSchedule(rule) ?? describeRoute(rule) ?? describeConnected(rule) ?? "each unit in exactly one group"}`);
  }
  for (const term of after.objective.terms.slice(before.objective.terms.length)) added.push(`the goal term ${term.id}`);
  return `Adds ${added.join("; ")}.`;
}

function AmountField({ label, value, onChange, options, units, shape }: {
  label: string; value: Amount; onChange: (a: Amount) => void; options: string[];
  units: Record<string, string | null | undefined>; shape: string;
}) {
  const fromParameter = "parameter" in value;
  return (
    <fieldset className="rounded border border-slate-200 p-2">
      <legend className="px-1 text-sm font-medium">{label}</legend>
      <select aria-label={`${label}: from`} className={`${INPUT_CLASS} w-full`} value={fromParameter ? "parameter" : "number"}
        onChange={(event) => onChange(event.target.value === "number" ? { const: 1 } : { parameter: options[0] ?? "" })}>
        <option value="number">A fixed number</option>
        <option value="parameter">A parameter ({shape})</option>
      </select>
      {fromParameter ? (
        <>
          <select aria-label={`${label}: parameter`} className={`${INPUT_CLASS} mt-1 w-full`} value={value.parameter}
            onChange={(event) => onChange({ parameter: event.target.value })}>
            {!options.length && <option value="">No parameter holds {shape}</option>}
            {options.map((option) => <option key={option} value={option}>{option}{units[option] ? ` (${units[option]})` : ""}</option>)}
          </select>
        </>
      ) : (
        <input aria-label={`${label}: number`} className={`${INPUT_CLASS} mt-1 w-full`} inputMode="decimal" value={String(value.const)}
          onChange={(event) => onChange({ const: Number(event.target.value) })} />
      )}
    </fieldset>
  );
}

/** A warning when two parameters compared in one rule carry different units. */
export function UnitCheck({ units, a, b }: { units: Record<string, string | null | undefined>; a: string | null; b: string | null }) {
  const warning = unitMismatch(units, a, b);
  return warning ? <p role="note" className="text-xs text-amber-800 sm:col-span-2">{warning}</p> : null;
}

export function unitMismatch(units: Record<string, string | null | undefined>, a: string | null, b: string | null): string | null {
  if (!a || !b) return null;
  const ua = units[a];
  const ub = units[b];
  if (!ua || !ub || ua === ub) return null;
  return `${a} is in ${ua} and ${b} in ${ub}: the rule compares them as they are, so check they measure the same thing.`;
}
