function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

/**
 * Formats a stored ISO/UTC instant as the local wall-clock string a
 * `datetime-local` input expects and displays (`YYYY-MM-DDTHH:mm`). Reads
 * the value through a `Date` object rather than string-slicing the ISO
 * text, since slicing shows the UTC clock time labeled as if it were
 * local. Returns the input unchanged if it doesn't parse as a valid date,
 * so a malformed stored value is at least visible rather than blanked.
 */
export function toDatetimeLocalValue(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}T${pad2(
    date.getHours()
  )}:${pad2(date.getMinutes())}`;
}

/**
 * Converts a `datetime-local` input's local wall-clock string (no
 * timezone) back to an ISO UTC instant for the API. `new Date(local)`
 * parses a timezone-less string as local time, so `.toISOString()` on the
 * result is the correct UTC round-trip. Sending the local string straight
 * through (the bug this replaces) made the backend store it as if it were
 * already UTC, drifting the displayed time by the browser's offset on
 * every save.
 */
export function fromDatetimeLocalValue(local: string): string {
  return new Date(local).toISOString();
}
