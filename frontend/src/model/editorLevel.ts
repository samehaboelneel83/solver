/**
 * Simple or Expert: how much of the model editor a person sees.
 *
 * Simple shows the model in plain words and boxes, one card open at a time,
 * with one “+ Add” per section. Expert shows everything: the equation line,
 * the drill-down diagram, every card's own view switch, Blocks, the graph,
 * the exact IR and the special rule kinds. Nothing is lost by switching;
 * both edit the same draft. The choice is remembered in this browser.
 */
import { createContext, useContext, useState } from "react";

export type EditorLevel = "simple" | "expert";
const KEY = "solver_editor_level";

export function useEditorLevel(): [EditorLevel, (next: EditorLevel) => void] {
  const [level, setLevel] = useState<EditorLevel>(() => {
    try {
      return localStorage.getItem(KEY) === "expert" ? "expert" : "simple";
    } catch {
      return "simple";
    }
  });
  return [level, (next) => {
    setLevel(next);
    try {
      localStorage.setItem(KEY, next);
    } catch {
      // Without storage the choice holds for this page only.
    }
  }];
}

/** The level the editor is at, for parts deep in it (the view switches). Expert where nothing says. */
export const EditorLevelContext = createContext<EditorLevel>("expert");
export const useLevel = () => useContext(EditorLevelContext);
