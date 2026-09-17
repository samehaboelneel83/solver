import { FormEvent, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { login } from "../api/client";
import { formatApiError } from "../api/errors";

function safeNext(next: string | null): string {
  if (next && next.startsWith("/") && !next.startsWith("//")) {
    return next;
  }
  return "/";
}

export default function Login() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const expired = searchParams.get("reason") === "expired";

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
    <div className="flex min-h-screen items-center justify-center bg-slate-50">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm space-y-4 rounded-lg border border-slate-200 bg-white p-6 shadow-sm"
      >
        <h1 className="text-lg font-semibold text-slate-900">Welcome back</h1>
        {expired && (
          <p className="text-sm text-slate-600">Your session expired — please sign in again</p>
        )}
        {error && <p className="text-sm text-red-600">{error}</p>}
        <div>
          <label className="block text-sm font-medium text-slate-700">Username</label>
          <input
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            data-testid="username"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700">Password</label>
          <input
            type="password"
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            data-testid="password"
          />
        </div>
        <button
          type="submit"
          className="w-full rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white hover:bg-slate-700"
        >
          Sign in
        </button>
      </form>
    </div>
  );
}
