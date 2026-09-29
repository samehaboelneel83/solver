/**
 * Stable identities for rules on screen (Epic UX, U-3).
 *
 * A rule is named by its id, but its id is edited a keystroke at a time, so the id
 * cannot be what React or the graph's focus hangs on. Each rule gets a key that
 * survives a rename (same position, same count), a deletion elsewhere (matched by
 * id), and an addition (a new key for the new rule only).
 */
let counter = 0;
const nextKey = () => `rule-${(counter += 1)}`;

export function stableKeys(previousIds: readonly string[], previousKeys: readonly string[], ids: readonly string[]): string[] {
  if (previousIds.length === ids.length) {
    // An edit in place -- a rename included -- keeps every key where it was.
    return ids.map((_, i) => previousKeys[i] ?? nextKey());
  }
  const unused = new Map<string, string[]>();
  previousIds.forEach((id, i) => unused.set(id, [...(unused.get(id) ?? []), previousKeys[i]]));
  return ids.map((id) => {
    const keys = unused.get(id);
    const key = keys?.shift();
    return key ?? nextKey();
  });
}
