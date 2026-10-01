/**
 * "From times" (improvement plan 5.2): link every pair of time slots that overlap or leave less than
 * a rest of so many hours, as a relationship a rule reads ("nobody takes both ends of a too-close
 * link"). Works on any kind of record with a start and an end (or a duration): shifts, tasks, lessons,
 * bookings. The server reads the times; nothing here knows what the slots are.
 */
import { useId, useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../api/client";
import { formatApiError } from "../api/errors";
import type { EntityType, Id } from "../api/v1";

// "enum": a column of times like 06:00 / 18:00 imported as a short list of choices still reads as times.
const TIMEY = new Set(["time", "integer", "number", "date", "text", "enum"]);
const TIME_WORDS = ["start", "end", "begin", "from", "until", "hour", "duration", "length", "day", "date", "time", "shift", "slot"];

/** How much a kind looks like a list of time slots: one point per time-sounding field, two for typed times. */
export function timeScore(t: EntityType): number {
  let score = /shift|slot|block|period|session|booking|time/i.test(t.name) ? 3 : 0;
  for (const a of t.attributes) {
    if (!TIMEY.has(a.data_type)) continue;
    if (a.data_type === "time" || a.data_type === "date") score += 2;
    else if (TIME_WORDS.some((w) => a.name.toLowerCase().includes(w))) score += a.data_type === "text" || a.data_type === "enum" ? 0.5 : 1;
  }
  return score;
}

export default function TimesTooClose({ domainId, entityTypes }: { domainId: Id; entityTypes: EntityType[] }) {
  const id = useId();
  const client = useQueryClient();
  // Kinds with at least two fields that can hold a time, best first: names that sound like times
  // ("start_hour", "end", "duration", "day") count most, so shifts/blocks lead and a lookup list
  // of names (two text fields) comes last instead of being picked by default.
  const timed = entityTypes
    .filter((t) => t.attributes.filter((a) => TIMEY.has(a.data_type)).length >= 2)
    .map((t) => ({ t, score: timeScore(t) }))
    .sort((a, b) => b.score - a.score)
    .map(({ t }) => t);
  const [chosen, setTypeId] = useState<Id | "">("");
  const typeId = timed.some((t) => t.id === chosen) ? chosen : (timed[0]?.id ?? "");
  const kind = timed.find((t) => t.id === typeId);
  const fields = (kind?.attributes ?? []).filter((a) => TIMEY.has(a.data_type)).map((a) => a.name);
  const guess = (names: string[], skip: string[] = []) =>
    fields.find((f) => !skip.includes(f) && names.some((n) => f.toLowerCase().includes(n))) ?? "";
  const [start, setStart] = useState("");
  const [endMode, setEndMode] = useState<"end" | "duration">("end");
  const [end, setEnd] = useState("");
  const [day, setDay] = useState("");
  const [gap, setGap] = useState("10");
  const [name, setName] = useState("too_close");
  const [said, setSaid] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (!timed.length) return null;
  const startField = start || guess(["start", "from", "begin"]);
  const endField = end || (endMode === "end" ? guess(["end", "until", "to"], [startField]) : guess(["duration", "length", "hour"], [startField]));
  const dayField = day === "-" ? "" : day || guess(["day", "date"], [startField, endField]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaid(null);
    const hours = Number(gap);
    if (!(hours >= 0)) return setSaid("Rest: a number of hours, 0 or more.");
    setBusy(true);
    try {
      const done = await apiFetch<{ links: number; records: number; unread: string[] }>(`/api/v1/domains/${domainId}/time/too-close`, {
        method: "POST",
        body: JSON.stringify({
          name, type_id: typeId, start_field: startField, min_gap_hours: hours,
          ...(endMode === "end" ? { end_field: endField } : { duration_field: endField }),
          ...(dayField ? { day_field: dayField } : {}),
        }),
      });
      void client.invalidateQueries();
      setSaid(`${name}: ${done.links} pairs of ${kind?.name ?? "slots"} too close (of ${done.records})${done.unread.length ? `; ${done.unread.length} whose times could not be read` : ""}.`);
    } catch (e) {
      setSaid(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  const select = (label: string, value: string, set: (v: string) => void, optional = false) => (
    <label className="text-xs text-slate-600">{label}
      <select className="ml-1 rounded border px-2 py-1 text-sm" value={value} onChange={(e) => set(e.target.value)}>
        {optional && <option value="-">none</option>}
        {fields.map((f) => <option key={f} value={f}>{f}</option>)}
      </select>
    </label>
  );
  return (
    <section aria-labelledby={`${id}-h`} className="mb-6 rounded-lg border border-slate-200 bg-white p-4">
      <h2 id={`${id}-h`} className="text-base font-semibold text-slate-900">From times</h2>
      <p className="mb-3 text-sm text-slate-600">
        Link time slots that overlap or leave too little rest, so a rule can keep anyone from taking both
        (the rule shape &ldquo;Nobody takes two slots that are too close&rdquo;).
      </p>
      <form onSubmit={(e) => void submit(e)} className="flex flex-wrap items-end gap-3">
        <label className="text-xs text-slate-600">Slots
          <select className="ml-1 rounded border px-2 py-1 text-sm" value={String(typeId)} onChange={(e) => setTypeId(Number(e.target.value))}>
            {timed.map((t) => <option key={String(t.id)} value={String(t.id)}>{t.name}</option>)}
          </select>
        </label>
        {select("day", dayField || "-", setDay, true)}
        {select("start", startField, setStart)}
        <label className="text-xs text-slate-600">ends by
          <select className="ml-1 rounded border px-2 py-1 text-sm" value={endMode} onChange={(e) => { setEndMode(e.target.value as "end" | "duration"); setEnd(""); }}>
            <option value="end">an end time</option>
            <option value="duration">a duration in hours</option>
          </select>
        </label>
        {select(endMode === "end" ? "end" : "duration", endField, setEnd)}
        <label className="text-xs text-slate-600">rest at least
          <input className="ml-1 w-16 rounded border px-2 py-1 text-sm" value={gap} onChange={(e) => setGap(e.target.value)} /> h
        </label>
        <label className="text-xs text-slate-600">named
          <input className="ml-1 w-32 rounded border px-2 py-1 font-mono text-sm" value={name} onChange={(e) => setName(e.target.value.trim())} />
        </label>
        <button type="submit" disabled={busy || !startField || !endField}
          className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60">
          Link too-close slots
        </button>
      </form>
      {said && <p role="status" className="mt-2 text-sm text-slate-700">{said}</p>}
    </section>
  );
}
