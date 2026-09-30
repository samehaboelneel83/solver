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
/** What the Simple level offers. */
export const SIMPLE_VIEWS: readonly EquationView[] = ["sentence", "boxes"];
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

/** How rules and goals are shown on this page, remembered in this browser. */
export function useEquationView(): [EquationView, (next: EquationView) => void] {
  const [view, setView] = useState<EquationView>(() => {
    try {
      const stored = localStorage.getItem(EQUATION_VIEW_KEY) as EquationView | null;
      return stored && EQUATION_VIEWS.includes(stored) ? stored : "equation";
    } catch {
      return "equation";
    }
  });
  return [view, (next) => {
    setView(next);
    try {
      localStorage.setItem(EQUATION_VIEW_KEY, next);
    } catch {
      // Without storage the choice holds for this page only.
    }
  }];
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
  // Simple: one switch for the page (not one per card), between the two plain views.
  const simple = useLevel() === "simple";
  const pageSwitch = name === "all" || name.startsWith("all ");
  if (simple && !pageSwitch) return null;
  const options = simple ? SIMPLE_VIEWS : EQUATION_VIEWS;
  return (
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
