/**
 * Walks along a relationship -- a hierarchy or any other link between items --
 * editable in words in the Sentence and Boxes views. In the model a walk is a
 * binding's `via`; read as a tree it is:
 *
 *   every employee e  linked from [m ▾] by [manages, going down ▾]  [in 1 or more steps ▾]  links called [r]  ✕
 *     start:     m, bound before this binding (via.from / via.to)
 *     relation:  manages
 *     direction: from m's end (down a hierarchy) or to it (up)
 *     depth:     1 step, 1 or more, or 0 or more (m itself too) -- only on a
 *                relationship from a set to itself
 *     condition: the binding's `where` (WhereBlanks)
 *     body:      what the total reads, which may be the links' own numbers
 *                (AttrBlanks: "the [sum ▾] of [weight ▾] along [r ▾]")
 *
 * Only walks the model can take are offered (`walksAvailable`): a declared
 * relationship with an end at this binding's set, from an item already bound.
 */
import { useState } from "react";
import { PATH_COMBINATIONS } from "../ir";
import {
  arithmeticAttributes,
  edgeAttributes,
  edgesInScope,
  viaOf,
  walkKey,
  walksAvailable,
  type Binding,
  type ModelContext,
  type Steps,
  type Term,
  type Via,
  type WalkEnd,
} from "./terms";
import { WhereBlanks } from "./WhereBlanks";
import { DEPTH_WORDS } from "./walkWords";

export function WalkBlanks({ label, binding, earlier, context, className, onChange }: {
  label: string;
  binding: Binding;
  /** Everything bound before this binding: where a walk can start. */
  earlier: Binding[];
  context: ModelContext;
  className: string;
  onChange: (next: Binding) => void;
}) {
  const offers = walksAvailable(context, binding.set, earlier);
  const current = viaOf(binding);
  const name = `${label}: walk`;
  const clear = () => {
    const { via: _dropped, ...rest } = binding;
    onChange(rest);
  };

  if (!current) {
    if (offers.length === 0) return <WalkHint label={label} set={binding.set} context={context} />;
    return (
      <button type="button" className="ml-1 text-xs text-blue-700 underline" aria-label={`Reach ${binding.set} through a relationship: ${label}`}
        onClick={() => onChange({ ...binding, via: { rel: offers[0].rel, [offers[0].anchorEnd]: offers[0].anchors[0] } as Via })}>
        + linked through…
      </button>
    );
  }

  const via = binding.via as Via;
  const offer = offers.find((o) => o.rel === current.rel && o.anchorEnd === current.anchorEnd);
  const relationship = context.relationships.find((r) => r.name === current.rel);
  const loops = !!relationship && relationship.from === relationship.to;
  const isTree = (rel: string) => context.relationships.some((r) => r.name === rel && r.hierarchy);
  const tree = isTree(current.rel);
  /** The walk re-anchored, keeping how far, which links, which day and the links' name. */
  const moved = (rel: string, end: WalkEnd, anchor: string, self: boolean): Via => {
    const { rel: _r, from: _f, to: _t, both: _b, depth, steps, where, ...rest } = via;
    return {
      rel,
      [end]: anchor,
      ...(self && depth ? { depth } : {}),
      ...(self && steps ? { steps } : {}),
      ...(rel === via.rel && where ? { where } : {}),
      ...rest,
    } as Via;
  };
  // Down or up a hierarchy; along or against any other link from a set to itself; or either way.
  const direction = (rel: string, end: WalkEnd, self: boolean) =>
    !self ? "" : end === "both" ? ", either way" : isTree(rel) ? (end === "from" ? ", going down" : ", going up") : end === "from" ? ", forwards" : ", backwards";
  const anchors = offer?.anchors ?? [];
  const lead = current.anchorEnd === "both" ? "linked either way to" : tree ? (current.anchorEnd === "from" ? "below" : "above") : `linked ${current.anchorEnd}`;
  const far = via.steps ? "range" : (via.depth ?? "one");
  const setVia = (next: Via) => onChange({ ...binding, via: next });
  const linkAttributes = relationship?.attributes ?? [];

  return (
    <span className="inline-flex flex-wrap items-center gap-1" data-testid="walk">
      <span className="text-slate-600">{binding.where?.length ? "," : ""} {lead}</span>
      <select aria-label={`${name}: starting at`} className={className} value={current.anchor}
        onChange={(event) => setVia(moved(current.rel, current.anchorEnd, event.target.value, loops))}>
        {!anchors.includes(current.anchor) && <option value={current.anchor}>{current.anchor || "choose…"}</option>}
        {anchors.map((a) => <option key={a} value={a}>{a} ({earlier.find((b) => b.index === a)?.set})</option>)}
      </select>
      <span className="text-slate-600">by</span>
      <select aria-label={`${name}: relationship`} className={className} value={walkKey(current.rel, current.anchorEnd)}
        onChange={(event) => {
          const picked = offers.find((o) => walkKey(o.rel, o.anchorEnd) === event.target.value);
          if (!picked) return;
          const anchor = picked.anchors.includes(current.anchor) ? current.anchor : picked.anchors[0];
          setVia(moved(picked.rel, picked.anchorEnd, anchor, picked.loops));
        }}>
        {!offer && <option value={walkKey(current.rel, current.anchorEnd)}>{current.rel || "choose…"}</option>}
        {offers.map((o) => (
          <option key={walkKey(o.rel, o.anchorEnd)} value={walkKey(o.rel, o.anchorEnd)}>{o.rel}{direction(o.rel, o.anchorEnd, o.loops)}</option>
        ))}
      </select>
      {(loops || far !== "one") && (
        <select aria-label={`${name}: how far`} className={className} value={far}
          onChange={(event) => {
            const { depth: _d, steps: _s, ...rest } = via;
            const value = event.target.value;
            setVia(value === "one" ? rest : value === "range" ? { ...rest, steps: { min: 1, max: 2 } } : { ...rest, depth: value as Via["depth"] });
          }}>
          {Object.entries(DEPTH_WORDS).map(([value, words]) => <option key={value} value={value}>{words}</option>)}
          <option value="range">a number of steps…</option>
        </select>
      )}
      {via.steps && (
        <StepsBlanks name={name} steps={via.steps} className={className} onChange={(steps) => setVia({ ...via, steps })} />
      )}
      {linkAttributes.length > 0 && (
        <WhereBlanks label={`${name} links`} set={`${current.rel} links`} where={via.where} context={context} className={className}
          attributes={linkAttributes} lead="through links whose" addText={["+ only through some links", "+ and"]}
          onChange={(where) => {
            const { where: _old, ...rest } = via;
            setVia(where ? { ...rest, where } : rest);
          }} />
      )}
      {via.on !== undefined ? (
        <span className="inline-flex items-center gap-1">
          <span className="text-slate-600">on</span>
          <input type="date" aria-label={`${name}: on the day`} className={className} value={via.on}
            title="Only the links valid that day: from their “valid from” to their “valid to”"
            onChange={(event) => setVia({ ...via, on: event.target.value })} />
          <button type="button" className="text-xs text-rose-700" aria-label={`Any day: ${name}`} title="Every link, whatever its dates"
            onClick={() => {
              const { on: _old, ...rest } = via;
              setVia(rest);
            }}>
            ✕
          </button>
        </span>
      ) : (
        <button type="button" className="text-xs text-blue-700 underline" aria-label={`Only the links valid on a day: ${name}`}
          title="Without a day, every link counts, whatever its dates"
          onClick={() => setVia({ ...via, on: new Date().toISOString().slice(0, 10) })}>
          + on a day
        </button>
      )}
      <span className="text-slate-600">, links called</span>
      <input aria-label={`${name}: name of each link`} className={`${className} w-14 font-mono`} placeholder="—" value={via.as ?? ""}
        title="Name the links to read their own numbers, such as a distance or a share"
        onChange={(event) => {
          const { as: _old, ...rest } = via;
          const next = event.target.value.trim();
          setVia(next ? { ...rest, as: next } : rest);
        }} />
      <button type="button" className="text-xs text-rose-700" aria-label={`Remove ${name}`} title="Range over all of them again" onClick={clear}>
        ✕
      </button>
    </span>
  );
}

/** "from [2] to [3] steps", the most left empty for no limit. */
function StepsBlanks({ name, steps, className, onChange }: { name: string; steps: Steps; className: string; onChange: (next: Steps) => void }) {
  const whole = (text: string) => (/^\d+$/.test(text.trim()) ? Number(text) : null);
  return (
    <span className="inline-flex items-center gap-1">
      <span className="text-slate-600">from</span>
      <input aria-label={`${name}: fewest steps`} inputMode="numeric" className={`${className} w-12 font-mono`} value={String(steps.min)}
        onChange={(event) => {
          const min = whole(event.target.value);
          if (min !== null) onChange({ ...steps, min });
        }} />
      <span className="text-slate-600">to</span>
      <input aria-label={`${name}: most steps`} inputMode="numeric" placeholder="any" className={`${className} w-12 font-mono`}
        value={steps.max === undefined ? "" : String(steps.max)}
        onChange={(event) => {
          const text = event.target.value.trim();
          const max = whole(text);
          if (text === "") onChange({ min: steps.min });
          else if (max !== null) onChange({ ...steps, max });
        }} />
      <span className="text-slate-600">steps</span>
    </span>
  );
}

/**
 * Why no walk is offered here, when the model has a relationship that could
 * reach this set: a walk starts at an item picked before it, and none is.
 */
function WalkHint({ label, set, context }: { label: string; set: string; context: ModelContext }) {
  const [open, setOpen] = useState(false);
  const starts = context.relationships
    .flatMap((r) => [
      ...(r.to === set ? [{ rel: r.name, from: r.from }] : []),
      ...(r.from === set && r.to !== set ? [{ rel: r.name, from: r.to }] : []),
    ]);
  if (starts.length === 0) return null;
  return (
    <>
      <button type="button" className="ml-1 text-xs text-slate-500 underline decoration-dotted" aria-expanded={open}
        aria-label={`Why no link: ${label}`} onClick={() => setOpen(!open)}>
        linked through…?
      </button>
      {open && (
        <span role="note" className="ml-1 text-xs text-slate-600">
          A link starts at an item picked before this one. To reach {set} through{" "}
          {starts.map((s, i) => <span key={i}>{i > 0 && " or "}{s.rel} (from its {s.from} end)</span>)}, first add “every{" "}
          {starts[0].from}” in “For each”, or before this one.
        </span>
      )}
    </>
  );
}

/** After a change of set dropped a binding's conditions or walk: say what went, and bring it back. */
export function UndoSetChange({ label, before, onUndo }: { label: string; before: Binding; onUndo: () => void }) {
  const what = [before.where?.length ? "its conditions" : "", before.via ? `the link by ${before.via.rel}` : ""].filter(Boolean).join(" and ");
  return (
    <span role="status" className="ml-1 text-xs text-amber-800">
      ({what} did not fit the new set;{" "}
      <button type="button" className="underline" aria-label={`Undo the change of set: ${label}`} onClick={onUndo}>
        undo
      </button>)
    </span>
  );
}

type AttrTerm = Extract<Term, { attr: unknown }>;

/**
 * A number read from an item ("[cap ▾] of [e ▾]") or from the links a walk
 * names ("[weight ▾] of [r ▾]"). Over a walk of many steps the links are many,
 * so it says how they combine: "the [sum ▾] of [weight ▾] along [r ▾]".
 */
export function AttrBlanks({ label, term, bound, context, className, onChange }: {
  label: (what: string) => string;
  term: AttrTerm;
  bound: Binding[];
  context: ModelContext;
  className: string;
  onChange: (next: Term) => void;
}) {
  const edges = edgesInScope(bound);
  const edge = edges.find((e) => e.name === term.attr.of);
  const item = edge ? undefined : [...bound].reverse().find((b) => b.index === term.attr.of);
  const attributesOf = (of: string) => {
    const link = edges.find((e) => e.name === of);
    if (link) return edgeAttributes(context, link.rel);
    const binding = [...bound].reverse().find((b) => b.index === of);
    return binding ? arithmeticAttributes(context, binding.set) : [];
  };
  const attrs = attributesOf(term.attr.of);
  const seen = new Set<string>();
  const items = [...bound].reverse().filter((b) => !seen.has(b.index) && seen.add(b.index)).reverse();

  const which = (
    <select aria-label={label("of which item")} className={className} value={term.attr.of}
      onChange={(event) => {
        const of = event.target.value;
        const link = edges.find((e) => e.name === of);
        const names = attributesOf(of).map((a) => a.name);
        const name = names.includes(term.attr.name) ? term.attr.name : names[0] ?? term.attr.name;
        onChange({ attr: link?.path ? { of, name, along: term.attr.along ?? "sum" } : { of, name } });
      }}>
      {!item && !edge && <option value={term.attr.of}>{term.attr.of || "choose…"}</option>}
      {items.map((b) => <option key={b.index} value={b.index}>{b.index} ({b.set})</option>)}
      {edges.map((e) => <option key={`@${e.name}`} value={e.name}>{e.name} (links by {e.rel})</option>)}
    </select>
  );
  const number = (
    <select aria-label={label("which number")} className={className} value={term.attr.name}
      onChange={(event) => onChange({ attr: { ...term.attr, name: event.target.value } })}>
      {!attrs.some((a) => a.name === term.attr.name) && <option value={term.attr.name}>{term.attr.name || "choose…"}</option>}
      {attrs.map((a) => <option key={a.name} value={a.name}>{a.name}</option>)}
    </select>
  );

  if (edge?.path || term.attr.along) {
    return (
      <span className="inline-flex flex-wrap items-center gap-1">
        the
        <select aria-label={label("how the links combine")} className={className} value={term.attr.along ?? ""}
          onChange={(event) => {
            const { along: _old, ...rest } = term.attr;
            onChange({ attr: event.target.value ? { ...rest, along: event.target.value as AttrTerm["attr"]["along"] } : rest });
          }}>
          {/* A walk cut back to one step, or an item, has one value: nothing to combine, and this takes it off. */}
          {(!term.attr.along || !edge?.path) && <option value="">{edge?.path ? "choose…" : "(one value, no combining)"}</option>}
          {PATH_COMBINATIONS.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        of {number} along {which}
      </span>
    );
  }
  return <span className="inline-flex flex-wrap items-center gap-1">{number} of {which}</span>;
}
