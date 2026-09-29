import { ApiError, NetworkError } from "../api/client";
import { formatApiError } from "../api/errors";

/** Why a read failed, in the three ways a planner acts on differently (Epic UX, U-1). */
export type FailureKind = "no-access" | "not-found" | "offline" | "failed";

export function failureKind(error: unknown): FailureKind {
  if (error instanceof ApiError && error.status === 403) return "no-access";
  if (error instanceof ApiError && error.status === 404) return "not-found";
  if (error instanceof NetworkError) return "offline";
  return "failed";
}

/**
 * A read that failed: said as a failure, never shown as an empty list.
 *
 * A 403 says the account may not open it (retrying cannot help; someone must grant access),
 * a 404 that nothing has that id (a stale or mistyped link); both still offer the way back.
 * Only a failure that may pass -- the network, a server error -- is worth a Retry.
 */
export default function LoadFailure({
  subject,
  error,
  retry,
  back,
}: {
  subject: string;
  error: unknown;
  retry: () => void;
  /** Where to go instead, e.g. the list this item belongs to. */
  back?: { label: string; to: string };
}) {
  const kind = failureKind(error);
  const lower = subject.toLowerCase();
  const message =
    kind === "no-access"
      ? `${subject} is not open to this account. Ask an administrator for access if you need it.`
      : kind === "not-found"
        ? `${subject} could not be found. It may have been deleted, or the link is mistyped.`
        : `${subject} could not be loaded. ${formatApiError(error)}`;
  return (
    <div role="alert" data-failure={kind} className="my-4 rounded border border-amber-300 p-4">
      <p>{message}</p>
      <div className="mt-2 flex gap-2">
        {(kind === "failed" || kind === "offline") && (
          <button type="button" className="rounded border px-3 py-2" aria-label={`Retry loading ${lower}`} onClick={retry}>
            Retry
          </button>
        )}
        {back && (
          <a href={back.to} className="rounded border px-3 py-2">
            {back.label}
          </a>
        )}
      </div>
    </div>
  );
}
