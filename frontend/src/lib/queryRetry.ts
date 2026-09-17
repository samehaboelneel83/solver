import { ApiError } from "../api/client";

/**
 * React Query's retry predicate. A 4xx response (bad request, not found, forbidden, ...) will
 * never succeed on retry, so it fails immediately. Anything else (5xx, network errors) gets a
 * single retry before giving up -- enough to smooth over a transient blip without leaving the
 * user staring at "Loading…" for several seconds across the default 3 backoff attempts.
 *
 * It lives here rather than in main.tsx so it can be imported by tests without pulling in the
 * module that mounts the application.
 */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
    return false;
  }
  return failureCount < 1;
}
