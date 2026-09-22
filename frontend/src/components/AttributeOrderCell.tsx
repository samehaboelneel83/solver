import type { AttributeDef, Id } from "../api/v1";

/**
 * An attribute's position, and the buttons that change it.
 *
 * Shared by entity types and relationship types, which both own attributes
 * (migration 0024) and both order them (0027). Two copies of the same two
 * buttons would drift, and the first sign would be one page moving focus
 * after a move and the other not.
 */
export default function AttributeOrderCell({
  attribute,
  index,
  count,
  canEdit,
  busy,
  onMove,
}: {
  attribute: AttributeDef;
  index: number;
  count: number;
  canEdit: boolean;
  busy: boolean;
  onMove: (index: number, by: -1 | 1) => void;
}) {
  return (
    <td className="whitespace-nowrap px-2 py-1 text-slate-700">
      <span className="inline-block w-6 py-1 tabular-nums">{attribute.sort_order}</span>
      {canEdit && (
        <>
          <button
            type="button"
            id={moveButtonId(attribute.id, -1)}
            aria-label={`Move ${attribute.name} up`}
            title="Move up"
            disabled={index === 0 || busy}
            onClick={() => onMove(index, -1)}
            className={BUTTON_CLASS}
          >
            <span aria-hidden="true">&uarr;</span>
          </button>
          <button
            type="button"
            id={moveButtonId(attribute.id, 1)}
            aria-label={`Move ${attribute.name} down`}
            title="Move down"
            disabled={index === count - 1 || busy}
            onClick={() => onMove(index, 1)}
            className={BUTTON_CLASS}
          >
            <span aria-hidden="true">&darr;</span>
          </button>
        </>
      )}
    </td>
  );
}

const BUTTON_CLASS =
  "rounded px-1.5 py-1 text-slate-600 hover:bg-slate-100 hover:text-slate-900 " +
  "disabled:cursor-not-allowed disabled:opacity-30";

export function moveButtonId(attributeId: Id, by: -1 | 1): string {
  return `move-attribute-${attributeId}-${by < 0 ? "up" : "down"}`;
}

/**
 * The whole list with one attribute swapped with its neighbour, or null when
 * there is no neighbour that way.
 *
 * The whole list, not "move this one": the server renumbers 1..n in one
 * statement and refuses a list that is not exactly the owner's attributes, so
 * a second person reordering at the same time gets a refusal rather than an
 * interleaving neither of them chose.
 */
export function swapped(attributes: AttributeDef[], index: number, by: -1 | 1): Id[] | null {
  const target = index + by;
  if (target < 0 || target >= attributes.length) return null;
  const ids = attributes.map((a) => a.id);
  [ids[index], ids[target]] = [ids[target], ids[index]];
  return ids;
}

/** Keep keyboard focus on the same button of the row that moved, so pressing
 * it again keeps moving that attribute rather than whichever row now sits
 * where it was. Deferred a frame: the list re-renders in its new order first.
 *
 * A row that reached the top or bottom has that button disabled, and a
 * disabled button cannot take focus -- it would fall to the page body and a
 * keyboard user would lose their place. The other button takes it instead. */
export function refocusMoved(attributeId: Id, by: -1 | 1): void {
  requestAnimationFrame(() => {
    const same = document.getElementById(moveButtonId(attributeId, by)) as HTMLButtonElement | null;
    const other = document.getElementById(moveButtonId(attributeId, by < 0 ? 1 : -1)) as HTMLButtonElement | null;
    (same && !same.disabled ? same : other)?.focus();
  });
}
