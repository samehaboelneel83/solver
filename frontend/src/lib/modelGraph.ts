/**
 * The optimization view: a problem's model, drawn as the flow of its parts.
 *
 * The ERD view says what the domain *is*; this one says what the model *does*
 * with it. Read left to right:
 *
 *     sets  ->  variables and parameters  ->  rules  ->  objective
 *
 * - a **set** is an entity type the model ranges over, drawn as the same
 *   coloured rectangle the ERD uses, so the two views name one thing one way;
 * - a **variable** (an ellipse) is a decision, indexed by sets;
 * - a **parameter** (a rounded box) is data, indexed by sets;
 * - a **rule** (a hexagon) is a constraint, joined to every variable and
 *   parameter it reads and to the sets it holds "for every" of -- dark when
 *   it must hold, amber and dashed when it may bend at a price;
 * - the **objective** (an octagon) is joined to what it adds up.
 *
 * Every edge points the way the model's dependencies run, which is what lets
 * a layered layout set the columns out in that order without being told.
 *
 * Like the ERD, this needs no endpoint of its own: it is built from a model
 * version's IR (docs/contracts/problem-ir.md) and the domain's entity types.
 * A set that names an entity type keeps that type's `type-<id>` node id and
 * colour, so one type is one thing across the views. Every node, sets
 * included, carries the facts the side panel shows, in `attributes.details`:
 * in this view a set is shown as the model uses it -- what it ranges over --
 * rather than as the domain defines it, which is the ERD's job.
 */

import type { EntityType } from "../api/v1";
import type { GraphResponse } from "../types/graph";
import { describeBinding, describeTerm } from "../model/terms";
import type { Term, Binding } from "../model/terms";
import { labelForeground, typeColour } from "./colour";
import { typeNodeId, type ErData, type GraphPalette } from "./typesGraph";

export const MODEL_NODE_PREFIX = "model-";
export const OBJECTIVE_NODE_ID = `${MODEL_NODE_PREFIX}objective`;

/** The filter bar's groups in this view: what a node *is* in the model. */
export const MODEL_PARTS = ["sets", "variables", "parameters", "rules", "objective"] as const;
export type ModelPart = (typeof MODEL_PARTS)[number];

type Ir = {
  sets?: string[];
  parameters?: Record<string, { index?: string[] }>;
  variables?: Record<string, { index?: string[]; domain?: string; lower?: number; upper?: number }>;
  constraints?: IrConstraint[];
  objective?: { sense?: string; terms?: { id?: string; weight?: number; expression?: Term }[] };
};

type IrConstraint = {
  id: string;
  note?: string;
  forall?: Binding[];
  left?: Term;
  relation?: string;
  right?: Term;
  severity?: string;
  weight?: number;
  penalty?: number;
};

/** One row of the side panel: a label and what it says. */
export type Detail = [string, string];

const RELATION_WORD: Record<string, string> = { "<=": "≤", ">=": "≥", "=": "=" };

function estimateWidth(lines: string[], pxPerChar: number, min: number, padding: number): number {
  const longest = Math.max(0, ...lines.map((line) => [...line].length));
  return Math.max(min, longest * pxPerChar + padding);
}

/** How many variables multiply together in the worst part of a term. The
 * contract's own rule (`degree` in ir/validate.ts): 1 is linear, 2 quadratic. */
function degree(term: unknown): number {
  if (!term || typeof term !== "object") return 0;
  const t = term as Record<string, unknown>;
  if (typeof t.var === "string" || t.pwl !== undefined) return 1;
  if (t.sum !== undefined) return degree(t.sum);
  if (Array.isArray(t.add)) return Math.max(0, ...t.add.map(degree));
  if (Array.isArray(t.mul)) return t.mul.reduce((total: number, child) => total + degree(child), 0);
  return 0;
}

/** What a term reads: variables, parameters, and the sets whose attributes
 * it uses as numbers. Walks every term kind the contract has. */
function collect(
  term: unknown,
  found: { vars: Set<string>; pars: Set<string>; attrs: Map<string, Set<string>> },
  bound: Map<string, string>
): void {
  if (!term || typeof term !== "object") return;
  const t = term as Record<string, unknown>;
  if (typeof t.var === "string") found.vars.add(t.var);
  if (typeof t.par === "string") found.pars.add(t.par);
  if (t.attr && typeof t.attr === "object") {
    const { of, name } = t.attr as { of?: string; name?: string };
    const set = of ? bound.get(of) : undefined;
    if (set && name) {
      if (!found.attrs.has(set)) found.attrs.set(set, new Set());
      found.attrs.get(set)!.add(name);
    }
  }
  if (t.sum !== undefined) {
    const inner = new Map(bound);
    for (const binding of (t.over as Binding[] | undefined) ?? []) inner.set(binding.index, binding.set);
    collect(t.sum, found, inner);
  }
  for (const key of ["add", "mul"]) {
    const list = t[key];
    if (Array.isArray(list)) list.forEach((item) => collect(item, found, bound));
  }
  // A piecewise curve reads the variable it is a curve of.
  if (t.pwl && typeof t.pwl === "object") collect(t.pwl, found, bound);
}

/**
 * The optimization view's graph and palette for one model version.
 *
 * Tolerant of a model version published before the IR contract, whose rules
 * carry only an id and a note: it is drawn with what it has, and its panel
 * says it has no expression, rather than the view failing on it.
 */
export function buildModelView(
  irInput: Record<string, unknown> | null | undefined,
  entityTypes: readonly EntityType[]
): { graph: GraphResponse; palette: GraphPalette } {
  const ir = (irInput ?? {}) as Ir;
  const nodeData: Record<string, ErData> = {};
  const edgeData: Record<string, ErData> = {};
  const palette: GraphPalette = { nodeFill: {}, nodeLabel: {}, edgeColour: {}, nodeData, edgeData };
  const nodes: GraphResponse["nodes"] = [];
  const edges: GraphResponse["edges"] = [];
  const typeByName = new Map(entityTypes.map((type) => [type.name, type]));

  const addNode = (
    id: string,
    part: ModelPart,
    er: ErData["er"],
    lines: string[],
    fill: string,
    details: Detail[],
    width: number,
    extra: Partial<ErData> = {}
  ) => {
    nodes.push({ id, type: part, label: lines.join("\n"), parent: null, attributes: { er, part, details } });
    palette.nodeFill[id] = fill;
    palette.nodeLabel[id] = labelForeground(fill);
    nodeData[id] = { er, w: width, ...extra };
  };
  const edgeIds = new Set<string>();
  const addEdge = (source: string, target: string, label = "", kind: ErData["er"] = "uses") => {
    const id = `modeledge-${source}->${target}`;
    if (edgeIds.has(id) || source === target) return;
    edgeIds.add(id);
    edges.push({ id, source, target, type: kind, label, attributes: {} });
    palette.edgeColour[id] = kind === "ranges" ? "#94a3b8" : "#475569";
    edgeData[id] = { er: kind };
  };

  // -- sets ------------------------------------------------------------------
  const setNode = new Map<string, string>();
  for (const name of ir.sets ?? []) {
    const type = typeByName.get(name);
    const id = type ? typeNodeId(type.id) : `${MODEL_NODE_PREFIX}set-${name}`;
    setNode.set(name, id);
    const fill = typeColour({ id: String(type?.id ?? name), colour: type?.colour ?? null });
    addNode(
      id,
      "sets",
      "set",
      [name],
      fill,
      [
        ["Kind", "Set"],
        ["Ranges over", type ? `every ${name} in the domain` : `${name} (no entity type of that name)`],
      ],
      estimateWidth([name], 10.2, 100, 40)
    );
  }
  const setOf = (name: string) => setNode.get(name);

  // -- parameters and variables ---------------------------------------------
  for (const [name, spec] of Object.entries(ir.parameters ?? {})) {
    const id = `${MODEL_NODE_PREFIX}par-${name}`;
    const index = spec.index ?? [];
    const lines = [name, index.length ? `[${index.join(", ")}]` : "scalar"];
    addNode(id, "parameters", "parameter", lines, "#e2e8f0",
      [["Kind", "Parameter (data)"], ["Indexed by", index.join(", ") || "nothing: one number"]],
      estimateWidth(lines, 7.8, 90, 28));
    for (const set of index) {
      const from = setOf(set);
      if (from) addEdge(from, id, "", "ranges");
    }
  }
  for (const [name, spec] of Object.entries(ir.variables ?? {})) {
    const id = `${MODEL_NODE_PREFIX}var-${name}`;
    const index = spec.index ?? [];
    const domain = spec.domain ?? "binary";
    const lines = [name, `${domain}${index.length ? ` [${index.join(", ")}]` : ""}`];
    const bounds =
      domain === "binary" ? "0 or 1" : `${spec.lower ?? 0} to ${spec.upper ?? "no stated limit"}`;
    addNode(id, "variables", "variable", lines, "#dbeafe",
      [["Kind", "Variable (decision)"], ["Domain", domain], ["Indexed by", index.join(", ") || "nothing: one value"], ["Values", bounds]],
      estimateWidth(lines, 7.8, 100, 34));
    for (const set of index) {
      const from = setOf(set);
      if (from) addEdge(from, id, "", "ranges");
    }
  }

  // -- rules ----------------------------------------------------------------
  for (const rule of ir.constraints ?? []) {
    const id = `${MODEL_NODE_PREFIX}con-${rule.id}`;
    const soft = rule.severity === "soft";
    const price = rule.weight ?? rule.penalty;
    const relation = rule.relation ? RELATION_WORD[rule.relation] ?? rule.relation : "?";
    const quadratic = Math.max(degree(rule.left), degree(rule.right)) >= 2;
    const lines = [
      rule.id,
      (soft ? `may bend · ${price ?? 1} per unit` : "must hold") + (quadratic ? " · quadratic" : ""),
    ];
    const expressed = rule.left !== undefined && rule.right !== undefined;
    const details: Detail[] = [
      [
        "Kind",
        (soft ? "Rule that may bend (soft)" : "Rule that must hold (hard)") + (quadratic ? ", quadratic" : ""),
      ],
      ["Rule", expressed ? `${describeTerm(rule.left)} ${relation} ${describeTerm(rule.right)}` : "(no expression: published before the IR contract)"],
    ];
    if (rule.forall?.length) details.push(["For every", rule.forall.map(describeBinding).join(", ")]);
    if (soft) details.push(["Price per unit broken", String(price ?? 1)]);
    if (rule.note) details.push(["Note", rule.note]);
    addNode(id, "rules", "constraint", lines, soft ? "#fef3c7" : "#1e293b", details,
      estimateWidth(lines, 7.8, 120, 50), { soft: soft ? "yes" : "no" });

    const bound = new Map<string, string>();
    for (const binding of rule.forall ?? []) bound.set(binding.index, binding.set);
    const found = { vars: new Set<string>(), pars: new Set<string>(), attrs: new Map<string, Set<string>>() };
    collect(rule.left, found, bound);
    collect(rule.right, found, bound);
    found.vars.forEach((name) => addEdge(`${MODEL_NODE_PREFIX}var-${name}`, id));
    found.pars.forEach((name) => addEdge(`${MODEL_NODE_PREFIX}par-${name}`, id));
    // The sets it holds for every one of, labelled with any attribute of
    // theirs it reads as a number -- hours_per_week flowing into the hours
    // rule is exactly what this view is for.
    const reached = new Set<string>([...(rule.forall ?? []).map((b) => b.set), ...found.attrs.keys()]);
    for (const set of reached) {
      const from = setOf(set);
      if (from) addEdge(from, id, [...(found.attrs.get(set) ?? [])].join(", "), "ranges");
    }
  }

  // -- objective -------------------------------------------------------------
  const terms = ir.objective?.terms ?? [];
  if (ir.objective && terms.length) {
    const sense = ir.objective.sense ?? "minimize";
    // A goal that multiplies decisions together says so: it is what decides
    // which solvers may take the model, and whether convexity is checked.
    const quadratic = terms.some((term) => degree(term.expression) >= 2);
    const lines = [
      sense,
      `${terms.length} term${terms.length === 1 ? "" : "s"}${quadratic ? " · quadratic" : ""}`,
    ];
    addNode(OBJECTIVE_NODE_ID, "objective", "objective", lines, "#16a34a",
      [["Kind", quadratic ? "Objective (quadratic)" : "Objective"], ["Sense", sense],
        ...terms.map((term): Detail => [term.id ?? "term", `${term.weight ?? 1} × ${describeTerm(term.expression)}`])],
      estimateWidth(lines, 8.4, 110, 50));
    const found = { vars: new Set<string>(), pars: new Set<string>(), attrs: new Map<string, Set<string>>() };
    terms.forEach((term) => collect(term.expression, found, new Map()));
    found.vars.forEach((name) => addEdge(`${MODEL_NODE_PREFIX}var-${name}`, OBJECTIVE_NODE_ID));
    found.pars.forEach((name) => addEdge(`${MODEL_NODE_PREFIX}par-${name}`, OBJECTIVE_NODE_ID));
    // A soft rule's price is paid in the objective.
    for (const rule of ir.constraints ?? []) {
      if (rule.severity === "soft") {
        addEdge(`${MODEL_NODE_PREFIX}con-${rule.id}`, OBJECTIVE_NODE_ID, "penalty");
      }
    }
  }

  // An edge to a variable or parameter the model never declared cannot be
  // drawn (cytoscape throws on a missing endpoint); the validator makes that
  // impossible for a published version, and this keeps a malformed one from
  // taking the canvas down with it.
  const known = new Set(nodes.map((node) => node.id));
  const drawable = edges.filter((edge) => known.has(edge.source) && known.has(edge.target));

  const parts = MODEL_PARTS.filter((part) => nodes.some((node) => node.type === part));
  return {
    graph: {
      nodes,
      edges: drawable,
      entity_types: parts.map((part) => ({ id: `part-${part}`, code: part, name: part, is_abstract: false, colour: null })),
      relationship_types: [],
      hierarchies: [],
      attribute_definitions: [],
    },
    palette,
  };
}

/** The facts a model node shows in the side panel, or null for a node that is
 * not one of this view's. */
export function modelDetails(node: { attributes?: Record<string, unknown> } | undefined): Detail[] | null {
  const details = node?.attributes?.details;
  return Array.isArray(details) ? (details as Detail[]) : null;
}
