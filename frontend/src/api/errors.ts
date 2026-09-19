import { ApiError } from "./client";

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
export function formatApiError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status >= 500) {
      return `Server error (${err.status}). Please try again.`;
    }

    const body = tryParseJson(err.message);
    const detail = body && typeof body === "object" ? (body as { detail?: unknown }).detail : undefined;

    if (err.status === 422 && Array.isArray(detail)) {
      const lines = (detail as ValidationDetail[]).map((d) => {
        const field = fieldNameFromLoc(d.loc);
        const msg = d.msg ?? "Invalid value";
        return field ? `${field}: ${msg}` : msg;
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
      return JSON.stringify(detail);
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
