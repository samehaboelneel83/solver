import { useId } from "react";
import { describeJoin, joinBody, joinChoices, type Constraint, type JoinBody, type ModelContext } from "./terms";

/**
 * A join rule (IR version 2, network design): the links built -- a yes-or-no decision per link -- join the places
 * into one network, or each place to a source; with "use", only the places a decision chooses. Only admissible
 * choices are offered: a yes-or-no decision over the links, two relationships from the links to the places (the
 * ends), a yes-or-no decision over the places, and the places' 0/1 fields as sources. Always required.
 */
export default function JoinEditor({
  constraint,
  context,
  onChange,
}: {
  constraint: Constraint;
  context: ModelContext;
  onChange: (next: Constraint) => void;
}) {
  const buildId = useId();
  const endAId = useId();
  const endBId = useId();
  const useId_ = useId();
  const sourcesId = useId();
  const body = constraint.join as JoinBody;
  const choices = joinChoices(context);
  const chosen = choices.find((c) => c.build === body.build.var && c.places === body.places.set);
  const ends = chosen?.ends ?? [];
  const sourceFields = (context.attributes[body.places.set] ?? [])
    .filter((a) => ["integer", "number", "boolean"].includes(a.data_type)).map((a) => a.name);

  function write(next: JoinBody) {
    const { severity: _s, weight: _w, when: _when, chance: _c, ...rest } = constraint;
    onChange({ ...rest, join: next, severity: "hard" });
  }

  const endSelect = (id: string, at: 0 | 1, label: string) => (
    <div>
      <label htmlFor={id} className="block text-xs text-slate-600">{label}</label>
      <select id={id} className="rounded border px-2 py-1" value={body.ends[at] ?? ""}
        onChange={(event) => {
          const next = [...body.ends];
          next[at] = event.target.value;
          write({ ...body, ends: next });
        }}>
        {!ends.includes(body.ends[at]) && <option value={body.ends[at] ?? ""}>{body.ends[at] || "choose"}</option>}
        {ends.map((name) => <option key={name} value={name}>{name}</option>)}
      </select>
    </div>
  );

  return (
    <div className="space-y-2 px-2 text-sm">
      <p className="font-mono text-xs text-slate-500">{describeJoin(constraint)}</p>
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label htmlFor={buildId} className="block text-xs text-slate-600">Links built</label>
          <select id={buildId} className="rounded border px-2 py-1" value={`${body.build.var}|${body.places.set}`}
            onChange={(event) => {
              const next = choices.find((c) => `${c.build}|${c.places}` === event.target.value);
              if (next) write(joinBody(next));
            }}>
            {!chosen && <option value={`${body.build.var}|${body.places.set}`}>{body.build.var} (no two relationships to {body.places.set})</option>}
            {choices.map((c) => (
              <option key={`${c.build}|${c.places}`} value={`${c.build}|${c.places}`}>
                {c.build} ({c.links} joining {c.places})
              </option>
            ))}
          </select>
        </div>
        {endSelect(endAId, 0, "One end along")}
        {endSelect(endBId, 1, "The other end along")}
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label htmlFor={useId_} className="block text-xs text-slate-600">Places to join</label>
          <select id={useId_} className="rounded border px-2 py-1" value={body.use?.var ?? ""}
            onChange={(event) => {
              const { use: _old, ...rest } = body;
              write(event.target.value ? { ...rest, use: { var: event.target.value, index: [body.places.index] } } : rest);
            }}>
            <option value="">every {body.places.set}</option>
            {(chosen?.uses ?? []).map((name) => <option key={name} value={name}>the {body.places.set} with {name} = 1</option>)}
          </select>
        </div>
        <div>
          <label htmlFor={sourcesId} className="block text-xs text-slate-600">Joined to (sources)</label>
          <select id={sourcesId} className="rounded border px-2 py-1"
            value={typeof body.sources === "string" ? body.sources : body.sources ? "(filters)" : ""}
            onChange={(event) => {
              const { sources: _old, ...rest } = body;
              if (!event.target.value) write(rest);
              else if (event.target.value !== "(filters)") write({ ...rest, sources: event.target.value });
            }}>
            <option value="">each other: one network</option>
            {Array.isArray(body.sources) && <option value="(filters)">fixed filters (edit in Exact IR)</option>}
            {sourceFields.map((name) => <option key={name} value={name}>a {body.places.set} whose {name} is 1</option>)}
          </select>
        </div>
      </div>
      <p className="text-xs text-slate-500">
        A join rule is always required. With every {body.places.set || "place"} joined and a goal that only adds up the
        links' costs, it is solved exactly as a minimum spanning tree (or forest, with sources); otherwise that tree is
        the solver's start.
      </p>
    </div>
  );
}
