import { useId } from "react";
import { describeRoute, routeBody, routeChoices, type Constraint, type ModelContext, type RouteBody } from "./terms";

/**
 * A route rule (IR version 2, queue R15b): every stop but the depot visited
 * once, each vehicle leaving the depot at most once and coming back, and --
 * with a load named -- no vehicle carrying more than its capacity. Only a
 * yes-or-no decision over [vehicles, stops, stops] is offered. Always
 * required: a stop half visited has no price.
 */
export default function RouteEditor({
  constraint,
  context,
  onChange,
}: {
  constraint: Constraint;
  context: ModelContext;
  onChange: (next: Constraint) => void;
}) {
  const variableId = useId();
  const depotId = useId();
  const demandId = useId();
  const capacityId = useId();
  const travelId = useId();
  const earliestId = useId();
  const latestId = useId();
  const serviceId = useId();
  const body = constraint.route as RouteBody;
  const choices = routeChoices(context);
  const chosen = choices.find((c) => c.variable === body.visit.var);
  const numbers = (set: string) =>
    (context.attributes[set] ?? []).filter((a) => a.data_type === "integer" || a.data_type === "number").map((a) => a.name);
  const stopNumbers = numbers(body.stops.set);
  const vehicleNumbers = numbers(body.vehicles.set);
  // Fields of a vehicle that can name its own depot: text, a choice, or a link (several depots).
  const vehicleFields = (context.attributes[body.vehicles.set] ?? [])
    .filter((a) => ["text", "enum", "reference"].includes(a.data_type)).map((a) => a.name);
  const loaded = body.demand !== undefined && body.capacity !== undefined;
  // Queue R15c: the parameters that can be a travel time -- over [stop, stop].
  const travels = Object.entries(context.parameters)
    .filter(([, p]) => p.index.length === 2 && p.index[0] === body.stops.set && p.index[1] === body.stops.set)
    .map(([name]) => name);
  const timed = body.travel !== undefined;
  const timing = { travel: body.travel, earliest: body.earliest, latest: body.latest, service: body.service };
  const keep = Object.fromEntries(Object.entries(timing).filter(([, v]) => v !== undefined));

  function write(next: RouteBody) {
    const { severity: _s, weight: _w, when: _when, ...rest } = constraint;
    onChange({ ...rest, route: next, severity: "hard" });
  }

  return (
    <div className="space-y-2 px-2 text-sm">
      <p className="font-mono text-xs text-slate-500">{describeRoute(constraint)}</p>
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label htmlFor={variableId} className="block text-xs text-slate-600">
            Visits
          </label>
          <select
            id={variableId}
            className="rounded border px-2 py-1"
            value={body.visit.var}
            onChange={(event) => {
              const next = choices.find((c) => c.variable === event.target.value);
              if (next)
                write({ ...routeBody(next, body.depot ?? "depot", loaded ? { demand: body.demand!, capacity: body.capacity! } : undefined), ...keep });
            }}
          >
            {!chosen && <option value={body.visit.var}>{body.visit.var} (not a yes-or-no over vehicle × stop × stop)</option>}
            {choices.map((c) => (
              <option key={c.variable} value={c.variable}>
                {c.variable} ({c.vehicles} × {c.stops} × {c.stops})
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs text-slate-600">
            <select aria-label="Where vehicles start" className="rounded border px-1 py-0.5 text-xs" value={body.depot_of !== undefined ? "own" : "one"}
              onChange={(event) => {
                const { depot: _d, depot_of: _o, ...rest } = body;
                write(event.target.value === "own" ? { ...rest, depot_of: vehicleFields[0] ?? "depot" } : { ...rest, depot: "depot" });
              }}>
              <option value="one">One depot for all</option>
              <option value="own">Each {body.vehicles.set || "vehicle"} from its own</option>
            </select>
          </label>
          {body.depot_of !== undefined ? (
            <select id={depotId} aria-label={`The ${body.vehicles.set || "vehicle"} field naming its depot`} className="rounded border px-2 py-1"
              value={body.depot_of} onChange={(event) => write({ ...body, depot_of: event.target.value })}>
              {!vehicleFields.includes(body.depot_of) && <option value={body.depot_of}>{body.depot_of}</option>}
              {vehicleFields.map((f) => <option key={f} value={f}>{f}</option>)}
            </select>
          ) : (
            <input id={depotId} aria-label={`Depot (${body.stops.set || "stop"} key)`} className="rounded border px-2 py-1" value={body.depot ?? ""}
                   onChange={(event) => write({ ...body, depot: event.target.value })} />
          )}
        </div>
      </div>
      <label className="flex items-center gap-2">
        <input
          type="checkbox"
          checked={loaded}
          disabled={!loaded && (stopNumbers.length === 0 || vehicleNumbers.length === 0)}
          onChange={(event) => {
            const { demand: _d, capacity: _c, ...plain } = body;
            write(event.target.checked ? { ...plain, demand: stopNumbers[0], capacity: vehicleNumbers[0] } : plain);
          }}
        />
        Each {body.vehicles.set || "vehicle"} carries a load
        {!loaded && (stopNumbers.length === 0 || vehicleNumbers.length === 0) && (
          <span className="text-xs text-slate-500">
            (needs a number on {body.stops.set || "stops"} and on {body.vehicles.set || "vehicles"})
          </span>
        )}
      </label>
      {loaded && (
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label htmlFor={demandId} className="block text-xs text-slate-600">
              Each {body.stops.set || "stop"} takes
            </label>
            <select id={demandId} className="rounded border px-2 py-1" value={body.demand}
                    onChange={(event) => write({ ...body, demand: event.target.value })}>
              {!stopNumbers.includes(body.demand!) && <option value={body.demand}>{body.demand}</option>}
              {stopNumbers.map((name) => <option key={name} value={name}>{name}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor={capacityId} className="block text-xs text-slate-600">
              Within each {body.vehicles.set || "vehicle"}&apos;s
            </label>
            <select id={capacityId} className="rounded border px-2 py-1" value={body.capacity}
                    onChange={(event) => write({ ...body, capacity: event.target.value })}>
              {!vehicleNumbers.includes(body.capacity!) && <option value={body.capacity}>{body.capacity}</option>}
              {vehicleNumbers.map((name) => <option key={name} value={name}>{name}</option>)}
            </select>
          </div>
        </div>
      )}
      <label className="flex items-center gap-2">
        <input
          type="checkbox"
          checked={timed}
          disabled={!timed && travels.length === 0}
          onChange={(event) => {
            const { travel: _t, earliest: _e, latest: _l, service: _s, ...plain } = body;
            write(event.target.checked
              ? { ...plain, travel: travels[0], ...(stopNumbers.length ? { earliest: stopNumbers[0], latest: stopNumbers[stopNumbers.length > 1 ? 1 : 0] } : {}) }
              : plain);
          }}
        />
        Each {body.stops.set || "stop"} has a time window
        {!timed && travels.length === 0 && (
          <span className="text-xs text-slate-500">
            (needs a data table over [{body.stops.set || "stop"}, {body.stops.set || "stop"}] for the travel time)
          </span>
        )}
      </label>
      {timed && (
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label htmlFor={travelId} className="block text-xs text-slate-600">Travel time</label>
            <select id={travelId} className="rounded border px-2 py-1" value={body.travel}
                    onChange={(event) => write({ ...body, travel: event.target.value })}>
              {!travels.includes(body.travel!) && <option value={body.travel}>{body.travel}</option>}
              {travels.map((name) => <option key={name} value={name}>{name}</option>)}
            </select>
          </div>
          {([["earliest", earliestId, "Open from"], ["latest", latestId, "Open until"], ["service", serviceId, "Time spent there"]] as const).map(
            ([key, id, label]) => (
              <div key={key}>
                <label htmlFor={id} className="block text-xs text-slate-600">{label}</label>
                <select id={id} className="rounded border px-2 py-1" value={body[key] ?? ""}
                        onChange={(event) => {
                          const { [key]: _old, ...rest } = body;
                          write(event.target.value ? { ...rest, [key]: event.target.value } : rest);
                        }}>
                  <option value="">{key === "service" ? "nothing" : key === "earliest" ? "0" : "any time"}</option>
                  {body[key] && !stopNumbers.includes(body[key]!) && <option value={body[key]}>{body[key]}</option>}
                  {stopNumbers.map((name) => <option key={name} value={name}>{name}</option>)}
                </select>
              </div>
            )
          )}
        </div>
      )}
      <p className="text-xs text-slate-500">
        A route rule is always required: a {body.stops.set || "stop"} half visited is not a nearly-kept rule.
      </p>
    </div>
  );
}
