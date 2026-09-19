import { FormEvent, useId, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  ENTITY_ROLES,
  ErrorSummary,
  FieldError,
  FieldLabel,
  INPUT_CLASS,
  describedBy,
  nameProblem,
  roleLabel,
  serverFieldErrors,
  useFieldErrors,
  type FieldErrors,
} from "../components/attrTypes";
import OfflineNotice from "../components/OfflineNotice";
import Skeleton from "../components/Skeleton";
import { useToast } from "../components/ToastProvider";
import { formatApiError } from "../api/errors";
import { useCreateEntityType, useEntityTypes, type EntityRole, type Id } from "../api/v1";
import { useDomain } from "../hooks/useDomain";
import { useDocumentTitle } from "../hooks/useDocumentTitle";

/**
 * The selected domain's entity types. Each row opens the type's editor
 * (`EntityTypeDetail`), where its attributes are defined; new types are
 * created here, then opened.
 *
 * A domain holds a handful of types, not thousands, so the page asks for
 * the API's maximum page (500) and does not paginate.
 */
export default function EntityTypes() {
  useDocumentTitle("Entity types");
  const { domainId } = useDomain();

  return (
    <div className="max-w-4xl">
      <h1 className="mb-4 text-lg font-semibold text-slate-900">Entity types</h1>
      {domainId === null ? (
        <div className="rounded-md border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
          <p>
            Choose a domain in the sidebar&rsquo;s Domain selector (under Menu on a small screen) to see its entity
            types.
          </p>
          <p className="mt-1">
            No domain yet?{" "}
            <Link to="/public/domain" className="inline-block rounded py-1 text-blue-600 underline">
              Create one on the Domains page
            </Link>
            .
          </p>
        </div>
      ) : (
        <>
          <TypeList domainId={domainId} />
          <CreateTypeForm domainId={domainId} />
        </>
      )}
    </div>
  );
}

function TypeList({ domainId }: { domainId: Id }) {
  const { data, error, isLoading, refetch, fetchStatus } = useEntityTypes(domainId, { limit: 500 });

  if (fetchStatus === "paused" && !data) return <OfflineNotice subject="The entity type list" />;
  if (isLoading) return <Skeleton rows={3} cols={3} />;
  if (error && !data) {
    return (
      <div className="mb-6 flex flex-wrap items-center gap-3">
        <p className="text-sm text-red-600">{formatApiError(error)}</p>
        <button
          type="button"
          onClick={() => refetch()}
          className="rounded-md border border-red-300 px-2 py-1 text-xs font-medium text-red-700 hover:bg-red-50"
        >
          Retry
        </button>
      </div>
    );
  }

  const types = data?.items ?? [];
  if (types.length === 0) {
    return (
      <p className="mb-6 text-sm text-slate-600">
        No entity types in this domain yet. Create the first one below.
      </p>
    );
  }

  return (
    <div className="mb-6 overflow-x-auto rounded-md border border-slate-200 bg-white">
      <table className="w-full text-left text-sm" aria-label="Entity types">
        <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-600">
          <tr>
            <th scope="col" className="px-3 py-2 font-semibold">
              Name
            </th>
            <th scope="col" className="px-3 py-2 font-semibold">
              Role
            </th>
            <th scope="col" className="px-3 py-2 font-semibold">
              Attributes
            </th>
          </tr>
        </thead>
        <tbody>
          {types.map((type) => (
            <tr key={type.id} className="border-b border-slate-100 last:border-0">
              <th scope="row" className="px-3 py-2 font-normal">
                <Link to={`/entity-types/${type.id}`} className="inline-block rounded py-1 font-mono text-blue-600 underline">
                  {type.name}
                </Link>
              </th>
              <td className="px-3 py-2 text-slate-700">{roleLabel(type.role)}</td>
              <td className="px-3 py-2 text-slate-700">{type.attributes.length}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const TYPE_FIELDS = ["name", "role"];

/** The name + role form shared by "new type" (here) and the type editor. */
export function EntityTypeFields({
  name,
  role,
  onName,
  onRole,
  errors,
}: {
  name: string;
  role: EntityRole;
  onName: (value: string) => void;
  onRole: (value: EntityRole) => void;
  errors: FieldErrors;
}) {
  const baseId = useId();
  const id = (field: string) => `${baseId}-${field}`;
  const errorId = (field: string) => `${baseId}-${field}-error`;
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <div>
        <FieldLabel htmlFor={id("name")} required>
          Name
        </FieldLabel>
        <input
          id={id("name")}
          type="text"
          autoComplete="off"
          spellCheck={false}
          className={`${INPUT_CLASS} font-mono`}
          value={name}
          aria-invalid={errors.name ? "true" : undefined}
          aria-describedby={describedBy(id("name-hint"), errors.name && errorId("name"))}
          onChange={(e) => onName(e.target.value)}
        />
        <p id={id("name-hint")} className="mt-1 text-xs text-slate-500">
          Lowercase, e.g. <code>employee</code>.
        </p>
        <FieldError id={errorId("name")} message={errors.name} />
      </div>
      <div>
        <FieldLabel htmlFor={id("role")} required>
          Role
        </FieldLabel>
        <select
          id={id("role")}
          className={INPUT_CLASS}
          value={role}
          aria-invalid={errors.role ? "true" : undefined}
          aria-describedby={describedBy(id("role-hint"), errors.role && errorId("role"))}
          onChange={(e) => onRole(e.target.value as EntityRole)}
        >
          {ENTITY_ROLES.map((r) => (
            <option key={r.value} value={r.value}>
              {r.label}
            </option>
          ))}
        </select>
        <p id={id("role-hint")} className="mt-1 text-xs text-slate-500">
          How screens (and, later, the model compiler) treat this type. It does not restrict what can be stored.
        </p>
        <FieldError id={errorId("role")} message={errors.role} />
      </div>
    </div>
  );
}

export const ENTITY_TYPE_FIELDS = TYPE_FIELDS;

function CreateTypeForm({ domainId }: { domainId: Id }) {
  const [name, setName] = useState("");
  const [role, setRole] = useState<EntityRole>("other");
  const [serverErrors, setServerErrors] = useState<FieldErrors | null>(null);
  const [general, setGeneral] = useState<string | null>(null);
  const { errors, replace, summaryRef } = useFieldErrors(serverErrors);
  const createType = useCreateEntityType();
  const toast = useToast();
  const navigate = useNavigate();

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setGeneral(null);
    const problem = nameProblem(name, false);
    replace(problem ? { name: problem } : {});
    if (problem) return;
    try {
      const created = await createType.mutateAsync({ domain_id: domainId, name, role });
      toast.success(`Entity type "${created.name}" created`);
      navigate(`/entity-types/${created.id}`);
    } catch (err) {
      const result = serverFieldErrors(err, TYPE_FIELDS, "entity type");
      setServerErrors(result.fields);
      setGeneral(result.general);
    }
  }

  return (
    <section aria-labelledby="new-entity-type-heading" className="rounded-md border border-slate-200 bg-white p-4">
      <h2 id="new-entity-type-heading" className="mb-3 text-base font-semibold text-slate-900">
        New entity type
      </h2>
      <form aria-label="New entity type" onSubmit={handleSubmit} noValidate className="space-y-4">
        <ErrorSummary errors={errors} order={TYPE_FIELDS} summaryRef={summaryRef} />
        {general && <p className="whitespace-pre-line text-sm text-red-600">{general}</p>}
        <EntityTypeFields
          name={name}
          role={role}
          errors={errors}
          onName={(value) => {
            setName(value);
            if (errors.name) {
              const { name: _drop, ...rest } = errors;
              replace(rest);
            }
          }}
          onRole={setRole}
        />
        <button
          type="submit"
          disabled={createType.isPending}
          className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {createType.isPending ? "Saving…" : "Create entity type"}
        </button>
      </form>
    </section>
  );
}
