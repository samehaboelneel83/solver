import { validationErrors } from "../api/v1";

/**
 * A server refusal of an expression, read back as the rule it is about.
 *
 * The client validates a document before sending it, so a 422 from the
 * compiler means one of three things: the catalogue moved under the page
 * (an attribute was deleted in another tab), the document was hand-written,
 * or the two validators genuinely disagree -- which is a bug, and the user
 * still has to be able to see WHICH condition it is about.
 *
 * The server answers in the platform's one 422 body shape (Ruling 19) with
 *
 *     loc: ["query", "expr", "query", "rules", 1, "rules", 0, "value"]
 *
 * -- the real JSON path into the document, the way Pydantic points into a
 * body. **The mapping keys on `loc`, not on a code (Ruling 30):** `loc`
 * says what was wrong, and the server deliberately sends no `kind` here
 * (`kind` means "a database trigger judged this", and none did).
 *
 * The numeric segments of that path, in order, are exactly the rule path
 * the builder and `validate.ts` already use -- `[1, 0]` is "condition 2.1"
 * -- because the only numbers in it are `rules` indices. Reading it that
 * way rather than by position means a future `loc` that names a different
 * key at the end ("operator", "field", "value", or nothing) maps to the
 * same rule without a second rule for each. The two constant prefix
 * segments need no slicing off for the same reason: they are strings, so
 * the same filter drops them. (Slicing them first was written here and
 * removed: mutating it away changed no test, because it could not.)
 */
export type ServerExpressionProblem = { path: number[]; message: string };

const PREFIX = ["query", "expr"];

export function serverExpressionProblems(error: unknown): ServerExpressionProblem[] {
  return validationErrors(error)
    .filter((item) => PREFIX.every((segment, index) => item.loc?.[index] === segment))
    .map((item) => ({
      path: item.loc.filter((segment): segment is number => typeof segment === "number"),
      message: item.msg,
    }));
}
