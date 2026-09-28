import type { ReactNode } from "react";
import { Link } from "react-router-dom";

/** One Home section: a quiet title, an optional line of purpose and a
 * "View all" link, then its cards. Every section on Home uses it, so the
 * page reads as one system rather than three styles of heading. */
export default function HomeSection({ id, title, note, viewAll, children }: {
  id: string;
  title: string;
  note?: ReactNode;
  viewAll?: { to: string; label?: string };
  children: ReactNode;
}) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="mb-8">
      <div className="mb-3 flex items-baseline justify-between gap-4">
        <div>
          <h2 id={`${id}-title`} className="font-sans text-base font-semibold tracking-normal text-slate-900">{title}</h2>
          {note && <p className="mt-0.5 text-sm text-slate-500">{note}</p>}
        </div>
        {viewAll && (
          <Link to={viewAll.to} className="shrink-0 rounded py-1 text-sm font-medium text-blue-700 hover:underline">
            {viewAll.label ?? "View all"}
          </Link>
        )}
      </div>
      {children}
    </section>
  );
}

/** The card every Home tile uses: surface, hairline border, a lift on hover. */
export const HOME_CARD =
  "group flex min-w-0 items-start gap-3 rounded-lg border border-slate-200 bg-white p-4 text-left transition hover:border-slate-300 hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 disabled:opacity-60";

/** The small tinted square that carries a card's icon. */
export const HOME_ICON = "flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-blue-50 text-blue-700";
