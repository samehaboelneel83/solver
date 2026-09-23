/**
 * A model as Blockly blocks: the optimization view's "Blocks" style.
 *
 * The IR is already a tree of terms (docs/contracts/problem-ir.md), which is
 * exactly what Blockly draws: a rule is a block with a "for every" line and
 * two sockets, and each side is built from blocks that plug into each other
 * -- a sum holding a product holding a variable. Read-only: the blocks show
 * the model, they do not edit it (the Model editor does that).
 *
 * This file is only data -- the block definitions and a model's serialised
 * workspace -- so it is tested without a browser; `BlocklyView` loads it.
 *
 * Blocks that stand for a part of the model (a set, a variable, a
 * parameter, a rule, the goal) carry that part's node id from
 * `buildModelView`, so selecting one opens the same side panel the other
 * styles do. Term blocks inside them take a generated id and select the
 * part they belong to.
 */

import type { Binding, Term } from "../model/terms";
import { describeBinding, schedulingKind } from "../model/terms";
import type { GraphResponse } from "../types/graph";
import { MODEL_NODE_PREFIX, OBJECTIVE_NODE_ID } from "./modelGraph";

const label = (name: string) => ({ type: "field_label_serializable", name, text: "" });
const value = (name: string) => ({ type: "input_value", name, check: "Number" });
const statement = (name: string, check: string) => ({ type: "input_statement", name, check });

const COLOUR = {
  model: "#475569",
  set: "#0d9488",
  decision: "#2563eb",
  data: "#64748b",
  hard: "#334155",
  soft: "#d97706",
  goal: "#16a34a",
  variable: "#3b82f6",
  parameter: "#94a3b8",
  constant: "#78716c",
  attribute: "#14b8a6",
  sum: "#7c3aed",
  operator: "#59c059",
};

/** The block types, in Blockly's JSON definition format. */
export const BLOCK_DEFINITIONS = [
  {
    type: "ir_model",
    message0: "optimization model %1",
    args0: [label("TITLE")],
    message1: "sets, decisions and data %1",
    args1: [statement("DECLARE", "declaration")],
    message2: "rules %1",
    args2: [statement("RULES", "rule")],
    message3: "goal %1",
    args3: [statement("GOAL", "goal")],
    colour: COLOUR.model,
    tooltip: "The model: what it ranges over, what it decides, the rules that hold, and what it optimises",
  },
  {
    type: "ir_set",
    message0: "set %1",
    args0: [label("NAME")],
    previousStatement: "declaration",
    nextStatement: "declaration",
    colour: COLOUR.set,
    tooltip: "A set the model ranges over: every entity of this type",
  },
  {
    type: "ir_variable",
    message0: "decide %1 %2 %3",
    args0: [label("NAME"), label("INDEX"), label("DOMAIN")],
    previousStatement: "declaration",
    nextStatement: "declaration",
    colour: COLOUR.decision,
    tooltip: "A decision the solver makes",
  },
  {
    type: "ir_parameter",
    message0: "data %1 %2",
    args0: [label("NAME"), label("INDEX")],
    previousStatement: "declaration",
    nextStatement: "declaration",
    colour: COLOUR.data,
    tooltip: "Numbers the model reads",
  },
  ...(["hard", "soft"] as const).map((severity) => ({
    type: `ir_rule_${severity}`,
    message0: severity === "hard" ? "rule %1 must hold" : "rule %1 may bend at %2 per unit",
    args0: severity === "hard" ? [label("ID")] : [label("ID"), label("PRICE")],
    message1: "for every %1",
    args1: [label("FORALL")],
    message2: "%1 %2 %3",
    args2: [value("LEFT"), label("RELATION"), value("RIGHT")],
    inputsInline: true,
    previousStatement: "rule",
    nextStatement: "rule",
    colour: COLOUR[severity],
    tooltip: severity === "hard" ? "A rule every answer must satisfy" : "A rule an answer may break, at a price",
  })),
  {
    type: "ir_objective",
    message0: "%1 the sum of %2",
    args0: [label("SENSE"), statement("TERMS", "term")],
    previousStatement: "goal",
    colour: COLOUR.goal,
    tooltip: "What the solver optimises",
  },
  {
    type: "ir_goal_term",
    message0: "%1 × %2",
    args0: [label("WEIGHT"), value("EXPRESSION")],
    inputsInline: true,
    previousStatement: "term",
    nextStatement: "term",
    colour: COLOUR.goal,
  },
  { type: "ir_const", message0: "%1", args0: [label("VALUE")], output: "Number", colour: COLOUR.constant },
  { type: "ir_var", message0: "%1 %2", args0: [label("NAME"), label("INDEX")], output: "Number", colour: COLOUR.variable },
  { type: "ir_par", message0: "%1 %2", args0: [label("NAME"), label("INDEX")], output: "Number", colour: COLOUR.parameter },
  { type: "ir_attr", message0: "%1 of %2", args0: [label("NAME"), label("OF")], output: "Number", colour: COLOUR.attribute },
  {
    type: "ir_sum",
    message0: "sum over %1 of %2",
    args0: [label("OVER"), value("BODY")],
    inputsInline: true,
    output: "Number",
    colour: COLOUR.sum,
  },
  {
    type: "ir_add",
    message0: "%1 + %2",
    args0: [value("A"), value("B")],
    inputsInline: true,
    output: "Number",
    colour: COLOUR.operator,
  },
  {
    type: "ir_mul",
    message0: "%1 × %2",
    args0: [value("A"), value("B")],
    inputsInline: true,
    output: "Number",
    colour: COLOUR.operator,
  },
];

/** One block in Blockly's serialisation format. */
export type SerialBlock = {
  type: string;
  id?: string;
  x?: number;
  y?: number;
  fields?: Record<string, string>;
  inputs?: Record<string, { block: SerialBlock }>;
  next?: { block: SerialBlock };
  movable?: boolean;
  deletable?: boolean;
  editable?: boolean;
};

type Ir = {
  sets?: string[];
  parameters?: Record<string, { index?: string[] }>;
  variables?: Record<string, { index?: string[]; domain?: string }>;
  constraints?: {
    id: string;
    forall?: Binding[];
    left?: Term;
    relation?: string;
    right?: Term;
    severity?: string;
    weight?: number;
    penalty?: number;
    no_overlap?: { interval: { var: string; index: string[] }; over?: Binding[] };
    cumulative?: { interval: { var: string; index: string[] }; over?: Binding[]; demand?: Term; capacity?: Term };
  }[];
  objective?: { sense?: string; terms?: { weight?: number; expression?: Term }[] };
};

const RELATION: Record<string, string> = { "<=": "≤", ">=": "≥", "=": "=", "==": "=", "<": "<", ">": ">" };

const bracket = (index: string[] | undefined) => (index && index.length ? `[${index.join(", ")}]` : "");

/** A read-only block: shown, selectable, not dragged, edited or deleted. */
const fixed = (block: SerialBlock): SerialBlock => ({ ...block, movable: false, deletable: false, editable: false });

export function termBlock(term: Term | undefined): SerialBlock {
  if (!term || typeof term !== "object") return fixed({ type: "ir_const", fields: { VALUE: "?" } });
  if ("const" in term) return fixed({ type: "ir_const", fields: { VALUE: String(term.const) } });
  if ("var" in term) return fixed({ type: "ir_var", fields: { NAME: term.var, INDEX: bracket(term.index) } });
  if ("par" in term) return fixed({ type: "ir_par", fields: { NAME: term.par, INDEX: bracket(term.index) } });
  if ("pwl" in term) {
    // No curve block yet (the editor slice): the variable it is a curve of.
    return fixed({ type: "ir_var", fields: { NAME: `curve(${term.pwl.var})`, INDEX: bracket(term.pwl.index) } });
  }
  if ("attr" in term) return fixed({ type: "ir_attr", fields: { NAME: term.attr.name, OF: term.attr.of } });
  if ("sum" in term) {
    return fixed({
      type: "ir_sum",
      fields: { OVER: (term.over ?? []).map(describeBinding).join(", ") },
      inputs: { BODY: { block: termBlock(term.sum) } },
    });
  }
  if ("mul" in term) {
    return fixed({
      type: "ir_mul",
      inputs: { A: { block: termBlock(term.mul[0]) }, B: { block: termBlock(term.mul[1]) } },
    });
  }
  if ("add" in term) {
    // Blockly's `+` has two sockets: a + b + c is a + (b + c).
    const parts = term.add;
    if (parts.length === 0) return fixed({ type: "ir_const", fields: { VALUE: "0" } });
    if (parts.length === 1) return termBlock(parts[0]);
    return fixed({
      type: "ir_add",
      inputs: { A: { block: termBlock(parts[0]) }, B: { block: termBlock({ add: parts.slice(1) }) } },
    });
  }
  return fixed({ type: "ir_const", fields: { VALUE: "?" } });
}

/** Link blocks into a stack: each one's `next` is the one after it. */
function stack(blocks: SerialBlock[]): { block: SerialBlock } | undefined {
  let next: { block: SerialBlock } | undefined;
  for (let i = blocks.length - 1; i >= 0; i -= 1) {
    next = { block: next ? { ...blocks[i], next } : blocks[i] };
  }
  return next;
}

/**
 * The model's workspace, in Blockly's serialisation format. `graph` is the
 * same `buildModelView` graph the other styles draw, used only for the ids
 * of the sets (a set that is an entity type keeps that type's node id).
 */
export function modelToBlocks(irInput: Record<string, unknown> | null | undefined, graph: GraphResponse, title = "") {
  const ir = (irInput ?? {}) as Ir;
  const setIds = new Map(
    graph.nodes.filter((node) => node.type === "sets").map((node) => [node.label.split("\n")[0], node.id])
  );

  const declarations: SerialBlock[] = [
    ...(ir.sets ?? []).map((name) =>
      fixed({ type: "ir_set", id: setIds.get(name) ?? `${MODEL_NODE_PREFIX}set-${name}`, fields: { NAME: name } })
    ),
    ...Object.entries(ir.variables ?? {}).map(([name, spec]) =>
      fixed({
        type: "ir_variable",
        id: `${MODEL_NODE_PREFIX}var-${name}`,
        fields: { NAME: name, INDEX: bracket(spec.index), DOMAIN: `(${spec.domain ?? "binary"})` },
      })
    ),
    ...Object.entries(ir.parameters ?? {}).map(([name, spec]) =>
      fixed({ type: "ir_parameter", id: `${MODEL_NODE_PREFIX}par-${name}`, fields: { NAME: name, INDEX: bracket(spec.index) } })
    ),
  ];

  const rules: SerialBlock[] = (ir.constraints ?? []).map((rule) => {
    const soft = rule.severity === "soft";
    const expressed = rule.left !== undefined && rule.right !== undefined;
    const kind = schedulingKind(rule);
    if (kind !== null) {
      // No scheduling block yet (the editor slice): the rule's intervals on
      // the left, and for a cumulative its capacity on the right.
      const body = rule[kind]!;
      return fixed({
        type: "ir_rule_hard",
        id: `${MODEL_NODE_PREFIX}con-${rule.id}`,
        fields: {
          ID: rule.id,
          FORALL: rule.forall?.length ? rule.forall.map(describeBinding).join(", ") : "nothing: it holds once",
          RELATION: kind === "no_overlap" ? "never overlap" : "stay within",
        },
        inputs: {
          LEFT: { block: termBlock({ sum: { var: body.interval.var, index: body.interval.index }, over: body.over ?? [] } as Term) },
          ...(rule.cumulative ? { RIGHT: { block: termBlock(rule.cumulative.capacity) } } : {}),
        },
      });
    }
    return fixed({
      type: soft ? "ir_rule_soft" : "ir_rule_hard",
      id: `${MODEL_NODE_PREFIX}con-${rule.id}`,
      fields: {
        ID: rule.id,
        ...(soft ? { PRICE: String(rule.weight ?? rule.penalty ?? 1) } : {}),
        FORALL: rule.forall?.length ? rule.forall.map(describeBinding).join(", ") : "nothing: it holds once",
        RELATION: expressed ? RELATION[rule.relation ?? ""] ?? rule.relation ?? "?" : "(no expression)",
      },
      inputs: expressed ? { LEFT: { block: termBlock(rule.left) }, RIGHT: { block: termBlock(rule.right) } } : {},
    });
  });

  const terms = ir.objective?.terms ?? [];
  const goal: SerialBlock[] =
    ir.objective && terms.length
      ? [
          fixed({
            type: "ir_objective",
            id: OBJECTIVE_NODE_ID,
            fields: { SENSE: ir.objective.sense ?? "minimize" },
            inputs: Object.fromEntries(
              Object.entries({
                TERMS: stack(
                  terms.map((term) =>
                    fixed({
                      type: "ir_goal_term",
                      fields: { WEIGHT: String(term.weight ?? 1) },
                      inputs: { EXPRESSION: { block: termBlock(term.expression) } },
                    })
                  )
                ),
              }).filter(([, input]) => input !== undefined)
            ) as Record<string, { block: SerialBlock }>,
          }),
        ]
      : [];

  const inputs: Record<string, { block: SerialBlock }> = {};
  for (const [name, blocks] of [
    ["DECLARE", declarations],
    ["RULES", rules],
    ["GOAL", goal],
  ] as const) {
    const linked = stack(blocks);
    if (linked) inputs[name] = linked;
  }

  return {
    blocks: {
      languageVersion: 0,
      blocks: [fixed({ type: "ir_model", id: "model-root", x: 24, y: 24, fields: { TITLE: title }, inputs })],
    },
  };
}

/** The model part a block belongs to: itself if it is one, else the
 * nearest block around it that is. `parentOf` walks outwards. */
export function partOfBlock(
  id: string | null,
  parentOf: (id: string) => string | null,
  known: Set<string>
): string | null {
  let current = id;
  while (current) {
    if (known.has(current)) return current;
    current = parentOf(current);
  }
  return null;
}
