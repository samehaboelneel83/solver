/**
 * The four ways a rule, a goal or a declaration is shown -- Sentence, Boxes,
 * Diagram, Equation, simplest first -- and the switches between them: one for
 * the page (remembered in this browser), one on each card.
 */
import { useEffect, useRef, useState } from "react";
import { useLevel } from "./editorLevel";

/** How a rule, goal or declaration is shown: in words, as nested boxes, as a drill-down diagram, or as one equation line. */
export type EquationView = "sentence" | "boxes" | "diagram" | "equation";
const EQUATION_VIEWS: readonly EquationView[] = ["sentence", "boxes", "diagram", "equation"];
/** What the Simple level offers: the equation too, a typed line (benchmark, October 2026: Expert only). */
export const SIMPLE_VIEWS: readonly EquationView[] = ["sentence", "boxes", "equation"];
/** A line under the Simple switch saying what each view is for. */
const HINT: Record<EquationView, string> = {
  sentence: "Sentence: each rule in plain words, with blanks to fill.",
  boxes: "Boxes: the parts of each rule, one inside another.",
  diagram: "Diagram: each rule drawn as a tree.",
  equation: "Equation: each rule as one line you can type, e.g. sum(x[s] for s in site) <= 3.",
};
/** The view shown at a level: Simple reads Diagram and Equation as Sentence. */
export const viewAt = (view: EquationView, simple: boolean): EquationView =>
  simple && !SIMPLE_VIEWS.includes(view) ? "sentence" : view;
const VIEW_TEXT: Record<EquationView, { button: string; all: string; one: string }> = {
  sentence: { button: "Sentence", all: "sentences", one: "a sentence" },
  boxes: { button: "Boxes", all: "boxes", one: "boxes" },
  diagram: { button: "Diagram", all: "diagrams", one: "a diagram" },
  equation: { button: "Equation", all: "equations", one: "an equation" },
};
const EQUATION_VIEW_KEY = "solver_equation_view";

/** How rules and goals are shown on this page, remembered in this browser -- per level: Expert
 * starts on equations, Simple on sentences, and an equation chosen in Simple is kept there. */
export function useEquationView(simple = false): [EquationView, (next: EquationView) => void] {
  const key = simple ? `${EQUATION_VIEW_KEY}_simple` : EQUATION_VIEW_KEY;
  const start: EquationView = simple ? "sentence" : "equation";
  const read = (): EquationView => {
    try {
      const stored = localStorage.getItem(key) as EquationView | null;
      return stored && EQUATION_VIEWS.includes(stored) ? stored : start;
    } catch {
      return start;
    }
  };
  const [view, setView] = useState<EquationView>(read);
  const [shownFor, setShownFor] = useState(key);
  if (shownFor !== key) {
    // The level switched: the view remembered for that level.
    setShownFor(key);
    setView(read());
  }
  return [view, (next) => {
    setView(next);
    try {
      localStorage.setItem(key, next);
    } catch {
      // Without storage the choice holds for this page only.
    }
  }];
}

/** Whether the person chose this view themselves, rather than it being where the level starts: a new
 * rule or goal then opens in it, not in boxes (benchmark round 3). */
export function viewChosen(simple: boolean, view: EquationView): boolean {
  try {
    return localStorage.getItem(simple ? `${EQUATION_VIEW_KEY}_simple` : EQUATION_VIEW_KEY) === view;
  } catch {
    return false;
  }
}

/** Sentence | Boxes | Diagram | Equation, as pressed-state buttons: the simplest first. */
export function ViewToggle({ value, onChange, name, size = "sm" }: {
  value: EquationView;
  onChange: (next: EquationView) => void;
  /** What is being shown, for the buttons' names: "all" or "all declarations" (a page switch), or one item's name. */
  name: string;
  size?: "sm" | "xs";
}) {
  const pad = size === "sm" ? "px-3 py-1 text-sm" : "px-2 py-0.5 text-xs";
  // Simple: one switch for the page (not one per card), between its three views, with a line on the one shown.
  const simple = useLevel() === "simple";
  const pageSwitch = name === "all" || name.startsWith("all ");
  if (simple && !pageSwitch) return null;
  const options = simple ? SIMPLE_VIEWS : EQUATION_VIEWS;
  const buttons = (
    <div role="group" aria-label={`Show ${name} as`} className="inline-flex overflow-hidden rounded-md border border-slate-300">
      {options.map((option) => (
        <button
          key={option}
          type="button"
          aria-pressed={value === option}
          aria-label={name === "all" || name.startsWith("all ") ? `Show ${name} as ${VIEW_TEXT[option].all}` : `Show ${name} as ${VIEW_TEXT[option].one}`}
          onClick={() => onChange(option)}
          className={`${pad} ${value === option ? "bg-blue-600 font-medium text-white" : "bg-white text-slate-700 hover:bg-slate-50"}`}
        >
          {VIEW_TEXT[option].button}
        </button>
      ))}
    </div>
  );
  if (!simple) return buttons;
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      {buttons}
      <span className="text-xs text-slate-500">{HINT[value] ?? HINT.sentence}</span>
    </span>
  );
}

/** A card's own view: the page's until the card is switched, and the page's again when the page switches. */
export function useCardView(page: EquationView, initial?: EquationView): [EquationView, (next: EquationView) => void] {
  // A card just composed opens where it is built (`initial`); the page's switch still takes it along.
  const [own, setOwn] = useState<EquationView | null>(initial ?? null);
  // Follow the page's switch when it changes -- not when the card first appears.
  const followed = useRef(page);
  useEffect(() => {
    if (followed.current !== page) {
      followed.current = page;
      setOwn(null);
    }
  }, [page]);
  return [own ?? page, setOwn];
}
