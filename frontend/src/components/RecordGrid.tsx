import { ClipboardEvent, useEffect, useState } from "react";
import { attrField, buildAttrs, draftsFromAttrs, type AttrDrafts } from "./AttrsForm";
import { parseLatLon } from "../lib/campGeo";
import { asGeometry, describeShape } from "../lib/geoShape";
import RecordPicker from "./RecordPicker";
import { useToast } from "./ToastProvider";
import { entityServerErrors } from "../pages/EntityRecord";
import {
  useCreateEntity,
  useDeleteEntity,
  useUpdateEntity,
  type AttributeDef,
  type Entity,
  type EntityType,
  type Id,
} from "../api/v1";
import type { FieldErrors } from "./attrTypes";

/** One line of the grid: a stored record being edited, or a new one (`id` null). */
type Row = {
  rowKey: string;
  id: Id | null;
  updatedAt: string | null;
  key: string;
  label: string;
  active: boolean;
  attrs: AttrDrafts;
  /** What the row was when loaded, to tell an edit from a look. */
  original: string;
  remove: boolean;
  errors: FieldErrors;
  general: string | null;
};

const CELL = "w-full min-w-[7rem] rounded border border-transparent bg-transparent px-1.5 py-1 text-sm hover:border-slate-300 focus:border-blue-500 focus:bg-white focus:outline-none";

let made = 0;

function snapshot(r: Pick<Row, "key" | "label" | "active" | "attrs">) {
  return JSON.stringify([r.key, r.label, r.active, r.attrs]);
}

function fromEntity(type: EntityType, e: Entity): Row {
  const base = { key: e.key, label: e.label ?? "", active: e.active, attrs: draftsFromAttrs(type.attributes, e.attrs ?? {}) };
  return { ...base, rowKey: `e${e.id}`, id: e.id, updatedAt: e.updated_at ?? null, original: snapshot(base), remove: false, errors: {}, general: null };
}

function blank(type: EntityType, prefill: AttrDrafts = {}): Row {
  const base = { key: "", label: "", active: true, attrs: { ...draftsFromAttrs(type.attributes, {}), ...prefill } };
  made += 1;
  return { ...base, rowKey: `n${made}`, id: null, updatedAt: null, original: snapshot(base), remove: false, errors: {}, general: null };
}

const isNew = (r: Row) => r.id === null;
const isDirty = (r: Row) => r.remove || snapshot(r) !== r.original;

/** The columns of the grid: every field. A shape is a "lat, lon" point here; lines and areas are drawn
 * in the workbench's Location tab and only named in the cell. */
function editable(type: EntityType): AttributeDef[] {
  return type.attributes;
}

const NUMBER = /^-?\d+(?:\.\d+)?$/;

/** A shape draft from text: "30.04, 31.23" (latitude first, as a map app copies it) becomes a point. */
export function shapeDraft(text: string): string {
  const p = parseLatLon(text);
  return p ? JSON.stringify({ type: "Point", coordinates: p }) : text;
}

/** A shape draft as the cell shows it: a point as "lat, lon"; anything else by what it is. */
function shapeText(draft: string): { text: string; editable: boolean } {
  if (draft.trim() === "") return { text: "", editable: true };
  try {
    const g = asGeometry(JSON.parse(draft));
    if (!g) return { text: draft, editable: true };
    if (g.type === "Point") return { text: `${g.coordinates[1]}, ${g.coordinates[0]}`, editable: true };
    return { text: describeShape(g), editable: false };
  } catch {
    return { text: draft, editable: true };
  }
}

function ShapeCell({ value, onChange, label }: { value: string; onChange: (v: string) => void; label: string }) {
  const shown = shapeText(value);
  const [text, setText] = useState(shown.text);
  if (!shown.editable) return <span className="px-1.5 text-xs text-slate-600" aria-label={label}>{shown.text}</span>;
  return (
    <input
      aria-label={label}
      className={CELL}
      placeholder="lat, lon"
      value={text}
      onChange={(e) => setText(e.target.value)}
      onBlur={() => onChange(shapeDraft(text))}
    />
  );
}

/** Text pasted from a spreadsheet: rows by line, cells by tab. */
export function pastedCells(text: string): string[][] {
  const lines = text.replace(/\r\n?/g, "\n").replace(/\n$/, "").split("\n");
  return lines.map((line) => line.split("\t"));
}

function Cell({
  attribute,
  value,
  onChange,
  label,
}: {
  attribute: AttributeDef;
  value: string;
  onChange: (v: string) => void;
  label: string;
}) {
  if (attribute.data_type === "geometry") {
    return <ShapeCell key={value} value={value} onChange={onChange} label={label} />;
  }
  if (attribute.data_type === "reference") {
    return (
      <RecordPicker
        typeId={(attribute.target_type_id as Id | null) ?? null}
        value={value}
        onChange={onChange}
        className={CELL}
        placeholder=""
        aria-label={label}
      />
    );
  }
  if (attribute.data_type === "boolean" || attribute.data_type === "enum") {
    const choices = attribute.data_type === "boolean" ? [["true", "Yes"], ["false", "No"]] : (attribute.enum_values ?? []).map((v) => [v, v]);
    return (
      <select aria-label={label} className={CELL} value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">—</option>
        {choices.map(([v, text]) => (
          <option key={v} value={v}>
            {text}
          </option>
        ))}
      </select>
    );
  }
  const type =
    attribute.data_type === "integer" || attribute.data_type === "number"
      ? "text"
      : attribute.data_type === "date"
        ? "date"
        : attribute.data_type === "time"
          ? "time"
          : "text";
  return (
    <input
      aria-label={label}
      className={`${CELL} ${attribute.data_type === "integer" || attribute.data_type === "number" ? "text-right" : ""}`}
      type={type}
      inputMode={attribute.data_type === "integer" ? "numeric" : attribute.data_type === "number" ? "decimal" : undefined}
      value={value}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

/**
 * A page of one kind's records as an editable grid: change cells, add rows, mark rows to delete,
 * or paste a block from Excel; then save what changed. Each row is checked like the record form
 * (`buildAttrs`) and saved on its own, so one refused row keeps its error beside it while the
 * rest are saved.
 */
export default function RecordGrid({
  type,
  records,
  onDone,
  prefill,
  afterCreate,
  startWithNew = false,
  onOpen,
}: {
  type: EntityType;
  records: Entity[];
  onDone?: () => void;
  /** Fields every new row starts with: the parent a workbench list sits under. */
  prefill?: AttrDrafts;
  /** Run after a new record is created, before it counts as saved (linking it into a hierarchy). */
  afterCreate?: (created: Entity) => Promise<void>;
  /** Open with one empty row ready to type into. */
  startWithNew?: boolean;
  /** Offer to open a stored row's record (the workbench shows it beside the grid). */
  onOpen?: (id: Id) => void;
}) {
  const toast = useToast();
  const create = useCreateEntity();
  const update = useUpdateEntity();
  const remove = useDeleteEntity();
  const columns = editable(type);
  const [rows, setRows] = useState<Row[]>(() => [
    ...records.map((e) => fromEntity(type, e)),
    ...(startWithNew ? [blank(type, prefill)] : []),
  ]);
  const [saving, setSaving] = useState(false);
  const names = type.attributes.map((a) => a.name);
  const fields = ["key", "label", ...columns.map((a) => a.name)];
  const shapes = new Set(columns.filter((a) => a.data_type === "geometry").map((a) => a.name));

  const changed = rows.filter(isDirty);
  // Unsaved cells are not lost to a closed tab or a reload without a word.
  const unsaved = changed.length > 0;
  useEffect(() => {
    if (!unsaved) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [unsaved]);
  /** A new row with this row's values and no key: the next truck like this one. */
  const duplicate = (row: Row) =>
    setRows((all) => {
      const copy = { ...blank(type, prefill), label: row.label, active: row.active, attrs: { ...row.attrs } };
      const at = all.findIndex((r) => r.rowKey === row.rowKey);
      return [...all.slice(0, at + 1), copy, ...all.slice(at + 1)];
    });
  const set = (rowKey: string, patch: Partial<Row>) =>
    setRows((all) => all.map((r) => (r.rowKey === rowKey ? { ...r, ...patch } : r)));
  const setAttr = (row: Row, name: string, value: string) => set(row.rowKey, { attrs: { ...row.attrs, [name]: value } });

  function setField(row: Row, field: string, value: string): Row {
    if (field === "key") return { ...row, key: value };
    if (field === "label") return { ...row, label: value };
    return { ...row, attrs: { ...row.attrs, [field]: value } };
  }

  /** A block pasted into a cell fills right and down from it, adding rows as needed. */
  function onPaste(event: ClipboardEvent, rowIndex: number, field: string) {
    const text = event.clipboardData.getData("text/plain");
    if (!text.includes("\t") && !text.includes("\n")) return;
    event.preventDefault();
    const block = pastedCells(text);
    const start = fields.indexOf(field);
    setRows((all) => {
      const next = [...all];
      block.forEach((cells, i) => {
        const at = rowIndex + i;
        while (next.length <= at) next.push(blank(type, prefill));
        let row = next[at];
        // A shape column takes "lat, lon" in one cell, or latitude and longitude in two.
        for (let j = 0, col = start; j < cells.length && col < fields.length; col += 1) {
          const f = fields[col];
          const value = cells[j].trim();
          if (shapes.has(f) && NUMBER.test(value) && NUMBER.test((cells[j + 1] ?? "").trim())) {
            row = setField(row, f, shapeDraft(`${value}, ${cells[j + 1].trim()}`));
            j += 2;
          } else {
            row = setField(row, f, shapes.has(f) ? shapeDraft(value) : value);
            j += 1;
          }
        }
        next[at] = row;
      });
      return next;
    });
  }

  async function save() {
    setSaving(true);
    let ok = 0;
    let failed = 0;
    const next: Row[] = [];
    for (const row of rows) {
      if (!isDirty(row)) {
        next.push(row);
        continue;
      }
      if (row.remove) {
        if (isNew(row)) continue;
        try {
          await remove.mutateAsync(row.id as Id);
          ok += 1;
        } catch (err) {
          failed += 1;
          next.push({ ...row, general: entityServerErrors(err, names).general ?? "Could not delete." });
        }
        continue;
      }
      const built = buildAttrs(type.attributes, row.attrs);
      const problems: FieldErrors = built.ok ? {} : { ...built.errors };
      if (row.key.trim() === "") problems.key = "Key: required.";
      if (!built.ok || Object.keys(problems).length > 0) {
        failed += 1;
        next.push({ ...row, errors: problems, general: null });
        continue;
      }
      const body = { key: row.key.trim(), label: row.label.trim() || null, active: row.active, attrs: built.attrs };
      try {
        const saved = isNew(row)
          ? await create.mutateAsync({ entity_type_id: type.id, ...body })
          : await update.mutateAsync({ id: row.id as Id, body: row.updatedAt ? { ...body, updated_at: row.updatedAt } : body });
        if (isNew(row) && afterCreate) await afterCreate(saved);
        ok += 1;
        next.push({ ...fromEntity(type, saved), rowKey: row.rowKey });
      } catch (err) {
        failed += 1;
        const result = entityServerErrors(err, names);
        next.push({ ...row, errors: result.fields, general: result.general });
      }
    }
    setRows(next);
    setSaving(false);
    if (failed === 0) toast.success(`${ok} change${ok === 1 ? "" : "s"} saved`);
    else toast.error(`${ok} saved; ${failed} row${failed === 1 ? "" : "s"} need${failed === 1 ? "s" : ""} attention (marked in red)`);
  }

  return (
    <div className="space-y-3" data-testid="record-grid">
      <p className="text-sm text-slate-600">
        Edit cells directly, or paste a block copied from Excel into any cell — it fills right and down and adds rows.
        {columns.some((a) => a.data_type === "geometry") &&
          " A place is “lat, lon”, or latitude and longitude pasted as two columns; draw lines and areas in Location."}
      </p>
      <div className="overflow-x-auto rounded-md border border-slate-200 bg-white">
        <table className="w-full text-left text-sm" aria-label={`Edit ${type.name} records`}>
          <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-600">
            <tr>
              <th scope="col" className="px-2 py-2">
                <span className="sr-only">Delete</span>
              </th>
              <th scope="col" className="px-2 py-2">Key *</th>
              <th scope="col" className="px-2 py-2">Label</th>
              <th scope="col" className="px-2 py-2">Active</th>
              {columns.map((a) => (
                <th key={a.id} scope="col" className="px-2 py-2 font-mono normal-case">
                  {a.name}
                  {a.required ? " *" : ""}
                  {a.unit ? <span className="font-sans text-slate-400"> ({a.unit})</span> : null}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => {
              const bad = Object.keys(row.errors).length > 0 || row.general !== null;
              const tone = row.remove ? "bg-red-50 line-through opacity-70" : bad ? "bg-red-50" : isDirty(row) ? "bg-amber-50" : "";
              const messages = [...Object.values(row.errors), ...(row.general ? [row.general] : [])];
              const who = row.key || `new row ${i + 1}`;
              return [
                <tr key={row.rowKey} className={`border-b border-slate-100 ${tone}`} data-testid={`grid-row-${i}`}>
                  <td className="whitespace-nowrap px-2">
                    {onOpen && row.id !== null && (
                      <button type="button" className="mr-1 text-blue-700" aria-label={`Open ${who}`} onClick={() => onOpen(row.id as Id)}>
                        ↗
                      </button>
                    )}
                    <button type="button" className="mr-1 text-slate-500 hover:text-slate-900" aria-label={`Duplicate ${who}`}
                      title="A new row with these values" onClick={() => duplicate(row)}>
                      ⧉
                    </button>
                    <input
                      type="checkbox"
                      aria-label={`Delete ${who}`}
                      checked={row.remove}
                      onChange={(e) => set(row.rowKey, { remove: e.target.checked })}
                    />
                  </td>
                  <td className="px-1">
                    <input
                      aria-label={`${who}: key`}
                      aria-invalid={row.errors.key ? "true" : undefined}
                      className={`${CELL} font-mono ${row.errors.key ? "border-red-400" : ""}`}
                      value={row.key}
                      onChange={(e) => set(row.rowKey, { key: e.target.value })}
                      onPaste={(e) => onPaste(e, i, "key")}
                    />
                  </td>
                  <td className="px-1">
                    <input
                      aria-label={`${who}: label`}
                      className={CELL}
                      value={row.label}
                      onChange={(e) => set(row.rowKey, { label: e.target.value })}
                      onPaste={(e) => onPaste(e, i, "label")}
                    />
                  </td>
                  <td className="px-2 text-center">
                    <input
                      type="checkbox"
                      aria-label={`${who}: active`}
                      checked={row.active}
                      onChange={(e) => set(row.rowKey, { active: e.target.checked })}
                    />
                  </td>
                  {columns.map((a) => (
                    <td
                      key={a.id}
                      className={`px-1 ${row.errors[attrField(a.name)] ? "outline outline-1 outline-red-400" : ""}`}
                      onPaste={(e) => onPaste(e, i, a.name)}
                    >
                      <Cell attribute={a} value={row.attrs[a.name] ?? ""} onChange={(v) => setAttr(row, a.name, v)} label={`${who}: ${a.name}`} />
                    </td>
                  ))}
                </tr>,
                messages.length > 0 && (
                  <tr key={`${row.rowKey}-msg`} className="bg-red-50">
                    <td />
                    <td colSpan={3 + columns.length} role="alert" className="px-2 pb-2 text-xs text-red-700">
                      {messages.join(" · ")}
                    </td>
                  </tr>
                ),
              ];
            })}
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <button type="button" className="rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50" onClick={() => setRows((all) => [...all, blank(type, prefill)])}>
          + Add row
        </button>
        <button
          type="button"
          disabled={saving || changed.length === 0}
          className="rounded-md bg-slate-900 px-4 py-1.5 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
          onClick={() => {
            const deleting = changed.filter((r) => r.remove && !isNew(r)).length;
            if (deleting > 0 && !window.confirm(`Delete ${deleting} record${deleting === 1 ? "" : "s"}? This cannot be undone.`)) return;
            void save();
          }}
        >
          {saving ? "Saving…" : `Save ${changed.length} change${changed.length === 1 ? "" : "s"}`}
        </button>
        {onDone && (
          <button
            type="button"
            className="text-sm text-slate-600 underline"
            onClick={() => {
              if (changed.length === 0 || window.confirm("Leave the grid without saving your changes?")) onDone();
            }}
          >
            Done
          </button>
        )}
      </div>
    </div>
  );
}
