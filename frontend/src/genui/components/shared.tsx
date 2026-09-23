import { createContext, useContext, type ReactNode } from "react";
import type { ComponentRecord } from "../runtime/store";

export type Variant = "compact" | "expanded";
export type GenUIProps = { record: ComponentRecord; variant: Variant };

/** Where the components sit: which scenario, so an action can link to it. */
export type WorkspaceContext = { problemId: number | null; scenarioId: number | null };
export const GenUIContext = createContext<WorkspaceContext>({ problemId: null, scenarioId: null });
export const useWorkspaceContext = () => useContext(GenUIContext);

export function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** Six significant figures: a solver's 4.99999862 is the 5 it was held to. */
export function formatNumber(value: unknown): string {
  const n = num(value);
  if (n === null) return "—";
  if (n !== 0 && (Math.abs(n) >= 1e9 || Math.abs(n) < 1e-4)) return n.toExponential(3);
  return Number(n.toPrecision(6)).toLocaleString("en-US", { maximumFractionDigits: 6 });
}

export function formatPercent(value: unknown): string {
  const n = num(value);
  return n === null ? "—" : `${Number((n * 100).toPrecision(3))}%`;
}

export function formatSeconds(value: unknown): string {
  const n = num(value);
  if (n === null) return "—";
  return n < 1 ? `${Math.round(n * 1000)} ms` : `${Number(n.toPrecision(3))} s`;
}

export function Card({ title, children, tone = "plain" }: { title: string; children: ReactNode; tone?: "plain" | "warn" | "bad" }) {
  const border = tone === "bad" ? "border-rose-300" : tone === "warn" ? "border-amber-300" : "border-slate-200";
  return (
    <section className={`rounded-lg border ${border} bg-white p-3 text-sm text-slate-700 shadow-sm`}>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</h3>
      {children}
    </section>
  );
}

export function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-0.5">
      <dt className="text-slate-500">{label}</dt>
      <dd className="font-mono tabular-nums text-slate-900">{value}</dd>
    </div>
  );
}

/** A placeholder bar; `w` a Tailwind width class, so a skeleton keeps the card's geometry. */
export function Bar({ w = "w-full", h = "h-3" }: { w?: string; h?: string }) {
  return <div className={`genui-shimmer rounded ${w} ${h}`} />;
}

export function SkeletonCard({ title, rows, children }: { title: string; rows?: number; children?: ReactNode }) {
  return (
    <section
      className="rounded-lg border border-slate-200 bg-white p-3 text-sm shadow-sm"
      aria-busy="true"
      aria-label={`${title}, loading`}
    >
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">{title}</h3>
      {children ?? (
        <div className="space-y-2">
          {Array.from({ length: rows ?? 3 }).map((_, i) => (
            <div key={i} className="flex justify-between gap-4">
              <Bar w="w-1/3" />
              <Bar w="w-1/4" />
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
