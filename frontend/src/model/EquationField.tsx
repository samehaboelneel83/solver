/**
 * One equation, typed as text (plan: rules and goals as equations). It reads
 * the text on every keystroke and says at once what is wrong and where, but
 * writes to the model only on Enter or leaving the field, and only a text that
 * reads cleanly. Until then the model keeps its last good equation.
 *
 * Name chips under the field insert a set, variable or parameter at the
 * cursor, so nobody has to remember how things are spelt.
 */
import { useEffect, useId, useRef, useState } from "react";
import type { Parsed } from "./formula";
import type { ModelContext } from "./terms";

export type Chip = { insert: string; label: string; title: string };

/** The names a person can put in an equation, as chips. */
export function chipsFor(context: ModelContext): Chip[] {
  return [
    ...Object.entries(context.variables)
      .filter(([, spec]) => spec.domain !== "interval")
      .map(([name, spec]) => ({ insert: spec.index.length ? `${name}[]` : name, label: spec.index.length ? `${name}[${spec.index.join(", ")}]` : name, title: `Decision ${name}` })),
    ...Object.entries(context.parameters).map(([name, spec]) => ({
      insert: spec.index.length ? `${name}[]` : name,
      label: spec.index.length ? `${name}[${spec.index.join(", ")}]` : name,
      title: `Data ${name}`,
    })),
    { insert: "sum( for  in )", label: "sum(… for i in set)", title: "A sum over a set" },
  ];
}

export default function EquationField<T>({
  label,
  equation,
  parse,
  onCommit,
  chips,
  placeholder,
  sets,
}: {
  label: string;
  /** The model's current equation; null starts an empty field. */
  equation: string | null;
  parse: (text: string) => Parsed<T>;
  onCommit: (value: T, text: string) => void;
  chips: Chip[];
  placeholder?: string;
  /** The model's sets, shown with the chips as a reminder of what `in` can name. */
  sets: string[];
}) {
  const id = useId();
  const input = useRef<HTMLTextAreaElement>(null);
  const [text, setText] = useState(equation ?? "");
  const [editing, setEditing] = useState(false);
  // The model changed from elsewhere (structure view, undo, another tab):
  // show it, unless the person is mid-edit.
  useEffect(() => {
    if (!editing) setText(equation ?? "");
  }, [equation, editing]);

  const parsed = text.trim() === "" ? null : parse(text);
  const problem = parsed && !parsed.ok ? parsed : null;

  function commit() {
    // An equation that does not read stays on screen with its problem; the
    // model keeps its last good one until this one is fixed or Esc undoes it.
    if (!parsed?.ok) return;
    setEditing(false);
    if (text.trim() !== (equation ?? "").trim()) onCommit(parsed.value, text);
  }

  function insert(chip: Chip) {
    const field = input.current;
    const start = field?.selectionStart ?? text.length;
    const end = field?.selectionEnd ?? text.length;
    const next = text.slice(0, start) + chip.insert + text.slice(end);
    setEditing(true);
    setText(next);
    // Put the cursor where the next thing is typed: inside brackets, or after.
    const bracket = chip.insert.indexOf("[]");
    const caret = start + (bracket >= 0 ? bracket + 1 : chip.insert.indexOf("( ") >= 0 ? 4 : chip.insert.length);
    requestAnimationFrame(() => {
      field?.focus();
      field?.setSelectionRange(caret, caret);
    });
  }

  return (
    <div className="min-w-0 flex-1">
      <label htmlFor={id} className="sr-only">
        {label}
      </label>
      <textarea
        id={id}
        ref={input}
        rows={Math.min(4, Math.max(1, Math.ceil(text.length / 90)))}
        spellCheck={false}
        value={text}
        placeholder={placeholder}
        aria-invalid={problem ? true : undefined}
        aria-describedby={problem ? `${id}-problem` : `${id}-hint`}
        onFocus={() => setEditing(true)}
        onChange={(event) => {
          setEditing(true);
          setText(event.target.value);
        }}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            commit();
          }
          if (event.key === "Escape") {
            setText(equation ?? "");
            setEditing(false);
          }
        }}
        className={`block w-full resize-y rounded-md border bg-white px-3 py-2 font-mono text-sm text-slate-900 ${problem ? "border-red-400" : "border-slate-300"}`}
      />
      {problem ? (
        <p id={`${id}-problem`} role="alert" className="mt-1 text-xs text-red-700">
          {problem.message}
          <span className="mt-1 block overflow-x-auto whitespace-pre font-mono text-slate-600">
            {text.slice(0, problem.at)}
            <mark className="rounded bg-red-100 px-0.5 text-red-800">{text.slice(problem.at, Math.max(problem.end, problem.at + 1)) || " "}</mark>
            {text.slice(Math.max(problem.end, problem.at + 1))}
          </span>
        </p>
      ) : (
        <p id={`${id}-hint`} className="mt-1 text-xs text-slate-500">
          {editing && parsed?.ok && text.trim() !== (equation ?? "").trim() ? "Press Enter to apply. Esc undoes the typing." : "Edit the equation; Enter applies it."}
        </p>
      )}
      {editing && (
        <div className="mt-1 flex flex-wrap items-center gap-1" aria-label="Insert a name">
          {chips.map((chip) => (
            <button
              key={chip.label}
              type="button"
              title={chip.title}
              // Keep the field focused, so the insert lands at the cursor.
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => insert(chip)}
              className="rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 font-mono text-xs text-slate-700 hover:border-slate-300"
            >
              {chip.label}
            </button>
          ))}
          {sets.length > 0 && <span className="ml-1 text-xs text-slate-500">sets: {sets.join(", ")}</span>}
        </div>
      )}
    </div>
  );
}
