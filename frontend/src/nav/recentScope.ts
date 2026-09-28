/**
 * Where a person last worked, remembered in this browser: the last domain or
 * problem a URL was scoped to, and the last problem opened in each domain.
 * Shortcuts only (plan §4.2) -- nothing here scopes a page by itself; the
 * sidebar offers them as links, and the domain switch uses them to land on
 * the same kind of page it left.
 */
import type { RecentScope } from "./registry";

const RECENT_SCOPE_KEY = "solver_recent_scope";
const LAST_PROBLEM_KEY = "solver_last_problem_by_domain";

function read(key: string): unknown {
  try {
    return JSON.parse(localStorage.getItem(key) ?? "null");
  } catch {
    return null;
  }
}

function write(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Without storage the shortcut lasts for this page only.
  }
}

export function readRecentScope(): RecentScope | null {
  const value = read(RECENT_SCOPE_KEY) as Partial<RecentScope> | null;
  if (!value || !Number.isSafeInteger(value.domainId)) return null;
  return { domainId: value.domainId!, problemId: Number.isSafeInteger(value.problemId) ? value.problemId! : null };
}

/** The last problem opened in `domainId`, or null. */
export function lastProblemIn(domainId: number): number | null {
  const map = read(LAST_PROBLEM_KEY);
  const value = map && typeof map === "object" ? (map as Record<string, unknown>)[String(domainId)] : null;
  return Number.isSafeInteger(value) ? (value as number) : null;
}

export function rememberScope(scope: RecentScope) {
  write(RECENT_SCOPE_KEY, scope);
  if (scope.problemId !== null) {
    const map = read(LAST_PROBLEM_KEY);
    write(LAST_PROBLEM_KEY, { ...(map && typeof map === "object" ? map : {}), [String(scope.domainId)]: scope.problemId });
  }
}
