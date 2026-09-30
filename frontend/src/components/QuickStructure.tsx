/**
 * Data and structure together (simplification plan, phase 2): a new kind of
 * record, or a new field on one, made from the Records page as the records
 * are typed -- rather than on a separate Structure page first. The full
 * editors (roles, colours, units, inheritance) stay under Structure.
 */
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { formatApiError } from "../api/errors";
import { createAttribute, createEntityType, type AttrType, type EntityType, type Id } from "../api/v1";

const INPUT = "rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm text-slate-900";
const BUTTON = "rounded-md border border-slate-300 px-3 py-2 text-sm font-medium text-slate-800 hover:bg-slate-50 disabled:opacity-50";
const PRIMARY = "rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50";

/** "Hours per week" -> "hours_per_week": a name the platform takes (lower case, digits and _). */
export function toName(text: string): string {
  return text.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").replace(/^([0-9])/, "n_$1");
}

const KINDS: [AttrType, string][] = [
  ["number", "a number"],
  ["integer", "a whole number"],
  ["text", "text"],
  ["boolean", "yes or no"],
  ["date", "a date"],
  ["enum", "one of a list"],
];

function useSave() {
  const client = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  async function save<T>(work: () => Promise<T>): Promise<T | null> {
    setBusy(true);
    setProblem(null);
    try {
      const made = await work();
      await client.invalidateQueries();
      return made;
    } catch (error) {
      setProblem(formatApiError(error));
      return null;
    } finally {
      setBusy(false);
    }
  }
  return { busy, problem, save };
}

export function NewKindForm({ domainId, onMade, onCancel }: { domainId: Id; onMade: (type: EntityType) => void; onCancel?: () => void }) {
  const [text, setText] = useState("");
  const { busy, problem, save } = useSave();
  const name = toName(text);
  return (
    <form className="flex flex-wrap items-center gap-2" aria-label="New kind of record"
      onSubmit={async (event) => {
        event.preventDefault();
        const made = await save(() => createEntityType({ domain_id: domainId, name }));
        if (made) onMade(made);
      }}>
      <label className="text-sm text-slate-700">
        A new kind of record, such as “employee” or “shift”:{" "}
        <input className={INPUT} value={text} onChange={(event) => setText(event.target.value)} placeholder="employee" />
      </label>
      {name && name !== text.trim() && <span className="text-xs text-slate-500">saved as <code>{name}</code></span>}
      <button type="submit" className={PRIMARY} disabled={busy || !name}>Create</button>
      {onCancel && <button type="button" className="text-sm text-slate-600 underline" onClick={onCancel}>Cancel</button>}
      {problem && <p role="alert" className="w-full text-sm text-red-700">{problem}</p>}
    </form>
  );
}

export function NewFieldForm({ type, onDone }: { type: EntityType; onDone: () => void }) {
  const [text, setText] = useState("");
  const [kind, setKind] = useState<AttrType>("number");
  const [choices, setChoices] = useState("");
  const { busy, problem, save } = useSave();
  const name = toName(text);
  const list = choices.split(",").map((c) => c.trim()).filter(Boolean);
  return (
    <form className="flex flex-wrap items-center gap-2" aria-label={`New field on ${type.name}`}
      onSubmit={async (event) => {
        event.preventDefault();
        const made = await save(() => createAttribute(type.id, { name, data_type: kind, ...(kind === "enum" ? { enum_values: list } : {}) }));
        if (made) onDone();
      }}>
      <label className="text-sm text-slate-700">
        Each {type.name} has a{" "}
        <input className={INPUT} value={text} onChange={(event) => setText(event.target.value)} placeholder="hours per week" />
      </label>
      <label className="text-sm text-slate-700">
        which is{" "}
        <select className={INPUT} value={kind} onChange={(event) => setKind(event.target.value as AttrType)}>
          {KINDS.map(([value, words]) => <option key={value} value={value}>{words}</option>)}
        </select>
      </label>
      {kind === "enum" && (
        <label className="text-sm text-slate-700">
          choices{" "}
          <input className={INPUT} value={choices} onChange={(event) => setChoices(event.target.value)} placeholder="junior, senior" />
        </label>
      )}
      {name && name !== text.trim() && <span className="text-xs text-slate-500">saved as <code>{name}</code></span>}
      <button type="submit" className={PRIMARY} disabled={busy || !name || (kind === "enum" && list.length === 0)}>Add</button>
      <button type="button" className="text-sm text-slate-600 underline" onClick={onDone}>Cancel</button>
      {problem && <p role="alert" className="w-full text-sm text-red-700">{problem}</p>}
    </form>
  );
}

/** The two buttons beside the record-type chooser, and the form either opens. */
export default function QuickStructure({ domainId, type, onMade }: { domainId: Id; type: EntityType | null; onMade: (type: EntityType) => void }) {
  const [open, setOpen] = useState<"kind" | "field" | null>(null);
  return (
    <div className="mb-4 space-y-2">
      <div className="flex flex-wrap gap-2">
        <button type="button" className={BUTTON} aria-expanded={open === "kind"} onClick={() => setOpen(open === "kind" ? null : "kind")}>
          + New kind of record
        </button>
        {type && !type.is_abstract && (
          <button type="button" className={BUTTON} aria-expanded={open === "field"} onClick={() => setOpen(open === "field" ? null : "field")}>
            + Add a field to {type.name}
          </button>
        )}
      </div>
      {open === "kind" && <NewKindForm domainId={domainId} onMade={(made) => { setOpen(null); onMade(made); }} onCancel={() => setOpen(null)} />}
      {open === "field" && type && <NewFieldForm type={type} onDone={() => setOpen(null)} />}
    </div>
  );
}
