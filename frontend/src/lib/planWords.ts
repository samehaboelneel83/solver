/**
 * A run's answer in plain words, before any table (simplification plan,
 * phase 4): whether there is a plan, what the goal came to, what was decided
 * and how the rules fared -- "Cost came to 43.53, as low as it can go. use:
 * Maize 64.29, Soybean meal 29.37, Wheat bran 6.35."
 *
 * Read from the run and the model it solved. Nothing is guessed: a decision
 * the run reports nothing for is left out rather than described as empty.
 */
import type { Run } from "../api/v1";

export type PlanWords = { headline: string; tone: "good" | "fair" | "bad"; lines: string[] };

const NUMBER = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });
const SHOWN = 4;

type Ir = {
  objective?: { sense?: string; terms?: { id?: string; note?: string }[] };
  variables?: Record<string, { domain?: string; index?: string[] }>;
};

/** "o_total_cost" -> "total cost"; "hours_per_week" -> "hours per week". */
export function plain(name: string): string {
  return name.replace(/^[a-z]_(?=[a-z])/, "").replace(/_/g, " ");
}

function number(value: number): string {
  return NUMBER.format(value);
}

function sentence(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function namer(run: Run, variable: string) {
  const sets = run.index_sets?.variables?.[variable];
  return (tuple: string[]) => tuple.map((key, i) => run.labels?.[sets?.[i] ?? ""]?.[key] ?? key).join(" · ");
}

function list(items: string[]): string {
  const shown = items.slice(0, SHOWN).join(", ");
  return items.length > SHOWN ? `${shown} and ${items.length - SHOWN} more` : shown;
}

function goalLine(run: Run, ir: Ir): string | null {
  if (run.objective === null || run.objective === undefined) return null;
  const value = Number(run.objective);
  if (!Number.isFinite(value)) return null;
  const terms = ir.objective?.terms ?? [];
  const minimise = (ir.objective?.sense ?? "minimize").startsWith("min");
  const name = terms.length === 1 ? terms[0].note?.trim() || plain(terms[0].id ?? "the goal") : "the goal";
  // A name is the author's choice and may not say what is counted ("Morning" for a late-slot
  // penalty, UX audit C-1): when it names none of the data the goal adds up, say that data too.
  const counts = [...new Set((ir.objective?.terms ?? []).flatMap((term) => dataRead((term as { expression?: unknown }).expression)))];
  const said = counts.length && !counts.some((c) => plain(c) === name.toLowerCase())
    ? `${sentence(name)}, the total of ${counts.map(plain).join(" and ")},`
    : sentence(name);
  const proven = run.status === "optimal";
  const how = minimise
    ? proven ? "as low as it can go" : "the lowest found"
    : proven ? "as high as it can go" : "the highest found";
  return `${said} came to ${number(value)}, ${how}.`;
}

/** The data values and record fields an expression reads, by name. */
function dataRead(node: unknown): string[] {
  if (Array.isArray(node)) return node.flatMap(dataRead);
  if (!node || typeof node !== "object") return [];
  const o = node as Record<string, unknown>;
  const own = typeof o.par === "string" ? [o.par] : (o.attr as { name?: string } | undefined)?.name ? [(o.attr as { name: string }).name] : [];
  return [...own, ...Object.values(o).flatMap(dataRead)];
}

function decisionLines(run: Run, ir: Ir): string[] {
  const lines: string[] = [];
  const names = Object.keys(ir.variables ?? {}).length ? Object.keys(ir.variables ?? {}) : Object.keys(run.assignments ?? {});
  for (const variable of names) {
    const name = namer(run, variable);
    const amounts = run.amounts?.[variable];
    if (amounts && amounts.length) {
      const taken = amounts.filter((a) => Math.abs(a.value) > 1e-9).sort((a, b) => Math.abs(b.value) - Math.abs(a.value));
      if (!taken.length) {
        lines.push(`${plain(variable)}: all zero.`);
        continue;
      }
      const text = taken.map((a) => (a.index.length ? `${name(a.index)} ${number(a.value)}` : number(a.value)));
      lines.push(`${plain(variable)}: ${list(text)}.`);
      continue;
    }
    const chosen = run.assignments?.[variable];
    if (!chosen) continue;
    const sets = run.index_sets?.variables?.[variable] ?? ir.variables?.[variable]?.index ?? [];
    const sizes = sets.map((set) => run.set_order?.[set]?.length);
    const total = sizes.length && sizes.every((n) => n !== undefined) ? sizes.reduce((a, b) => (a ?? 0) * (b ?? 0), 1) : null;
    const count = chosen.length;
    const of = total ? ` of ${total}` : "";
    lines.push(count
      ? `${plain(variable)}: ${count}${of} chosen — ${list(chosen.map(name))}.`
      : `${plain(variable)}: none chosen${total ? ` of ${total}` : ""}.`);
  }
  return lines;
}

function rulesLine(run: Run): string | null {
  const hard = run.constraints.filter((c) => c.hard);
  const soft = run.constraints.filter((c) => !c.hard);
  if (!hard.length && !soft.length) return null;
  const broke = hard.filter((c) => !c.satisfied).length;
  const bent = soft.filter((c) => !c.satisfied).length;
  const paid = soft.reduce((sum, c) => sum + (c.penalty_paid ?? 0), 0);
  const parts = [broke ? `${broke} required ${broke === 1 ? "rule" : "rules"} broke` : "Every required rule holds"];
  if (soft.length) parts.push(bent ? `${bent} ${bent === 1 ? "preference" : "preferences"} could not be met${paid ? `, at a cost of ${number(paid)}` : ""}` : "every preference is met");
  return `${parts.join("; ")}.`;
}

/** Null while the run has not settled. */
export function planWords(run: Run, ir: Record<string, unknown> | undefined): PlanWords | null {
  const model = (ir ?? {}) as Ir;
  switch (run.status) {
    case "queued":
    case "running":
      return null;
    case "optimal":
    case "feasible": {
      const lines = [goalLine(run, model), ...decisionLines(run, model), rulesLine(run)].filter((l): l is string => Boolean(l));
      return {
        headline: run.status === "optimal" ? "The best plan possible was found." : "A plan was found; a better one may exist.",
        tone: run.status === "optimal" ? "good" : "fair",
        lines,
      };
    }
    case "infeasible":
      return {
        headline: "No plan can meet every rule.",
        tone: "bad",
        lines: run.conflict?.length ? ["The rules that clash are listed just below: change or relax one of them and solve again."] : [],
      };
    default:
      // The error itself follows, as the run's alert: not said twice.
      return { headline: `No plan was found: the run ended ${run.status}.`, tone: "bad", lines: [] };
  }
}
