import { FormEvent, useId, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { login } from "../api/client";
import { formatApiError } from "../api/errors";

// eslint-disable-next-line no-control-regex
const CONTROL_CHARS = /[\x00-\x1f\x7f]/;

/**
 * Only accept `next` values that resolve, same-origin, to a path on this
 * app. Rejects control characters (tabs/newlines can be stripped by URL
 * parsing and turn an apparently-relative path into a protocol-relative
 * one), absolute URLs to other origins, and protocol-relative URLs
 * (`//evil.example.com`).
 */
function safeNext(next: string | null): string {
  if (!next || CONTROL_CHARS.test(next)) {
    return "/";
  }
  try {
    const resolved = new URL(next, window.location.origin);
    if (resolved.origin !== window.location.origin || !resolved.pathname.startsWith("/")) {
      return "/";
    }
  } catch {
    return "/";
  }
  return next;
}

export default function Login() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const expired = searchParams.get("reason") === "expired";
  const formId = useId();
  const usernameId = `${formId}-username`;
  const passwordId = `${formId}-password`;

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await login(username, password);
      navigate(safeNext(searchParams.get("next")));
    } catch (err) {
      setError(formatApiError(err));
    }
  }

  return (
    // H-12: the only page in the app with no `main` landmark -- axe flagged
    // both `landmark-one-main` and `region` (its content wasn't contained in
    // any landmark at all) here specifically. Every other page state gets
    // `<main>` for free from AppShell; this one renders outside AppShell
    // (there's no signed-in shell to render yet), so it needs its own.
    <main className="flex min-h-screen items-center justify-center bg-slate-50 px-shell">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm space-y-shell rounded-shell border border-slate-200/80 bg-white p-shell-lg shadow-panel"
      >
        <div className="space-y-1">
          <p className="text-xs font-semibold uppercase tracking-wider text-blue-700">Problem Solver</p>
          <h1 className="text-xl font-semibold text-slate-900 sm:text-2xl">Welcome back</h1>
        </div>
        {expired && (
          <p className="text-sm text-slate-600">Your session expired — please sign in again</p>
        )}
        {error && <p className="text-sm text-red-600">{error}</p>}
        <div>
          <label htmlFor={usernameId} className="block text-sm font-medium text-slate-700">
            Username
          </label>
          <input
            id={usernameId}
            name="username"
            autoComplete="username"
            className="mt-1.5 w-full rounded-shell border border-slate-300 px-3 py-2 text-sm shadow-sm"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            data-testid="username"
          />
        </div>
        <div>
          <label htmlFor={passwordId} className="block text-sm font-medium text-slate-700">
            Password
          </label>
          <input
            id={passwordId}
            name="password"
            type="password"
            autoComplete="current-password"
            className="mt-1.5 w-full rounded-shell border border-slate-300 px-3 py-2 text-sm shadow-sm"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            data-testid="password"
          />
        </div>
        <button
          type="submit"
          className="w-full rounded-shell bg-blue-600 px-3 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-blue-700"
        >
          Sign in
        </button>
      </form>
      <p className="mt-4 text-center text-xs text-slate-500">
        Cannot sign in? <Link className="underline" to="/health">See whether the platform is working</Link>
      </p>
    </main>
  );
}
