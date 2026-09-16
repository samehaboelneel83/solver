import { FormEvent, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../api/client";
import type { ListResult } from "../api/entities";
import type { FieldMeta } from "../types/meta";

type EntityFormProps = {
  fields: FieldMeta[];
  initialValues?: Record<string, unknown>;
  onSubmit: (values: Record<string, unknown>) => void;
  submitLabel: string;
};

function defaultValueFor(field: FieldMeta): unknown {
  return field.type === "boolean" ? false : "";
}

function FkSelect({
  fkTable,
  value,
  onChange,
}: {
  fkTable: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const [schemaName, tableName] = fkTable.split(".");
  const { data } = useQuery({
    queryKey: ["fk-options", fkTable],
    queryFn: () => apiFetch<ListResult>(`/api/${schemaName}/${tableName}/?limit=200&offset=0`),
  });

  return (
    <select
      className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
      value={value}
      onChange={(e) => onChange(e.target.value)}
    >
      <option value="">—</option>
      {data?.items.map((row) => (
        <option key={String(row.id)} value={String(row.id)}>
          {String((row as Record<string, unknown>).code ?? (row as Record<string, unknown>).name ?? row.id)}
        </option>
      ))}
    </select>
  );
}

export default function EntityForm({ fields, initialValues, onSubmit, submitLabel }: EntityFormProps) {
  const writableFields = fields.filter((f) => f.writable);
  const [values, setValues] = useState<Record<string, unknown>>(() => {
    const initial: Record<string, unknown> = {};
    for (const field of writableFields) {
      initial[field.name] = initialValues?.[field.name] ?? defaultValueFor(field);
    }
    return initial;
  });

  function setField(name: string, value: unknown) {
    setValues((prev) => ({ ...prev, [name]: value }));
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const payload: Record<string, unknown> = {};
    for (const field of writableFields) {
      const raw = values[field.name];
      if (raw === "") {
        continue; // omit empty optional fields so the backend/DB default applies
      }
      if (field.type === "json" && typeof raw === "string") {
        try {
          payload[field.name] = JSON.parse(raw);
        } catch {
          payload[field.name] = raw;
        }
      } else if (field.type === "integer" || field.type === "number") {
        payload[field.name] = Number(raw);
      } else {
        payload[field.name] = raw;
      }
    }
    onSubmit(payload);
  }

  return (
    <form onSubmit={handleSubmit} className="max-w-xl space-y-4">
      {writableFields.map((field) => (
        <div key={field.name}>
          <label className="block text-sm font-medium text-slate-700">
            {field.name}
            {field.required && <span className="text-red-500"> *</span>}
          </label>
          {field.is_fk && field.fk_table ? (
            <FkSelect
              fkTable={field.fk_table}
              value={String(values[field.name] ?? "")}
              onChange={(v) => setField(field.name, v)}
            />
          ) : field.type === "boolean" ? (
            <input
              type="checkbox"
              checked={Boolean(values[field.name])}
              onChange={(e) => setField(field.name, e.target.checked)}
              data-testid={`field-${field.name}`}
            />
          ) : field.type === "json" ? (
            <textarea
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 font-mono text-xs"
              rows={4}
              value={
                typeof values[field.name] === "string"
                  ? (values[field.name] as string)
                  : JSON.stringify(values[field.name] ?? "")
              }
              onChange={(e) => setField(field.name, e.target.value)}
              data-testid={`field-${field.name}`}
            />
          ) : (
            <input
              type={
                field.type === "integer" || field.type === "number"
                  ? "number"
                  : field.type === "date"
                    ? "date"
                    : field.type === "datetime"
                      ? "datetime-local"
                      : "text"
              }
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              value={String(values[field.name] ?? "")}
              onChange={(e) => setField(field.name, e.target.value)}
              data-testid={`field-${field.name}`}
            />
          )}
        </div>
      ))}
      <button
        type="submit"
        className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700"
      >
        {submitLabel}
      </button>
    </form>
  );
}
