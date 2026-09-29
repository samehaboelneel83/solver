/** Previous / next over a server-paged list, with where the planner is in it (Epic UX, U-1). */
export default function Pager({
  label,
  offset,
  size,
  total,
  onOffset,
}: {
  label: string;
  offset: number;
  size: number;
  total: number;
  onOffset: (offset: number) => void;
}) {
  if (total <= size) return null;
  return (
    <nav aria-label={`${label} pages`} className="my-3 flex items-center gap-3 text-sm">
      <button type="button" className="rounded border px-2 py-1 disabled:opacity-50" disabled={offset === 0}
        onClick={() => onOffset(Math.max(0, offset - size))}>
        Previous
      </button>
      <span>
        {offset + 1}–{Math.min(offset + size, total)} of {total}
      </span>
      <button type="button" className="rounded border px-2 py-1 disabled:opacity-50" disabled={offset + size >= total}
        onClick={() => onOffset(offset + size)}>
        Next
      </button>
    </nav>
  );
}
