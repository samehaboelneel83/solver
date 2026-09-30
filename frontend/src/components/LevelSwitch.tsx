/**
 * Simple or Expert, for the whole platform (simplification plan, phase 2):
 * in the top bar, so it is one click from any page. The sidebar, the model
 * editor and the Runs page all follow it.
 */
import { useEditorLevel, type EditorLevel } from "../model/editorLevel";

const HINT: Record<EditorLevel, string> = {
  simple: "The pages and choices a planner needs, in plain words",
  expert: "Everything: versions, scenarios, sources, operations, solver choice and the exact model",
};

export default function LevelSwitch() {
  const [level, setLevel] = useEditorLevel();
  return (
    <div role="group" aria-label="How much to show" className="inline-flex overflow-hidden rounded-md border border-slate-300 text-xs">
      {(["simple", "expert"] as const).map((option) => (
        <button key={option} type="button" aria-pressed={level === option} title={HINT[option]} onClick={() => setLevel(option)}
          className={`px-2.5 py-1.5 font-medium ${level === option ? "bg-blue-600 text-white" : "bg-white text-slate-700 hover:bg-slate-50"}`}>
          {option === "simple" ? "Simple" : "Expert"}
        </button>
      ))}
    </div>
  );
}
