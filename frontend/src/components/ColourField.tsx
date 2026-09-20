import { useEffect, useId, useRef, useState } from "react";
import { FieldError, FieldLabel, INPUT_CLASS } from "./attrTypes";
import { fallbackColour, labelForeground, normaliseColour } from "../lib/colour";

/**
 * The colour control for an entity type or a relationship type.
 *
 * Three things it has to get right, none of which a plain
 * `<input type="color">` does on its own:
 *
 * **"No colour" has to be reachable.** A native colour input has no empty
 * state -- it always reports something -- so `null` needs its own control.
 * That matters because null is not a cosmetic default: it is what lets the
 * graph assign a deterministic fallback, and re-deriving one after a user
 * has explicitly chosen a colour would be wrong.
 *
 * **The hex has to be typeable.** The swatch is a picker; the text box is
 * how a value from a brand palette or a design tool gets in. It accepts
 * either case, because the API does (and stores lower case).
 *
 * **The choice has to show what it will look like.** The preview is the
 * type's name drawn in the label colour the canvas will use on that fill,
 * which is the only place in this app that judgement is visible at all --
 * the canvas is a bitmap, so nothing can be inspected there. It is large
 * bold text, so its contrast floor is WCAG's 3:1 for large text, which the
 * foreground rule clears for every possible fill.
 */

type ColourFieldProps = {
  /** The stored colour, or null for "not chosen". */
  value: string | null;
  onChange: (value: string | null) => void;
  /**
   * Why the box cannot be committed, or null when it can.
   *
   * `onChange` reports VALUES, and an unparseable entry has none -- which
   * is exactly how this field used to fail silently: the parent form
   * heard nothing, submitted, dropped what the user typed and toasted
   * "Entity type saved". Every other invalid field in the product blocks
   * the save, so this one has to be able to as well, and a value callback
   * cannot say "there is no value, and here is why". Fired on every
   * change of the problem, including back to null when the box becomes
   * valid again or the row is re-seeded underneath the field.
   */
  onProblemChange?: (problem: string | null) => void;
  /**
   * The message the enclosing form wants shown for this field, which wins
   * over the one derived here. It is what keeps a refused save to ONE
   * message per field: the form's error summary and the text under the
   * control say the same thing, as they do for every other field.
   */
  error?: string;
  /** The id whose fallback colour is previewed when nothing is chosen --
   * the same id the canvas keys on, so the preview is not a lie. */
  fallbackKey: string;
  /** Drawn inside the preview, so the contrast is judged on real text. */
  sampleText: string;
  label?: string;
  disabled?: boolean;
};

export default function ColourField({
  value,
  onChange,
  onProblemChange,
  error,
  fallbackKey,
  sampleText,
  label = "Colour",
  disabled,
}: ColourFieldProps) {
  const baseId = useId();
  const textId = `${baseId}-hex`;
  const [draft, setDraft] = useState(value ?? "");

  // Re-seed when the row changes underneath (a save returning the
  // normalised value, or a different type being selected on the canvas).
  useEffect(() => {
    setDraft(value ?? "");
  }, [value]);

  const trimmed = draft.trim();
  const parsed = normaliseColour(trimmed);
  const problem = trimmed !== "" && parsed === null ? "Use a six-digit hex colour, e.g. #1f77b4." : undefined;

  // Reported from an effect on the DERIVED problem rather than from the
  // change handler, so the re-seed above (a save elsewhere, or "Reload and
  // keep my changes") clears a stale problem too -- otherwise a form could
  // be left refusing a save over a box that no longer holds anything wrong.
  const reportProblem = useRef(onProblemChange);
  reportProblem.current = onProblemChange;
  useEffect(() => {
    reportProblem.current?.(problem ?? null);
  }, [problem]);

  // What the canvas would draw: the chosen colour, or the fallback this id
  // hashes to. Computed from the *committed* value, not the draft, so a
  // half-typed hex does not flicker the preview through other colours.
  const shown = error ?? problem;

  const effective = normaliseColour(value) ?? fallbackColour(fallbackKey);
  const foreground = labelForeground(effective);

  function commit(next: string) {
    setDraft(next);
    const normalised = normaliseColour(next);
    if (next.trim() === "") {
      onChange(null);
    } else if (normalised !== null) {
      onChange(normalised);
    }
    // A partial or wrong entry is left uncommitted: `problem` explains it,
    // and the last good value stays until the box holds a real colour.
  }

  return (
    <div>
      <FieldLabel htmlFor={textId}>{label}</FieldLabel>
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="color"
          // The swatch always needs a concrete colour; when nothing is
          // chosen it shows the fallback, so picking "the colour it already
          // looks like" is one click rather than a hunt.
          value={effective}
          disabled={disabled}
          onChange={(event) => commit(event.target.value)}
          className="h-9 w-12 cursor-pointer rounded-md border border-slate-300 bg-white p-1"
          aria-label={`${label} swatch`}
          data-testid="colour-swatch"
        />
        <input
          id={textId}
          type="text"
          inputMode="text"
          autoComplete="off"
          spellCheck={false}
          placeholder="#1f77b4"
          className={`${INPUT_CLASS} w-32 font-mono`}
          value={draft}
          disabled={disabled}
          aria-invalid={shown ? "true" : undefined}
          aria-describedby={shown ? `${baseId}-error` : `${baseId}-hint`}
          onChange={(event) => commit(event.target.value)}
          data-testid="colour-hex"
        />
        <button
          type="button"
          onClick={() => {
            setDraft("");
            onChange(null);
          }}
          disabled={disabled || value === null}
          className="rounded-md border border-slate-300 px-2 py-1 text-xs text-slate-600 disabled:cursor-not-allowed disabled:opacity-40"
          data-testid="colour-clear"
        >
          Use automatic
        </button>
        <span
          className="rounded px-3 py-1 text-xl font-bold"
          style={{ backgroundColor: effective, color: foreground }}
          data-testid="colour-preview"
          data-fill={effective}
          data-foreground={foreground}
        >
          {sampleText}
        </span>
      </div>
      <p id={`${baseId}-hint`} className="mt-1 text-xs text-slate-500">
        {value === null
          ? "No colour chosen — the graph picks a stable one from this type's id."
          : "Used for this type's nodes and edges in both graph views."}
      </p>
      <FieldError id={`${baseId}-error`} message={shown} />
    </div>
  );
}
