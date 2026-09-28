import { useState } from "react";

/** Keep template payloads inspectable without turning the library into a JSON viewer. */
export default function TemplateSummary({ value, kind }: { value: unknown; kind: "seed" | "model" }) {
  const [open, setOpen] = useState(false);
  const data = value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
  const count = (key: string) => Array.isArray(data[key]) ? data[key].length : data[key] && typeof data[key] === "object" ? Object.keys(data[key]).length : 0;
  const objective = data.objective && typeof data.objective === "object" ? data.objective as Record<string, unknown> : {};
  const metric = (key: string, label: string) => `${count(key)} ${label}${count(key) === 1 ? "" : "s"}`;
  const stats = kind === "seed"
    ? [metric("entity_types", "record type"), metric("entities", "sample record"), metric("parameters", "parameter")].join(" · ")
    : [metric("variables", "decision"), metric("constraints", "rule"), metric("sets", "set")].join(" · ");
  return <div className="min-w-48 max-w-md space-y-2 text-left" onClick={event => event.stopPropagation()}>
    <p className="text-sm font-medium text-slate-800">{stats}</p>
    {kind === "seed" && typeof data.note === "string" && <p className="line-clamp-3 text-sm text-slate-500">{data.note}</p>}
    {kind === "model" && typeof objective.sense === "string" && <p className="text-sm text-slate-500">Objective: {objective.sense}</p>}
    <details open={open} onToggle={event => setOpen(event.currentTarget.open)}>
      <summary className="w-fit cursor-pointer rounded py-2 text-sm text-blue-700 underline">Technical details ({kind === "seed" ? "sample data" : "model"})</summary>
      {open && <pre tabIndex={0} aria-label={kind === "seed" ? "Sample data JSON" : "Model JSON"} className="max-h-64 max-w-full overflow-auto whitespace-pre-wrap break-all rounded border border-slate-200 bg-slate-50 p-3 text-xs text-slate-800">{JSON.stringify(value, null, 2)}</pre>}
    </details>
  </div>;
}
