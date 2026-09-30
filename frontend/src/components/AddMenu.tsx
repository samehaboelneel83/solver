/**
 * One “+ Add …” button per section, opening what can be added there: a blank
 * item, the starting shapes, or a form. The panel closes itself when a choice
 * is made (`close`) and with Escape.
 */
import { useId, useState, type ReactNode } from "react";

export default function AddMenu({ label, children }: { label: string; children: (close: () => void) => ReactNode }) {
  const [open, setOpen] = useState(false);
  const panel = useId();
  return (
    <div className="mt-3" onKeyDown={(event) => event.key === "Escape" && setOpen(false)}>
      <button type="button" aria-expanded={open} aria-controls={panel} onClick={() => setOpen((current) => !current)}
        className="rounded-md border border-blue-600 bg-white px-3 py-2 text-sm font-medium text-blue-700 hover:bg-blue-50">
        {open ? "× Close" : `+ ${label}`}
      </button>
      {open && (
        <div id={panel} role="group" aria-label={label} className="mt-2 space-y-2 rounded-md border border-slate-200 bg-white p-3 shadow-sm">
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  );
}

/** A choice in an Add menu: what it makes, in a line, and why it is not offered yet when it is not. */
export function AddChoice({ title, hint, disabledReason, onPick }: {
  title: string;
  hint?: string;
  disabledReason?: string | null;
  onPick: () => void;
}) {
  return (
    <button type="button" disabled={!!disabledReason} onClick={onPick}
      className="block w-full rounded-md border border-slate-200 px-3 py-2 text-left text-sm hover:border-blue-300 hover:bg-blue-50 disabled:cursor-not-allowed disabled:opacity-60">
      <span className="font-medium text-slate-900">{title}</span>
      {(disabledReason || hint) && <span className="block text-xs text-slate-600">{disabledReason ? `Needs ${disabledReason} first.` : hint}</span>}
    </button>
  );
}
