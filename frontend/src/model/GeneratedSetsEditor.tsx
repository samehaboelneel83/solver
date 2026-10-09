import { useState } from "react";
import { checkRecipe, outputs, RECIPE_KINDS } from "../ir/generate";

type Json = Record<string, unknown>;
type TypeInfo = { name: string; attributes: { name: string }[] };

const INPUT = "rounded border border-slate-300 px-2 py-1 text-sm";
const KIND_TEXT: Record<string, string> = {
  range: "Numbers from … to … (periods, hours, levels)",
  product: "Every combination of two to four sets (pairings, assignments)",
  positions: "Every position items fit in on drawn areas (a layout's candidate list)",
};

function blank(kind: string): Json {
  if (kind === "range") return { kind, set: "", from: 1, to: 10 };
  if (kind === "product") return { kind, set: "", of: ["", ""] };
  return { kind, areas: "", shape: "shape", kinds: "", length: "length_cells", width: "width_cells", can_turn: "can_turn",
    value: "value", step: 0.5, origin: [0, 0], items: "item", cells: "cell", occupies: "occupies" };
}

/** One line on what a recipe makes. */
function summary(recipe: Json): string {
  try {
    const made = outputs(recipe);
    const sets = made.sets.join(" and ");
    if (recipe.kind === "range") return `${sets}: ${recipe.from} to ${recipe.to}${recipe.step && recipe.step !== 1 ? ` by ${recipe.step}` : ""}`;
    if (recipe.kind === "product") {
      return `${sets}: every ${(recipe.of as string[]).join(" × ")}${recipe.linked ? ` linked by ${recipe.linked}` : ""}`
        + (made.relationships.length ? `, with links ${made.relationships.join(", ")}` : "");
    }
    return `${sets}: positions on ${recipe.areas} for each ${recipe.kinds}, ${recipe.step} m grid${recipe.aisle ? `, aisle ${recipe.aisle} cells` : ""}`
      + `; links ${made.relationships.join(", ")}`;
  } catch {
    return String(recipe.kind);
  }
}

/**
 * Sets the run builds from a recipe instead of stored records (`generate`, plan 1B): authored here without the
 * Assistant (owner, 9 October 2026). What each recipe makes is a set (and links) the rules can range over at once.
 */
export function GeneratedSetsEditor({ generate, sets, relationships, types, canEdit, onChange }: {
  generate: Json[];
  /** The sets the model lists (and so the recipes may read). */
  sets: string[];
  relationships: string[];
  types: TypeInfo[];
  canEdit: boolean;
  onChange: (next: Json[]) => void;
}) {
  const [editing, setEditing] = useState<{ at: number | null; recipe: Json } | null>(null);
  const known = (upTo: number) => {
    const s = new Set(sets);
    const r = new Set(relationships);
    generate.slice(0, upTo).forEach((recipe) => {
      try {
        const made = outputs(recipe);
        made.sets.forEach((n) => s.add(n));
        made.relationships.forEach((n) => r.add(n));
      } catch {
        // A recipe that does not check makes nothing to read.
      }
    });
    return { s, r };
  };
  const at = editing ? (editing.at ?? generate.length) : generate.length;
  const { s: readable, r: readableRels } = known(at);
  const fault = editing ? checkRecipe(editing.recipe, readable, readableRels) : null;
  const attrsOf = (set: unknown) => types.find((t) => t.name === set)?.attributes.map((a) => a.name) ?? [];
  const r = editing?.recipe ?? {};
  const set = (patch: Json) => editing && setEditing({ ...editing, recipe: { ...editing.recipe, ...patch } });
  const unset = (key: string) => {
    if (!editing) return;
    const { [key]: _gone, ...rest } = editing.recipe;
    setEditing({ ...editing, recipe: rest });
  };
  const num = (value: string) => (value.trim() === "" || Number.isNaN(Number(value)) ? value : Number(value));
  const setPicker = (label: string, key: string, options: string[], optional = false) => (
    <label className="text-sm">{label}{" "}
      <select aria-label={label} className={INPUT} value={String(r[key] ?? "")}
        onChange={(e) => (e.target.value === "" && optional ? unset(key) : set({ [key]: e.target.value }))}>
        <option value="">{optional ? "none" : "choose…"}</option>
        {options.map((o) => <option key={o} value={o}>{o}</option>)}
      </select></label>
  );
  const text = (label: string, key: string, width = "w-28") => (
    <label className="text-sm">{label}{" "}
      <input aria-label={label} className={`${INPUT} ${width}`} value={String(r[key] ?? "")}
        onChange={(e) => (e.target.value === "" ? unset(key) : set({ [key]: e.target.value }))} /></label>
  );
  const number = (label: string, key: string) => (
    <label className="text-sm">{label}{" "}
      <input aria-label={label} className={`${INPUT} w-20`} inputMode="decimal" value={String(r[key] ?? "")}
        onChange={(e) => (e.target.value === "" ? unset(key) : set({ [key]: num(e.target.value) }))} /></label>
  );

  return (
    <section aria-labelledby="generated-sets" className="mt-6 rounded-lg border border-slate-200 bg-white p-4">
      <h3 id="generated-sets" className="font-semibold text-slate-900">Generated sets</h3>
      <p className="text-sm text-slate-600">
        Sets each run builds from a recipe, never stored as records: ranges of numbers, every combination of other
        sets, or every position items fit in on drawn areas. Rules and decisions range over them like any set.
      </p>
      {generate.length > 0 && (
        <ul className="my-2 space-y-1 text-sm">{generate.map((recipe, n) => (
          <li key={n}>
            <span>{summary(recipe)}</span>
            {canEdit && <>
              <button type="button" className="ml-2 text-xs text-blue-700 underline"
                onClick={() => setEditing({ at: n, recipe: { ...recipe } })}>Edit</button>
              <button type="button" className="ml-2 text-xs text-red-700 underline"
                onClick={() => onChange(generate.filter((_, k) => k !== n))}>Remove</button>
            </>}
          </li>
        ))}</ul>
      )}
      {canEdit && !editing && (
        <div className="mt-2 flex flex-wrap gap-2">
          {RECIPE_KINDS.map((kind) => (
            <button key={kind} type="button" className="rounded border px-2 py-1 text-sm"
              onClick={() => setEditing({ at: null, recipe: blank(kind) })}>Add: {KIND_TEXT[kind]}</button>
          ))}
        </div>
      )}
      {editing && (
        <div role="group" aria-label="Recipe" className="mt-3 space-y-2 rounded border border-blue-200 bg-blue-50 p-3">
          <p className="text-sm font-medium">{KIND_TEXT[String(r.kind)]}</p>
          {r.kind === "range" && <div className="flex flex-wrap gap-3">
            {text("Set name", "set")}{number("From", "from")}{number("To", "to")}{number("Step", "step")}
          </div>}
          {r.kind === "product" && <div className="space-y-2">
            <div className="flex flex-wrap gap-3">
              {text("Set name", "set")}
              {((r.of as string[]) ?? []).map((part, k) => (
                <label key={k} className="text-sm">{`Part ${k + 1}`}{" "}
                  <select aria-label={`Part ${k + 1}`} className={INPUT} value={part}
                    onChange={(e) => set({ of: (r.of as string[]).map((p, j) => (j === k ? e.target.value : p)) })}>
                    <option value="">choose…</option>
                    {[...readable].map((o) => <option key={o} value={o}>{o}</option>)}
                  </select></label>
              ))}
              {((r.of as string[]) ?? []).length < 4 && <button type="button" className="text-xs text-blue-700 underline"
                onClick={() => set({ of: [...(r.of as string[]), ""] })}>Add a part</button>}
              {((r.of as string[]) ?? []).length > 2 && <button type="button" className="text-xs text-red-700 underline"
                onClick={() => set({ of: (r.of as string[]).slice(0, -1) })}>Remove the last part</button>}
            </div>
            <div className="flex flex-wrap gap-3">
              {setPicker("Only pairs linked by", "linked", [...readableRels], true)}
              <label className="text-sm">Same values (first's=second's, comma-separated){" "}
                <input aria-label="Same values" className={`${INPUT} w-48`}
                  value={((r.same as string[][]) ?? []).map(([a, b]) => `${a}=${b}`).join(", ")}
                  onChange={(e) => {
                    const pairs = e.target.value.split(",").map((p) => p.split("=").map((x) => x.trim())).filter((p) => p[0]);
                    if (pairs.length) set({ same: pairs.map((p) => [p[0], p[1] ?? p[0]]) });
                    else unset("same");
                  }} /></label>
              <label className="text-sm"><input type="checkbox" className="mr-1" checked={Boolean(r.distinct)}
                onChange={(e) => (e.target.checked ? set({ distinct: true }) : unset("distinct"))} />no repeats</label>
              <label className="text-sm"><input type="checkbox" className="mr-1" checked={Boolean(r.unordered)}
                onChange={(e) => (e.target.checked ? set({ unordered: true }) : unset("unordered"))} />each pair once</label>
            </div>
          </div>}
          {r.kind === "positions" && <div className="space-y-2">
            <div className="flex flex-wrap gap-3">
              {setPicker("Areas (polygons)", "areas", [...readable])}
              {setPicker("Shape attribute (WKT, metres)", "shape", attrsOf(r.areas))}
            </div>
            <div className="flex flex-wrap gap-3">
              {setPicker("Item kinds", "kinds", [...readable])}
              {setPicker("Length in cells", "length", attrsOf(r.kinds))}
              {setPicker("Width in cells", "width", attrsOf(r.kinds))}
              {setPicker("May turn (0/1)", "can_turn", attrsOf(r.kinds), true)}
              {setPicker("Worth", "value", attrsOf(r.kinds), true)}
            </div>
            <div className="flex flex-wrap gap-3">
              {number("Grid step (m)", "step")}
              <label className="text-sm">Origin x, y (m){" "}
                <input aria-label="Origin x" className={`${INPUT} w-20`} value={String((r.origin as number[])?.[0] ?? "")}
                  onChange={(e) => set({ origin: [num(e.target.value), (r.origin as number[])?.[1] ?? 0] })} />{" "}
                <input aria-label="Origin y" className={`${INPUT} w-20`} value={String((r.origin as number[])?.[1] ?? "")}
                  onChange={(e) => set({ origin: [(r.origin as number[])?.[0] ?? 0, num(e.target.value)] })} /></label>
              <label className="text-sm">Aisle (cells){" "}
                <input aria-label="Aisle (cells)" className={`${INPUT} w-16`} inputMode="numeric" value={String(r.aisle ?? "")}
                  onChange={(e) => {
                    const cells = Number(e.target.value) || 0;
                    if (cells > 0) set({ aisle: cells, aisle_sides: r.aisle_sides ?? "any", keeps_free: r.keeps_free ?? "keeps_free" });
                    else if (editing) {
                      const { aisle: _a, aisle_sides: _s, keeps_free: _k, ...rest } = editing.recipe;
                      setEditing({ ...editing, recipe: rest });
                    }
                  }} /></label>
              {Boolean(r.aisle) && <label className="text-sm">On{" "}
                <select aria-label="Aisle side" className={INPUT} value={String(r.aisle_sides ?? "any")}
                  onChange={(e) => set({ aisle_sides: e.target.value })}>
                  <option value="any">any side</option><option value="long">a long side</option><option value="short">a short side</option>
                </select></label>}
            </div>
            <div className="flex flex-wrap gap-3">
              <label className="text-sm">Reachable from{" "}
                <select aria-label="Reachable from" className={INPUT} value={String(r.access ?? "")} onChange={(e) => {
                  if (e.target.value) set({ access: e.target.value, access_shape: r.access_shape ?? "shape", next_to: r.next_to ?? "next_to" });
                  else if (editing) {
                    const { access: _a, access_shape: _s, next_to: _n, ...rest } = editing.recipe;
                    setEditing({ ...editing, recipe: rest });
                  }
                }}>
                  <option value="">nowhere in particular</option>
                  {[...readable].map((o) => <option key={o} value={o}>{o}</option>)}
                </select></label>
              {Boolean(r.access) && setPicker("Their shape attribute", "access_shape", attrsOf(r.access))}
            </div>
            <div className="flex flex-wrap gap-3">
              {text("Positions set", "items")}{text("Cells set", "cells")}{text("Covers links", "occupies")}
              {Boolean(r.aisle) && text("Aisle links", "keeps_free")}
              {Boolean(r.access) && text("Neighbour links", "next_to")}
            </div>
          </div>}
          <p role="status" className={`text-sm ${fault ? "text-red-700" : "text-green-800"}`}>
            {fault ? `${fault[2]} [${fault[0]}${fault[1].length ? ` at ${fault[1].join(" / ")}` : ""}]` : `Makes ${summary(r)}.`}
          </p>
          <div className="flex gap-2">
            <button type="button" className="rounded bg-blue-700 px-3 py-1.5 text-sm text-white disabled:opacity-50"
              disabled={Boolean(fault)} onClick={() => {
                onChange(editing.at === null ? [...generate, editing.recipe]
                  : generate.map((g, k) => (k === editing.at ? editing.recipe : g)));
                setEditing(null);
              }}>{editing.at === null ? "Add the recipe" : "Keep the changes"}</button>
            <button type="button" className="rounded border px-3 py-1.5 text-sm" onClick={() => setEditing(null)}>Cancel</button>
          </div>
        </div>
      )}
    </section>
  );
}
