/**
 * An IR document as a Blockly workspace (serialisation JSON) -- one block per
 * construct, in the vocabulary of `vocabulary.ts`. `blocksToIr` (toIr.ts) is
 * the exact inverse; `roundTrip.test.ts` holds the two to that over every
 * fixture and template.
 *
 * A construct the vocabulary has no block for yet travels in an opaque block
 * carrying it verbatim, so nothing is lost and it is visibly not editable
 * here (Blockly edit mode plan, Task 4).
 */
import type { Binding, Term } from "../../model/terms";

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

const VARIABLE_KEYS = new Set(["index", "domain", "lower", "upper"]);
const RULE_KEYS = new Set(["id", "note", "forall", "left", "relation", "right", "severity", "weight"]);
/** The most terms an `add` block holds; a longer sum is carried opaque rather than nested (nesting would not round-trip). */
export const MAX_ADD_TERMS = 8;

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

  function binding(b: Binding, loc: IrLoc): SerialBlock {
    const via = b.via as { rel: string; from?: string; to?: string; depth?: string } | undefined;
    const where = (b.where ?? []) as { attr: string; op: string; value: unknown }[];
    return block(loc, {
      type: "ir_binding",
      fields: {
        INDEX: b.index,
        SET: b.set,
        VIA_REL: via?.rel ?? "",
        VIA_END: via?.to !== undefined ? "to" : "from",
        VIA_ANCHOR: via?.from ?? via?.to ?? "",
        VIA_DEPTH: via?.depth ?? "",
      },
      inputs: inputs({
        WHERE: stack(
          where.map((f, k) =>
            block([...loc, "where", k], { type: "ir_filter", fields: { ATTR: f.attr, OP: f.op, VALUE: JSON.stringify(f.value) } })
          )
        ),
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
      const index = (x.index as string[]) ?? [];
      return block(loc, {
        type: `ir_${kind}`,
        fields: { NAME: String(x[kind]), ...Object.fromEntries(index.map((idx, i) => [`IDX${i}`, idx])) },
        extraState: { arity: index.length },
      });
    }
    if ("attr" in x) {
      const attr = x.attr as { of: string; name: string };
      return block(loc, { type: "ir_attr", fields: { OF: attr.of, NAME: attr.name } });
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
    const kind = Object.keys(x)[0] ?? "term";
    return opaque("term", loc, t, `${kind} (kept as it is)`);
  }

  const wrap = (b: SerialBlock | undefined) => (b ? { block: b } : undefined);

  // -- declarations -------------------------------------------------------
  const declarations: SerialBlock[] = [
    ...((ir.sets as string[]) ?? []).map((name, i) => block(["sets", i], { type: "ir_set", fields: { SET: name } })),
    ...Object.entries((ir.variables as Record<string, Json>) ?? {}).map(([name, spec]) => {
      const loc = ["variables", name];
      if (spec.domain === "interval" || Object.keys(spec).some((k) => !VARIABLE_KEYS.has(k))) {
        return opaque("declaration", loc, { kind: "variable", name, spec }, `decide ${name} (kept as it is)`);
      }
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
        },
        extraState: { arity: index.length },
      });
    }),
    ...Object.entries((ir.parameters as Record<string, Json>) ?? {}).map(([name, spec]) => {
      const loc = ["parameters", name];
      if (Object.keys(spec).some((k) => k !== "index")) {
        return opaque("declaration", loc, { kind: "parameter", name, spec }, `data ${name} (kept as it is)`);
      }
      const index = (spec.index as string[]) ?? [];
      return block(loc, {
        type: "ir_parameter",
        fields: { NAME: name, INDEX: index.length ? `[${index.join(", ")}]` : "" },
        extraState: { index },
      });
    }),
  ];

  // -- rules ---------------------------------------------------------------
  const rules = ((ir.constraints as Json[]) ?? []).map((rule, i) => {
    const loc = ["constraints", i];
    const plain =
      rule.left !== undefined && rule.right !== undefined && rule.relation !== undefined &&
      Object.keys(rule).every((k) => RULE_KEYS.has(k));
    if (!plain) return opaque("rule", loc, rule, `rule ${String(rule.id)} (kept as it is)`);
    return block(loc, {
      type: "ir_rule",
      fields: {
        ID: String(rule.id),
        NOTE: (rule.note as string) ?? "",
        SEVERITY: String(rule.severity ?? "hard"),
        WEIGHT: String(rule.weight ?? 1),
        RELATION: String(rule.relation),
      },
      inputs: inputs({
        FORALL: bindings(rule.forall as Binding[], [...loc, "forall"]),
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
    extraState: { version: ir.version ?? 2 },
    inputs: inputs({ DECLARE: stack(declarations), RULES: stack(rules), GOAL: stack(goal) }),
  });
  root.id = "model-root";
  return { blocks: { languageVersion: 0, blocks: [root] } };
}
