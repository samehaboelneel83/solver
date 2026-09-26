import { useMemo, useState } from "react";
import { formatApiError } from "../api/errors";
import {
  useAskWhyNot,
  useCreateRun,
  useCreateScenario,
  useProbe,
  useScenario,
  type Id,
  type Run,
  type Verdict,
  type WhyNotCell,
} from "../api/v1";
import { formatAmount } from "../lib/runViews";

/**
 * The planner's tools on an answered plan (queue R28): hold part of it and solve the rest again
 * (R24 locks, R25 staying close), ask why a cell is not otherwise (R26), and -- on a linear
 * model -- how far each number may move before the plan changes (R27).
 */
export default function PlannerPanel({ run, onOpen }: { run: Run; onOpen?: (id: Id) => void }) {
  const decisions = Object.keys(run.index_sets.variables).filter((v) => (run.index_sets.variables[v] ?? []).length > 0
    && (run.variable_kinds?.[v] ?? "binary") !== "interval");
  if (run.purpose && run.purpose !== "plan") return null;
  if (run.status !== "optimal" && run.status !== "feasible") return null;
  return (
    <section aria-label="Plan again or ask" className="mt-6 space-y-4 rounded-md border border-slate-200 bg-slate-50 p-4">
      <h3 className="text-sm font-semibold text-slate-900">Plan again, or ask why</h3>
      {decisions.length > 0 && <LockAndResolve run={run} decisions={decisions} onOpen={onOpen} />}
      {decisions.length > 0 && <WhyNot run={run} decisions={decisions} />}
      <Sensitivity run={run} />
    </section>
  );
}

function members(run: Run, set: string): string[] {
  return run.set_order?.[set] ?? Object.keys(run.labels[set] ?? {});
}

function label(run: Run, set: string, key: string): string {
  return run.labels[set]?.[key] ?? key;
}

function LockAndResolve({ run, decisions, onOpen }: { run: Run; decisions: string[]; onOpen?: (id: Id) => void }) {
  const scenario = useScenario(run.scenario_id);
  const createScenario = useCreateScenario();
  const createRun = useCreateRun();
  const [variable, setVariable] = useState(decisions[0]);
  const sets = run.index_sets.variables[variable] ?? [];
  const [set, setSet] = useState(sets[0]);
  const [held, setHeld] = useState<Set<string>>(new Set());
  const [close, setClose] = useState(true);
  const [failure, setFailure] = useState<string | null>(null);
  const busy = createScenario.isPending || createRun.isPending;
  const chosenSet = sets.includes(set) ? set : sets[0];

  function toggle(key: string) {
    const next = new Set(held);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setHeld(next);
  }

  function resolve() {
    if (!scenario.data) return;
    setFailure(null);
    const base = scenario.data.patch ?? {};
    const patch = {
      ...base,
      lock: [...(base.lock ?? []), { var: variable, where: { [chosenSet]: [...held] }, from_run: Number(run.id) }],
      ...(close ? { stay_close: { from_run: Number(run.id), mode: "lex" as const } } : {}),
    };
    const kept = [...held].map((k) => label(run, chosenSet, k)).join(", ");
    createScenario.mutate(
      {
        problem_id: scenario.data.problem_id,
        model_version_id: scenario.data.model_version_id,
        name: `run ${run.id} again, ${variable} kept for ${kept} (${new Date().toISOString().slice(0, 19)})`,
        patch,
      },
      {
        onSuccess: (made) =>
          createRun.mutate(
            { scenarioId: made.id, body: { reuse: false } },
            { onSuccess: (queued) => onOpen?.(queued.id), onError: (error) => setFailure(formatApiError(error)) },
          ),
        onError: (error) => setFailure(formatApiError(error)),
      },
    );
  }

  return (
    <div>
      <h4 className="mb-1 text-sm font-medium text-slate-800">Keep part of this plan, solve the rest again</h4>
      <p className="mb-2 text-xs text-slate-600">
        What you keep is held exactly as this run has it -- who is on and who is off. The rest is solved again on
        today&rsquo;s data{close ? ", moving as little as the rules allow" : ""}.
      </p>
      <div className="flex flex-wrap items-end gap-3 text-sm">
        <label className="flex flex-col text-slate-700">
          Decision
          <select value={variable} onChange={(e) => { setVariable(e.target.value); setHeld(new Set()); setSet((run.index_sets.variables[e.target.value] ?? [])[0]); }}
                  className="mt-1 rounded-md border border-slate-300 px-2 py-1">
            {decisions.map((v) => <option key={v} value={v}>{v}</option>)}
          </select>
        </label>
        <label className="flex flex-col text-slate-700">
          Keep it for
          <select value={chosenSet} onChange={(e) => { setSet(e.target.value); setHeld(new Set()); }}
                  className="mt-1 rounded-md border border-slate-300 px-2 py-1">
            {[...new Set(sets)].map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
      </div>
      <fieldset className="mt-2">
        <legend className="sr-only">Which {chosenSet} to keep</legend>
        <div className="flex max-h-32 flex-wrap gap-2 overflow-y-auto">
          {members(run, chosenSet).map((key) => (
            <label key={key} className="flex items-center gap-1 text-xs text-slate-800">
              <input type="checkbox" checked={held.has(key)} onChange={() => toggle(key)} />
              {label(run, chosenSet, key)}
            </label>
          ))}
        </div>
      </fieldset>
      <label className="mt-2 flex items-center gap-1 text-xs text-slate-700">
        <input type="checkbox" checked={close} onChange={() => setClose(!close)} />
        Stay close to this plan (the cheapest plan first, then the fewest changes)
      </label>
      {failure && <p role="alert" className="mt-2 text-sm text-red-700">{failure}</p>}
      <button type="button" onClick={resolve} disabled={busy || held.size === 0 || !scenario.data}
              className="mt-2 rounded-md bg-blue-700 px-3 py-1.5 text-sm text-white disabled:opacity-60">
        {busy ? "Starting…" : `Keep ${held.size || "…"} and solve the rest`}
      </button>
    </div>
  );
}

function WhyNot({ run, decisions }: { run: Run; decisions: string[] }) {
  const binaries = decisions.filter((v) => (run.variable_kinds?.[v] ?? "binary") === "binary");
  const ask = useAskWhyNot();
  const [variable, setVariable] = useState(binaries[0] ?? "");
  const sets = run.index_sets.variables[variable] ?? [];
  const [cell, setCell] = useState<string[]>([]);
  const [probe, setProbe] = useState<number | null>(null);
  const [answer, setAnswer] = useState<Verdict | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const index = sets.map((s, p) => cell[p] ?? members(run, s)[0] ?? "");
  const chosen = useMemo(() => new Set((run.assignments?.[variable] ?? []).map((c) => c.join("\u0001"))), [run.assignments, variable]);
  const isOn = chosen.has(index.join("\u0001"));
  if (binaries.length === 0) return null;

  function submit() {
    setFailure(null);
    setAnswer(null);
    setProbe(null);
    const force: WhyNotCell[] = [{ var: variable, index, value: isOn ? 0 : 1 }];
    ask.mutate({ runId: run.id, force }, {
      onSuccess: (got) => (got.run_id !== null ? setProbe(got.run_id) : setAnswer(got.verdict)),
      onError: (error) => setFailure(formatApiError(error)),
    });
  }

  const name = index.map((k, p) => label(run, sets[p], k)).join(" · ");
  return (
    <div>
      <h4 className="mb-1 text-sm font-medium text-slate-800">Why not?</h4>
      <div className="flex flex-wrap items-end gap-3 text-sm">
        <label className="flex flex-col text-slate-700">
          Decision
          <select value={variable} onChange={(e) => { setVariable(e.target.value); setCell([]); }} className="mt-1 rounded-md border border-slate-300 px-2 py-1">
            {binaries.map((v) => <option key={v} value={v}>{v}</option>)}
          </select>
        </label>
        {sets.map((s, p) => (
          <label key={`${s}-${p}`} className="flex flex-col text-slate-700">
            {s}
            <select value={index[p]} onChange={(e) => { const next = [...index]; next[p] = e.target.value; setCell(next); }}
                    className="mt-1 rounded-md border border-slate-300 px-2 py-1">
              {members(run, s).map((k) => <option key={k} value={k}>{label(run, s, k)}</option>)}
            </select>
          </label>
        ))}
        <button type="button" onClick={submit} disabled={ask.isPending || index.some((k) => !k)}
                className="rounded-md border border-blue-700 bg-white px-3 py-1.5 text-sm text-blue-800 disabled:opacity-60">
          {isOn ? `Why is ${name} on?` : `Why isn't ${name} on?`}
        </button>
      </div>
      {failure && <p role="alert" className="mt-2 text-sm text-red-700">{failure}</p>}
      {probe !== null && <Probe id={probe} run={run} />}
      {answer && <VerdictText verdict={answer} run={run} />}
    </div>
  );
}

function Probe({ id, run }: { id: number; run: Run }) {
  const probe = useProbe(id);
  if (!probe.data?.verdict) return <p role="status" className="mt-2 text-sm text-slate-600">Solving the question (run {id})…</p>;
  return <VerdictText verdict={probe.data.verdict} run={run} />;
}

function cellText(run: Run, cell: string[]): string {
  const [variable, ...index] = cell;
  const sets = run.index_sets.variables[variable] ?? [];
  return `${variable} · ${index.map((k, p) => label(run, sets[p], k)).join(" · ")}`;
}

export function VerdictText({ verdict, run }: { verdict: Verdict; run: Run }) {
  const box = "mt-2 rounded-md border p-3 text-sm";
  if (verdict.kind === "already") return <p role="status" className={`${box} border-slate-200 bg-white`}>The plan already has it that way.</p>;
  if (verdict.kind === "unanswered")
    return (
      <p role="status" className={`${box} border-amber-300 bg-amber-50`}>
        No answer: the question ended {verdict.status}{verdict.error ? ` (${verdict.error})` : ""}. Nothing is claimed either way.
      </p>
    );
  if (verdict.kind === "blocked") {
    const rules = [...new Set((verdict.conflict ?? []).map((c) => c.constraint_id))];
    return (
      <div role="status" className={`${box} border-red-300 bg-red-50`}>
        <p className="font-medium text-red-900">No plan allows it{verdict.minimal === false ? " (these may be more rules than it takes)" : ""}. It is blocked by:</p>
        <ul className="mt-1 list-disc pl-5">
          {rules.map((r) => (
            <li key={r}>
              {verdict.forced.includes(r) ? "what you asked" : run.rule_notes?.[r] ? `${run.rule_notes[r]} (${r})` : r}
            </li>
          ))}
        </ul>
      </div>
    );
  }
  const cost = verdict.delta === null ? "" : verdict.delta === 0 ? "at no extra cost" : `for ${verdict.delta > 0 ? "+" : ""}${formatAmount(verdict.delta)} on the goal`;
  return (
    <div role="status" className={`${box} border-green-300 bg-green-50`}>
      <p className="font-medium text-green-900">
        Possible, {cost}{verdict.proven ? "" : " (the best found, not proven)"} -- the closest plan moves {verdict.change ?? "?"} cell{verdict.change === 1 ? "" : "s"}.
      </p>
      {verdict.turned_on.length > 0 && <p className="mt-1 text-xs">On: {verdict.turned_on.map((c) => cellText(run, c)).join("; ")}</p>}
      {verdict.turned_off.length > 0 && <p className="mt-1 text-xs">Off: {verdict.turned_off.map((c) => cellText(run, c)).join("; ")}</p>}
    </div>
  );
}

function Sensitivity({ run }: { run: Run }) {
  if (!run.ranges) {
    if (run.status !== "optimal") return null;
    return (
      <p className="text-xs text-slate-600">
        How far each number may move is exact only for linear models with no whole-number decisions; for this one, ask
        &ldquo;why not?&rdquo; instead.
      </p>
    );
  }
  const end = (v: number | null) => (v === null ? "no limit" : formatAmount(v));
  return (
    <div>
      <h4 className="mb-1 text-sm font-medium text-slate-800">How far each number may move</h4>
      {run.ranges.rows.length > 0 && (
        <table className="mb-2 text-xs">
          <caption className="sr-only">Binding limits</caption>
          <thead><tr className="text-left text-slate-600"><th className="pr-3">Rule</th><th className="pr-3">Limit</th><th className="pr-3">One more unit is worth</th><th>Exact from … to</th></tr></thead>
          <tbody>
            {run.ranges.rows.map((r) => (
              <tr key={`${r.rule}-${Object.values(r.index).join(",")}`}>
                <td className="pr-3">{run.rule_notes?.[r.rule] ?? r.rule}</td>
                <td className="pr-3">{r.rhs === null ? "—" : formatAmount(r.rhs)}</td>
                <td className="pr-3">{formatAmount(r.dual)}</td>
                <td>{end(r.low)} … {end(r.high)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {run.ranges.costs.length > 0 && (
        <table className="text-xs">
          <caption className="sr-only">Costs</caption>
          <thead><tr className="text-left text-slate-600"><th className="pr-3">Decision</th><th className="pr-3">Cost</th><th>The plan stays while the cost is in</th></tr></thead>
          <tbody>
            {run.ranges.costs.map((c) => (
              <tr key={`${c.var}-${c.index.join(",")}`}>
                <td className="pr-3">{cellText(run, [c.var, ...c.index])}</td>
                <td className="pr-3">{c.cost === null ? "—" : formatAmount(c.cost)}</td>
                <td>{end(c.low)} … {end(c.high)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
