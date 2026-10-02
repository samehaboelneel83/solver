import { ApiError, NetworkError } from "./client";

/**
 * The phrase `app/api/concurrency.py` puts in the 409 it refuses a save
 * built on a superseded read with (Ruling 42). It is a wire contract:
 * `backend/app/api/concurrency.py::STALE_PREFIX` holds the same string and
 * both sides' tests assert it.
 *
 * Matching on text is not the first choice, but a 409 body is
 * `{"detail": "<text>"}` and has nowhere else to carry a discriminator --
 * only the 422 list shape has `kind` (Ruling 19), and giving this one case
 * an object `detail` would leave the API with a third body shape for a
 * client to sniff. The precedent is already here: the entity form tells
 * `UNIQUE (entity_type_id, key)` apart the same way.
 */
export const STALE_RECORD_PHRASE = "changed by someone else";

/**
 * True when a save was refused because the record moved on since it was
 * read -- as opposed to the other 409 a save can get, a unique-key
 * collision, which is a field error the form pins to a control.
 */
export function isStaleRecordError(err: unknown): boolean {
  if (!(err instanceof ApiError) || err.status !== 409) return false;
  return formatApiError(err).includes(STALE_RECORD_PHRASE);
}

/** One entry of a 422's `detail` list. Every 422 the backend sends has
 * this shape (Ruling 19): FastAPI's own validation errors, and schema v1's
 * database validation triggers, which `translate_db_error` emits in the
 * same shape plus a machine-readable `kind` (`unknown_attribute`, `cycle`,
 * `parameter_index`, ...). `kind` is for code that needs to branch on the
 * failure; it is never shown to the user. */
type ValidationDetail = { loc?: (string | number)[]; msg?: string; kind?: string };

function tryParseJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return undefined;
  }
}

const LEADING_LOC_SEGMENTS = new Set(["body", "query", "path"]);

/** FastAPI's `loc` is e.g. ["body", "attributes", "rank"] (a leading
 * request-part marker, then the field path). Strip that marker and join
 * the rest with "." (`attributes.rank`). Returns "" when nothing names a
 * field: a `loc` of bare ["body"] (a model-level validator, or a trigger
 * payload with no `field`) blames the request as a whole, and "body" is
 * request plumbing, not a field name to show the user. A missing or empty
 * `loc` keeps its "value" label. */
function fieldNameFromLoc(loc: (string | number)[] | undefined): string {
  if (!Array.isArray(loc) || loc.length === 0) return "value";
  const segments = loc.map(String);
  const rest = LEADING_LOC_SEGMENTS.has(segments[0]) ? segments.slice(1) : segments;
  return rest.join(".");
}

/**
 * The single place error objects get turned into user-facing text.
 * - 422 (validation): one line per field, "<field>: <msg>", joined with "\n",
 *   or just "<msg>" when `loc` names no field. Database trigger failures
 *   take this path too: since Ruling 19 they arrive in the same list shape,
 *   with `kind` as an extra key that is deliberately not rendered.
 * - 409/404/400 with a string `detail`: that string verbatim.
 * - 5xx: a generic "try again" message (the raw body is not shown).
 * - anything else that is an ApiError with a non-string, non-array `detail`
 *   (e.g. an object): that `detail`, JSON-stringified.
 * - anything else that is an ApiError: the raw body.
 * - a non-ApiError Error: its `message`.
 */
/** A validation message in plain words: "must be at most 20000", not "Input should be less than or equal to 20000"
 * (benchmark, October 2026: raw validation text shown to a planner). Anything else as it came. */
export function plainValidation(msg: string): string {
  const rules: [RegExp, string][] = [
    [/^Input should be less than or equal to (.+)$/, "must be at most $1"],
    [/^Input should be greater than or equal to (.+)$/, "must be at least $1"],
    [/^Input should be less than (.+)$/, "must be below $1"],
    [/^Input should be greater than (.+)$/, "must be above $1"],
    [/^Field required$/, "is required"],
    [/^Input should be a valid number.*$/, "must be a number"],
    [/^Input should be a valid integer.*$/, "must be a whole number"],
    [/^String should match pattern .*$/, "must be lower-case letters, digits and _, starting with a letter"],
    [/^String should have at most (\d+) characters?$/, "must be at most $1 characters"],
    [/^List should have at most (\d+) items?.*$/, "may have at most $1 items"],
  ];
  for (const [pattern, words] of rules) if (pattern.test(msg)) return msg.replace(pattern, words);
  return msg;
}

export function formatApiError(err: unknown): string {
  if (err instanceof NetworkError) {
    if (typeof navigator !== "undefined" && navigator.onLine === false) {
      return "You appear to be offline. Check your connection and try again.";
    }
    return err.message;
  }

  if (err instanceof ApiError) {
    if (err.status >= 500) {
      return `Server error (${err.status}). Please try again.`;
    }

    const body = tryParseJson(err.message);
    const detail = body && typeof body === "object" ? (body as { detail?: unknown }).detail : undefined;

    if (err.status === 422 && Array.isArray(detail)) {
      const lines = (detail as ValidationDetail[]).map((d) => {
        const field = fieldNameFromLoc(d.loc);
        const raw = d.msg ?? "Invalid value";
        const msg = plainValidation(raw);
        // "code is required", "join_m must be at most 20000"; an unrecognised message keeps its colon.
        return field ? (msg !== raw ? `${field} ${msg}` : `${field}: ${msg}`) : msg;
      });
      if (lines.length > 0) {
        return lines.join("\n");
      }
    }

    // Task 6 added a second 422 branch here for the database triggers'
    // object `detail`. Ruling 19 moved those onto the list shape above, so
    // it is gone: an object `detail` now takes the generic path below like
    // any other unrecognised body.

    if (typeof detail === "string") {
      return detail;
    }

    if (detail !== undefined && !Array.isArray(detail)) {
      // An object: its own sentence when it carries one, else its parts in words -- never raw JSON
      // (benchmark, October 2026).
      const o = (detail ?? {}) as Record<string, unknown>;
      const said = [o.message, o.says, o.detail].find((v) => typeof v === "string" && v.trim());
      if (said) return said as string;
      return Object.entries(o).map(([k, v]) => `${k.replace(/_/g, " ")}: ${typeof v === "string" ? v : JSON.stringify(v)}`).join("; ");
    }

    return err.message;
  }

  if (err instanceof Error) {
    // D-7: a network-level failure (fetch itself rejecting, e.g. the
    // connection dropping mid-request) surfaces here as a plain Error with
    // a browser-specific, not-very-human message ("Failed to fetch",
    // "NetworkError when attempting to fetch resource…"). When the browser
    // itself reports offline, that's almost certainly why -- say so plainly
    // instead of the raw browser string. (A query that never gets far
    // enough to fail at all -- React Query pausing it while offline -- is a
    // separate case, handled by OfflineNotice where each query is read.)
    if (typeof navigator !== "undefined" && navigator.onLine === false) {
      return "You appear to be offline. Check your connection and try again.";
    }
    return err.message;
  }

  return String(err);
}
