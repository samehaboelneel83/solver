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
  const sourcesId = useId();
  const body = constraint.connected as ConnectedBody;
  // A decision over the units alone is a choice only with sources: one network rooted at them.
  const choices = connectedChoices(context).filter((c) => c.groups || body.sources);
  // The units' 0/1 fields (whole-number or yes/no) may say which units are sources.
  const sourceFields = (context.attributes[body.units.set] ?? [])
    .filter((a) => ["integer", "number", "boolean"].includes(a.data_type)).map((a) => a.name);
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
              if (next) {
                const made = connectedBody(next, next.vias.includes(body.via) ? body.via : next.vias[0] ?? "", empty);
                write(body.sources ? { ...made, sources: body.sources } : made);
              }
            }}
          >
            {!chosen && <option value={body.assign.var}>{body.assign.var} (not a yes-or-no over two sets)</option>}
            {choices.map((c) => (
              <option key={c.variable} value={c.variable}>
                {c.variable} ({c.groups ? `${c.units} × ${c.groups}` : c.units})
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
      <div>
        <label htmlFor={sourcesId} className="block text-xs text-slate-600">
          Reached from (sources)
        </label>
        <select
          id={sourcesId}
          className="rounded border px-2 py-1"
          value={typeof body.sources === "string" ? body.sources : body.sources ? "(filters)" : ""}
          onChange={(event) => {
            const { sources: _old, ...rest } = body;
            if (!event.target.value) {
              // Without sources a rule needs its groups: back to the first choice that has them.
              if (rest.groups) write(rest);
              else {
                const grouped = connectedChoices(context).find((c) => c.groups && c.units === body.units.set) ?? connectedChoices(context).find((c) => c.groups);
                if (grouped) write(connectedBody(grouped, grouped.vias[0] ?? body.via, empty));
              }
            } else if (event.target.value !== "(filters)") write({ ...rest, sources: event.target.value });
          }}
        >
          <option value="">nowhere: each group is one piece</option>
          {Array.isArray(body.sources) && <option value="(filters)">fixed filters (edit in Exact IR)</option>}
          {sourceFields.map((name) => (
            <option key={name} value={name}>
              {body.units.set || "units"} whose {name} is 1
            </option>
          ))}
        </select>
        {!sourceFields.length && <p className="text-xs text-slate-500">
          Give {body.units.set || "the units"} a 0/1 field (doors, entrances, depots) to start networks from them.</p>}
      </div>
      <label className="flex items-center gap-2">
        <input
          type="checkbox"
          checked={empty === "allowed"}
          onChange={(event) => write({ ...body, empty: event.target.checked ? "allowed" : "forbidden" })}
        />
        A {body.groups?.set || "group"} may be left with no {body.units.set || "units"}
      </label>
      <p className="text-xs text-slate-500">
        A connected rule is always required: a {body.groups?.set || "group"} in two pieces is not a nearly-kept rule.
      </p>
    </div>
  );
}
