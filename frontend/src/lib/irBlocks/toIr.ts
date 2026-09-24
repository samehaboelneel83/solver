/**
 * A Blockly workspace (serialisation JSON) back to the IR -- the exact
 * inverse of `irToBlocks`. Pure data: no Blockly runtime, so it runs on
 * every change and in tests alike.
 *
 * Alongside the IR it returns where each block landed in it (`paths`), so a
 * refusal's `loc` can be put back on the block that produced it, and how many
 * blocks sit outside the model root (`outside`) -- a block dropped on the
 * empty canvas is not part of the model, and Publish says so rather than
 * losing it silently.
 *
 * An unfinished block is never dropped: an empty socket is `{"const": null}`
 * and an unchosen dropdown is `""`, both of which the validators refuse by
 * name at that place.
 */
import type { IrLoc, SerialBlock } from "./toBlocks";

type Json = Record<string, unknown>;
type SavedWorkspace = { blocks?: { blocks?: SerialBlock[] } };

const UNFINISHED = { const: null };

function* stackOf(first: { block: SerialBlock } | undefined): Generator<SerialBlock> {
  for (let b = first?.block; b; b = b.next?.block) yield b;
}

const fieldOf = (b: SerialBlock, name: string) => b.fields?.[name] ?? "";

function numberOr(text: string, fallback: number | null): number | null {
  if (text === "") return fallback;
  const n = Number(text);
  return Number.isFinite(n) ? n : null;
}

/** Every relationship a piece of IR walks: `via.rel` in any binding, `connected.via`. */
function walkedIn(value: unknown, into: Set<string>) {
  if (Array.isArray(value)) value.forEach((v) => walkedIn(v, into));
  else if (value && typeof value === "object") {
    const x = value as Json;
    if (x.via && typeof x.via === "object" && typeof (x.via as Json).rel === "string") into.add((x.via as Json).rel as string);
    if (x.connected && typeof x.connected === "object" && typeof (x.connected as Json).via === "string") into.add((x.connected as Json).via as string);
    Object.values(x).forEach((v) => walkedIn(v, into));
  }
}

export function blocksToIr(workspace: SavedWorkspace): { ir: Json; paths: Map<string, IrLoc>; outside: number } {
  const tops = workspace.blocks?.blocks ?? [];
  const root = tops.find((b) => b.type === "ir_model" && b.id === "model-root") ?? tops.find((b) => b.type === "ir_model");
  const paths = new Map<string, IrLoc>();
  const mark = (b: SerialBlock, loc: IrLoc) => {
    if (b.id) paths.set(b.id, loc);
  };
  const outside = tops.filter((b) => b !== root).length;

  function binding(b: SerialBlock, loc: IrLoc): Json {
    mark(b, loc);
    const where = [...stackOf(b.inputs?.WHERE)].map((f, k) => {
      mark(f, [...loc, "where", k]);
      let value: unknown = null;
      try {
        value = JSON.parse(fieldOf(f, "VALUE"));
      } catch {
        value = fieldOf(f, "VALUE");
      }
      return { attr: fieldOf(f, "ATTR"), op: fieldOf(f, "OP"), value };
    });
    const rel = fieldOf(b, "VIA_REL");
    const depth = fieldOf(b, "VIA_DEPTH");
    return {
      index: fieldOf(b, "INDEX"),
      set: fieldOf(b, "SET"),
      ...(where.length ? { where } : {}),
      ...(rel
        ? { via: { rel, [fieldOf(b, "VIA_END") === "to" ? "to" : "from"]: fieldOf(b, "VIA_ANCHOR"), ...(depth ? { depth } : {}) } }
        : {}),
    };
  }

  const bindings = (first: { block: SerialBlock } | undefined, loc: IrLoc) =>
    [...stackOf(first)].map((b, j) => binding(b, [...loc, j]));

  function term(slot: { block: SerialBlock } | undefined, loc: IrLoc): unknown {
    const b = slot?.block;
    if (!b) return { ...UNFINISHED };
    mark(b, loc);
    const state = (b.extraState ?? {}) as Json;
    switch (b.type) {
      case "ir_const":
        return { const: numberOr(fieldOf(b, "VALUE"), null) };
      case "ir_var":
      case "ir_par": {
        const arity = Number(state.arity ?? 0);
        return {
          [b.type === "ir_var" ? "var" : "par"]: fieldOf(b, "NAME"),
          index: Array.from({ length: arity }, (_, i) => fieldOf(b, `IDX${i}`)),
        };
      }
      case "ir_attr":
        return { attr: { of: fieldOf(b, "OF"), name: fieldOf(b, "NAME") } };
      case "ir_sum":
        return { sum: term(b.inputs?.BODY, [...loc, "sum"]), over: bindings(b.inputs?.OVER, [...loc, "over"]) };
      case "ir_mul":
        return { mul: [term(b.inputs?.A, [...loc, "mul", 0]), term(b.inputs?.B, [...loc, "mul", 1])] };
      case "ir_add": {
        const count = Number(state.count ?? 2);
        return { add: Array.from({ length: count }, (_, k) => term(b.inputs?.[`T${k}`], [...loc, "add", k])) };
      }
      case "ir_opaque_term":
        return state.json;
      default:
        return { ...UNFINISHED };
    }
  }

  const ir: Json = {
    version: Number(((root?.extraState ?? {}) as Json).version ?? 2),
    sets: [],
    parameters: {},
    variables: {},
    constraints: [],
  };
  const sets = ir.sets as string[];
  const parameters = ir.parameters as Record<string, unknown>;
  const variables = ir.variables as Record<string, unknown>;

  for (const d of stackOf(root?.inputs?.DECLARE)) {
    if (d.type === "ir_set") {
      mark(d, ["sets", sets.length]);
      sets.push(fieldOf(d, "SET"));
    } else if (d.type === "ir_variable") {
      const name = fieldOf(d, "NAME");
      mark(d, ["variables", name]);
      const arity = Number(((d.extraState ?? {}) as Json).arity ?? 0);
      const lower = numberOr(fieldOf(d, "LOWER"), null);
      const upper = numberOr(fieldOf(d, "UPPER"), null);
      variables[name] = {
        index: Array.from({ length: arity }, (_, i) => fieldOf(d, `SET${i}`)),
        domain: fieldOf(d, "DOMAIN") || "binary",
        ...(fieldOf(d, "LOWER") !== "" ? { lower } : {}),
        ...(fieldOf(d, "UPPER") !== "" ? { upper } : {}),
      };
    } else if (d.type === "ir_parameter") {
      const name = fieldOf(d, "NAME");
      mark(d, ["parameters", name]);
      parameters[name] = { index: [...((((d.extraState ?? {}) as Json).index as string[]) ?? [])] };
    } else if (d.type === "ir_opaque_declaration") {
      const json = ((d.extraState ?? {}) as Json).json as { kind: string; name: string; spec: unknown };
      mark(d, [json.kind === "variable" ? "variables" : "parameters", json.name]);
      (json.kind === "variable" ? variables : parameters)[json.name] = json.spec;
    }
  }

  const constraints = ir.constraints as unknown[];
  for (const r of stackOf(root?.inputs?.RULES)) {
    const loc = ["constraints", constraints.length];
    mark(r, loc);
    if (r.type === "ir_opaque_rule") {
      constraints.push(((r.extraState ?? {}) as Json).json);
      continue;
    }
    const severity = fieldOf(r, "SEVERITY") || "hard";
    const forall = bindings(r.inputs?.FORALL, [...loc, "forall"]);
    const note = fieldOf(r, "NOTE");
    constraints.push({
      id: fieldOf(r, "ID"),
      ...(note ? { note } : {}),
      ...(forall.length ? { forall } : {}),
      left: term(r.inputs?.LEFT, [...loc, "left"]),
      relation: fieldOf(r, "RELATION"),
      right: term(r.inputs?.RIGHT, [...loc, "right"]),
      severity,
      ...(severity === "soft" ? { weight: numberOr(fieldOf(r, "WEIGHT"), null) } : {}),
    });
  }

  const goal = [...stackOf(root?.inputs?.GOAL)].map((g, k) => {
    mark(g, ["objective", "terms", k]);
    return {
      id: fieldOf(g, "ID"),
      weight: numberOr(fieldOf(g, "WEIGHT"), null),
      expression: term(g.inputs?.EXPRESSION, ["objective", "terms", k, "expression"]),
    };
  });
  if (goal.length) {
    const mode = root ? fieldOf(root, "MODE") : "";
    ir.objective = { sense: (root && fieldOf(root, "SENSE")) || "minimize", ...(mode === "lex" ? { mode: "lex" } : {}), terms: goal };
  }

  const walked = new Set<string>();
  walkedIn(ir.constraints, walked);
  walkedIn(ir.objective, walked);
  if (walked.size) ir.relationships = [...walked].sort();

  return { ir, paths, outside };
}

/** The block whose recorded place is the longest prefix of `loc`: where a refusal belongs. */
export function blockForLoc(paths: Map<string, IrLoc>, loc: IrLoc): string | null {
  let best: string | null = null;
  let bestLength = -1;
  for (const [id, path] of paths) {
    if (path.length > loc.length || path.length <= bestLength) continue;
    if (path.every((step, i) => step === loc[i])) {
      best = id;
      bestLength = path.length;
    }
  }
  return best;
}
