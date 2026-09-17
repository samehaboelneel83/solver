import { ApiError } from "./client";

type ValidationDetail = { loc?: (string | number)[]; msg?: string };

function tryParseJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return undefined;
  }
}

/**
 * The single place error objects get turned into user-facing text.
 * - 422 (validation): one line per field, "<field>: <msg>", joined with "\n".
 * - 409/404/400 with a string `detail`: that string verbatim.
 * - 5xx: a generic "try again" message (the raw body is not shown).
 * - anything else that is an ApiError: the string `detail` if present, else the raw body.
 * - a non-ApiError Error: its `message`.
 */
export function formatApiError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status >= 500) {
      return `Server error (${err.status}). Please try again.`;
    }

    const body = tryParseJson(err.message);

    if (err.status === 422 && body && typeof body === "object" && Array.isArray((body as { detail?: unknown }).detail)) {
      const details = (body as { detail: ValidationDetail[] }).detail;
      const lines = details.map((d) => {
        const field = Array.isArray(d.loc) && d.loc.length > 0 ? String(d.loc[d.loc.length - 1]) : "value";
        return `${field}: ${d.msg ?? "Invalid value"}`;
      });
      if (lines.length > 0) {
        return lines.join("\n");
      }
    }

    if (body && typeof body === "object" && typeof (body as { detail?: unknown }).detail === "string") {
      return (body as { detail: string }).detail;
    }

    return err.message;
  }

  if (err instanceof Error) {
    return err.message;
  }

  return String(err);
}
