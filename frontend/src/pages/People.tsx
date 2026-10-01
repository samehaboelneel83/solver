/**
 * People and their roles (UX audit A-1, A-2). Who can sign in, what each may
 * do, and who holds no role at all -- which the generic table never showed:
 * two accounts named "Planner" held nothing, and nothing said so. Roles are
 * changed in place; deactivating ends that person's sessions at once.
 */
import { useState } from "react";
import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { formatApiError } from "../api/errors";
import { setPersonActive, setPersonRoles, usePeople, type Person, type RoleSummary } from "../api/v1";
import { useDocumentTitle } from "../hooks/useDocumentTitle";

const BUTTON = "rounded-md border border-slate-300 px-2 py-1 text-xs font-medium text-slate-800 hover:bg-slate-50 disabled:opacity-50";

function RolesEditor({ person, roles, onDone }: { person: Person; roles: RoleSummary[]; onDone: () => void }) {
  const client = useQueryClient();
  const [chosen, setChosen] = useState(new Set(person.roles.map((r) => r.id)));
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  return (
    <fieldset className="mt-2 rounded border border-slate-200 bg-slate-50 p-2">
      <legend className="px-1 text-xs text-slate-600">Roles for {person.display_name ?? person.username}</legend>
      <div className="flex flex-wrap gap-3">
        {roles.map((role) => (
          <label key={role.id} className="text-sm">
            <input type="checkbox" checked={chosen.has(role.id)}
              onChange={(event) => setChosen((current) => {
                const next = new Set(current);
                if (event.target.checked) next.add(role.id); else next.delete(role.id);
                return next;
              })} /> {role.name}
          </label>
        ))}
      </div>
      <div className="mt-2 flex gap-2">
        <button type="button" className="rounded-md bg-blue-600 px-3 py-1 text-xs font-medium text-white disabled:opacity-50" disabled={busy}
          onClick={async () => {
            setBusy(true);
            setProblem(null);
            try {
              await setPersonRoles(person.id, [...chosen]);
              await client.invalidateQueries();
              onDone();
            } catch (error) {
              setProblem(formatApiError(error));
            } finally {
              setBusy(false);
            }
          }}>Save roles</button>
        <button type="button" className="text-xs underline" onClick={onDone}>Cancel</button>
      </div>
      {problem && <p role="alert" className="mt-1 text-xs text-red-700">{problem}</p>}
    </fieldset>
  );
}

function PersonRow({ person, roles }: { person: Person; roles: RoleSummary[] }) {
  const client = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const noRole = person.roles.length === 0;
  return (
    <tr className="border-t border-slate-100 align-top">
      <th scope="row" className="py-2 pr-3 text-left font-normal">
        <span className="font-medium text-slate-900">{person.display_name ?? person.username}</span>
        <span className="block font-mono text-xs text-slate-500">{person.username}</span>
      </th>
      <td className="py-2 pr-3">
        {noRole
          ? <span className="rounded bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-900">No role: can sign in, but do nothing</span>
          : <span className="flex flex-wrap gap-1">{person.roles.map((r) => <span key={r.id} className="rounded bg-slate-100 px-2 py-0.5 text-xs">{r.name}</span>)}</span>}
        {editing && <RolesEditor person={person} roles={roles} onDone={() => setEditing(false)} />}
      </td>
      <td className="py-2 pr-3 text-sm">{person.is_active ? "Active" : <span className="text-slate-500">Deactivated</span>}</td>
      <td className="py-2">
        <div className="flex flex-wrap gap-2">
          {!editing && <button type="button" className={BUTTON} onClick={() => setEditing(true)}>Change roles</button>}
          <button type="button" className={BUTTON} disabled={busy}
            onClick={async () => {
              setBusy(true);
              setProblem(null);
              try {
                await setPersonActive(person.id, !person.is_active);
                await client.invalidateQueries();
              } catch (error) {
                setProblem(formatApiError(error));
              } finally {
                setBusy(false);
              }
            }}>{person.is_active ? "Deactivate" : "Activate"}</button>
          <Link className={BUTTON} to={`/iam/user_account/${person.id}`}>Edit details</Link>
        </div>
        {problem && <p role="alert" className="mt-1 text-xs text-red-700">{problem}</p>}
      </td>
    </tr>
  );
}

export default function People() {
  useDocumentTitle("People & roles");
  const people = usePeople();
  const users = people.data?.users ?? [];
  const roles = people.data?.roles ?? [];
  const roleless = users.filter((u) => u.is_active && u.roles.length === 0);
  return (
    <div className="max-w-5xl space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">People &amp; roles</h1>
          <p className="mt-1 text-sm text-slate-600">Who can sign in, and what each person may do. A role is a set of permissions; a person can hold several.</p>
        </div>
        <Link className="rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white" to="/iam/user_account/new">New user</Link>
      </header>
      {people.isLoading && <p role="status" className="text-sm text-slate-600">Loading…</p>}
      {people.isError && <p role="alert" className="text-sm text-red-700">{formatApiError(people.error)}</p>}
      {roleless.length > 0 && (
        <p role="note" className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
          {roleless.length === 1 ? "1 person has" : `${roleless.length} people have`} no role, so they can sign in but do nothing:{" "}
          {roleless.map((u) => u.display_name && users.filter((o) => o.display_name === u.display_name).length > 1 ? `${u.display_name} (${u.username})` : (u.display_name ?? u.username)).join(", ")}.
          Give each one a role with “Change roles”.
        </p>
      )}
      {users.length > 0 && (
        <section aria-labelledby="people-heading" className="rounded-lg border border-slate-200 bg-white p-4">
          <h2 id="people-heading" className="mb-2 text-lg font-semibold text-slate-900">People</h2>
          <table className="w-full text-sm">
            <thead><tr className="text-left text-xs uppercase tracking-wide text-slate-500"><th className="py-1">Person</th><th>Roles</th><th>Status</th><th><span className="sr-only">Actions</span></th></tr></thead>
            <tbody>{users.map((person) => <PersonRow key={person.id} person={person} roles={roles} />)}</tbody>
          </table>
        </section>
      )}
      {roles.length > 0 && (
        <section aria-labelledby="roles-heading" className="rounded-lg border border-slate-200 bg-white p-4">
          <h2 id="roles-heading" className="mb-2 text-lg font-semibold text-slate-900">Roles</h2>
          <table className="w-full text-sm">
            <thead><tr className="text-left text-xs uppercase tracking-wide text-slate-500"><th className="py-1">Role</th><th>People</th><th>May</th><th><span className="sr-only">Edit</span></th></tr></thead>
            <tbody>
              {roles.map((role) => (
                <tr key={role.id} className="border-t border-slate-100 align-top">
                  <th scope="row" className="py-2 pr-3 text-left font-medium">{role.name} <span className="block font-mono text-xs font-normal text-slate-500">{role.code}</span></th>
                  <td className="py-2 pr-3">{role.users}</td>
                  <td className="py-2 pr-3 text-xs text-slate-700">
                    {role.capabilities.length ? `${role.capabilities.length} ${role.capabilities.length === 1 ? "permission" : "permissions"}: ${role.capabilities.join(", ")}` : "Nothing yet"}
                  </td>
                  <td className="py-2"><Link className={BUTTON} to={`/iam/role/${role.id}`}>Edit permissions</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
