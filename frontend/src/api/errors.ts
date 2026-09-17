import { ApiError } from "./client";

type ValidationDetail = { loc?: (string | number)[]; msg?: string };

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
 * the rest with "." (`attributes.rank`); if nothing is left after
 * stripping (or `loc` is missing/empty), fall back to its last segment. */
function fieldNameFromLoc(loc: (string | number)[] | undefined): string {
  if (!Array.isArray(loc) || loc.length === 0) return "value";
  const segments = loc.map(String);
  const rest = LEADING_LOC_SEGMENTS.has(segments[0]) ? segments.slice(1) : segments;
  return (rest.length > 0 ? rest : segments).join(".");
}

/**
 * The single place error objects get turned into user-facing text.
 * - 422 (validation): one line per field, "<field>: <msg>", joined with "\n".
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
      const lines = (detail as ValidationDetail[]).map(
        (d) => `${fieldNameFromLoc(d.loc)}: ${d.msg ?? "Invalid value"}`
      );
      if (lines.length > 0) {
        return lines.join("\n");
      }
    }

    if (typeof detail === "string") {
      return detail;
    }

    if (detail !== undefined && !Array.isArray(detail)) {
      return JSON.stringify(detail);
    }

    return err.message;
  }

  if (err instanceof Error) {
    return err.message;
  }

  return String(err);
}
