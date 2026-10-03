/**
 * The Model editor's forms over the shared draft (Blockly edit mode spec §2).
 *
 * The draft is the whole IR document; the forms edit five of its keys. These
 * three functions are that projection and its inverse, and what the forms
 * have always published -- moved here from `ModelEditor` unchanged, so the
 * Blocks editor publishes exactly what the forms would.
 */
import { IR_VERSION } from "../ir/contract";
import { cleanVariable, type ParameterSpec, type VariableSpec } from "./declarations";
import { cleanBinding, cleanTerm, declaredRelationships, type Constraint, type ObjectiveTerm } from "./terms";

export type FormDraft = {
  sets: string[];
  parameters: Record<string, ParameterSpec>;
  variables: Record<string, VariableSpec>;
  constraints: Constraint[];
  objective: { sense: string; mode: string; terms: ObjectiveTerm[] };
};

/** The five keys the forms edit, copied so an edit never mutates the draft in place. */
export function formDraftOf(ir: Record<string, unknown>): FormDraft {
  const objective = (ir.objective ?? {}) as { sense?: string; mode?: string; terms?: ObjectiveTerm[] };
  return {
    sets: [...((ir.sets as string[]) ?? [])],
    parameters: { ...((ir.parameters as FormDraft["parameters"]) ?? {}) },
    variables: { ...((ir.variables as FormDraft["variables"]) ?? {}) },
    constraints: ((ir.constraints as Constraint[]) ?? []).map((c) => ({ ...c })),
    objective: {
      sense: objective.sense ?? "minimize",
      mode: objective.mode === "lex" ? "lex" : "weighted",
      terms: (objective.terms ?? []).map((t) => ({ ...t })),
    },
  };
}

/** `ir` with the forms' five keys replaced; every other key -- `relationships`, `version` -- kept. */
export function withFormDraft(ir: Record<string, unknown>, draft: FormDraft): Record<string, unknown> {
  return {
    ...ir,
    sets: draft.sets,
    parameters: draft.parameters,
    variables: draft.variables,
    constraints: draft.constraints,
    objective: { ...((ir.objective as Record<string, unknown>) ?? {}), ...draft.objective },
  };
}

/** What Publish sends: the draft as the contract wants it. */
export function publishable(ir: Record<string, unknown>): Record<string, unknown> {
  const draft = formDraftOf(ir);
  // An objective with no terms is refused by the contract -- "omit the
  // objective otherwise" -- because an empty one and an absent one would
  // otherwise be two spellings of "optimise nothing". A model with only
  // rules is legitimate: it asks for any answer that satisfies them.
  const { objective: _previous, relationships: _edges, ...withoutObjective } = ir;
  const walked = declaredRelationships(draft.constraints, draft.objective.terms);
  return {
    ...withoutObjective,
    // The editor always writes the current version: version 2 is version 1
    // plus what it adds, so a model started as 1 is still valid as 2, and
    // a condition or a curve added to it is refused in 1 with no control
    // on this screen to change that.
    version: IR_VERSION,
    sets: draft.sets,
    // Derived from the walks, not declared by hand. `sets` is declared
    // because a set may legitimately be carried and never used -- for
    // display, or for a later version (contract 3.1). A relationship has no
    // such use: you declare one to walk it. Deriving it removes the only
    // way this screen could build a `binding_via_rel_not_declared`.
    ...(walked.length > 0 ? { relationships: walked } : {}),
    parameters: draft.parameters,
    variables: Object.fromEntries(
      Object.entries(draft.variables).map(([name, spec]) => [name, cleanVariable(spec)])
    ),
    // A rule left as it was started, "0 is at most 0", says nothing: it is not published (benchmark
    // round 3: blank rules made by a mis-click lingered in the model).
    constraints: draft.constraints.filter((c) => !isBlankRule(c)).map((constraint) => {
      // A hard rule must not carry a weight (contract §3.4); a soft one
      // must. The Strength control keeps the draft honest, and this
      // strips a leftover weight so Publish is not blocked by a key
      // the person can no longer see.
      let next: Constraint =
        constraint.severity === "soft"
          ? {
              ...constraint,
              weight: constraint.weight && constraint.weight >= 1 ? constraint.weight : 1,
            }
          : (() => {
              const { weight: _dropped, ...rest } = constraint;
              return rest;
            })();
      // A blank "What it means" is not prose — omit the key rather than
      // publish an empty string.
      if (!next.note?.trim()) {
        const { note: _blank, ...rest } = next;
        next = rest;
      }
      // An empty forall is refused; omit it the same way the editor does
      // when the last index is removed.
      if (Array.isArray(next.forall) && next.forall.length === 0) {
        const { forall: _empty, ...rest } = next;
        next = rest;
      }
      // Drop empty where arrays and any UI-only `problems` left on a
      // binding after a filter was refused then fixed.
      if (next.forall) {
        next = { ...next, forall: next.forall.map(cleanBinding) };
      }
      if (next.left) next = { ...next, left: cleanTerm(next.left) };
      if (next.right) next = { ...next, right: cleanTerm(next.right) };
      if (next.no_overlap) {
        next = { ...next, no_overlap: { ...next.no_overlap, over: next.no_overlap.over.map(cleanBinding) } };
      }
      if (next.cumulative) {
        const body = next.cumulative;
        next = {
          ...next,
          cumulative: {
            ...body,
            over: body.over.map(cleanBinding),
            demand: cleanTerm(body.demand),
            capacity: cleanTerm(body.capacity),
          },
        };
      }
      return next;
    }),
    ...(draft.objective.terms.length > 0
      ? {
          objective: {
            sense: draft.objective.sense,
            ...(draft.objective.mode === "lex" ? { mode: "lex" } : {}),
            terms: draft.objective.terms.map((term) => ({
              ...term,
              expression: term.expression ? cleanTerm(term.expression) : term.expression,
            })),
          },
        }
      : {}),
  };
}

/** A model with nothing in it: what "start from scratch" means. The keys are
 * all present because the contract requires every top-level key, including
 * the empty ones -- a missing `constraints` is a different document from an
 * empty one, and only one of them is valid. */
export const EMPTY_MODEL = {
  version: 2,
  sets: [],
  parameters: {},
  variables: {},
  constraints: [],
  objective: { sense: "minimize", mode: "weighted", terms: [] },
} as const;

/** A rule still as "A blank rule" starts it: 0 is at most 0, nothing else. */
export function isBlankRule(c: Constraint): boolean {
  const zero = (t: unknown) => !!t && typeof t === "object" && Object.keys(t).length === 1 && (t as { const?: unknown }).const === 0;
  return zero(c.left) && zero(c.right) && c.relation === "<=" && !c.note?.trim()
    && !(c as { when?: unknown }).when && !(c as { chance?: unknown }).chance;
}
