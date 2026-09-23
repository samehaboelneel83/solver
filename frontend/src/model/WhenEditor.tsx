import { useId } from "react";
import { ReferencePicker } from "./TermBuilder";
import type { Binding, ModelContext, When } from "./terms";

/**
 * A rule that holds only while a yes-or-no decision has a value (IR version
 * 2, `when`): "ship nothing from a site while it is closed". Only a required
 * rule takes one -- a preferred rule can already be broken at a cost -- and
 * the switch is read at indices the rule's own "for every" binds.
 */
export default function WhenEditor({
  when,
  soft,
  bound,
  context,
  onChange,
}: {
  when: When | undefined;
  soft: boolean;
  bound: Binding[];
  context: ModelContext;
  onChange: (next: When | undefined) => void;
}) {
  const toggleId = useId();
  const isId = useId();
  const switches = Object.keys(context.variables).filter((n) => context.variables[n].domain === "binary");

  return (
    <div className="px-2 py-1">
      <div className="flex items-center gap-2">
        <input
          id={toggleId}
          type="checkbox"
          checked={when !== undefined}
          disabled={soft || (when === undefined && switches.length === 0)}
          onChange={(event) => {
            if (!event.target.checked) {
              onChange(undefined);
              return;
            }
            const name = switches[0];
            const sets = context.variables[name].index;
            onChange({
              var: name,
              index: sets.map((set) => bound.find((b) => b.set === set)?.index ?? ""),
              is: 1,
            });
          }}
        />
        <label htmlFor={toggleId} className="text-xs text-slate-700">
          Only while a yes-or-no decision is set
        </label>
      </div>
      {soft && (
        <p className="mt-1 text-xs text-slate-500">
          A preferred rule can already be broken at a cost, so it takes no condition.
        </p>
      )}
      {!soft && when === undefined && switches.length === 0 && (
        <p className="mt-1 text-xs text-slate-500">Declare a yes-or-no variable to switch a rule with.</p>
      )}
      {when !== undefined && (
        <div className="mt-1 flex flex-wrap items-end gap-2">
          <ReferencePicker
            kind="var"
            label="Switch"
            value={{ var: when.var, index: when.index }}
            onChange={(next) => onChange({ ...when, var: next.var, index: next.index })}
            context={context}
            bound={bound}
            allow={(domain) => domain === "binary"}
          />
          <div>
            <label htmlFor={isId} className="block text-xs text-slate-600">
              is
            </label>
            <select
              id={isId}
              className="rounded border border-slate-300 px-2 py-1 text-xs"
              value={String(when.is ?? 1)}
              onChange={(event) => onChange({ ...when, is: event.target.value === "0" ? 0 : 1 })}
            >
              <option value="1">yes</option>
              <option value="0">no</option>
            </select>
          </div>
        </div>
      )}
    </div>
  );
}
