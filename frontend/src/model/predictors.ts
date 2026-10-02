/**
 * Trained predictors in the model editor (benchmark, October 2026: every attempt to use a trained
 * model ended in "not a predictor this model declares", and nothing in the editor declared one).
 *
 * The workspace's predictors are offered wherever a formula is written; the document declares
 * (`predictors`, contract §3.6) exactly those its rules and goals call, with each one's number of
 * inputs, as it is saved. Declarations a document already carries are kept.
 */
import type { Predictor } from "../api/v1";

export type Declared = Record<string, { inputs: number }>;

/** Every predictor a formula may call: the workspace's, and any the document declares already. */
export function offered(declared: Declared | undefined, workspace: Pick<Predictor, "name" | "inputs">[]): Declared {
  const out: Declared = {};
  for (const p of workspace) out[p.name] = { inputs: p.inputs.length };
  return { ...out, ...(declared ?? {}) };
}

/** The names of the predictors a document's rules and goals call. */
export function called(node: unknown, into: Set<string> = new Set()): Set<string> {
  if (Array.isArray(node)) node.forEach((item) => called(item, into));
  else if (node && typeof node === "object") {
    const o = node as Record<string, unknown>;
    if (typeof o.predict === "string") into.add(o.predict);
    Object.values(o).forEach((value) => called(value, into));
  }
  return into;
}

/** The document with every predictor it calls declared; unchanged when it calls none it lacks. */
export function declareCalled(ir: Record<string, unknown>, workspace: Pick<Predictor, "name" | "inputs">[]): Record<string, unknown> {
  const declared = { ...((ir.predictors as Declared | undefined) ?? {}) };
  let added = false;
  for (const name of called({ constraints: ir.constraints, objective: ir.objective })) {
    if (declared[name]) continue;
    const found = workspace.find((p) => p.name === name);
    if (!found) continue;
    declared[name] = { inputs: found.inputs.length };
    added = true;
  }
  return added ? { ...ir, predictors: declared } : ir;
}
