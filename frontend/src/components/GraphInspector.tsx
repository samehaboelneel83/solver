import { useEffect, useId, useState } from "react";
import type { ModelPart } from "../lib/modelGraph";
import type { FormDraft } from "../model/draftIr";
import { applyDeletion, connect, connectionFor, planDeletion, rename, type Connection, type PartRef } from "../model/graphCommands";
import { withDomain } from "../model/declarations";

/** A graph card as the commands name it. */
export type GraphPart = PartRef & { nodeId: string; label: string };

export type GraphEdit = (current: FormDraft) => FormDraft;

/** The selected card's own editor, and its Connect and Delete actions (Epic UX, U-2). */
export default function GraphInspector({
  draft,
  part,
  parts,
  onEdit,
  mode,
  onMode,
}: {
  draft: FormDraft;
  part: GraphPart;
  /** Every card, for the Connect list. */
  parts: GraphPart[];
  onEdit: (edit: GraphEdit, done: string) => void;
  mode: "inspect" | "connect" | "delete";
  onMode: (mode: "inspect" | "connect" | "delete") => void;
}) {
  return (
    <section aria-label={`Inspector: ${part.label}`} className="rounded-lg border border-slate-300 bg-white p-3 text-sm">
      <h3 className="mb-2 font-semibold">{KIND[part.part]} {part.name}</h3>
      {mode === "connect" ? (
        <ConnectForm draft={draft} source={part} parts={parts} onEdit={onEdit} onCancel={() => onMode("inspect")} />
      ) : mode === "delete" ? (
        <DeleteForm draft={draft} target={part} onEdit={onEdit} onCancel={() => onMode("inspect")} />
      ) : (
        <>
          {part.part === "variables" && <VariableFields draft={draft} name={part.name} onEdit={onEdit} />}
          {part.part === "parameters" && <ParameterFacts draft={draft} name={part.name} />}
          {part.part === "sets" && <SetFacts draft={draft} name={part.name} />}
          {(part.part === "rules" || part.part === "objective") && (
            <p className="text-slate-600">Its own editor is open below this graph; renaming it there follows every reference.</p>
          )}
          <div className="mt-3 flex flex-wrap gap-2">
            {(part.part === "sets" || part.part === "variables" || part.part === "parameters") && (
              <button type="button" className="rounded border px-3 py-2" onClick={() => onMode("connect")}>Connect…</button>
            )}
            <button type="button" className="rounded border border-red-300 px-3 py-2 text-red-800" onClick={() => onMode("delete")}>Delete…</button>
          </div>
        </>
      )}
    </section>
  );
}

const KIND: Record<ModelPart, string> = { sets: "Set", variables: "Decision", parameters: "Parameter", rules: "Rule", objective: "Goal" };

function Problem({ text }: { text: string | null }) {
  return text ? <p role="alert" className="mt-2 text-red-700">{text}</p> : null;
}

function RenameField({ draft, target, onEdit, label }: { draft: FormDraft; target: PartRef; onEdit: (edit: GraphEdit, done: string) => void; label: string }) {
  const id = useId();
  const [value, setValue] = useState(target.name);
  const [problem, setProblem] = useState<string | null>(null);
  useEffect(() => setValue(target.name), [target.name]);
  const apply = () => {
    try {
      rename(draft, target, value.trim());
      setProblem(null);
      onEdit((current) => rename(current, target, value.trim()), `Renamed ${target.name} to ${value.trim()}; every reference follows.`);
    } catch (error) {
      setProblem((error as Error).message);
    }
  };
  return (
    <div className="mb-2">
      <label htmlFor={id} className="block text-xs text-slate-600">{label}</label>
      <div className="flex gap-2">
        <input id={id} value={value} onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => { if (event.key === "Enter") apply(); }}
          className="rounded border border-slate-300 px-2 py-1 font-mono" />
        <button type="button" className="rounded border px-3 py-1" onClick={apply} disabled={value.trim() === target.name}>Rename</button>
      </div>
      <Problem text={problem} />
    </div>
  );
}

function VariableFields({ draft, name, onEdit }: { draft: FormDraft; name: string; onEdit: (edit: GraphEdit, done: string) => void }) {
  const spec = draft.variables[name];
  const [lower, setLower] = useState(spec?.lower === undefined ? "" : String(spec.lower));
  const [upper, setUpper] = useState(spec?.upper === undefined ? "" : String(spec.upper));
  const [problem, setProblem] = useState<string | null>(null);
  useEffect(() => {
    setLower(spec?.lower === undefined ? "" : String(spec.lower));
    setUpper(spec?.upper === undefined ? "" : String(spec.upper));
  }, [spec?.lower, spec?.upper]);
  if (!spec) return null;
  const update = (next: typeof spec, done: string) =>
    onEdit((current) => ({ ...current, variables: { ...current.variables, [name]: next } }), done);
  const saveBounds = () => {
    const lo = lower.trim() === "" ? undefined : Number(lower);
    const hi = upper.trim() === "" ? undefined : Number(upper);
    if ([lo, hi].some((v) => v !== undefined && !Number.isFinite(v))) return setProblem("Bounds must be numbers.");
    if (lo !== undefined && hi !== undefined && lo > hi) return setProblem("The minimum must not exceed the maximum.");
    if (spec.domain === "integer" && [lo, hi].some((v) => v !== undefined && !Number.isInteger(v))) {
      return setProblem("A whole-number decision needs whole-number bounds.");
    }
    setProblem(null);
    const next = { ...spec };
    delete next.lower;
    delete next.upper;
    update({ ...next, ...(lo !== undefined ? { lower: lo } : {}), ...(hi !== undefined ? { upper: hi } : {}) },
      `${name} now ranges from ${lo ?? "0"} to ${hi ?? "no stated limit"}.`);
  };
  return (
    <div className="space-y-2">
      <RenameField draft={draft} target={{ part: "variables", name }} onEdit={onEdit} label="Name" />
      <p className="text-slate-600">One value for {spec.index.length ? `each ${spec.index.join(" and ")}` : "the whole model"}.</p>
      {spec.domain === "interval" ? (
        <p className="text-slate-600">A task: from {spec.start} to {spec.end}, lasting {String(spec.size)}. Edit it in the declarations below.</p>
      ) : (
        <>
          <label className="block">
            <span className="block text-xs text-slate-600">Kind of value</span>
            <select value={spec.domain} className="rounded border border-slate-300 px-2 py-1"
              onChange={(event) => update(withDomain(spec, event.target.value as typeof spec.domain), `${name} is now ${event.target.value}.`)}>
              <option value="binary">yes or no</option>
              <option value="integer">whole number</option>
              <option value="continuous">any number</option>
            </select>
          </label>
          {spec.domain !== "binary" && (
            <div className="flex flex-wrap items-end gap-2">
              <label><span className="block text-xs text-slate-600">Minimum</span>
                <input value={lower} onChange={(event) => setLower(event.target.value)} inputMode="decimal" className="w-24 rounded border border-slate-300 px-2 py-1" /></label>
              <label><span className="block text-xs text-slate-600">Maximum</span>
                <input value={upper} onChange={(event) => setUpper(event.target.value)} inputMode="decimal" className="w-24 rounded border border-slate-300 px-2 py-1" /></label>
              <button type="button" className="rounded border px-3 py-1" onClick={saveBounds}>Save bounds</button>
            </div>
          )}
        </>
      )}
      <Problem text={problem} />
    </div>
  );
}

function usersOf(draft: FormDraft, match: (text: string) => boolean): string[] {
  return [
    ...draft.constraints.filter((rule) => match(JSON.stringify(rule))).map((rule) => `rule ${rule.id}`),
    ...draft.objective.terms.filter((term) => match(JSON.stringify(term))).map((term) => `goal term ${term.id}`),
  ];
}

function ParameterFacts({ draft, name }: { draft: FormDraft; name: string }) {
  const spec = draft.parameters[name];
  if (!spec) return null;
  const users = usersOf(draft, (text) => text.includes(`"par":"${name}"`));
  return (
    <div className="space-y-1 text-slate-700">
      <p>Data from the domain: one number for {spec.index.length ? `each ${spec.index.join(" and ")}` : "the whole model"}.</p>
      <p>Its values and name are kept on the domain&rsquo;s Parameters page.</p>
      <p>{users.length ? `Read by ${users.join(", ")}.` : "Not read by any rule or goal term yet."}</p>
    </div>
  );
}

function SetFacts({ draft, name }: { draft: FormDraft; name: string }) {
  const indexed = [
    ...Object.entries(draft.variables).filter(([, s]) => s.index.includes(name)).map(([n]) => `decision ${n}`),
    ...Object.entries(draft.parameters).filter(([, s]) => s.index.includes(name)).map(([n]) => `parameter ${n}`),
  ];
  const users = usersOf(draft, (text) => text.includes(`"set":"${name}"`));
  return (
    <div className="space-y-1 text-slate-700">
      <p>Every {name} in the domain&rsquo;s data.</p>
      <p>{indexed.length ? `Indexes ${indexed.join(", ")}.` : "Indexes nothing yet."}</p>
      {users.length > 0 && <p>Ranged over by {users.join(", ")}.</p>}
    </div>
  );
}

function ConnectForm({ draft, source, parts, onEdit, onCancel }: {
  draft: FormDraft; source: GraphPart; parts: GraphPart[]; onEdit: (edit: GraphEdit, done: string) => void; onCancel: () => void;
}) {
  const targets = parts.flatMap((target) => {
    const found = connectionFor(source, target);
    return "kind" in found ? [{ target, ...found }] : [];
  });
  const [chosen, setChosen] = useState(targets[0]?.target.nodeId ?? "");
  const [coefficient, setCoefficient] = useState("1");
  const [problem, setProblem] = useState<string | null>(null);
  const pick = targets.find((t) => t.target.nodeId === chosen);
  if (targets.length === 0) {
    return <div><p>Nothing in this model can take a connection from {source.name}.</p>
      <button type="button" className="mt-2 rounded border px-3 py-2" onClick={onCancel}>Back</button></div>;
  }
  const needsCoefficient = pick?.kind === "use-in-rule" || pick?.kind === "use-in-objective";
  const submit = () => {
    if (!pick) return;
    const c = Number(coefficient);
    const connection: Connection =
      pick.kind === "index" ? { kind: "index", set: source.name, variable: pick.target.name }
        : pick.kind === "for-each" ? { kind: "for-each", set: source.name, rule: pick.target.name }
          : pick.kind === "use-in-rule" ? { kind: "use-in-rule", source, rule: pick.target.name, coefficient: c }
            : { kind: "use-in-objective", variable: source.name, coefficient: c };
    try {
      connect(draft, connection);
      onEdit((current) => connect(current, connection), `Connected: ${pick.says}.`);
      onCancel();
    } catch (error) {
      setProblem((error as Error).message);
    }
  };
  return (
    <form onSubmit={(event) => { event.preventDefault(); submit(); }} className="space-y-2">
      <label className="block">
        <span className="block text-xs text-slate-600">Connect {source.name} to</span>
        <select autoFocus value={chosen} onChange={(event) => { setChosen(event.target.value); setProblem(null); }}
          className="rounded border border-slate-300 px-2 py-1">
          {targets.map(({ target }) => <option key={target.nodeId} value={target.nodeId}>{KIND[target.part]} {target.name}</option>)}
        </select>
      </label>
      {pick && <p className="text-slate-600">{pick.says}.</p>}
      {needsCoefficient && (
        <label className="block"><span className="block text-xs text-slate-600">Coefficient</span>
          <input value={coefficient} onChange={(event) => setCoefficient(event.target.value)} inputMode="decimal"
            className="w-24 rounded border border-slate-300 px-2 py-1" /></label>
      )}
      <Problem text={problem} />
      <div className="flex gap-2">
        <button type="submit" className="rounded bg-blue-600 px-3 py-2 text-white">Connect</button>
        <button type="button" className="rounded border px-3 py-2" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}

function DeleteForm({ draft, target, onEdit, onCancel }: {
  draft: FormDraft; target: GraphPart; onEdit: (edit: GraphEdit, done: string) => void; onCancel: () => void;
}) {
  const plan = planDeletion(draft, target);
  if (plan.refused) {
    return <div><p role="alert" className="text-red-700">{plan.refused}</p>
      <button type="button" autoFocus className="mt-2 rounded border px-3 py-2" onClick={onCancel}>Back</button></div>;
  }
  return (
    <div className="space-y-2">
      <p>Delete {target.part === "objective" ? "the goal" : `${KIND[target.part].toLowerCase()} ${target.name}`}?</p>
      {plan.removes.length > 0 && <p>These go with it, since they cannot stand without it: {plan.removes.join(", ")}.</p>}
      {plan.trims.length > 0 && <p>These stay, losing only the part that reads it: {plan.trims.join(", ")}.</p>}
      {plan.removes.length === 0 && plan.trims.length === 0 && <p>Nothing else uses it; nothing else changes.</p>}
      <div className="flex gap-2">
        <button type="button" autoFocus className="rounded bg-red-700 px-3 py-2 text-white"
          onClick={() => { onEdit((current) => applyDeletion(current, target), `Deleted ${target.name}.`); onCancel(); }}>Delete</button>
        <button type="button" className="rounded border px-3 py-2" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}
