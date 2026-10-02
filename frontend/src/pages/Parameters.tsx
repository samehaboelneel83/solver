import LoadFailure from "../components/LoadFailure";
import Pager from "../components/Pager";
import SearchBox, { NoMatches } from "../components/SearchBox";
import { FormEvent, useId, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import MeasureFromMap from "../components/MeasureFromMap";
import ComputedFrom, { type MadeSource } from "../components/ComputedFrom";
import TimesTooClose from "../components/TimesTooClose";
import ParameterGrid, { parseCellValue } from "../components/ParameterGrid";
import EntityParameterGrid from "../components/EntityParameterGrid";
import BulkPanel from "../components/BulkPanel";
import ParameterPicture from "../components/ParameterPicture";
import {
  ErrorSummary,
  FieldError,
  FieldLabel,
  INPUT_CLASS,
  describedBy,
  nameProblem,
  serverFieldErrors,
  useFieldErrors,
  type FieldErrors,
} from "../components/attrTypes";
import OfflineNotice from "../components/OfflineNotice";
import Skeleton from "../components/Skeleton";
import { useToast } from "../components/ToastProvider";
import { formatApiError } from "../api/errors";
import {
  useCreateParameter,
  useDeleteParameter,
  useEntityTypes,
  useParameter,
  useParameters,
  useUpdateParameter,
  type EntityType,
  type Id,
  type ParameterDef,
} from "../api/v1";
import { useCapabilities } from "../hooks/useCapability";
import { useDomain } from "../hooks/useDomain";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { parseRouteId } from "../lib/routeId";

/**
 * The selected domain's parameters, and the grid of values of whichever
 * one is open (`?parameter=<id>`, so a grid can be linked to and survives a
 * reload).
 *
 * A parameter is indexed data that belongs to no single entity --
 * `demand[day, shift]` -- so it is defined here and filled in by
 * `ParameterGrid`, which owns everything about the values themselves.
 *
 * What this page deliberately does **not** offer: re-indexing. The server
 * refuses it with a 409 as soon as a cell is stored (the cells were
 * entered for the old index and no trigger revisits them), and offering an
 * editor that works only while a parameter is empty would be a worse
 * explanation than saying so.
 */

const FIELDS = ["name", "index_type_ids", "default_value", "unit"];

export default function Parameters() {
  useDocumentTitle("Parameters");
  const { domainId } = useDomain();

  return (
    <div className="max-w-5xl">
      <h1 className="mb-4 text-lg font-semibold text-slate-900">Parameters</h1>
      {domainId === null ? (
        <div className="rounded-md border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
          <p>
            Choose a domain in the sidebar&rsquo;s Domain selector (under Menu on a small screen) to see its
            parameters.
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
        <ForDomain domainId={domainId} />
      )}
    </div>
  );
}

/** Parameters shown at once; the rest are paged and searched on the server (Epic UX, U-1). */
const PARAMETER_PAGE = 100;

function ForDomain({ domainId }: { domainId: Id }) {
  const { can } = useCapabilities();
  const canEdit = can("domain.edit");
  const [searchParams, setSearchParams] = useSearchParams();
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const parameters = useParameters(domainId, { limit: PARAMETER_PAGE, offset, q });
  const types = useEntityTypes(domainId, { limit: 500 });
  const requested = parseRouteId(searchParams.get("parameter"));
  // A linked parameter past this page (or outside the search) is fetched by its id (Epic UX, U-1).
  const listedHere = (parameters.data?.items ?? []).some((parameter) => parameter.id === requested);
  const linked = useParameter(requested !== null && parameters.data && !listedHere ? requested : null);

  if ((parameters.fetchStatus === "paused" && !parameters.data) || (types.fetchStatus === "paused" && !types.data)) {
    return <OfflineNotice subject="The parameter list" />;
  }
  if ((parameters.isLoading && !parameters.data) || types.isLoading) return <Skeleton rows={3} cols={4} />;
  if (parameters.isError && !parameters.data) {
    return <Failed error={parameters.error} onRetry={() => parameters.refetch()} />;
  }
  if (types.isError && !types.data) return <Failed error={types.error} onRetry={() => types.refetch()} />;

  const items = parameters.data?.items ?? [];
  const total = parameters.data?.total ?? items.length;
  const entityTypes = types.data?.items ?? [];
  const fromLink = linked.data && Number(linked.data.domain_id) === Number(domainId) ? linked.data : null;
  const selected = items.find((parameter) => parameter.id === requested) ?? fromLink;

  return (
    <>
      {requested !== null && !listedHere && linked.isError && (
        <LoadFailure subject="The linked parameter" error={linked.error} retry={() => void linked.refetch()} />
      )}
      {requested !== null && linked.data && !fromLink && (
        <p role="alert" className="mb-4 text-sm text-amber-800">The linked parameter belongs to another domain; nothing was substituted.</p>
      )}
      {(q || total > PARAMETER_PAGE) && (
        <div className="mb-3">
          <SearchBox label="parameters" initial={q} onSearch={(text) => { setQ(text); setOffset(0); }} />
        </div>
      )}
      {items.length === 0 && q ? (
        <NoMatches label="parameters" q={q} />
      ) : items.length === 0 ? (
        <p className="mb-6 text-sm text-slate-600">
          No parameters in this domain yet.{" "}
          {entityTypes.length > 0 && canEdit ? "Define the first one below." : ""}
        </p>
      ) : (
        <ParameterTable
          parameters={items}
          entityTypes={entityTypes}
          selectedId={selected?.id ?? null}
          onSelect={(id) => setSearchParams({ parameter: String(id) }, { replace: true })}
        />
      )}
      <Pager label="Parameter" offset={offset} size={PARAMETER_PAGE} total={total} onOffset={setOffset} />

      {selected ? (
        <section aria-labelledby="parameter-values-heading" className="mb-8">
          <h2 id="parameter-values-heading" className="mb-3 text-base font-semibold text-slate-900">
            <span className="font-mono">{selected.name}</span> values
          </h2>
          <ComputedFrom key={`made-${selected.id}`} parameterId={selected.id} source={selected.source as MadeSource | null | undefined} />
          <ParameterSettings key={`settings-${selected.id}`} parameter={selected} entityTypes={entityTypes} />
          {selected.index_type_ids.length === 0 ? (
            // One number (migration 0104): its value is its default, changed in the settings above.
            <p className="rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700">
              One number for the whole model: <span className="font-mono font-semibold">{String(selected.default_value)}</span>.
              Change it as its default value above; a model reads it as <code className="font-mono">{selected.name}</code>.
            </p>
          ) : selected.value_type_id != null ? (
            <EntityParameterGrid key={selected.id} parameter={selected} entityTypes={entityTypes} />
          ) : (
            <>
              <ParameterGrid key={selected.id} parameter={selected} />
              {/* Queue R17b: the same numbers as a picture, drawn like an answer. */}
              <div className="mt-4">
                <ParameterPicture key={`picture-${selected.id}`} parameter={selected} entityTypes={entityTypes} />
              </div>
            </>
          )}
          {selected.index_type_ids.length > 0 && (
            <div className="mt-4">
              <BulkPanel base={`/api/v1/parameters/${selected.id}`} what={`${selected.name} cells`} exportRows={false} />
            </div>
          )}
        </section>
      ) : (
        items.length > 0 && (
          <p className="mb-8 text-sm text-slate-600">Choose a parameter above to fill in its values.</p>
        )
      )}

      {entityTypes.length === 0 ? (
        <div className="rounded-md border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
          <p>Every parameter is indexed by at least one entity type, and this domain has none yet.</p>
          <p className="mt-1">
            <Link to="/entity-types" className="inline-block rounded py-1 text-blue-600 underline">
              Define an entity type first
            </Link>
            .
          </p>
        </div>
      ) : (
        canEdit && (
        <>
        <MeasureFromMap domainId={domainId} entityTypes={entityTypes} />
        <TimesTooClose domainId={domainId} entityTypes={entityTypes} />
        <CreateParameterForm
          domainId={domainId}
          entityTypes={entityTypes}
          onCreated={(id) => setSearchParams({ parameter: String(id) }, { replace: true })}
        />
        </>
        )
      )}
    </>
  );
}

function Failed({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  return <LoadFailure subject="The parameter list" error={error} retry={() => void onRetry()} />;
}

/** The index types of a parameter, named, **in index order**:
 * `demand[day, shift]` and `supply[shift, day]` are different parameters. */
function indexNames(parameter: ParameterDef, entityTypes: EntityType[]): string {
  if (parameter.index_type_ids.length === 0) return "— (one number)";
  return parameter.index_type_ids
    .map((id) => entityTypes.find((type) => type.id === id)?.name ?? `#${id}`)
    .join(", ");
}

function ParameterTable({
  parameters,
  entityTypes,
  selectedId,
  onSelect,
}: {
  parameters: ParameterDef[];
  entityTypes: EntityType[];
  selectedId: Id | null;
  onSelect: (id: Id) => void;
}) {
  const { can } = useCapabilities();
  const canEdit = can("domain.edit");
  const remove = useDeleteParameter();
  const toast = useToast();

  async function handleDelete(parameter: ParameterDef) {
    const confirmed = window.confirm(
      `Delete parameter "${parameter.name}"? Every value stored in its grid is deleted with it. ` +
        "This cannot be undone."
    );
    if (!confirmed) return;
    try {
      await remove.mutateAsync(parameter.id);
      toast.success(`Parameter "${parameter.name}" deleted`);
    } catch (err) {
      toast.error(formatApiError(err));
    }
  }

  return (
    <div className="mb-6 overflow-x-auto rounded-md border border-slate-200 bg-white">
      <table className="w-full text-left text-sm" aria-label="Parameters">
        <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-600">
          <tr>
            <th scope="col" className="px-3 py-2 font-semibold">
              Name
            </th>
            <th scope="col" className="px-3 py-2 font-semibold">
              Indexed by
            </th>
            <th scope="col" className="px-3 py-2 font-semibold">
              Default
            </th>
            <th scope="col" className="px-3 py-2 font-semibold">
              Unit
            </th>
            <th scope="col" className="px-3 py-2 font-semibold">
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {parameters.map((parameter) => (
            <tr
              key={parameter.id}
              className={`border-b border-slate-100 last:border-0 ${
                parameter.id === selectedId ? "bg-slate-50" : ""
              }`}
            >
              <th scope="row" className="px-3 py-2 font-normal">
                <button
                  type="button"
                  onClick={() => onSelect(parameter.id)}
                  aria-current={parameter.id === selectedId ? "true" : undefined}
                  className="rounded py-1 font-mono text-blue-600 underline hover:text-blue-800"
                >
                  {parameter.name}
                </button>
              </th>
              <td className="px-3 py-2 font-mono text-slate-700">{indexNames(parameter, entityTypes)}</td>
              <td className="px-3 py-2 text-slate-700">
                {parameter.value_type_id != null
                  ? `a ${entityTypes.find((t) => t.id === parameter.value_type_id)?.name ?? "entity"}`
                  : parameter.default_value}
              </td>
              <td className="px-3 py-2 text-slate-700">{parameter.unit ?? "—"}</td>
              <td className="whitespace-nowrap px-3 py-1 text-right">
                {canEdit && (
                <button
                  type="button"
                  aria-label={`Delete ${parameter.name}`}
                  onClick={() => handleDelete(parameter)}
                  className="rounded px-2 py-1.5 text-sm text-red-700 underline hover:text-red-900"
                >
                  Delete
                </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The name/default/unit boxes, shared by the create form and the settings
 * form. The index types are not here: they are chosen only at creation. */
function DefinitionFields({
  baseId,
  name,
  defaultValue,
  unit,
  errors,
  onName,
  onDefault,
  onUnit,
  entityValued = false,
}: {
  /** Queue R20b: an entity's parameter has no default -- an empty cell is none. */
  entityValued?: boolean;
  baseId: string;
  name: string;
  defaultValue: string;
  unit: string;
  errors: FieldErrors;
  onName: (value: string) => void;
  onDefault: (value: string) => void;
  onUnit: (value: string) => void;
}) {
  const id = (field: string) => `${baseId}-${field}`;
  const errorId = (field: string) => `${baseId}-${field}-error`;
  return (
    <div className="grid gap-4 sm:grid-cols-3">
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
          onChange={(event) => onName(event.target.value)}
        />
        <p id={id("name-hint")} className="mt-1 text-xs text-slate-500">
          Lowercase, e.g. <code>demand</code>.
        </p>
        <FieldError id={errorId("name")} message={errors.name} />
      </div>
      {!entityValued && (
      <div>
        <FieldLabel htmlFor={id("default_value")}>Default value</FieldLabel>
        <input
          id={id("default_value")}
          type="text"
          inputMode="numeric"
          autoComplete="off"
          className={`${INPUT_CLASS} font-mono`}
          value={defaultValue}
          aria-invalid={errors.default_value ? "true" : undefined}
          aria-describedby={describedBy(id("default-hint"), errors.default_value && errorId("default_value"))}
          onChange={(event) => onDefault(event.target.value)}
        />
        <p id={id("default-hint")} className="mt-1 text-xs text-slate-500">
          A number, used by every cell left empty. Values may have up to six decimal places (2.5, 0.125).
        </p>
        <FieldError id={errorId("default_value")} message={errors.default_value} />
      </div>
      )}
      <div>
        <FieldLabel htmlFor={id("unit")}>Unit</FieldLabel>
        <input
          id={id("unit")}
          type="text"
          autoComplete="off"
          className={INPUT_CLASS}
          value={unit}
          aria-invalid={errors.unit ? "true" : undefined}
          aria-describedby={describedBy(id("unit-hint"), errors.unit && errorId("unit"))}
          onChange={(event) => onUnit(event.target.value)}
        />
        <p id={id("unit-hint")} className="mt-1 text-xs text-slate-500">
          Shown beside the grid, e.g. <code>people</code>. Optional.
        </p>
        <FieldError id={errorId("unit")} message={errors.unit} />
      </div>
    </div>
  );
}

function CreateParameterForm({
  domainId,
  entityTypes,
  onCreated,
}: {
  domainId: Id;
  entityTypes: EntityType[];
  onCreated: (id: Id) => void;
}) {
  const baseId = useId();
  const [name, setName] = useState("");
  const [indexes, setIndexes] = useState<Id[]>([entityTypes[0].id]);
  const [defaultValue, setDefaultValue] = useState("0");
  const [unit, setUnit] = useState("");
  const [serverErrors, setServerErrors] = useState<FieldErrors | null>(null);
  const [general, setGeneral] = useState<string | null>(null);
  const { errors, replace, summaryRef } = useFieldErrors(serverErrors);
  const create = useCreateParameter();
  const toast = useToast();

  const [valueType, setValueType] = useState<Id | "">("");
  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setGeneral(null);
    setServerErrors(null);

    const refused: FieldErrors = {};
    const nameError = nameProblem(name, false);
    if (nameError) refused.name = nameError;
    const parsed = parseCellValue(defaultValue, "Default value", 0);
    if (!parsed.ok) refused.default_value = parsed.message;
    replace(refused);
    if (Object.keys(refused).length > 0) return;

    try {
      const created = await create.mutateAsync({
        domain_id: domainId,
        name,
        index_type_ids: indexes,
        default_value: parsed.ok ? parsed.value : 0,
        ...(valueType !== "" ? { value_type_id: valueType } : {}),
        unit: unit.trim() === "" ? null : unit.trim(),
      });
      toast.success(`Parameter "${created.name}" created`);
      setName("");
      setUnit("");
      setDefaultValue("0");
      setIndexes([entityTypes[0].id]);
      setValueType("");
      onCreated(created.id);
    } catch (err) {
      const result = serverFieldErrors(err, FIELDS, "parameter");
      setServerErrors(result.fields);
      setGeneral(result.general);
    }
  }

  return (
    <section aria-labelledby="new-parameter-heading" className="rounded-md border border-slate-200 bg-white p-4">
      <h2 id="new-parameter-heading" className="mb-3 text-base font-semibold text-slate-900">
        New parameter
      </h2>
      <form aria-label="New parameter" onSubmit={handleSubmit} noValidate className="space-y-4">
        <ErrorSummary errors={errors} order={FIELDS} summaryRef={summaryRef} />
        {general && <p className="whitespace-pre-line text-sm text-red-600">{general}</p>}
        <DefinitionFields
          entityValued={valueType !== ""}
          baseId={baseId}
          name={name}
          defaultValue={defaultValue}
          unit={unit}
          errors={errors}
          onName={setName}
          onDefault={setDefaultValue}
          onUnit={setUnit}
        />
        <IndexChooser
          baseId={baseId}
          entityTypes={entityTypes}
          indexes={indexes}
          onChange={setIndexes}
          error={errors.index_type_ids}
        />
        <div>
          <label htmlFor={`${baseId}-value-type`} className="block text-sm font-medium text-slate-700">
            Its values are
          </label>
          <select
            id={`${baseId}-value-type`}
            className="mt-1 block w-full max-w-xs rounded-md border border-slate-300 bg-white px-3 py-2 text-sm"
            value={valueType === "" ? "" : String(valueType)}
            onChange={(e) => setValueType(e.target.value === "" ? "" : (Number(e.target.value) as Id))}
          >
            <option value="">numbers</option>
            {entityTypes.map((t) => (
              <option key={t.id} value={t.id}>
                a {t.name} (one per cell)
              </option>
            ))}
          </select>
          <p className="mt-1 text-xs text-slate-500">
            A {"preferred shift"} per person and day, say: a model reads it as an index or in a filter.
          </p>
        </div>
        <button
          type="submit"
          disabled={create.isPending}
          className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {create.isPending ? "Saving…" : "Create parameter"}
        </button>
      </form>
    </section>
  );
}

/** The ordered list of index types. Order is meaning, not presentation:
 * `demand[day, shift]` is a different parameter from `demand[shift, day]`,
 * so the indexes are chosen one at a time rather than ticked off a list. */
function IndexChooser({
  baseId,
  entityTypes,
  indexes,
  onChange,
  error,
}: {
  baseId: string;
  entityTypes: EntityType[];
  indexes: Id[];
  onChange: (next: Id[]) => void;
  error?: string;
}) {
  const errorId = `${baseId}-index-error`;
  return (
    <fieldset>
      <legend className="block text-sm font-medium text-slate-700">
        Indexed by
        <span className="text-red-500" aria-hidden="true">
          {" "}
          *
        </span>
      </legend>
      <p id={`${baseId}-index-hint`} className="mt-1 text-xs text-slate-500">
        One entity type per index, in order: <code>demand[day, shift]</code> is not the same parameter as{" "}
        <code>demand[shift, day]</code>. The same type twice is a distance matrix. Two indexes are laid out as a
        grid; three or more are listed.
      </p>
      <div className="mt-2 flex flex-wrap items-end gap-2">
        {indexes.map((typeId, position) => (
          <div key={position}>
            <label htmlFor={`${baseId}-index-${position}`} className="block text-xs font-medium text-slate-600">
              {`Index ${position + 1}`}
            </label>
            <select
              id={`${baseId}-index-${position}`}
              className={`${INPUT_CLASS} font-mono`}
              value={String(typeId)}
              aria-invalid={error ? "true" : undefined}
              aria-describedby={describedBy(`${baseId}-index-hint`, error && errorId)}
              onChange={(event) => {
                const next = [...indexes];
                next[position] = Number(event.target.value);
                onChange(next);
              }}
            >
              {entityTypes.map((type) => (
                <option key={type.id} value={type.id}>
                  {type.name}
                </option>
              ))}
            </select>
          </div>
        ))}
        <button
          type="button"
          onClick={() => onChange([...indexes, entityTypes[0].id])}
          className="rounded-md border border-slate-300 px-3 py-2 text-sm font-medium text-slate-800 hover:bg-slate-50"
        >
          Add an index
        </button>
        {indexes.length === 0 && (
          // One number, no index (migration 0104): a budget, a truck's capacity.
          <p className="text-sm text-slate-700">No index: one number, its default value below.</p>
        )}
        {indexes.length > 0 && (
          <button
            type="button"
            onClick={() => onChange(indexes.slice(0, -1))}
            className="rounded-md border border-slate-300 px-3 py-2 text-sm font-medium text-slate-800 hover:bg-slate-50"
          >
            Remove the last index
          </button>
        )}
      </div>
      <FieldError id={errorId} message={error} />
    </fieldset>
  );
}

function ParameterSettings({
  parameter,
  entityTypes,
}: {
  parameter: ParameterDef;
  entityTypes: EntityType[];
}) {
  const { can } = useCapabilities();
  const canEdit = can("domain.edit");
  const baseId = useId();
  const [name, setName] = useState(parameter.name);
  const [defaultValue, setDefaultValue] = useState(String(parameter.default_value));
  const [unit, setUnit] = useState(parameter.unit ?? "");
  const [serverErrors, setServerErrors] = useState<FieldErrors | null>(null);
  const [general, setGeneral] = useState<string | null>(null);
  const { errors, replace, summaryRef } = useFieldErrors(serverErrors);
  const update = useUpdateParameter();
  const toast = useToast();

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setGeneral(null);
    setServerErrors(null);

    const refused: FieldErrors = {};
    const nameError = nameProblem(name, false);
    if (nameError) refused.name = nameError;
    const parsed = parseCellValue(defaultValue, "Default value", parameter.default_value);
    if (!parsed.ok) refused.default_value = parsed.message;
    replace(refused);
    if (Object.keys(refused).length > 0) return;

    // PATCH means "omitted is unchanged", so only what changed is sent --
    // which also keeps an untouched field from reviving a value someone
    // else changed underneath this form.
    const body: Record<string, unknown> = {};
    if (name !== parameter.name) body.name = name;
    if (parsed.ok && parsed.value !== parameter.default_value) body.default_value = parsed.value;
    const nextUnit = unit.trim() === "" ? null : unit.trim();
    if (nextUnit !== parameter.unit) body.unit = nextUnit;
    if (Object.keys(body).length === 0) {
      setGeneral("Nothing to save: no setting was changed.");
      return;
    }

    try {
      await update.mutateAsync({ id: parameter.id, body });
      toast.success(`Parameter "${name}" saved`);
    } catch (err) {
      const result = serverFieldErrors(err, FIELDS, "parameter");
      setServerErrors(result.fields);
      setGeneral(result.general);
    }
  }

  return (
    <form
      aria-label="Parameter settings"
      onSubmit={handleSubmit}
      noValidate
      className="mb-4 space-y-4 rounded-md border border-slate-200 bg-white p-4"
    >
      <ErrorSummary errors={errors} order={FIELDS} summaryRef={summaryRef} />
      {general && <p className="whitespace-pre-line text-sm text-red-600">{general}</p>}
      <DefinitionFields
        entityValued={parameter.value_type_id != null}
        baseId={baseId}
        name={name}
        defaultValue={defaultValue}
        unit={unit}
        errors={errors}
        onName={setName}
        onDefault={setDefaultValue}
        onUnit={setUnit}
      />
      <p className="text-xs text-slate-500">
        Indexed by <span className="font-mono">{indexNames(parameter, entityTypes)}</span>. Index types cannot be
        changed once a parameter exists: its stored cells were entered for the old index and nothing re-checks
        them, so the server refuses it. Create a second parameter instead.
      </p>
      <p className="text-xs text-slate-500">
        Changing the default: stored cells are not rewritten — every empty cell takes the new default, and a cell
        that happens to equal it stays stored until you clear it.
      </p>
      {canEdit && (
      <button
        type="submit"
        disabled={update.isPending}
        className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-800 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
      >
        {update.isPending ? "Saving…" : "Save settings"}
      </button>
      )}
    </form>
  );
}
