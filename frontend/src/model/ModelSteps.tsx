/**
 * Step by step, at the Simple level: the model is built in the order a
 * person thinks about it -- what is involved, what is known, what is
 * decided, what must be true, what is best -- one step on screen at a time,
 * then checked. Each step says whether it is done, needs something, or has
 * something to fix; any step can be opened directly, and everything can be
 * shown on one page instead.
 *
 * And one list of what to fix, for the whole model, each item opening the
 * card that has it.
 */
import { useState } from "react";

export type Step = "sets" | "data" | "decisions" | "rules" | "goal" | "check";
export type StepStatus = "done" | "todo" | "fix" | "optional";

export const STEPS: { step: Step; title: string; hint: string }[] = [
  { step: "sets", title: "Things involved", hint: "The kinds of thing the rules range over: employees, days, products…" },
  { step: "data", title: "Data", hint: "What is known about them: demand, costs, capacities." },
  { step: "decisions", title: "Decisions", hint: "What the solver chooses." },
  { step: "rules", title: "Rules", hint: "What must be true of every plan." },
  { step: "goal", title: "Goal", hint: "What makes one plan better than another." },
  { step: "check", title: "Check", hint: "Read the whole model back, then publish it." },
];

const KEY = "solver_editor_steps";

/** Step by step (the default at Simple) or everything on one page; remembered in this browser. */
export function useStepByStep(): [boolean, (next: boolean) => void] {
  const [on, setOn] = useState(() => {
    try {
      return localStorage.getItem(KEY) !== "all";
    } catch {
      return true;
    }
  });
  return [on, (next) => {
    setOn(next);
    try {
      localStorage.setItem(KEY, next ? "steps" : "all");
    } catch {
      // Without storage the choice holds for this page only.
    }
  }];
}

const MARK: Record<StepStatus, { text: string; style: string; words: string }> = {
  done: { text: "✓", style: "bg-emerald-100 text-emerald-800", words: "done" },
  todo: { text: "•", style: "bg-slate-100 text-slate-600", words: "to do" },
  fix: { text: "!", style: "bg-rose-100 text-rose-700", words: "something to fix" },
  optional: { text: "–", style: "bg-slate-100 text-slate-500", words: "optional" },
};

export function Stepper({ current, status, onStep, onAll }: {
  current: Step;
  status: Record<Step, StepStatus>;
  onStep: (step: Step) => void;
  onAll: () => void;
}) {
  const at = STEPS.findIndex((s) => s.step === current);
  return (
    <nav aria-label="Steps" className="mb-4 space-y-2">
      <ol className="flex flex-wrap gap-1">
        {STEPS.map(({ step, title }, i) => {
          const mark = MARK[status[step]];
          return (
            <li key={step}>
              <button type="button" onClick={() => onStep(step)} aria-current={step === current ? "step" : undefined}
                aria-label={`Step ${i + 1}, ${title}: ${mark.words}`}
                className={`flex items-center gap-2 rounded-md border px-3 py-1.5 text-sm ${step === current ? "border-blue-600 bg-blue-50 font-medium text-blue-800" : "border-slate-200 bg-white text-slate-700 hover:border-slate-300"}`}>
                <span aria-hidden="true" className={`inline-flex h-5 w-5 items-center justify-center rounded-full text-xs font-semibold ${mark.style}`}>{mark.text}</span>
                <span>{i + 1}. {title}</span>
              </button>
            </li>
          );
        })}
      </ol>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-slate-600">{STEPS[at].hint}</p>
        <button type="button" className="text-xs text-blue-700 underline" onClick={onAll}>Show all steps on one page</button>
      </div>
    </nav>
  );
}

export function StepNav({ current, onStep }: { current: Step; onStep: (step: Step) => void }) {
  const at = STEPS.findIndex((s) => s.step === current);
  const back = STEPS[at - 1];
  const next = STEPS[at + 1];
  return (
    <div className="mb-6 flex flex-wrap items-center justify-between gap-2 border-t border-slate-200 pt-3">
      {back ? (
        <button type="button" className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700" onClick={() => onStep(back.step)}>
          ← Back: {back.title}
        </button>
      ) : <span />}
      {next && (
        <button type="button" className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white" onClick={() => onStep(next.step)}>
          Next: {next.title} →
        </button>
      )}
    </div>
  );
}

export type Fix = { key: string; where: string; message: string; go: () => void };

/** Everything the model still needs, in one place, each opening where it is. Nothing when all is well. */
export function ThingsToFix({ items }: { items: Fix[] }) {
  const [open, setOpen] = useState(true);
  if (items.length === 0) return null;
  return (
    <section aria-label="Things to fix" className="mb-4 rounded-md border border-rose-200 bg-rose-50 p-3 text-sm">
      <div className="flex items-center justify-between gap-2">
        <h2 className="font-sans text-sm font-semibold tracking-normal text-rose-800">{items.length} {items.length === 1 ? "thing" : "things"} to fix before publishing</h2>
        <button type="button" aria-expanded={open} className="text-xs text-rose-800 underline" onClick={() => setOpen(!open)}>
          {open ? "Hide" : "Show"}
        </button>
      </div>
      {open && (
        <ul className="mt-2 space-y-1">
          {items.map((item) => (
            <li key={item.key} className="flex flex-wrap items-baseline gap-2">
              <button type="button" className="font-medium text-rose-800 underline" onClick={item.go}>{item.where}</button>
              <span className="text-rose-900">{item.message}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
