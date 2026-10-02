import { useEffect, useState } from "react";

/**
 * How long the solver may look, chosen where Solve is pressed (benchmark, October 2026: every
 * button sent 30 seconds, a run stopped at a 2.9% gap, and "try a longer time limit" named nothing
 * to change). Remembered in this browser for the next solve.
 */
export const EFFORTS = [
  { seconds: 10, label: "Quick look (10 s)" },
  { seconds: 30, label: "Normal (30 s)" },
  { seconds: 120, label: "Thorough (2 min)" },
  { seconds: 600, label: "Long (10 min)" },
  { seconds: 1800, label: "Until proven best (up to 30 min)" },
] as const;

const KEY = "solver_solve_seconds";
const DEFAULT = 30;

function read(): number {
  try {
    const n = Number(localStorage.getItem(KEY));
    return EFFORTS.some((e) => e.seconds === n) ? n : DEFAULT;
  } catch {
    return DEFAULT;
  }
}

const listeners = new Set<(n: number) => void>();

/** The chosen time limit in seconds, shared by every Solve button on the page. */
export function useSolveSeconds(): [number, (n: number) => void] {
  const [seconds, setSeconds] = useState(read);
  useEffect(() => {
    listeners.add(setSeconds);
    return () => { listeners.delete(setSeconds); };
  }, []);
  const set = (n: number) => {
    try { localStorage.setItem(KEY, String(n)); } catch { /* kept for this page only */ }
    listeners.forEach((l) => l(n));
  };
  return [seconds, set];
}

export default function SolveEffort({ className = "" }: { className?: string }) {
  const [seconds, setSeconds] = useSolveSeconds();
  return (
    <label className={`inline-flex items-center gap-1 text-sm text-slate-700 ${className}`}>
      <span>Look for</span>
      <select aria-label="How long to look for an answer" className="rounded border border-slate-300 px-2 py-1 text-sm"
        value={seconds} onChange={(e) => setSeconds(Number(e.target.value))}>
        {EFFORTS.map((e) => <option key={e.seconds} value={e.seconds}>{e.label}</option>)}
      </select>
    </label>
  );
}
