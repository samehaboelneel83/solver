/**
 * A problem as five steps -- Data, Model, Check, Solve, Results -- each done,
 * to do, to fix or waiting, and the one thing to do next (simplification
 * plan, phase 1). Read from the problem's readiness.
 */
import type { PreflightFinding, Readiness } from "../api/v1";

export type StepKey = "data" | "model" | "check" | "solve" | "results";
export type StepState = "done" | "todo" | "fix" | "wait";
export type Step = { key: StepKey; title: string; state: StepState; says: string };

export type NextAction =
  | { kind: "build" }
  | { kind: "publish-and-solve" }
  | { kind: "fill"; count: number }
  | { kind: "check" }
  | { kind: "fix" }
  | { kind: "solve" }
  | { kind: "follow"; runId: string | number }
  | { kind: "results"; runId: string | number };

const SETTLED_OK = new Set(["optimal", "feasible"]);
const RUNNING = new Set(["queued", "running"]);

export function missingOf(readiness: Readiness): PreflightFinding[] {
  return (readiness.check?.findings ?? []).filter((f) => f.code === "missing_values");
}

/** Blockers other than missing values, which the Data step shows and fills. */
export function otherBlockers(readiness: Readiness): PreflightFinding[] {
  return (readiness.check?.findings ?? []).filter((f) => f.kind === "blocker" && f.code !== "missing_values");
}

export function problemSteps(readiness: Readiness): Step[] {
  const { latest_version: latest, draft, check, last_run: run } = readiness;
  const missing = missingOf(readiness);
  const empty = (check?.findings ?? []).filter((f) => f.code === "set_empty");
  const counts = Object.entries(check?.sets ?? {}).map(([set, n]) => `${set}: ${n}`).join(" · ");
  const values = missing.reduce((n, f) => n + (f.missing?.records.length ?? 0), 0);

  const data: Step = !latest
    ? { key: "data", title: "Data", state: "wait", says: "The model says which records it needs; build it first, or add records now." }
    : !check
      ? { key: "data", title: "Data", state: "wait", says: "Checking whether today’s data is ready for this model." }
    : missing.length
      ? { key: "data", title: "Data", state: "fix", says: `${values} ${values === 1 ? "value is" : "values are"} missing. Fill ${values === 1 ? "it" : "them"} in below.` }
      : empty.length
        ? { key: "data", title: "Data", state: "todo", says: `No ${empty.map((f) => f.set).join(", ")} records yet.` }
        : { key: "data", title: "Data", state: "done", says: counts || "Every record the model reads is here." };

  const model: Step = !latest
    ? { key: "model", title: "Model", state: "todo", says: "Say what is decided, what must be true and what is best, then publish it." }
    : draft?.unpublished
      ? { key: "model", title: "Model", state: "todo", says: `Version ${latest.version} is published; your changes since are not yet.` }
      : { key: "model", title: "Model", state: "done", says: `Version ${latest.version} published.` };

  const blockers = otherBlockers(readiness);
  const checkStep: Step = !check
    ? { key: "check", title: "Check", state: "wait", says: "Checked once a version is published." }
    : check.ready
      ? { key: "check", title: "Check", state: "done", says: "Nothing stops it from solving." }
      : blockers.length
        ? { key: "check", title: "Check", state: "fix", says: `${blockers.length} ${blockers.length === 1 ? "thing stops" : "things stop"} it from solving.` }
        : { key: "check", title: "Check", state: "wait", says: "Ready once the missing values are filled in." };

  const solve: Step = run && RUNNING.has(run.status)
    ? { key: "solve", title: "Solve", state: "wait", says: run.status === "queued" ? "Waiting for a worker…" : "Solving…" }
    : run
      ? { key: "solve", title: "Solve", state: "done", says: `Last solved on the ${run.scenario} scenario.` }
      : { key: "solve", title: "Solve", state: check?.ready ? "todo" : "wait", says: check?.ready ? "Ready to solve." : "Once the checks pass." };

  const results: Step = !run || RUNNING.has(run.status)
    ? { key: "results", title: "Results", state: "wait", says: run ? "Coming when the run settles." : "No run yet." }
    : SETTLED_OK.has(run.status)
      ? { key: "results", title: "Results", state: "done", says: `A plan was found${run.objective !== null ? `, worth ${run.objective}` : ""}.` }
      : { key: "results", title: "Results", state: "fix", says: run.status === "infeasible"
          ? "No plan meets every rule; the results say which rules clash."
          : `The run ended ${run.status}; the results say why.` };

  return [data, model, checkStep, solve, results];
}

/** The one thing to do next, in the order a person would. */
export function nextAction(readiness: Readiness, canPublish: boolean): NextAction {
  const { latest_version: latest, draft, check, last_run: run } = readiness;
  if (!latest) return { kind: "build" };
  if (draft?.unpublished && canPublish) return { kind: "publish-and-solve" };
  if (!check) return { kind: "check" };
  const missing = missingOf(readiness).reduce((n, f) => n + (f.missing?.records.length ?? 0), 0);
  if (missing) return { kind: "fill", count: missing };
  if (check && !check.ready) return { kind: "fix" };
  if (run && RUNNING.has(run.status)) return { kind: "follow", runId: run.id };
  if (run) return { kind: "results", runId: run.id };
  return { kind: "solve" };
}
