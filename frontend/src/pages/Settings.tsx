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

      <AccountForm />

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
        <Note>{formatApiError(settings.error)}</Note>
      ) : (
        <ul className="space-y-3">
          {(settings.data?.items ?? []).map((item) => (
            <SettingRow
              key={item.key}
              setting={item}
              scope={scope}
              scopeId={scope === "platform" ? null : scope === "domain" ? domainId : problem}
            />
          ))}
        </ul>
      )}
    </div>
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
  const [draft, setDraft] = useState<string>(setting.value === null ? "" : String(setting.value));
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
          <input
            aria-label={setting.key}
            className="w-40 rounded-md border border-slate-300 px-2 py-1 text-sm"
            value={draft}
            disabled={!can("settings.edit")}
            placeholder={setHere ? "" : "inherited"}
            onChange={(event) => setDraft(event.target.value)}
          />
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
