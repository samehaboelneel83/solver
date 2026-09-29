import LoadFailure from "../components/LoadFailure";
import { useId, useState } from "react";
import OfflineNotice from "../components/OfflineNotice";
import Skeleton from "../components/Skeleton";
import { useToast } from "../components/ToastProvider";
import { formatApiError } from "../api/errors";
import { useApiKeys, useCreateApiKey, useMe, useRevokeApiKey, type ApiKey, type ApiKeyCreated } from "../api/v1";
import { useDocumentTitle } from "../hooks/useDocumentTitle";

/**
 * API keys: credentials for programs that call the platform -- a nightly
 * import, a scheduler that submits runs.
 *
 * A key acts as the person who made it, with at most the capabilities ticked
 * here, and never more than that person holds at the time it is used. Its
 * token is shown once, when it is made: the server keeps only a hash of it,
 * so a lost token is revoked and replaced, not recovered.
 */

const EXPIRY_CHOICES: { label: string; days: number | null }[] = [
  { label: "30 days", days: 30 },
  { label: "90 days", days: 90 },
  { label: "1 year", days: 365 },
  { label: "Never", days: null },
];

function when(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "—";
}

function status(key: ApiKey): { text: string; tone: string } {
  if (key.revoked_at) return { text: "Revoked", tone: "bg-slate-100 text-slate-600" };
  if (key.expires_at && new Date(key.expires_at) <= new Date()) return { text: "Expired", tone: "bg-amber-100 text-amber-900" };
  return { text: "Active", tone: "bg-green-100 text-green-900" };
}

export default function ApiKeys() {
  useDocumentTitle("API keys");
  const toast = useToast();
  const me = useMe();
  const keys = useApiKeys();
  const create = useCreateApiKey();
  const revoke = useRevokeApiKey();
  const nameId = useId();
  const expiryId = useId();

  const held = me.data?.capabilities ?? [];
  const [name, setName] = useState("");
  const [chosen, setChosen] = useState<Set<string> | null>(null);
  const [expiry, setExpiry] = useState<number | null>(90);
  const [made, setMade] = useState<ApiKeyCreated | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const ticked = chosen ?? new Set(held);

  function toggle(capability: string) {
    const next = new Set(ticked);
    if (next.has(capability)) next.delete(capability);
    else next.add(capability);
    setChosen(next);
  }

  function submit(event: React.FormEvent) {
    event.preventDefault();
    setFailure(null);
    create.mutate(
      { name: name.trim(), capabilities: [...ticked].sort(), expires_in_days: expiry },
      {
        onSuccess: (key) => {
          setMade(key);
          setName("");
          setChosen(null);
        },
        onError: (error) => setFailure(formatApiError(error)),
      }
    );
  }

  async function copy(token: string) {
    try {
      await navigator.clipboard.writeText(token);
      toast.success("Token copied");
    } catch {
      toast.error("Could not copy: select the token and copy it by hand");
    }
  }

  return (
    <div className="max-w-5xl">
      <h1 className="mb-1 text-lg font-semibold text-slate-900">API keys</h1>
      <p className="mb-4 max-w-3xl text-sm text-slate-600">
        A key lets a program call the platform as you, with at most the capabilities you give it and never more
        than you hold. Send it as <code className="rounded bg-slate-100 px-1">Authorization: Bearer sk_…</code>.
        Its token is shown once, when you make it.
      </p>
      <OfflineNotice />

      {made && (
        <section
          role="status"
          aria-labelledby="made-heading"
          className="mb-6 rounded-md border border-green-300 bg-green-50 p-4"
          data-testid="api-key-made"
        >
          <h2 id="made-heading" className="mb-1 text-sm font-semibold text-green-900">
            Key “{made.name}” made. Copy its token now: it will not be shown again.
          </h2>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <code className="break-all rounded border border-green-200 bg-white px-2 py-1 text-sm" data-testid="api-key-token">
              {made.token}
            </code>
            <button
              type="button"
              onClick={() => void copy(made.token)}
              className="rounded-md border border-green-700 bg-white px-3 py-1 text-sm text-green-800"
            >
              Copy
            </button>
            <button type="button" onClick={() => setMade(null)} className="px-2 py-1 text-sm text-slate-600 underline">
              Done
            </button>
          </div>
        </section>
      )}

      <form onSubmit={submit} className="mb-8 rounded-md border border-slate-200 bg-white p-4" aria-label="Make an API key">
        <h2 className="mb-3 text-sm font-semibold text-slate-900">Make a key</h2>
        <div className="flex flex-wrap items-end gap-4">
          <label htmlFor={nameId} className="flex flex-col text-sm text-slate-700">
            Name
            <input
              id={nameId}
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="nightly import"
              maxLength={100}
              required
              className="mt-1 w-64 rounded-md border border-slate-300 px-2 py-1"
            />
          </label>
          <label htmlFor={expiryId} className="flex flex-col text-sm text-slate-700">
            Expires after
            <select
              id={expiryId}
              value={expiry ?? ""}
              onChange={(event) => setExpiry(event.target.value === "" ? null : Number(event.target.value))}
              className="mt-1 rounded-md border border-slate-300 px-2 py-1"
            >
              {EXPIRY_CHOICES.map((choice) => (
                <option key={choice.label} value={choice.days ?? ""}>
                  {choice.label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <fieldset className="mt-4">
          <legend className="text-sm text-slate-700">What it may do</legend>
          {me.isLoading ? (
            <Skeleton rows={1} cols={3} />
          ) : held.length === 0 ? (
            <p className="mt-1 text-sm text-slate-500">
              Your account holds no capabilities, so a key could only read what needs none.
            </p>
          ) : (
            <div className="mt-1 flex flex-wrap gap-3">
              {held.map((capability) => (
                <label key={capability} className="flex items-center gap-1 text-sm text-slate-800">
                  <input type="checkbox" checked={ticked.has(capability)} onChange={() => toggle(capability)} />
                  <code>{capability}</code>
                </label>
              ))}
            </div>
          )}
        </fieldset>
        {failure && (
          <p role="alert" className="mt-3 text-sm text-red-700">
            {failure}
          </p>
        )}
        <button
          type="submit"
          disabled={create.isPending || name.trim() === ""}
          className="mt-4 rounded-md bg-blue-700 px-3 py-2 text-sm text-white disabled:opacity-60"
        >
          {create.isPending ? "Making…" : "Make key"}
        </button>
      </form>

      <h2 className="mb-2 text-sm font-semibold text-slate-900">Keys</h2>
      {keys.isError && !keys.data ? (
        <LoadFailure subject="The key list" error={keys.error} retry={() => void keys.refetch()} />
      ) : keys.isLoading ? (
        <Skeleton rows={3} cols={6} />
      ) : !keys.data || keys.data.items.length === 0 ? (
        <p className="rounded-md border border-slate-200 bg-white p-4 text-sm text-slate-600">No keys yet.</p>
      ) : (
        <table className="w-full table-auto border-collapse text-sm">
          <caption className="sr-only">API keys, newest first</caption>
          <thead>
            <tr className="border-b border-slate-200 text-left text-slate-600">
              <th scope="col" className="py-2 pr-3 font-medium">Name</th>
              <th scope="col" className="py-2 pr-3 font-medium">Token starts</th>
              <th scope="col" className="py-2 pr-3 font-medium">Owner</th>
              <th scope="col" className="py-2 pr-3 font-medium">May</th>
              <th scope="col" className="py-2 pr-3 font-medium">Last used</th>
              <th scope="col" className="py-2 pr-3 font-medium">Expires</th>
              <th scope="col" className="py-2 pr-3 font-medium">Status</th>
              <th scope="col" className="py-2 font-medium"><span className="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody>
            {keys.data.items.map((key) => {
              const state = status(key);
              return (
                <tr key={key.id} className="border-b border-slate-100 align-top">
                  <td className="py-2 pr-3 text-slate-900">{key.name}</td>
                  <td className="py-2 pr-3 font-mono text-xs">sk_{key.prefix}_…</td>
                  <td className="py-2 pr-3">{key.username}</td>
                  <td className="py-2 pr-3 text-xs">{key.capabilities.join(", ") || "reading only"}</td>
                  <td className="py-2 pr-3">{when(key.last_used_at)}</td>
                  <td className="py-2 pr-3">{key.expires_at ? when(key.expires_at) : "never"}</td>
                  <td className="py-2 pr-3">
                    <span className={`rounded px-2 py-0.5 text-xs ${state.tone}`}>{state.text}</span>
                  </td>
                  <td className="py-2">
                    {!key.revoked_at && (
                      <button
                        type="button"
                        onClick={() => {
                          if (!window.confirm(`Revoke “${key.name}”? Programs using it will stop working at once.`)) return;
                          revoke.mutate(key.id, {
                            onSuccess: () => toast.success(`Revoked “${key.name}”`),
                            onError: (error) => toast.error(formatApiError(error)),
                          });
                        }}
                        className="text-sm text-red-700 underline"
                      >
                        Revoke
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
