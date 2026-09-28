import { formatApiError } from "../api/errors";

/** A read that failed: said as a failure, with a retry -- never shown as an empty list. */
export default function LoadFailure({ subject, error, retry }: { subject: string; error: unknown; retry: () => void }) {
  return <div role="alert" className="my-4 rounded border border-amber-300 p-4">
    <p>{subject} could not be loaded. {formatApiError(error)}</p>
    <button type="button" className="mt-2 rounded border px-3 py-2" aria-label={`Retry loading ${subject.toLowerCase()}`} onClick={retry}>Retry</button>
  </div>;
}
