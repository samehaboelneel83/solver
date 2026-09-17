type SkeletonProps = {
  /** Number of placeholder rows to render. */
  rows?: number;
  /** Number of placeholder cells per row. */
  cols?: number;
};

/**
 * A pulsing placeholder table used in place of a bare "Loading…" string
 * (D-5): a slow page reads as "working" instead of "stalled". `aria-hidden`
 * because it carries no information of its own -- the surrounding page is
 * expected to announce the loading state (or its result) via the toast/live
 * region machinery in ToastProvider, not via this decoration.
 */
export default function Skeleton({ rows = 5, cols = 4 }: SkeletonProps) {
  return (
    <table className="w-full border-collapse text-sm" aria-hidden="true">
      <tbody>
        {Array.from({ length: rows }).map((_, rowIndex) => (
          <tr key={rowIndex} data-testid="skeleton-row" className="border-b border-slate-100">
            {Array.from({ length: cols }).map((_, colIndex) => (
              <td key={colIndex} className="px-3 py-2">
                <div className="h-4 w-full animate-pulse rounded bg-slate-200 motion-reduce:animate-none" />
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
