import LoadFailure from "../components/LoadFailure";
import { useEffect, useId, useState } from "react";
import OfflineNotice from "../components/OfflineNotice";
import Skeleton from "../components/Skeleton";
import { useToast } from "../components/ToastProvider";
import { useEntityList } from "../api/entities";
import { formatApiError } from "../api/errors";
import {
  useMe,
  useSetSetting,
  useSettings,
  useUpdateMe,
  type Id,
  type MeUpdate,
  type SettingScope,
  type SettingValue,
} from "../api/v1";
import { useCapabilities } from "../hooks/useCapability";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { useDomain } from "../hooks/useDomain";

/**
 * What governs a solve, and where each value comes from.
 *
 * Three levels override in one direction -- problem beats domain beats
 * platform beats the built-in default -- and the screen shows which one
 * supplied each value. That attribution is the point: "60, from this domain"
 * tells you which of three places to edit, where a bare "60" sends you
 * looking.
 *
 * **Clearing a box unsets that level** rather than writing a zero, and the
 * value visibly falls back to whatever the level above says. Without that, a
 * platform could only ever accumulate overrides.
 */

const SCOPE_NOTE: Record<SettingScope, string> = {
  platform: "Everything, unless a domain or problem says otherwise.",
  domain: "This domain's problems, unless a problem says otherwise.",
  problem: "This problem alone.",
};

const SOURCE_LABEL: Record<string, string> = {
  platform: "set for the platform",
  domain: "set for this domain",
  problem: "set for this problem",
  default: "built-in default",
};

export default function Settings() {
  useDocumentTitle("Settings");
  const { domainId } = useDomain();
  const [scope, setScope] = useState<SettingScope>("platform");
  const [problemId, setProblemId] = useState<Id | null>(null);

  const problems = useEntityList("public", "problem", {
    limit: 500,
    offset: 0,
    orderBy: "name",
    order: "asc",
    filters: domainId === null ? {} : { domain_id: String(domainId) },
  });
  const problemItems = problems.data?.items ?? [];
  const problem = problemId ?? (problemItems[0] ? Number(problemItems[0].id) : null);

  // Reading always resolves against the most specific context on screen, so
  // the values shown are the ones a run would actually get.
  const settings = useSettings({
    problemId: scope === "problem" ? problem : null,
    domainId: scope === "platform" ? null : domainId,
  });

  return (
    <div className="max-w-4xl">
      <h1 className="mb-1 text-lg font-semibold text-slate-900">Settings</h1>
      <p className="mb-4 text-sm text-slate-500">
        What a solve does when nobody says otherwise. A problem overrides its domain, which overrides the
        platform; where nothing is set, the built-in default applies.
      </p>

      <div className="mb-4 flex flex-wrap items-end gap-4">
        <label className="text-sm text-slate-700">
          <span className="mr-2 font-medium">Level</span>
          <select
            className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm"
            value={scope}
            onChange={(event) => setScope(event.target.value as SettingScope)}
          >
            <option value="platform">Platform</option>
            <option value="domain" disabled={domainId === null}>
              Domain
            </option>
            <option value="problem" disabled={problemItems.length === 0}>
              Problem
            </option>
          </select>
        </label>

        {scope === "problem" && (
          <label className="text-sm text-slate-700">
            <span className="mr-2 font-medium">Problem</span>
            <select
              className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm"
              value={problem === null ? "" : String(problem)}
              onChange={(event) => setProblemId(Number(event.target.value))}
            >
              {problemItems.map((row) => (
                <option key={String(row.id)} value={String(row.id)}>
                  {typeof row.name === "string" ? row.name : String(row.id)}
                </option>
              ))}
            </select>
          </label>
        )}

        <p className="text-sm text-slate-500">{SCOPE_NOTE[scope]}</p>
      </div>

      {scope === "domain" && domainId === null ? (
        <Note>Choose a domain in the sidebar&rsquo;s Domain selector to set domain-level values.</Note>
      ) : settings.fetchStatus === "paused" && !settings.data ? (
        <OfflineNotice subject="Settings" />
      ) : settings.isLoading ? (
        <Skeleton rows={4} cols={3} />
      ) : settings.isError && !settings.data ? (
        <LoadFailure subject="Settings" error={settings.error} retry={() => void settings.refetch()} />
      ) : (
        <Grouped items={settings.data?.items ?? []} scope={scope}
          scopeId={scope === "platform" ? null : scope === "domain" ? domainId : problem} />
      )}

      {/* Your own password is not a platform setting (UX audit A-3): kept here, folded away. */}
      <details className="mt-8">
        <summary className="cursor-pointer text-sm font-semibold text-slate-900">Your account (display name and password)</summary>
        <div className="mt-3"><AccountForm /></div>
      </details>
    </div>
  );
}

/** What each family of keys is about, for its heading. */
const FAMILIES: Record<string, string> = {
  solve: "Solving and solver choice",
  retention: "How long things are kept",
  spatial: "Maps",
  shadow: "Shadow runs",
  governance: "Governance and approvals",
  audit: "Audit",
  run: "Runs",
  ml: "Learned models",
};

function family(key: string): string {
  const prefix = key.split(".")[0];
  return FAMILIES[prefix] ?? prefix.charAt(0).toUpperCase() + prefix.slice(1).replace(/_/g, " ");
}

/** The settings in families, findable by words, and narrowable to those set at this level (UX audit A-3). */
function Grouped({ items, scope, scopeId }: { items: SettingValue[]; scope: SettingScope; scopeId: Id | null }) {
  const [q, setQ] = useState("");
  const [changedOnly, setChangedOnly] = useState(false);
  const words = q.trim().toLowerCase();
  const shown = items.filter((item) => (!changedOnly || item.source === scope)
    && (!words || item.key.toLowerCase().includes(words) || (item.description ?? "").toLowerCase().includes(words)));
  const families = [...new Set(shown.map((item) => family(item.key)))];
  return (
    <>
      <div className="mb-4 flex flex-wrap items-center gap-4">
        <label className="text-sm text-slate-700">Find a setting{" "}
          <input type="search" className="ms-2 rounded-md border border-slate-300 px-2 py-1 text-sm" value={q}
            onChange={(event) => setQ(event.target.value)} placeholder="retention, solver…" />
        </label>
        <label className="text-sm text-slate-700">
          <input type="checkbox" checked={changedOnly} onChange={(event) => setChangedOnly(event.target.checked)} />{" "}
          Only those set at this level
        </label>
      </div>
      {shown.length === 0 && <Note>No setting matches.</Note>}
      {families.map((name) => (
        <section key={name} aria-label={name} className="mb-6">
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-600">{name}</h2>
          <ul className="space-y-3">
            {shown.filter((item) => family(item.key) === name).map((item) => (
              <SettingRow key={item.key} setting={item} scope={scope} scopeId={scopeId} />
            ))}
          </ul>
        </section>
      ))}
    </>
  );
}

function AccountForm() {
  const me = useMe();
  const save = useUpdateMe();
  const toast = useToast();
  const formId = useId();
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [failure, setFailure] = useState<string | null>(null);

  useEffect(() => {
    if (!me.data) return;
    setDisplayName(me.data.display_name ?? "");
    setEmail(me.data.email ?? "");
  }, [me.data]);

  function commit() {
    setFailure(null);
    const body: MeUpdate = {
      display_name: displayName.trim() === "" ? null : displayName,
      email: email.trim() === "" ? null : email,
    };
    if (password !== "") {
      body.password = password;
    }
    save.mutate(body, {
      onSuccess: () => {
        setPassword("");
        toast.success("Account saved");
      },
      onError: (error: unknown) => setFailure(formatApiError(error)),
    });
  }

  if (!me.data) {
    return null;
  }

  return (
    <section className="mb-6 rounded-md border border-slate-200 bg-white p-3">
      <h2 className="text-sm font-semibold text-slate-900">Your account</h2>
      <p className="mb-3 text-xs text-slate-500">
        Signed in as {me.data.username}. Changing this is not granting a role.
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-sm text-slate-700">
          <span className="mb-1 block font-medium">Display name</span>
          <input
            id={`${formId}-display-name`}
            className="w-52 rounded-md border border-slate-300 px-2 py-1 text-sm"
            value={displayName}
            onChange={(event) => setDisplayName(event.target.value)}
          />
        </label>
        <label className="text-sm text-slate-700">
          <span className="mb-1 block font-medium">Email</span>
          <input
            id={`${formId}-email`}
            type="email"
            className="w-56 rounded-md border border-slate-300 px-2 py-1 text-sm"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </label>
        <label className="text-sm text-slate-700">
          <span className="mb-1 block font-medium">Password</span>
          <input
            id={`${formId}-password`}
            type="password"
            autoComplete="new-password"
            className="w-52 rounded-md border border-slate-300 px-2 py-1 text-sm"
            value={password}
            placeholder="leave blank to keep"
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>
        <button
          type="button"
          onClick={commit}
          disabled={save.isPending}
          className="rounded-md bg-blue-600 px-3 py-1 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
        >
          Save account
        </button>
      </div>
      {failure && (
        <p role="alert" className="mt-2 text-xs text-red-600">
          {failure}
        </p>
      )}
    </section>
  );
}

function SettingRow({
  setting,
  scope,
  scopeId,
}: {
  setting: SettingValue;
  scope: SettingScope;
  scopeId: Id | null;
}) {
  const { can } = useCapabilities();
  const save = useSetSetting();
  const toast = useToast();
  // A yes/no setting that is only inherited starts on "inherited", so picking Yes or No shows.
  const [draft, setDraft] = useState<string>(
    setting.value === null || (setting.value_type === "boolean" && setting.source !== scope) ? "" : String(setting.value));
  const [failure, setFailure] = useState<string | null>(null);

  // Set here, or inherited from somewhere else? Only the first can be unset
  // on this screen, and saying so stops "clear" reading as "set to nothing".
  const setHere = setting.source === scope;

  function commit() {
    setFailure(null);
    const trimmed = draft.trim();
    const value =
      trimmed === ""
        ? null
        : setting.value_type === "number"
          ? Number(trimmed)
          : setting.value_type === "boolean"
            ? trimmed === "true"
            : trimmed;
    if (setting.value_type === "number" && value !== null && Number.isNaN(value)) {
      setFailure(`${setting.key} is a number`);
      return;
    }
    save.mutate(
      { scope, scope_id: scopeId, key: setting.key, value },
      {
        onSuccess: () => toast.success(value === null ? `${setting.key} unset` : `${setting.key} saved`),
        onError: (error: unknown) => setFailure(formatApiError(error)),
      }
    );
  }

  return (
    <li className="rounded-md border border-slate-200 bg-white p-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="font-mono text-sm text-slate-900">{setting.key}</p>
          <p className="text-xs text-slate-500">{setting.description}</p>
        </div>
        <div className="flex items-center gap-2">
          {setting.value_type === "boolean" ? (
            // Yes or no, not a text box to type "true" into (UX audit A-3).
            <select
              aria-label={setting.key}
              className="w-40 rounded-md border border-slate-300 bg-white px-2 py-1 text-sm"
              value={draft}
              disabled={!can("settings.edit")}
              onChange={(event) => setDraft(event.target.value)}
            >
              <option value="">{setHere ? "unset (inherit)" : `inherited: ${setting.value ? "yes" : "no"}`}</option>
              <option value="true">Yes</option>
              <option value="false">No</option>
            </select>
          ) : (
            <input
              aria-label={setting.key}
              className="w-40 rounded-md border border-slate-300 px-2 py-1 text-sm"
              value={draft}
              disabled={!can("settings.edit")}
              placeholder={setHere ? "" : "inherited"}
              onChange={(event) => setDraft(event.target.value)}
            />
          )}
          {can("settings.edit") && (
            <button
              type="button"
              onClick={commit}
              disabled={save.isPending}
              className="rounded-md bg-blue-600 px-3 py-1 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
            >
              Save
            </button>
          )}
        </div>
      </div>
      <p className="mt-1 text-xs text-slate-500">
        {SOURCE_LABEL[setting.source] ?? setting.source}
        {setHere && can("settings.edit") && " — clear the box to unset it and inherit again"}
      </p>
      {failure && (
        <p role="alert" className="mt-1 text-xs text-red-600">
          {failure}
        </p>
      )}
    </li>
  );
}

function Note({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
      {children}
    </div>
  );
}
