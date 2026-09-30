/**
 * Simple or Expert: how much of the platform a person sees -- the sidebar,
 * the model editor and the Runs page all follow the one setting.
 *
 * Simple shows the model in plain words and boxes, one card open at a time,
 * with one “+ Add” per section, a short sidebar, and a Solve button with no
 * solver to pick. Expert shows everything: the equation line, the drill-down
 * diagram, every card's own view switch, Blocks, the graph, the exact IR,
 * the special rule kinds, versions, scenarios, sources, operations and the
 * solver picker. Nothing is lost by switching. The choice is remembered in
 * this browser, and every part that reads it changes at once.
 */
import { createContext, useContext, useSyncExternalStore } from "react";

export type EditorLevel = "simple" | "expert";
const KEY = "solver_editor_level";
const CHANGED = "solver-level-changed";

function read(): EditorLevel {
  try {
    return localStorage.getItem(KEY) === "expert" ? "expert" : "simple";
  } catch {
    return "simple";
  }
}

// Without storage the choice holds for this page only.
let fallback: EditorLevel | null = null;

function subscribe(onChange: () => void) {
  window.addEventListener(CHANGED, onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(CHANGED, onChange);
    window.removeEventListener("storage", onChange);
  };
}

export function setEditorLevel(next: EditorLevel) {
  try {
    localStorage.setItem(KEY, next);
  } catch {
    fallback = next;
  }
  window.dispatchEvent(new Event(CHANGED));
}

export function useEditorLevel(): [EditorLevel, (next: EditorLevel) => void] {
  const level = useSyncExternalStore(subscribe, () => fallback ?? read(), () => "simple" as EditorLevel);
  return [level, setEditorLevel];
}

/** The level the editor is at, for parts deep in it (the view switches). Expert where nothing says. */
export const EditorLevelContext = createContext<EditorLevel>("expert");
export const useLevel = () => useContext(EditorLevelContext);
