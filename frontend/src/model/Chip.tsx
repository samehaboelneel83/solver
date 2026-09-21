import type { ReactNode } from "react";

/**
 * An inline blank in a rule sentence. Mono, because the value is a machine
 * name; the accent colour is the only one on the page that means "click to
 * edit this slot".
 */
export default function Chip({
  label,
  value,
  open,
  onToggle,
  children,
}: {
  label: string;
  value: string;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
}) {
  return (
    <span className="relative inline-block">
      <button
        type="button"
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-label={label}
        className="mx-0.5 rounded px-1 font-mono text-[0.95rem] text-blue-700 underline decoration-blue-200 underline-offset-2 hover:bg-blue-50"
        onClick={onToggle}
      >
        {value || "\u2026"}
      </button>
      {open && (
        <div
          role="dialog"
          aria-label={label}
          className="absolute left-0 z-20 mt-1 min-w-[14rem] rounded border border-slate-200 bg-white p-3 text-left"
        >
          {children}
        </div>
      )}
    </span>
  );
}
