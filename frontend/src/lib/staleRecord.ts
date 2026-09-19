/**
 * Reloading a record that changed underneath an open form, without
 * throwing away what the person typed (Ruling 42).
 *
 * The server refuses a save whose `updated_at` is not the stored one, so
 * the form has to offer a way forward. "Reload" cannot mean "discard my
 * edits and start again" -- that is the same data loss the refusal exists
 * to prevent, pointed the other way -- and it cannot mean "keep my form
 * exactly as it is" either, because then the next save reverts the other
 * client's work all over again.
 *
 * So it is a three-way merge, per field, and the third input is what makes
 * it decidable: the values the form was SEEDED with. A field the person has
 * not touched still holds its seed, so the freshly-read value can replace
 * it safely; a field they have touched differs from its seed, so their
 * value stays. This is the same rule a version-control merge uses, and it
 * needs no dirty flags scattered through the controls.
 *
 * It deliberately does NOT narrow what the save then sends. The form still
 * submits every field, because Tasks 11/12 require the whole `attrs` object
 * to be rebuilt from today's `attribute_def` rows so a deleted definition's
 * key disappears (`EntityRecord.test.tsx` pins that). The merge decides what
 * the CONTROLS hold; the payload is as wide as it ever was.
 */

/**
 * Per key: the person's value when they changed it, otherwise the server's.
 *
 * `baseline` is what the form was seeded with, `current` is what its
 * controls hold now, `fresh` is what the server has just returned. Keys
 * come from `fresh`, so an attribute whose definition was deleted while the
 * form was open does not come back through the merge.
 *
 * Comparison is `!==`. Every value this is used on is a string, a boolean
 * or a number -- the drafts are all strings by construction
 * (`AttrDrafts`), and the type forms hold primitives -- so reference
 * identity is never the question.
 */
export function mergeReload<T extends Record<string, unknown>>(
  baseline: T,
  current: T,
  fresh: T
): T {
  const merged: Record<string, unknown> = {};
  for (const key of Object.keys(fresh)) {
    const touched = current[key] !== baseline[key];
    merged[key] = touched ? current[key] : fresh[key];
  }
  return merged as T;
}

/** The keys `mergeReload` took from the server rather than from the form --
 * what a reload actually brought in. Used to tell the person what changed
 * instead of leaving them to spot it. */
export function reloadedKeys<T extends Record<string, unknown>>(
  baseline: T,
  current: T,
  fresh: T
): string[] {
  return Object.keys(fresh).filter(
    (key) => current[key] === baseline[key] && fresh[key] !== baseline[key]
  );
}
