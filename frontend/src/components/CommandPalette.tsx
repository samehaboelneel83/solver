import { useLocation, useNavigate } from "react-router-dom";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { Search } from "lucide-react";
import { buildNavGroups } from "../nav/registry";
import { useDomain } from "../hooks/useDomain";
import { parseRouteId } from "../lib/routeId";
import { useConfirmLeave } from "../hooks/useUnsavedChangesGuard";

type Entry = { to: string; label: string; group: string };

/**
 * Ctrl+K: every page of the app, found by typing (queue R22 / OAAS N05).
 * Arrow keys move, Enter opens, Escape closes. Only pages this account may
 * open are listed. Entries come from the shared nav registry via NAV_GROUPS.
 */
export default function CommandPalette({ open, onClose, can }: { open: boolean; onClose: () => void; can: (capability: string) => boolean }) {
  const id = useId();
  const navigate = useNavigate();
  const location = useLocation();
  const { domainId } = useDomain();
  const confirmLeave = useConfirmLeave();
  const pathProblem = location.pathname.match(/^\/domains\/[^/]+\/problems\/([^/]+)(?:\/|$)/);
  const problemId = parseRouteId(pathProblem ? pathProblem[1] : new URLSearchParams(location.search).get("problem"));
  const input = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [at, setAt] = useState(0);
  const entries: Entry[] = useMemo(
    () =>
      buildNavGroups({ domainId, problemId }).flatMap((g) =>
        g.items
          .filter((i) => !i.capability || can(i.capability))
          .map((i) => ({ to: i.to, label: i.label, group: g.label }))
      ),
    [can, domainId, problemId]
  );
  const needle = query.trim().toLowerCase();
  const found = needle ? entries.filter((e) => `${e.label} ${e.group}`.toLowerCase().includes(needle)) : entries;

  useEffect(() => {
    if (open) {
      const previous = document.activeElement;
      setQuery("");
      setAt(0);
      const frame = requestAnimationFrame(() => input.current?.focus());
      return () => {
        cancelAnimationFrame(frame);
        if (previous instanceof HTMLElement && previous.isConnected) previous.focus();
      };
    }
  }, [open]);

  if (!open) return null;

  function go(entry: Entry | undefined) {
    if (!entry || !confirmLeave()) return;
    onClose();
    navigate(entry.to);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-slate-900/40 p-4 pt-[12vh]" onMouseDown={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${id}-label`}
        className="w-full max-w-lg overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xl"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <label id={`${id}-label`} className="flex items-center gap-2 border-b border-slate-200 px-4">
          <Search className="h-4 w-4 text-slate-400" aria-hidden />
          <span className="sr-only">Go to a page</span>
          <input
            ref={input}
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setAt(0);
            }}
            onKeyDown={(event) => {
              // Search is the dialog's only tab stop.
              if (event.key === "Tab") event.preventDefault();
              else if (event.key === "Escape") onClose();
              else if (event.key === "ArrowDown") {
                event.preventDefault();
                setAt((i) => Math.min(i + 1, found.length - 1));
              } else if (event.key === "ArrowUp") {
                event.preventDefault();
                setAt((i) => Math.max(i - 1, 0));
              } else if (event.key === "Enter") go(found[at]);
            }}
            placeholder="Go to a page…"
            role="combobox"
            aria-expanded="true"
            aria-controls={`${id}-list`}
            aria-activedescendant={found[at] ? `${id}-${at}` : undefined}
            className="w-full bg-transparent py-3 text-sm text-slate-900 outline-none placeholder:text-slate-400"
          />
        </label>
        <ul id={`${id}-list`} role="listbox" className="max-h-80 overflow-y-auto py-1">
          {found.length === 0 && <li className="px-4 py-3 text-sm text-slate-500">No page is called that.</li>}
          {found.map((entry, i) => (
            <li
              key={entry.to}
              id={`${id}-${i}`}
              role="option"
              aria-selected={i === at}
              onMouseEnter={() => setAt(i)}
              onClick={() => go(entry)}
              className={`flex cursor-pointer items-center justify-between px-4 py-2 text-sm ${i === at ? "bg-blue-50 text-blue-700" : "text-slate-700"}`}
            >
              <span>{entry.label}</span>
              <span className="text-xs text-slate-400">{entry.group}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
