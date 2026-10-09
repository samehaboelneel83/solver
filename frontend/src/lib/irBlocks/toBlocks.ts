/**
 * An IR document as a Blockly workspace (serialisation JSON) -- one block per
 * construct, in the vocabulary of `vocabulary.ts`. `blocksToIr` (toIr.ts) is
 * the exact inverse; `roundTrip.test.ts` holds the two to that over every
 * fixture and template.
 *
 * Every construct of the contract has its own block. One the vocabulary does
 * not know -- a future construct, or a shape these blocks could not write
 * back exactly -- travels in an opaque block carrying it verbatim, so
 * nothing is lost and it is visibly not editable here.
 */
import { CONNECTED_KEYS, ROUTE_KEYS, SCHEDULING_KEYS } from "../../ir/contract";
import type { Binding, Term } from "../../model/terms";
import { cellText } from "./catalogue";

export type IrLoc = (string | number)[];

export type SerialBlock = {
  type: string;
  id?: string;
  x?: number;
  y?: number;
  fields?: Record<string, string>;
  inputs?: Record<string, { block: SerialBlock }>;
  next?: { block: SerialBlock };
  extraState?: unknown;
  movable?: boolean;
  deletable?: boolean;
  editable?: boolean;
};

export type Workspace = { blocks: { languageVersion: 0; blocks: SerialBlock[] } };

type Json = Record<string, unknown>;

const VARIABLE_KEYS = new Set(["index", "domain", "lower", "upper", "stage"]);
const INTERVAL_VARIABLE_KEYS = new Set(["index", "domain", "start", "end", "size", "presence"]);
const RULE_KEYS = new Set(["id", "note", "forall", "left", "relation", "right", "severity", "weight", "when", "chance"]);
/** The most terms an `add` block holds; a longer sum is carried opaque rather than nested (nesting would not round-trip). */
export const MAX_ADD_TERMS = 16;
/** The most points a curve block holds (`MAX_POINTS` in vocabulary.ts). */
const MAX_CURVE_POINTS = 12;
/** The inputs a `predict` block holds: a predictor takes 1 to 32 (the contract). */
const MAX_PREDICT_INPUTS = 32;

const isObject = (v: unknown): v is Json => typeof v === "object" && v !== null && !Array.isArray(v);
/** `value` is an object whose keys are exactly `keys` (the optional ones may be missing). */
function shaped(value: unknown, keys: readonly string[], optional: readonly string[] = []): value is Json {
  if (!isObject(value)) return false;
  const present = Object.keys(value);
  return present.every((k) => keys.includes(k) || optional.includes(k)) && keys.every((k) => k in value);
}
const isName = (v: unknown): v is string => typeof v === "string";
const isIndex = (v: unknown): v is string[] => Array.isArray(v) && v.every(isName);
/** `{var, index}`: a reference to one cell of a decision. */
const isRef = (v: unknown): v is { var: string; index: string[] } => shaped(v, ["var", "index"]) && isName(v.var) && isIndex(v.index);
const refFields = (ref: { index: string[] }) => Object.fromEntries(ref.index.map((idx, i) => [`IDX${i}`, idx]));

/** Link blocks into a stack: each one's `next` is the one after it. */
export function stack(blocks: SerialBlock[]): { block: SerialBlock } | undefined {
  let next: { block: SerialBlock } | undefined;
  for (let i = blocks.length - 1; i >= 0; i -= 1) next = { block: next ? { ...blocks[i], next } : blocks[i] };
  return next;
}

/** Only the inputs that hold something. */
function inputs(entries: Record<string, { block: SerialBlock } | undefined>): Record<string, { block: SerialBlock }> {
  return Object.fromEntries(Object.entries(entries).filter(([, v]) => v !== undefined)) as Record<string, { block: SerialBlock }>;
}

export function irToBlocks(
  irInput: Json | null | undefined,
  options: { editable?: boolean; title?: string; ids?: (loc: IrLoc) => string | undefined } = {}
): Workspace {
  const ir = (irInput ?? {}) as Json;
  let counter = 0;
  const block = (loc: IrLoc | null, spec: Omit<SerialBlock, "id">): SerialBlock => {
    const id = (loc && options.ids?.(loc)) || `b${counter++}`;
    const made: SerialBlock = { ...spec, id };
    return options.editable === false ? { ...made, movable: false, deletable: false, editable: false } : made;
  };

  const opaque = (kind: "declaration" | "rule" | "term", loc: IrLoc, json: unknown, label: string) =>
    block(loc, { type: `ir_opaque_${kind}`, fields: { LABEL: label }, extraState: { json } });

  /** A `where` list as a stack: a filter block each, and an "any of" block for a group. */
  function filters(list: unknown[], loc: IrLoc): { block: SerialBlock } | undefined {
    return stack(
      (list as Json[]).map((f, k): SerialBlock =>
        "any" in f
          ? block([...loc, k], {
              type: "ir_filter_any",
              inputs: inputs({ ANY: filters(f.any as unknown[], [...loc, k, "any"]) }),
            })
          : "index" in f
            ? block([...loc, k], { type: "ir_filter_index", fields: { INDEX: String(f.index), OP: String(f.op) } })
            : block([...loc, k], { type: "ir_filter", fields: { ATTR: String(f.attr), OP: String(f.op), VALUE: JSON.stringify(f.value) } })
      )
    );
  }

  function binding(b: Binding, loc: IrLoc): SerialBlock {
    const via = b.via as
      | { rel: string; from?: string; to?: string; both?: string; depth?: string; steps?: { min: number; max?: number }; where?: unknown[]; on?: string; as?: string }
      | undefined;
    return block(loc, {
      type: "ir_binding",
      fields: {
        INDEX: b.index,
        SET: b.set,
        VIA_REL: via?.rel ?? "",
        VIA_END: via?.to !== undefined ? "to" : via?.both !== undefined ? "both" : "from",
        VIA_ANCHOR: via?.from ?? via?.to ?? via?.both ?? "",
        VIA_DEPTH: via?.depth ?? "",
        VIA_MIN: via?.steps ? String(via.steps.min) : "",
        VIA_MAX: via?.steps?.max !== undefined ? String(via.steps.max) : "",
        VIA_ON: via?.on ?? "",
        VIA_AS: via?.as ?? "",
      },
      inputs: inputs({
        VIA_WHERE: filters(via?.where ?? [], [...loc, "via", "where"]),
        WHERE: filters(b.where ?? [], [...loc, "where"]),
      }),
    });
  }

  const bindings = (list: Binding[] | undefined, loc: IrLoc) => stack((list ?? []).map((b, j) => binding(b, [...loc, j])));

  function term(t: Term | undefined, loc: IrLoc): SerialBlock | undefined {
    if (t === undefined || t === null) return undefined;
    const x = t as Json;
    if ("const" in x) return block(loc, { type: "ir_const", fields: { VALUE: x.const === null ? "" : String(x.const) } });
    if ("var" in x || "par" in x) {
      const kind = "var" in x ? "var" : "par";
      // A cell of an entity-valued parameter (queue R20b) is written into its slot as text.
      const index = ((x.index as unknown[]) ?? []).map(cellText);
      return block(loc, {
        type: `ir_${kind}`,
        fields: { NAME: String(x[kind]), ...Object.fromEntries(index.map((idx, i) => [`IDX${i}`, idx])) },
        extraState: { arity: index.length },
      });
    }
    if ("attr" in x) {
      const attr = x.attr as { of: string; name: string; along?: string };
      return block(loc, { type: "ir_attr", fields: { OF: attr.of, NAME: attr.name, ALONG: attr.along ?? "" } });
    }
    if ("sum" in x) {
      return block(loc, {
        type: "ir_sum",
        inputs: inputs({ OVER: bindings(x.over as Binding[], [...loc, "over"]), BODY: wrap(term(x.sum as Term, [...loc, "sum"])) }),
      });
    }
    if ("mul" in x) {
      const [a, b] = x.mul as [Term, Term];
      return block(loc, {
        type: "ir_mul",
        inputs: inputs({ A: wrap(term(a, [...loc, "mul", 0])), B: wrap(term(b, [...loc, "mul", 1])) }),
      });
    }
    if ("add" in x && (x.add as Term[]).length >= 2 && (x.add as Term[]).length <= MAX_ADD_TERMS) {
      const parts = x.add as Term[];
      return block(loc, {
        type: "ir_add",
        fields: { COUNT: String(parts.length) },
        extraState: { count: parts.length },
        inputs: inputs(Object.fromEntries(parts.map((p, k) => [`T${k}`, wrap(term(p, [...loc, "add", k]))]))),
      });
    }
    if (shaped(x, ["pwl", "points"]) && isRef(x.pwl) && Array.isArray(x.points)) {
      const points = x.points as unknown[];
      const pairs = points.every((pt) => Array.isArray(pt) && pt.length === 2 && pt.every((n) => typeof n === "number"));
      if (pairs && points.length >= 2 && points.length <= MAX_CURVE_POINTS) {
        const ref = x.pwl as { var: string; index: string[] };
        return block(loc, {
          type: "ir_pwl",
          fields: {
            VAR: ref.var,
            ...refFields(ref),
            COUNT: String(points.length),
            ...Object.fromEntries((points as [number, number][]).flatMap(([px, py], k) => [[`X${k}`, String(px)], [`Y${k}`, String(py)]])),
          },
          extraState: { arity: ref.index.length, count: points.length },
        });
      }
    }
    if (
      shaped(x, ["predict", "of"]) && isName(x.predict) && Array.isArray(x.of) &&
      x.of.length >= 1 && x.of.length <= MAX_PREDICT_INPUTS
    ) {
      const parts = x.of as Term[];
      return block(loc, {
        type: "ir_predict",
        fields: { NAME: x.predict, COUNT: String(parts.length) },
        extraState: { count: parts.length },
        inputs: inputs(Object.fromEntries(parts.map((p, k) => [`X${k}`, wrap(term(p, [...loc, "of", k]))]))),
      });
    }
    if (shaped(x, ["fn", "of"]) && isName(x.fn)) {
      return block(loc, { type: "ir_fn", fields: { NAME: x.fn }, inputs: inputs({ OF: wrap(term(x.of as Term, [...loc, "of"])) }) });
    }
    const kind = Object.keys(x)[0] ?? "term";
    return opaque("term", loc, t, `${kind} (kept as it is)`);
  }

  const wrap = (b: SerialBlock | undefined) => (b ? { block: b } : undefined);

  // -- declarations -------------------------------------------------------
  const declarations: SerialBlock[] = [
    ...((ir.sets as string[]) ?? []).map((name, i) => block(["sets", i], { type: "ir_set", fields: { SET: name } })),
    ...Object.entries((ir.variables as Record<string, Json>) ?? {}).map(([name, spec]) => {
      const loc = ["variables", name];
      const interval = spec.domain === "interval";
      const known = interval
        ? Object.keys(spec).every((k) => INTERVAL_VARIABLE_KEYS.has(k)) &&
          isName(spec.start) && isName(spec.end) && (isName(spec.size) || Number.isInteger(spec.size)) &&
          (spec.presence === undefined || isName(spec.presence))
        : Object.keys(spec).every((k) => VARIABLE_KEYS.has(k)) &&
          (spec.stage === undefined || spec.stage === 1 || spec.stage === 2);
      if (!known) return opaque("declaration", loc, { kind: "variable", name, spec }, `decide ${name} (kept as it is)`);
      const index = (spec.index as string[]) ?? [];
      return block(loc, {
        type: "ir_variable",
        fields: {
          NAME: name,
          ARITY: String(index.length),
          ...Object.fromEntries(index.map((set, i) => [`SET${i}`, set])),
          DOMAIN: String(spec.domain ?? "binary"),
          LOWER: spec.lower === undefined ? "" : String(spec.lower),
          UPPER: spec.upper === undefined ? "" : String(spec.upper),
          STAGE: spec.stage === 1 || spec.stage === 2 ? String(spec.stage) : "",
          ...(interval
            ? { START: String(spec.start), END: String(spec.end), SIZE: String(spec.size), PRESENCE: (spec.presence as string) ?? "" }
            : {}),
        },
        extraState: { arity: index.length },
      });
    }),
    ...Object.entries((ir.parameters as Record<string, Json>) ?? {}).map(([name, spec]) => {
      const loc = ["parameters", name];
      const u = spec.uncertainty;
      const uncertainty =
        u === undefined
          ? true
          : (shaped(u, ["kind", "deviation"], ["gamma"]) && u.kind === "interval" && typeof u.deviation === "number" &&
              (u.gamma === undefined || typeof u.gamma === "number")) ||
            (shaped(u, ["kind", "futures"]) && u.kind === "scenarios" && Array.isArray(u.futures) &&
              u.futures.every((f) => shaped(f, ["factor"], ["label"]) && typeof f.factor === "number" &&
                (f.label === undefined || typeof f.label === "string")));
      if (Object.keys(spec).some((k) => k !== "index" && k !== "uncertainty" && k !== "entity") || !uncertainty) {
        return opaque("declaration", loc, { kind: "parameter", name, spec }, `data ${name} (kept as it is)`);
      }
      const index = (spec.index as string[]) ?? [];
      const given = (u ?? {}) as { kind?: string; deviation?: number; gamma?: number; futures?: { label?: string; factor: number }[] };
      return block(loc, {
        type: "ir_parameter",
        fields: {
          NAME: name,
          INDEX: index.length ? `[${index.join(", ")}]` : "",
          UNCERTAINTY: given.kind ?? "exact",
          DEVIATION: given.deviation === undefined ? "0.1" : String(given.deviation),
          GAMMA: given.gamma === undefined ? "" : String(given.gamma),
          ENTITY: typeof spec.entity === "string" ? spec.entity : "",
        },
        extraState: { index },
        inputs: inputs({ FUTURES: stack((given.futures ?? []).map((future, i) =>
          block([...loc, "uncertainty", "futures", i], {
            type: "ir_future",
            fields: { LABEL: future.label ?? "", FACTOR: String(future.factor) },
            extraState: { labelPresent: future.label !== undefined },
          }))) }),
      });
    }),
  ];

  // -- rules ---------------------------------------------------------------
  function scheduling(rule: Json, loc: IrLoc, kind: "no_overlap" | "cumulative"): SerialBlock | null {
    const body = rule[kind];
    const fits =
      Object.keys(rule).every((k) => ["id", "note", "forall", "severity", kind].includes(k)) && rule.severity === "hard" &&
      shaped(body, SCHEDULING_KEYS[kind]) && isRef(body.interval) && Array.isArray(body.over);
    if (!fits) return null;
    const b = body as { interval: { var: string; index: string[] }; over: Binding[]; demand?: Term; capacity?: Term };
    return block(loc, {
      type: kind === "no_overlap" ? "ir_no_overlap" : "ir_cumulative",
      fields: { ID: String(rule.id), NOTE: (rule.note as string) ?? "", INTERVAL: b.interval.var, ...refFields(b.interval) },
      extraState: { arity: b.interval.index.length },
      inputs: inputs({
        FORALL: bindings(rule.forall as Binding[], [...loc, "forall"]),
        OVER: bindings(b.over, [...loc, kind, "over"]),
        ...(kind === "cumulative"
          ? { DEMAND: wrap(term(b.demand, [...loc, kind, "demand"])), CAPACITY: wrap(term(b.capacity, [...loc, kind, "capacity"])) }
          : {}),
      }),
    });
  }

  function connected(rule: Json, loc: IrLoc): SerialBlock | null {
    const c = rule.connected;
    const fits =
      Object.keys(rule).every((k) => ["id", "note", "severity", "connected"].includes(k)) && rule.severity === "hard" &&
      shaped(c, ["assign", "units", "groups", "via"], CONNECTED_KEYS) && isRef(c.assign) && isName(c.via) &&
      shaped(c.units, ["index", "set"]) && shaped(c.groups, ["index", "set"]) &&
      (c.empty === undefined || c.empty === "forbidden" || c.empty === "allowed");
    if (!fits) return null;
    const units = c.units as { index: string; set: string };
    const groups = c.groups as { index: string; set: string };
    const assign = c.assign as { var: string; index: string[] };
    // The decision is read as [unit, group]: the blocks write it that way, so only that shape comes back exactly.
    if (assign.index.length !== 2 || assign.index[0] !== units.index || assign.index[1] !== groups.index) return null;
    return block(loc, {
      type: "ir_connected",
      fields: {
        ID: String(rule.id),
        NOTE: (rule.note as string) ?? "",
        VAR: assign.var,
        U_INDEX: units.index,
        U_SET: units.set,
        Z_INDEX: groups.index,
        Z_SET: groups.set,
        VIA: c.via as string,
        EMPTY: (c.empty as string) ?? "forbidden",
      },
      extraState: { emptyGiven: c.empty !== undefined },
    });
  }

  function route(rule: Json, loc: IrLoc): SerialBlock | null {
    const r = rule.route;
    const fits =
      Object.keys(rule).every((k) => ["id", "note", "severity", "route"].includes(k)) && rule.severity === "hard" &&
      shaped(r, ["visit", "vehicles", "stops"], ROUTE_KEYS) && isRef(r.visit) &&
      // One depot for all, or each vehicle's own (`depot_of`, or `depot_by` a relationship), one way only.
      [r.depot, r.depot_of, r.depot_by].filter((x) => x !== undefined).length === 1 && isName(r.depot ?? r.depot_of ?? r.depot_by) &&
      shaped(r.vehicles, ["index", "set"]) && shaped(r.stops, ["index", "set"]) &&
      (r.demand === undefined) === (r.capacity === undefined) &&
      (r.demand === undefined || (isName(r.demand) && isName(r.capacity))) &&
      ["travel", "earliest", "latest", "service"].every((k) => r[k] === undefined || isName(r[k])) &&
      (r.travel !== undefined || ["earliest", "latest", "service"].every((k) => r[k] === undefined));
    if (!fits) return null;
    const vehicles = r.vehicles as { index: string; set: string };
    const stops = r.stops as { index: string; set: string };
    const visit = r.visit as { var: string; index: string[] };
    // Read as [vehicle, stop, next stop]: the blocks write it that way, so only that shape comes back exactly.
    if (visit.index.length !== 3 || visit.index[0] !== vehicles.index || visit.index[1] !== stops.index) return null;
    return block(loc, {
      type: "ir_route",
      fields: {
        ID: String(rule.id),
        NOTE: (rule.note as string) ?? "",
        VAR: visit.var,
        V_INDEX: vehicles.index,
        V_SET: vehicles.set,
        S_INDEX: stops.index,
        S_SET: stops.set,
        TO_INDEX: visit.index[2],
        DEPOT_MODE: r.depot_by !== undefined ? "linked" : r.depot_of !== undefined ? "own" : "one",
        DEPOT: (r.depot ?? r.depot_of ?? r.depot_by) as string,
        DEMAND: (r.demand as string) ?? "",
        CAPACITY: (r.capacity as string) ?? "",
        TRAVEL: (r.travel as string) ?? "",
        EARLIEST: (r.earliest as string) ?? "",
        LATEST: (r.latest as string) ?? "",
        SERVICE: (r.service as string) ?? "",
      },
    });
  }

  function when(w: unknown, loc: IrLoc): SerialBlock | null | undefined {
    if (w === undefined) return undefined;
    if (!(shaped(w, ["var", "index"], ["is"]) && isName(w.var) && isIndex(w.index) && (w.is === undefined || w.is === 0 || w.is === 1))) return null;
    return block(loc, {
      type: "ir_when",
      fields: { VAR: w.var, ...refFields(w as { index: string[] }), IS: String(w.is ?? 1) },
      extraState: { arity: (w.index as string[]).length, isGiven: w.is !== undefined },
    });
  }

  const rules = ((ir.constraints as Json[]) ?? []).map((rule, i) => {
    const loc = ["constraints", i];
    const kept = () => opaque("rule", loc, rule, `rule ${String(rule.id)} (kept as it is)`);
    if ("no_overlap" in rule || "cumulative" in rule) return scheduling(rule, loc, "no_overlap" in rule ? "no_overlap" : "cumulative") ?? kept();
    if ("connected" in rule) return connected(rule, loc) ?? kept();
    if ("route" in rule) return route(rule, loc) ?? kept();
    const plain =
      rule.left !== undefined && rule.right !== undefined && rule.relation !== undefined &&
      Object.keys(rule).every((k) => RULE_KEYS.has(k));
    const condition = when(rule.when, [...loc, "when"]);
    const chance = rule.chance;
    const chanceFits = chance === undefined || (shaped(chance, ["epsilon"]) && typeof chance.epsilon === "number");
    if (!plain || condition === null || !chanceFits) return kept();
    return block(loc, {
      type: "ir_rule",
      fields: {
        ID: String(rule.id),
        NOTE: (rule.note as string) ?? "",
        SEVERITY: String(rule.severity ?? "hard"),
        WEIGHT: String(rule.weight ?? 1),
        RELATION: String(rule.relation),
        CHANCE: chance === undefined ? "" : String((chance as { epsilon: number }).epsilon),
      },
      inputs: inputs({
        FORALL: bindings(rule.forall as Binding[], [...loc, "forall"]),
        WHEN: wrap(condition),
        LEFT: wrap(term(rule.left as Term, [...loc, "left"])),
        RIGHT: wrap(term(rule.right as Term, [...loc, "right"])),
      }),
    });
  });

  // -- goal ------------------------------------------------------------------
  const objective = (ir.objective as Json | undefined) ?? {};
  const goal = ((objective.terms as Json[]) ?? []).map((t, k) =>
    block(["objective", "terms", k], {
      type: "ir_goal_term",
      fields: { ID: String(t.id), WEIGHT: String(t.weight ?? 1) },
      inputs: inputs({ EXPRESSION: wrap(term(t.expression as Term, ["objective", "terms", k, "expression"])) }),
    })
  );

  const root = block(null, {
    type: "ir_model",
    x: 24,
    y: 24,
    fields: {
      TITLE: options.title ?? "",
      SENSE: String(objective.sense ?? "minimize"),
      MODE: String(objective.mode ?? "weighted"),
    },
    // Every top-level key no block draws (`generate`, and any a later version adds) rides on the model block, so
    // an edit in Blocks never drops it.
    extraState: { version: ir.version ?? 2, ...(ir.predictors ? { predictors: ir.predictors } : {}),
      ...(Object.keys(carried(ir)).length ? { carried: carried(ir) } : {}) },
    inputs: inputs({ DECLARE: stack(declarations), RULES: stack(rules), GOAL: stack(goal) }),
  });
  root.id = "model-root";
  return { blocks: { languageVersion: 0, blocks: [root] } };
}

/** The top-level keys Blocks has no block for, carried through it untouched. */
const DRAWN = new Set(["version", "sets", "parameters", "variables", "constraints", "objective", "relationships",
  "predictors"]);
function carried(ir: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(ir).filter(([key]) => !DRAWN.has(key)));
}
