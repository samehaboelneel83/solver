import { FormEvent, useId, useMemo, useState } from "react";
import { useQueries } from "@tanstack/react-query";
import {
  ErrorSummary,
  FieldError,
  describedBy,
  parseAttrValue,
  useFieldErrors,
  type FieldErrors,
} from "./attrTypes";
import OfflineNotice from "./OfflineNotice";
import Skeleton from "./Skeleton";
import { useToast } from "./ToastProvider";
import { formatApiError } from "../api/errors";
import {
  listEntities,
  useParameterValues,
  usePutParameterValues,
  validationErrors,
  type Entity,
  type Id,
  type ParameterCell,
  type ParameterDef,
  type ParameterValues,
} from "../api/v1";

/**
 * A parameter's values, as the spreadsheet spec §5 calls them rather than
 * as rows: the first index down the rows, the second across the columns.
 *
 * Three things about the API decide how this behaves (see
 * `backend/app/api/parameters.py`):
 *
 * 1. **Storage is sparse, deliberately.** A cell whose value equals
 *    `default_value` is deleted rather than stored, so "never set" and
 *    "set back to the default" are the same state. An empty box here
 *    therefore *shows* the default (as a placeholder, in a muted style)
 *    instead of pretending the cell has no value, and clearing a box sends
 *    the default so the server deletes the row. A stored cell that happens
 *    to equal the default -- which `PATCH default_value` can leave behind,
 *    since it does not rewrite cells -- is still shown as stored, because
 *    it is.
 * 2. **Values are integers, and that is a modelling decision** (spec §2:
 *    `int` columns, for CP-SAT), not a UI shortcut. The rule is stated on
 *    screen and enforced before the request: a decimal is refused here, so
 *    no one meets a raw 422. `<input type="number">` is deliberately not
 *    used -- Task 11's finding: it reports an invalid entry as `""`, which
 *    in this grid would silently read as "clear the cell".
 * 3. **A PUT is atomic and carries many cells**, so a rejected cell's 422
 *    points at `["body","cells",<i>,"entity_ids"]` (Ruling 23). `<i>` is an
 *    index into the request, not into the grid, so the request order is
 *    kept and the message is re-attached to the box the user edited.
 *
 * Only two indexes can be laid out as a matrix. Three or more fall back to
 * a flat list of the stored cells -- the spec's shape is still a grid, but
 * a 3-D one has no honest 2-D layout, and rendering nothing would be worse.
 */

/** The API's maximum page. An axis with more entities than this is shown
 * truncated, with a notice, rather than silently cut off. */
export const AXIS_PAGE_SIZE = 500;

// `parameter_value.value` is `int` (int4). The server refuses anything
// outside it with a 422; this is the same rule, said before the request.
const INT4_MIN = -(2 ** 31);
const INT4_MAX = 2 ** 31 - 1;

/** How an entity is named everywhere it is shown: its label, or its key
 * when it has none (the same rule the graph uses). */
export function entityDisplay(entity: Entity): string {
  return entity.label && entity.label.trim() !== "" ? entity.label : entity.key;
}

/**
 * What one box holds, as the number to send, or why it cannot be sent.
 * Empty means "use the default", which is sent as the default value so the
 * server deletes the row (sparse storage, above).
 */
export function parseCellValue(
  raw: string,
  label: string,
  defaultValue: number
): { ok: true; value: number } | { ok: false; message: string } {
  const text = raw.trim();
  if (text === "") return { ok: true, value: defaultValue };
  // Task 11's integer parser: digits only, so `5.0` and `5e3` are refused
  // exactly as `StrictInt` refuses them server-side.
  const parsed = parseAttrValue("integer", text, [], label);
  if (!parsed.ok) return parsed;
  const value = parsed.value as number;
  if (value < INT4_MIN || value > INT4_MAX) {
    return { ok: false, message: `${label}: must be between ${INT4_MIN} and ${INT4_MAX}.` };
  }
  return { ok: true, value };
}

const coordKey = (ids: Id[]) => ids.join(",");

// Not INPUT_CLASS: a full-height form control in every cell makes a grid
// unreadable, and the stored/empty distinction needs its own background and
// text colour -- which, layered on INPUT_CLASS, would be two competing
// utilities for the same property whose winner depends on Tailwind's output
// order. Same visual language, built from non-overlapping utilities.
const CELL_CLASS =
  "block w-full rounded border px-2 py-1 text-right font-mono text-sm aria-[invalid=true]:border-red-500";
export const STORED_CELL_CLASS = `${CELL_CLASS} border-slate-300 bg-white font-medium text-slate-900`;
export const EMPTY_CELL_CLASS = `${CELL_CLASS} border-slate-200 bg-slate-50 text-slate-600 placeholder:text-slate-400`;

type Axis = { id: Id; name: string };
type CellSpec = { key: string; ids: Id[]; label: string };

export default function ParameterGrid({ parameter }: { parameter: ParameterDef }) {
  const values = useParameterValues(parameter.id);
  const axes = values.data?.index_types ?? [];

  // One query per *distinct* index type, sharing `useEntities`'s cache key
  // so a grid and an entity list of the same type do not fetch twice.
  // `useQueries` because the number of axes is data, not a constant;
  // distinct because a self-indexed parameter names the same type twice and
  // React Query warns about duplicate queries in one observer.
  const typeIds = [...new Set(axes.map((axis) => axis.id))];
  const queries = useQueries({
    queries: typeIds.map((typeId) => ({
      queryKey: ["v1", "entities", { entityTypeId: typeId, limit: AXIS_PAGE_SIZE }],
      queryFn: () => listEntities({ entityTypeId: typeId, limit: AXIS_PAGE_SIZE }),
    })),
  });
  const entityQueries = axes.map((axis) => queries[typeIds.indexOf(axis.id)]);

  if (values.fetchStatus === "paused" && !values.data) return <OfflineNotice subject="This parameter's values" />;
  if (values.isLoading || !values.data) {
    if (values.isError) return <Failed error={values.error} onRetry={() => values.refetch()} />;
    return <Skeleton rows={4} cols={4} />;
  }

  const missing = axes.filter((axis) => axis.name === null);
  if (missing.length > 0) {
    return (
      <p className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-800">
        One of this parameter&rsquo;s index types no longer exists, so its values cannot be shown. The parameter
        survives the entity type it was indexed by, but it can never take a value again — delete it, or recreate
        the missing type.
      </p>
    );
  }

  if (entityQueries.some((q) => q.fetchStatus === "paused" && !q.data)) {
    return <OfflineNotice subject="This parameter's values" />;
  }
  if (entityQueries.some((q) => q.isLoading)) return <Skeleton rows={4} cols={4} />;
  const failed = entityQueries.find((q) => q.isError);
  if (failed) return <Failed error={failed.error} onRetry={() => failed.refetch()} />;

  const entities = entityQueries.map((q) => q.data?.items ?? []);
  const totals = entityQueries.map((q) => q.data?.total ?? 0);
  const namedAxes = axes as Axis[];

  const empty = namedAxes.findIndex((_, i) => entities[i].length === 0);
  if (empty >= 0) {
    return (
      <p className="rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-600">
        Index type <span className="font-mono">{namedAxes[empty].name}</span> has no entities yet, so this
        parameter has no cells. Add its entities first.
      </p>
    );
  }

  return (
    <Editor
      key={parameter.id}
      parameter={parameter}
      values={values.data}
      axes={namedAxes}
      entities={entities}
      totals={totals}
    />
  );
}

function Failed({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <p className="text-sm text-red-600">{formatApiError(error)}</p>
      <button
        type="button"
        onClick={onRetry}
        className="rounded-md border border-red-300 px-2 py-1 text-xs font-medium text-red-700 hover:bg-red-50"
      >
        Retry
      </button>
    </div>
  );
}

function Editor({
  parameter,
  values,
  axes,
  entities,
  totals,
}: {
  parameter: ParameterDef;
  values: ParameterValues;
  axes: Axis[];
  entities: Entity[][];
  totals: number[];
}) {
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [serverErrors, setServerErrors] = useState<FieldErrors | null>(null);
  const [general, setGeneral] = useState<string | null>(null);
  const { errors, replace, summaryRef } = useFieldErrors(serverErrors);
  const put = usePutParameterValues();
  const toast = useToast();
  const baseId = useId();

  const flat = axes.length > 2;
  const stored = useMemo(
    () => new Map(values.cells.map((cell) => [coordKey(cell.entity_ids), cell.value])),
    [values.cells]
  );
  const byId = useMemo(
    () => entities.map((list) => new Map(list.map((entity) => [entity.id, entity]))),
    [entities]
  );

  const nameAt = (axisIndex: number, id: Id) => {
    const entity = byId[axisIndex]?.get(id);
    return entity ? entityDisplay(entity) : `#${id}`;
  };
  const cellLabel = (ids: Id[]) => `${parameter.name}[${ids.map((id, i) => nameAt(i, id)).join(", ")}]`;

  // Every cell that can be edited, in the order it is read on screen --
  // which is also the order cells are sent in, so a 422's cell index maps
  // back here. For three or more indexes only stored cells are listed:
  // there is no layout that offers the whole cartesian product.
  const cellSpecs: CellSpec[] = useMemo(() => {
    const specs: CellSpec[] = [];
    if (flat) {
      for (const cell of values.cells) {
        specs.push({ key: coordKey(cell.entity_ids), ids: cell.entity_ids, label: cellLabel(cell.entity_ids) });
      }
      return specs;
    }
    const columns = axes.length === 2 ? entities[1] : [null];
    for (const row of entities[0]) {
      for (const column of columns) {
        const ids = column ? [row.id, column.id] : [row.id];
        specs.push({ key: coordKey(ids), ids, label: cellLabel(ids) });
      }
    }
    return specs;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [flat, values.cells, axes, entities, parameter.name]);

  const labelByKey = useMemo(
    () => new Map(cellSpecs.map((spec) => [spec.key, spec.label])),
    [cellSpecs]
  );

  const storedText = (key: string) => (stored.has(key) ? String(stored.get(key)) : "");
  const textOf = (key: string) => draft[key] ?? storedText(key);
  const changed = cellSpecs.filter((spec) => textOf(spec.key) !== storedText(spec.key));

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setGeneral(null);
    setServerErrors(null);

    const refused: FieldErrors = {};
    const cells: ParameterCell[] = [];
    for (const spec of changed) {
      const parsed = parseCellValue(textOf(spec.key), spec.label, values.default_value);
      if (parsed.ok) cells.push({ entity_ids: spec.ids, value: parsed.value });
      else refused[spec.key] = parsed.message;
    }
    replace(refused);
    if (Object.keys(refused).length > 0) return;
    if (cells.length === 0) return;

    try {
      await put.mutateAsync({ id: parameter.id, cells });
      setDraft({});
      toast.success(cells.length === 1 ? "1 cell saved" : `${cells.length} cells saved`);
    } catch (err) {
      const items = validationErrors(err);
      const mapped: FieldErrors = {};
      const rest: string[] = [];
      for (const item of items) {
        const loc = item.loc ?? [];
        // ["body", "cells", <i>, ...]: <i> indexes the request we just sent.
        const index = loc[1] === "cells" && typeof loc[2] === "number" ? loc[2] : null;
        const sent = index !== null ? cells[index] : undefined;
        if (sent) {
          const key = coordKey(sent.entity_ids);
          mapped[key] = `${labelByKey.get(key) ?? key}: ${item.msg}`;
        } else {
          rest.push(item.msg);
        }
      }
      if (Object.keys(mapped).length > 0) setServerErrors(mapped);
      setGeneral(rest.length > 0 ? rest.join("\n") : items.length > 0 ? null : formatApiError(err));
    }
  }

  const truncated = totals
    .map((total, i) => ({ axis: axes[i], shown: entities[i].length, total }))
    .filter((t) => t.total > t.shown);

  const order = cellSpecs.map((spec) => spec.key);

  return (
    <form onSubmit={handleSubmit} noValidate aria-label={`${parameter.name} values`} className="space-y-3">
      <p data-testid="grid-rules" className="text-sm text-slate-600">
        Values are whole numbers — no decimals{parameter.unit ? `, in ${parameter.unit}` : ""}. An empty cell uses
        this parameter&rsquo;s default of <strong>{values.default_value}</strong>; typing{" "}
        {values.default_value} into a cell clears it back to the default rather than storing it.
      </p>

      {truncated.map((t) => (
        <p key={t.axis.id} className="text-sm text-amber-700">
          Showing the first {t.shown} of {t.total} <span className="font-mono">{t.axis.name}</span> entities: this
          grid cannot show them all. Narrow the model, or set the remaining cells through the API.
        </p>
      ))}

      <ErrorSummary errors={errors} order={order} summaryRef={summaryRef} />
      {general && <p className="whitespace-pre-line text-sm text-red-600">{general}</p>}

      <div
        data-testid="grid-scroll"
        className="max-h-[70vh] overflow-auto rounded-md border border-slate-200 bg-white"
      >
        {flat ? (
          <FlatTable
            parameter={parameter}
            axes={axes}
            specs={cellSpecs}
            errors={errors}
            baseId={baseId}
            nameAt={nameAt}
            textOf={textOf}
            onChange={(key, value) => setDraft((prev) => ({ ...prev, [key]: value }))}
            stored={stored}
          />
        ) : (
          <MatrixTable
            parameter={parameter}
            axes={axes}
            rows={entities[0]}
            columns={axes.length === 2 ? entities[1] : null}
            errors={errors}
            baseId={baseId}
            textOf={textOf}
            onChange={(key, value) => setDraft((prev) => ({ ...prev, [key]: value }))}
            stored={stored}
            defaultValue={values.default_value}
            cellLabel={cellLabel}
          />
        )}
      </div>

      {flat && (
        <p data-testid="flat-note" className="text-sm text-slate-600">
          This parameter has three or more indexes, so its cells are listed instead of laid out as a grid. The
          cells already stored can be edited here; new ones have to be set through the API for now.
        </p>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="submit"
          disabled={changed.length === 0 || put.isPending}
          className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {put.isPending ? "Saving…" : "Save values"}
        </button>
        <span className="text-sm text-slate-500">
          {changed.length === 0
            ? "No unsaved changes."
            : changed.length === 1
              ? "1 cell edited."
              : `${changed.length} cells edited.`}
        </span>
      </div>
    </form>
  );
}

function CellInput({
  label,
  cellKey,
  text,
  isStored,
  defaultValue,
  error,
  baseId,
  onChange,
}: {
  label: string;
  cellKey: string;
  text: string;
  isStored: boolean;
  defaultValue: number | null;
  error?: string;
  baseId: string;
  onChange: (key: string, value: string) => void;
}) {
  const errorId = `${baseId}-${cellKey}-error`;
  return (
    <>
      <input
        type="text"
        inputMode="numeric"
        autoComplete="off"
        spellCheck={false}
        aria-label={label}
        aria-invalid={error ? "true" : undefined}
        aria-describedby={describedBy(error && errorId)}
        data-stored={isStored ? "true" : "false"}
        className={isStored ? STORED_CELL_CLASS : EMPTY_CELL_CLASS}
        value={text}
        {...(isStored || defaultValue === null ? {} : { placeholder: String(defaultValue) })}
        onChange={(event) => onChange(cellKey, event.target.value)}
      />
      <FieldError id={errorId} message={error} />
    </>
  );
}

function MatrixTable({
  parameter,
  axes,
  rows,
  columns,
  errors,
  baseId,
  textOf,
  onChange,
  stored,
  defaultValue,
  cellLabel,
}: {
  parameter: ParameterDef;
  axes: Axis[];
  rows: Entity[];
  columns: Entity[] | null;
  errors: FieldErrors;
  baseId: string;
  textOf: (key: string) => string;
  onChange: (key: string, value: string) => void;
  stored: Map<string, number>;
  defaultValue: number;
  cellLabel: (ids: Id[]) => string;
}) {
  return (
    <table className="w-full border-collapse text-left text-sm" aria-label={`${parameter.name} values`}>
      <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-600">
        <tr>
          <th scope="col" className="px-3 py-2 font-mono font-semibold normal-case">
            {columns ? `${axes[0].name} \\ ${axes[1].name}` : axes[0].name}
          </th>
          {columns ? (
            columns.map((column) => (
              <th key={column.id} scope="col" className="px-3 py-2 font-semibold normal-case">
                {entityDisplay(column)}
              </th>
            ))
          ) : (
            <th scope="col" className="px-3 py-2 font-semibold">
              Value
            </th>
          )}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.id} className="border-b border-slate-100 last:border-0">
            <th scope="row" className="whitespace-nowrap px-3 py-2 font-normal text-slate-700">
              {entityDisplay(row)}
            </th>
            {(columns ?? [null]).map((column) => {
              const ids = column ? [row.id, column.id] : [row.id];
              const key = coordKey(ids);
              return (
                <td key={key} className="px-3 py-2 align-top">
                  <CellInput
                    label={cellLabel(ids)}
                    cellKey={key}
                    text={textOf(key)}
                    isStored={stored.has(key)}
                    defaultValue={defaultValue}
                    error={errors[key]}
                    baseId={baseId}
                    onChange={onChange}
                  />
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function FlatTable({
  parameter,
  axes,
  specs,
  errors,
  baseId,
  nameAt,
  textOf,
  onChange,
  stored,
}: {
  parameter: ParameterDef;
  axes: Axis[];
  specs: CellSpec[];
  errors: FieldErrors;
  baseId: string;
  nameAt: (axisIndex: number, id: Id) => string;
  textOf: (key: string) => string;
  onChange: (key: string, value: string) => void;
  stored: Map<string, number>;
}) {
  return (
    <table className="w-full border-collapse text-left text-sm" aria-label={`${parameter.name} values`}>
      <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-600">
        <tr>
          {axes.map((axis, index) => (
            <th key={`${axis.id}-${index}`} scope="col" className="px-3 py-2 font-mono font-semibold normal-case">
              {axis.name}
            </th>
          ))}
          <th scope="col" className="px-3 py-2 font-semibold">
            Value
          </th>
        </tr>
      </thead>
      <tbody>
        {specs.length === 0 ? (
          <tr>
            <td className="px-3 py-2 text-slate-600" colSpan={axes.length + 1}>
              No cells stored yet: every cell of this parameter is at its default.
            </td>
          </tr>
        ) : (
          specs.map((spec) => (
            <tr key={spec.key} className="border-b border-slate-100 last:border-0">
              {spec.ids.map((id, index) => (
                <td key={index} className="whitespace-nowrap px-3 py-2 text-slate-700">
                  {nameAt(index, id)}
                </td>
              ))}
              <td className="px-3 py-2 align-top">
                <CellInput
                  label={spec.label}
                  cellKey={spec.key}
                  text={textOf(spec.key)}
                  isStored={stored.has(spec.key)}
                  defaultValue={null}
                  error={errors[spec.key]}
                  baseId={baseId}
                  onChange={onChange}
                />
              </td>
            </tr>
          ))
        )}
      </tbody>
    </table>
  );
}
