import { useEffect, useId, useState, type ReactNode } from "react";

/**
 * Nested-block chrome for the Model editor, matching the look of
 * MrLightful's shadcn tree-view (chevron that rotates, hover row, indented
 * children) without pulling in Radix, lucide or shadcn CSS variables.
 *
 * It does not own modelling: callers still edit IR terms. Drag-and-drop is
 * omitted on purpose — reordering a sum or product is not a tree-file
 * move, and would change what the model means.
 *
 * @see https://github.com/MrLightful/shadcn-tree-view
 */

function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

function ChevronRight({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="m9 18 6-6-6-6" />
    </svg>
  );
}

export type TreeItemProps = {
  itemId?: string;
  name: string;
  /** When true, no chevron: the body stays visible. */
  leaf?: boolean;
  defaultOpen?: boolean;
  header: ReactNode;
  /** Shown instead of `header` while closed -- a one-line summary that opens the item. */
  collapsedHeader?: ReactNode;
  /** Each new value opens the item (a “go to it” from elsewhere on the page). */
  openSignal?: number;
  actions?: ReactNode;
  children?: ReactNode;
  className?: string;
};

export function TreeItem({
  itemId,
  name,
  leaf = false,
  defaultOpen = true,
  header,
  collapsedHeader,
  openSignal,
  actions,
  children,
  className,
}: TreeItemProps) {
  const generatedId = useId();
  const panelId = itemId ?? generatedId;
  const [open, setOpen] = useState(defaultOpen);
  useEffect(() => {
    if (openSignal !== undefined) setOpen(true);
  }, [openSignal]);
  const showChildren = leaf || open;

  return (
    <div className={cn("relative", className)}>
      <div
        className={cn(
          "group relative z-0 flex items-center gap-1 rounded-lg px-2 py-1.5",
          "before:absolute before:inset-y-0 before:left-0 before:-z-10 before:w-full before:rounded-lg",
          "before:bg-slate-100 before:opacity-0 hover:before:opacity-100",
          !leaf && open && "before:opacity-70"
        )}
      >
        {leaf ? (
          <span className="inline-flex h-6 w-6 shrink-0" />
        ) : (
          <button
            type="button"
            aria-expanded={open}
            aria-controls={panelId}
            aria-label={open ? `Collapse ${name}` : `Expand ${name}`}
            className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded text-slate-500 hover:text-slate-800"
            onClick={() => setOpen((current) => !current)}
          >
            <ChevronRight
              className={cn("h-4 w-4 transition-transform", open && "rotate-90")}
            />
          </button>
        )}
        {!leaf && !open && collapsedHeader != null ? (
          <button type="button" className="flex min-w-0 flex-1 items-center gap-2 text-left" onClick={() => setOpen(true)}>
            {collapsedHeader}
          </button>
        ) : (
          <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">{header}</div>
        )}
        {actions != null && <div className="ml-auto shrink-0">{actions}</div>}
      </div>
      {showChildren && children != null && (
        <div
          id={leaf ? undefined : panelId}
          className={leaf ? "ml-8 mt-1" : "ml-5 border-l border-slate-200 pl-3"}
        >
          {children}
        </div>
      )}
    </div>
  );
}

export function TreeView({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return <div className={cn("space-y-0.5", className)}>{children}</div>;
}
