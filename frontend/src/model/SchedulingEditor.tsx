import { useId } from "react";
import TermBuilder, { BindingsEditor, ReferencePicker } from "./TermBuilder";
import {
  boundIndices,
  describeSchedule,
  seedForSet,
  type Binding,
  type Constraint,
  type ModelContext,
  type SchedulingBody,
  type Term,
} from "./terms";

type Kind = "no_overlap" | "cumulative";
type Cumulative = SchedulingBody & { demand: Term; capacity: Term };

/**
 * A scheduling rule (IR version 2): the intervals an `over` ranges across
 * either never run at once (`no_overlap`), or share a capacity -- at every
 * moment the demands of those running add up to no more than it
 * (`cumulative`). Once per instance of the rule's own "for every", like
 * any rule. Always required: a scheduling rule has no price for breaking.
 */
export default function SchedulingEditor({
  constraint,
  context,
  onChange,
}: {
  constraint: Constraint;
  context: ModelContext;
  onChange: (next: Constraint) => void;
}) {
  const kindId = useId();
  const kind: Kind = constraint.cumulative ? "cumulative" : "no_overlap";
  const body = (constraint[kind] ?? { interval: { var: "", index: [] }, over: [] }) as Cumulative;
  const forall = constraint.forall ?? [];
  const inner = boundIndices(forall, body.over);

  function withBody(next: SchedulingBody | Cumulative, as: Kind = kind): Constraint {
    const { no_overlap: _a, cumulative: _b, ...rest } = constraint;
    return { ...rest, [as]: next } as Constraint;
  }

  return (
    <div className="space-y-2 px-2 py-1">
      <p className="font-mono text-xs text-slate-500">
        {forall.length ? `for every ${forall.map((b) => `${b.index} in ${b.set}`).join(", ")}: ` : ""}
        {describeSchedule(constraint)}
      </p>
      <div>
        <label htmlFor={kindId} className="block text-xs text-slate-600">
          The intervals
        </label>
        <select
          id={kindId}
          className="rounded border border-slate-300 px-2 py-1 text-xs"
          value={kind}
          onChange={(event) => {
            const next = event.target.value as Kind;
            if (next === kind) return;
            const shared = { interval: body.interval, over: body.over };
            onChange(
              withBody(
                next === "cumulative" ? { ...shared, demand: { const: 1 }, capacity: { const: 1 } } : shared,
                next
              )
            );
          }}
        >
          <option value="no_overlap">never overlap</option>
          <option value="cumulative">share a capacity</option>
        </select>
      </div>

      <BindingsEditor
        bindings={forall}
        onChange={(next) => {
          if (next.length === 0) {
            const { forall: _dropped, ...rest } = constraint;
            onChange(rest);
            return;
          }
          onChange({ ...constraint, forall: next });
        }}
        context={context}
        outer={[]}
        legend="For every"
        minBindings={0}
      />
      <BindingsEditor
        bindings={body.over}
        onChange={(over) => onChange(withBody({ ...body, over }))}
        context={context}
        outer={forall}
        legend="Over"
        minBindings={1}
      />
      <ReferencePicker
        kind="var"
        label="Interval"
        value={body.interval}
        onChange={(interval) => onChange(withBody({ ...body, interval }))}
        context={context}
        bound={inner}
        allow={(domain) => domain === "interval"}
      />
      {kind === "cumulative" && (
        <>
          <TermBuilder
            value={body.demand}
            onChange={(demand) => onChange(withBody({ ...body, demand }))}
            context={context}
            bound={inner}
            label="Each takes"
          />
          <TermBuilder
            value={body.capacity}
            onChange={(capacity) => onChange(withBody({ ...body, capacity }))}
            context={context}
            bound={forall}
            label="Out of a capacity of"
          />
        </>
      )}
      <p className="text-xs text-slate-500">A scheduling rule is always required.</p>
    </div>
  );
}

/** A new `no_overlap` over the first interval: one binding per set it is
 * indexed by, so it names every one of them. Null with no interval yet. */
export function newSchedulingRule(id: string, context: ModelContext): Constraint | null {
  const intervals = Object.keys(context.variables).filter((n) => context.variables[n].domain === "interval");
  // An indexed one first: a rule over a single interval has nothing to keep apart.
  const name = intervals.find((n) => context.variables[n].index.length > 0) ?? intervals[0];
  if (name === undefined) return null;
  const over: Binding[] = [];
  for (const set of context.variables[name].index) {
    const seed = seedForSet(set);
    let index = seed;
    for (let n = 2; over.some((b) => b.index === index); n += 1) index = `${seed}${n}`;
    over.push({ index, set });
  }
  return {
    id,
    no_overlap: { interval: { var: name, index: over.map((b) => b.index) }, over },
    severity: "hard",
  } as Constraint;
}
