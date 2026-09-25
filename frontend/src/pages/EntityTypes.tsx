import { FormEvent, useId, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  ENTITY_ROLES,
  ErrorSummary,
  FieldError,
  FieldLabel,
  INPUT_CLASS,
  colourFieldError,
  describedBy,
  nameProblem,
  roleLabel,
  serverFieldErrors,
  useFieldErrors,
  type FieldErrors,
} from "../components/attrTypes";
import ColourField from "../components/ColourField";
import OfflineNotice from "../components/OfflineNotice";
import Skeleton from "../components/Skeleton";
import { useToast } from "../components/ToastProvider";
import { formatApiError } from "../api/errors";
import GridGeneratorForm from "../components/GridGeneratorForm";
import { useCreateEntityType, useEntityTypes, type EntityRole, type Id } from "../api/v1";
import InheritanceFields from "../components/InheritanceFields";
import { typeColour } from "../lib/colour";
import { useCapabilities } from "../hooks/useCapability";
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
  const { can } = useCapabilities();
  const canEdit = can("domain.edit");

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
          {canEdit && <CreateTypeForm domainId={domainId} />}
          {canEdit && <GridSection domainId={domainId} />}
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
              Colour
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
              <td className="px-3 py-2 text-slate-700">
                <span className="flex items-center gap-2">
                  <span
                    aria-hidden="true"
                    className="inline-block h-4 w-4 rounded border border-slate-300"
                    style={{ backgroundColor: typeColour({ id: String(type.id), colour: type.colour }) }}
                    data-testid={`type-swatch-${type.name}`}
                  />
                  {/* The swatch is decorative; the text is what a screen
                      reader and a colour-blind user actually read. */}
                  <span className="font-mono text-xs">{type.colour ?? "automatic"}</span>
                </span>
              </td>
              <td className="px-3 py-2 text-slate-700">
                {roleLabel(type.role)}
                {type.is_abstract && <span className="ms-2 rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-600">abstract</span>}
              </td>
              <td className="px-3 py-2 text-slate-700">{type.attributes.length}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const TYPE_FIELDS = ["name", "role", "colour", "icon", "inherited_from", "is_abstract"];

/** The name + role + colour form shared by "new type" (here) and the type
 * editor. `colour` is optional: null means the graph picks a stable one
 * from the type's id, which is why the control has an explicit "use
 * automatic" rather than only a swatch. */
export function EntityTypeFields({
  name,
  role,
  colour,
  onName,
  onRole,
  onColour,
  onColourProblem,
  errors,
  fallbackKey,
}: {
  name: string;
  role: EntityRole;
  colour: string | null;
  onName: (value: string) => void;
  onRole: (value: EntityRole) => void;
  onColour: (value: string | null) => void;
  /** What the colour box cannot commit, so the form can refuse the save.
   * Without it an unparseable colour was simply never reported, the save
   * went ahead and the toast said it had worked. */
  onColourProblem: (problem: string | null) => void;
  errors: FieldErrors;
  /** The id the graph hashes for the fallback colour. A type being created
   * has none yet, so the preview uses its name -- honest about being a
   * preview, and it is the only stable handle a new type has. */
  fallbackKey: string;
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
      <div className="sm:col-span-2">
        <ColourField
          value={colour}
          onChange={onColour}
          onProblemChange={onColourProblem}
          // One message, not two: ColourField draws whatever the form is
          // showing for this field, so the summary and the text under the
          // control agree the way they do everywhere else.
          error={errors.colour}
          fallbackKey={fallbackKey}
          sampleText={name.trim() === "" ? "employee" : name}
        />
      </div>
    </div>
  );
}

export const ENTITY_TYPE_FIELDS = TYPE_FIELDS;

function CreateTypeForm({ domainId }: { domainId: Id }) {
  const [name, setName] = useState("");
  const [role, setRole] = useState<EntityRole>("other");
  const [inheritedFrom, setInheritedFrom] = useState<Id | null>(null);
  const [isAbstract, setIsAbstract] = useState(false);
  const siblings = useEntityTypes(domainId, { limit: 500 });
  const [colour, setColour] = useState<string | null>(null);
  // What the colour box holds but cannot commit. Held here rather than in
  // `colour`, because a value that cannot be parsed is not a colour.
  const [colourProblem, setColourProblem] = useState<string | null>(null);
  const [serverErrors, setServerErrors] = useState<FieldErrors | null>(null);
  const [general, setGeneral] = useState<string | null>(null);
  const { errors, replace, summaryRef } = useFieldErrors(serverErrors);
  const createType = useCreateEntityType();
  const toast = useToast();
  const navigate = useNavigate();

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setGeneral(null);
    const problems: FieldErrors = {};
    const problem = nameProblem(name, false);
    if (problem) problems.name = problem;
    const colourMessage = colourFieldError(colourProblem);
    if (colourMessage) problems.colour = colourMessage;
    replace(problems);
    if (Object.keys(problems).length > 0) return;
    try {
      const created = await createType.mutateAsync({
        domain_id: domainId, name, role, colour,
        ...(isAbstract ? { is_abstract: true } : {}),
        ...(inheritedFrom !== null ? { inherited_from: inheritedFrom } : {}),
      });
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
          colour={colour}
          errors={errors}
          fallbackKey={name}
          onName={(value) => {
            setName(value);
            if (errors.name) {
              const { name: _drop, ...rest } = errors;
              replace(rest);
            }
          }}
          onRole={setRole}
          onColour={setColour}
          onColourProblem={setColourProblem}
        />
        <InheritanceFields
          types={siblings.data?.items ?? []}
          inheritedFrom={inheritedFrom}
          isAbstract={isAbstract}
          onInheritedFrom={setInheritedFrom}
          onAbstract={setIsAbstract}
          errors={errors}
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

/** GIS 3: cells and their adjacency, made over an area drawn on a record. */
function GridSection({ domainId }: { domainId: Id }) {
  const { data } = useEntityTypes(domainId, { limit: 500 });
  return (
    <section className="mt-6 rounded-md border border-slate-200 bg-white p-4" aria-labelledby="grid-heading">
      <h2 id="grid-heading" className="mb-2 font-medium text-slate-900">Make a grid</h2>
      <GridGeneratorForm domainId={domainId} entityTypes={data?.items ?? []} />
    </section>
  );
}
