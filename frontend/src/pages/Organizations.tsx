import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { ApiError, apiFetch } from "../api/client";
import { formatApiError } from "../api/errors";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { useCapabilities } from "../hooks/useCapability";

const INPUT = "rounded border border-slate-300 px-2 py-1 text-sm";
const LIMITS: [string, string][] = [
  ["max_concurrent_runs", "Runs at once"], ["max_queued_runs", "Runs waiting"], ["max_time_limit_s", "Longest run (s)"],
  ["max_vars", "Decisions per model"], ["cpu_seconds_month", "CPU seconds a month"], ["requests_per_minute", "Requests a minute"],
  ["priority_weight", "Priority weight"], ["max_memory_mb", "Memory per run (MB)"],
];
const TIERS = ["free", "standard", "enterprise"];

type Quota = { tier: string | null; limits: Record<string, number | null>; this_month: { cpu_seconds: number; runs: number } };
type Provider = { configured: boolean; issuer?: string; client_id?: string; scopes?: string; group_claim?: string;
  role_map?: Record<string, string>; sso_required?: boolean };
type Org = { id: string; code: string; name: string; is_active: boolean; is_operator: boolean; created_at: string;
  users: number; problems: number; quota: (Record<string, number | string | null> & { tier?: string | null }) | null };

const put = (path: string, body: unknown) => apiFetch(path, { method: "PUT", body: JSON.stringify(body) });
const postJson = <T,>(path: string, body?: unknown) =>
  apiFetch<T>(path, { method: "POST", ...(body === undefined ? {} : { body: JSON.stringify(body) }) });

/** This organization's quota and what it used this month (read-only: an operator sets quotas). */
function OwnQuota() {
  const quota = useQuery({ queryKey: ["quota"], queryFn: () => apiFetch<Quota>("/api/v1/quota") });
  if (!quota.data) return null;
  return <section aria-labelledby="own-quota" className="rounded-xl border border-slate-200 bg-white p-4">
    <h2 id="own-quota" className="text-lg font-semibold">This organization's limits</h2>
    <p className="text-sm text-slate-600">Tier {quota.data.tier ?? "none"}; this month {quota.data.this_month.runs.toLocaleString()} runs,{" "}
      {Math.round(quota.data.this_month.cpu_seconds).toLocaleString()} CPU seconds. The platform's operator sets these.</p>
    <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-4">
      {LIMITS.map(([key, label]) => <div key={key}><dt className="text-slate-500">{label}</dt>
        <dd>{quota.data!.limits[key] == null ? "no limit" : Number(quota.data!.limits[key]).toLocaleString()}</dd></div>)}
    </dl>
  </section>;
}

/** Sign-in through the organization's identity provider (OpenID Connect), and its group-to-role map. */
function SingleSignOn() {
  const client = useQueryClient();
  const id = useId();
  const current = useQuery({ queryKey: ["sso-provider"], queryFn: () => apiFetch<Provider>("/api/v1/sso/provider") });
  const [form, setForm] = useState<{ issuer: string; client_id: string; client_secret: string; scopes: string;
    group_claim: string; role_map: string; sso_required: boolean } | null>(null);
  const shown = form ?? {
    issuer: current.data?.issuer ?? "", client_id: current.data?.client_id ?? "", client_secret: "",
    scopes: current.data?.scopes ?? "openid profile email", group_claim: current.data?.group_claim ?? "groups",
    role_map: Object.entries(current.data?.role_map ?? {}).map(([g, r]) => `${g}=${r}`).join(", "),
    sso_required: current.data?.sso_required ?? false,
  };
  const set = (patch: Partial<typeof shown>) => setForm({ ...shown, ...patch });
  const save = useMutation({
    mutationFn: () => put("/api/v1/sso/provider", {
      issuer: shown.issuer.trim(), client_id: shown.client_id.trim(), client_secret: shown.client_secret,
      scopes: shown.scopes.trim(), group_claim: shown.group_claim.trim(), sso_required: shown.sso_required,
      role_map: Object.fromEntries(shown.role_map.split(",").map((p) => p.split("=").map((x) => x.trim()))
        .filter((p) => p[0] && p[1])),
    }),
    onSuccess: () => { setForm(null); void client.invalidateQueries({ queryKey: ["sso-provider"] }); },
  });
  const field = (key: "issuer" | "client_id" | "client_secret" | "scopes" | "group_claim" | "role_map", label: string, type = "text") => (
    <label className="block text-sm" htmlFor={`${id}-${key}`}>{label}
      <input id={`${id}-${key}`} type={type} autoComplete={type === "password" ? "new-password" : "off"}
        className={`${INPUT} mt-1 w-full`} value={shown[key]} onChange={(e) => set({ [key]: e.target.value })} /></label>
  );
  return <section aria-labelledby="sso" className="rounded-xl border border-slate-200 bg-white p-4">
    <h2 id="sso" className="text-lg font-semibold">Single sign-on</h2>
    <p className="text-sm text-slate-600">{current.data?.configured
      ? `Signing in through ${current.data.issuer}${current.data.sso_required ? " only" : " (passwords still work)"}.`
      : "Not set up: people sign in with a password."} The client secret is encrypted and never shown again.</p>
    <form className="mt-2 grid gap-2 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
      {field("issuer", "Issuer (https://…)")}{field("client_id", "Client id")}
      {field("client_secret", current.data?.configured ? "Client secret (again, to save)" : "Client secret", "password")}
      {field("scopes", "Scopes")}{field("group_claim", "Group claim")}
      {field("role_map", "Groups to roles (group=role, comma-separated)")}
      <label className="text-sm sm:col-span-2"><input type="checkbox" className="mr-1" checked={shown.sso_required}
        onChange={(e) => set({ sso_required: e.target.checked })} />Only sign-on: no passwords for this organization</label>
      <div className="sm:col-span-2"><button type="submit" className="rounded bg-blue-700 px-3 py-1.5 text-sm text-white disabled:opacity-50"
        disabled={!shown.issuer || !shown.client_id || !shown.client_secret || save.isPending}>Save sign-on</button></div>
    </form>
    {save.isError && <p role="alert" className="text-sm text-red-700">{formatApiError(save.error)}</p>}
    {save.isSuccess && <p role="status" className="text-sm text-green-800">Saved.</p>}
  </section>;
}

/** A token for the identity provider's directory sync (SCIM 2.0), shown once. */
function DirectorySync() {
  const mint = useMutation({ mutationFn: () => postJson<{ token: string }>("/api/v1/scim/token") });
  return <section aria-labelledby="scim" className="rounded-xl border border-slate-200 bg-white p-4">
    <h2 id="scim" className="text-lg font-semibold">Directory sync (SCIM)</h2>
    <p className="text-sm text-slate-600">Give the identity provider this platform's <span className="font-mono">/scim/v2</span> address
      and a token, and it adds, changes and removes people here. A new token replaces the one before.</p>
    <button type="button" className="mt-2 rounded border px-3 py-1.5 text-sm" disabled={mint.isPending} onClick={() => mint.mutate()}>
      Make a new token</button>
    {mint.isError && <p role="alert" className="text-sm text-red-700">{formatApiError(mint.error)}</p>}
    {mint.data && <p role="status" className="mt-2 text-sm">Copy it now; it is not shown again:{" "}
      <code className="break-all rounded bg-slate-100 px-1">{mint.data.token}</code></p>}
  </section>;
}

/** One organization's quota, set by the operator: a tier, with any limit given overriding it. */
function SetQuota({ org, onDone }: { org: Org; onDone: () => void }) {
  const [tier, setTier] = useState(String(org.quota?.tier ?? ""));
  const [values, setValues] = useState<Record<string, string>>(Object.fromEntries(LIMITS.map(([k]) =>
    [k, org.quota?.[k] == null ? "" : String(org.quota[k])])));
  const save = useMutation({
    mutationFn: () => put(`/api/v1/organizations/${org.id}/quota`, {
      ...(tier ? { tier } : {}),
      ...Object.fromEntries(Object.entries(values).filter(([, v]) => v.trim()).map(([k, v]) => [k, Number(v)])),
    }),
    onSuccess: onDone,
  });
  return <div role="group" aria-label={`Quota of ${org.code}`} className="mt-2 space-y-2 rounded border border-slate-200 p-3 text-sm">
    <label>Tier{" "}<select className={INPUT} value={tier} onChange={(e) => setTier(e.target.value)}>
      <option value="">none (only the limits below)</option>{TIERS.map((t) => <option key={t} value={t}>{t}</option>)}</select></label>
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">{LIMITS.map(([key, label]) => (
      <label key={key} className="block">{label}
        <input aria-label={`${org.code}: ${label}`} className={`${INPUT} mt-1 w-full`} inputMode="decimal" placeholder="no limit"
          value={values[key]} onChange={(e) => setValues({ ...values, [key]: e.target.value })} /></label>))}</div>
    <button type="button" className="rounded bg-blue-700 px-3 py-1.5 text-white disabled:opacity-50" disabled={save.isPending}
      onClick={() => save.mutate()}>Save the quota</button>
    {save.isError && <p role="alert" className="text-red-700">{formatApiError(save.error)}</p>}
  </div>;
}

/** Every organization, for the platform's operator: start one, set its quota, export it, delete it. */
function AllOrganizations() {
  const client = useQueryClient();
  const orgs = useQuery({ queryKey: ["organizations"], queryFn: () => apiFetch<{ items: Org[] }>("/api/v1/organizations"),
    retry: false });
  const [made, setMade] = useState({ code: "", name: "", admin_username: "", admin_password: "", tier: "standard" });
  const [open, setOpen] = useState<{ id: string; what: "quota" | "delete" } | null>(null);
  const [confirm, setConfirm] = useState("");
  const reload = () => void client.invalidateQueries({ queryKey: ["organizations"] });
  const create = useMutation({
    mutationFn: () => postJson("/api/v1/organizations", { ...made, ...(made.tier ? {} : { tier: undefined }) }),
    onSuccess: () => { setMade({ code: "", name: "", admin_username: "", admin_password: "", tier: "standard" }); reload(); },
  });
  const remove = useMutation({
    mutationFn: (org: Org) => postJson(`/api/v1/organizations/${org.id}/delete`, { confirm_code: confirm }),
    onSuccess: () => { setOpen(null); setConfirm(""); reload(); },
  });
  const exportOrg = useMutation({
    mutationFn: async (org: Org) => {
      const data = await apiFetch<unknown>(`/api/v1/organizations/${org.id}/export`);
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = `${org.code}-export.json`;
      a.click();
      URL.revokeObjectURL(url);
    },
  });
  // Only the operator organization sees every organization: anyone else is told nothing more.
  if (orgs.error instanceof ApiError && orgs.error.status === 403) return null;
  if (!orgs.data) return orgs.isError ? <p role="alert" className="text-red-700">{formatApiError(orgs.error)}</p> : null;
  return <section aria-labelledby="all-orgs" className="rounded-xl border border-slate-200 bg-white p-4">
    <h2 id="all-orgs" className="text-lg font-semibold">All organizations</h2>
    <p className="text-sm text-slate-600">As the platform's operator: each tenant's people, problems and quota.</p>
    <table className="mt-2 w-full text-left text-sm" aria-label="Organizations">
      <thead><tr className="text-xs text-slate-500"><th>Code</th><th>Name</th><th>People</th><th>Problems</th><th>Tier</th><th /></tr></thead>
      <tbody>{orgs.data.items.map((org) => <tr key={org.id} className="border-t border-slate-100 align-top">
        <td className="py-1 font-mono">{org.code}{org.is_operator ? " (operator)" : ""}</td><td>{org.name}</td>
        <td>{org.users}</td><td>{org.problems}</td><td>{String(org.quota?.tier ?? "—")}</td>
        <td className="space-x-2 whitespace-nowrap">
          <button type="button" className="text-blue-700 underline" onClick={() => setOpen(open?.id === org.id && open.what === "quota" ? null : { id: org.id, what: "quota" })}>Quota</button>
          {!org.is_operator && <>
            <button type="button" className="text-blue-700 underline" disabled={exportOrg.isPending} onClick={() => exportOrg.mutate(org)}>Export</button>
            <button type="button" className="text-red-700 underline" onClick={() => { setConfirm(""); setOpen({ id: org.id, what: "delete" }); }}>Delete</button>
          </>}
          {open?.id === org.id && open.what === "quota" && <SetQuota org={org} onDone={() => { setOpen(null); reload(); }} />}
          {open?.id === org.id && open.what === "delete" && <div role="group" aria-label={`Delete ${org.code}`} className="mt-2 whitespace-normal rounded border border-red-200 bg-red-50 p-2">
            <p>Deletes every person, problem, run and record of {org.name}, for good. Export it first. Type its code to confirm.</p>
            <input aria-label={`Type ${org.code} to confirm`} className={`${INPUT} mt-1`} value={confirm} onChange={(e) => setConfirm(e.target.value)} />{" "}
            <button type="button" className="rounded bg-red-700 px-3 py-1 text-white disabled:opacity-50" disabled={confirm !== org.code || remove.isPending}
              onClick={() => remove.mutate(org)}>Delete {org.code}</button>
            {remove.isError && <p role="alert" className="text-red-700">{formatApiError(remove.error)}</p>}
          </div>}
        </td></tr>)}</tbody>
    </table>
    {exportOrg.isError && <p role="alert" className="text-sm text-red-700">{formatApiError(exportOrg.error)}</p>}
    <form aria-label="Start an organization" className="mt-4 grid gap-2 sm:grid-cols-3" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
      <h3 className="font-semibold sm:col-span-3">Start an organization</h3>
      {([["code", "Code (lower-case, unique)"], ["name", "Name"], ["admin_username", "First administrator's user name"]] as const).map(([key, label]) => (
        <label key={key} className="block text-sm">{label}
          <input className={`${INPUT} mt-1 w-full`} value={made[key]} onChange={(e) => setMade({ ...made, [key]: e.target.value })} /></label>))}
      <label className="block text-sm">Their first password (12 characters or more; they change it)
        <input type="password" autoComplete="new-password" className={`${INPUT} mt-1 w-full`} value={made.admin_password}
          onChange={(e) => setMade({ ...made, admin_password: e.target.value })} /></label>
      <label className="block text-sm">Tier
        <select className={`${INPUT} mt-1 w-full`} value={made.tier} onChange={(e) => setMade({ ...made, tier: e.target.value })}>
          <option value="">none</option>{TIERS.map((t) => <option key={t} value={t}>{t}</option>)}</select></label>
      <div className="self-end"><button type="submit" className="rounded bg-blue-700 px-3 py-1.5 text-sm text-white disabled:opacity-50"
        disabled={!made.code || !made.name || !made.admin_username || made.admin_password.length < 12 || create.isPending}>Start it</button></div>
    </form>
    {create.isError && <p role="alert" className="text-sm text-red-700">{formatApiError(create.error)}</p>}
    {create.isSuccess && <p role="status" className="text-sm text-green-800">Started. Its administrator can sign in now.</p>}
  </section>;
}

/** The organization's own sign-in, directory sync and limits, and -- for the operator -- every organization. */
export default function Organizations() {
  useDocumentTitle("Organizations and sign-in");
  const { can } = useCapabilities();
  return <div className="max-w-5xl space-y-6">
    <header><h1 className="text-2xl font-semibold text-slate-900">Organizations and sign-in</h1>
      <p className="mt-1 text-sm text-slate-600">How people sign in to this organization, its limits, and the organizations this platform serves.</p></header>
    <OwnQuota />
    {can("iam.manage") && <><SingleSignOn /><DirectorySync /><AllOrganizations /></>}
  </div>;
}
