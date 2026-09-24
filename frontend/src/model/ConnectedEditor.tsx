import { useId } from "react";
import {
  connectedBody,
  connectedChoices,
  describeConnected,
  type ConnectedBody,
  type Constraint,
  type ModelContext,
} from "./terms";

/**
 * A connected rule (IR version 2): for every group, the units assigned to
 * it form one piece over a relationship -- a district is one contiguous
 * area. Only admissible choices are offered: a yes-or-no variable over
 * units then groups, and a relationship joining the units to themselves.
 * Always required: a piece that is half connected has no price.
 */
export default function ConnectedEditor({
  constraint,
  context,
  onChange,
}: {
  constraint: Constraint;
  context: ModelContext;
  onChange: (next: Constraint) => void;
}) {
  const variableId = useId();
  const viaId = useId();
  const body = constraint.connected as ConnectedBody;
  const choices = connectedChoices(context);
  const chosen = choices.find((c) => c.variable === body.assign.var);
  const empty = body.empty === "allowed" ? "allowed" : "forbidden";

  function write(next: ConnectedBody) {
    const { severity: _s, weight: _w, when: _when, ...rest } = constraint;
    onChange({ ...rest, connected: next, severity: "hard" });
  }

  return (
    <div className="space-y-2 px-2 text-sm">
      <p className="font-mono text-xs text-slate-500">{describeConnected(constraint)}</p>
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label htmlFor={variableId} className="block text-xs text-slate-600">
            Assignment
          </label>
          <select
            id={variableId}
            className="rounded border px-2 py-1"
            value={body.assign.var}
            onChange={(event) => {
              const next = choices.find((c) => c.variable === event.target.value);
              if (next) write(connectedBody(next, next.vias.includes(body.via) ? body.via : next.vias[0] ?? "", empty));
            }}
          >
            {!chosen && <option value={body.assign.var}>{body.assign.var} (not a yes-or-no over two sets)</option>}
            {choices.map((c) => (
              <option key={c.variable} value={c.variable}>
                {c.variable} ({c.units} × {c.groups})
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor={viaId} className="block text-xs text-slate-600">
            Connected over
          </label>
          <select
            id={viaId}
            className="rounded border px-2 py-1"
            value={body.via}
            onChange={(event) => write({ ...body, via: event.target.value })}
          >
            {!chosen?.vias.includes(body.via) && (
              <option value={body.via}>
                {chosen?.vias.length ? body.via || "choose" : `no relationship joins ${body.units.set || "the units"} to itself`}
              </option>
            )}
            {(chosen?.vias ?? []).map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </div>
      </div>
      <label className="flex items-center gap-2">
        <input
          type="checkbox"
          checked={empty === "allowed"}
          onChange={(event) => write({ ...body, empty: event.target.checked ? "allowed" : "forbidden" })}
        />
        A {body.groups.set || "group"} may be left with no {body.units.set || "units"}
      </label>
      <p className="text-xs text-slate-500">
        A connected rule is always required: a {body.groups.set || "group"} in two pieces is not a nearly-kept rule.
      </p>
    </div>
  );
}
