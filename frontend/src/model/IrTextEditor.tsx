import { useEffect, useMemo, useState } from "react";
import { checkIrShape } from "../ir/validate";

type Json = Record<string, unknown>;

/** Where in the text a JSON parse failed, as line and column (the browsers' messages differ; the position is ours). */
function parseError(text: string): { message: string; line?: number; column?: number } | null {
  try {
    const value = JSON.parse(text);
    if (typeof value !== "object" || value === null || Array.isArray(value)) {
      return { message: "A model is one JSON object: { \"version\": 2, \"sets\": [...], ... }" };
    }
    return null;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    const at = /position (\d+)/.exec(message);
    if (!at) return { message };
    const before = text.slice(0, Number(at[1]));
    const line = before.split("\n").length;
    return { message, line, column: Number(at[1]) - before.lastIndexOf("\n") };
  }
}

/**
 * The model as its exact IR, editable: every construct of the contract -- generated sets, placement rules, any key
 * a form does not draw -- can be written here, checked as it is typed by the same rules as the server, and applied
 * to the same draft the forms and Blocks edit (owner, 9 October 2026: everything doable without the Assistant).
 */
export function IrTextEditor({ ir, canEdit, refusal, onApply }: {
  ir: Json;
  canEdit: boolean;
  /** The server's refusal of the current draft (its dry run), shown beside the local check. */
  refusal?: { loc: (string | number)[]; message: string; code?: string } | null;
  onApply: (next: Json) => void;
}) {
  const shown = useMemo(() => JSON.stringify(ir, null, 2), [ir]);
  const [text, setText] = useState(shown);
  const [dirty, setDirty] = useState(false);
  // A change made elsewhere (forms, Blocks) shows here unless this text has edits of its own.
  useEffect(() => {
    if (!dirty) setText(shown);
  }, [shown, dirty]);

  const syntax = useMemo(() => parseError(text), [text]);
  const contract = useMemo(() => (syntax ? null : checkIrShape(JSON.parse(text))), [syntax, text]);

  return (
    <section aria-label="Exact IR" className="mb-6">
      <p className="mb-2 text-sm text-slate-600">
        {canEdit
          ? "The model exactly as it is stored. Edit it here for anything the forms do not draw (generated sets, placement rules, any contract key); it is checked as you type, and Apply puts it into the same draft the other tabs edit."
          : "The model exactly as it is stored (read-only for this account)."}
      </p>
      <label className="sr-only" htmlFor="exact-ir-text">Exact IR (JSON)</label>
      <textarea
        id="exact-ir-text"
        spellCheck={false}
        readOnly={!canEdit}
        value={text}
        onChange={(event) => {
          setText(event.target.value);
          setDirty(true);
        }}
        rows={28}
        className="w-full rounded-lg border border-slate-300 bg-slate-50 p-3 font-mono text-xs"
        aria-invalid={Boolean(syntax || contract)}
        aria-describedby="exact-ir-check"
      />
      <div id="exact-ir-check" role="status" className="mt-2 text-sm">
        {syntax ? (
          <p className="text-red-700">
            Not valid JSON{syntax.line ? ` (line ${syntax.line}, column ${syntax.column})` : ""}: {syntax.message}
          </p>
        ) : contract ? (
          <p className="text-red-700">
            {contract.message} <span className="font-mono text-xs">[{contract.code} at {contract.loc.join(" / ") || "the top"}]</span>
          </p>
        ) : dirty ? (
          <p className="text-green-800">The contract accepts this model. Apply it to check it against this domain's data too.</p>
        ) : refusal ? (
          <p className="text-amber-800">
            The server refuses the current draft: {refusal.message}{" "}
            <span className="font-mono text-xs">[{refusal.code ? `${refusal.code} at ` : "at "}{refusal.loc.join(" / ") || "the top"}]</span>
          </p>
        ) : null}
      </div>
      {canEdit && (
        <div className="mt-2 flex gap-2">
          <button
            type="button"
            className="rounded bg-blue-700 px-3 py-1.5 text-sm text-white disabled:opacity-50"
            disabled={!dirty || Boolean(syntax)}
            onClick={() => {
              onApply(JSON.parse(text));
              setDirty(false);
            }}
          >
            Apply to the draft
          </button>
          <button
            type="button"
            className="rounded border px-3 py-1.5 text-sm disabled:opacity-50"
            disabled={!dirty}
            onClick={() => {
              setText(shown);
              setDirty(false);
            }}
          >
            Discard edits
          </button>
        </div>
      )}
    </section>
  );
}
