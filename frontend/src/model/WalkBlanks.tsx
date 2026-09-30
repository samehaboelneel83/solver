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
  type Term,
  type Via,
} from "./terms";
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
    if (offers.length === 0) return null;
    return (
      <button type="button" className="ml-1 text-xs text-blue-700 underline" aria-label={`Reach ${binding.set} through a relationship: ${label}`}
        onClick={() => onChange({ ...binding, via: { rel: offers[0].rel, [offers[0].anchorEnd]: offers[0].anchors[0] } as Via })}>
        + linked through…
      </button>
    );
  }

  const via = binding.via as Via;
  const offer = offers.find((o) => o.rel === current.rel && o.anchorEnd === current.anchorEnd);
  const loops = context.relationships.some((r) => r.name === current.rel && r.from === r.to);
  const keep = () => ({ ...(via.depth && loops ? { depth: via.depth } : {}), ...(via.as ? { as: via.as } : {}) });
  const direction = (end: "from" | "to", self: boolean) => (self ? (end === "from" ? ", going down" : ", going up") : "");
  const anchors = offer?.anchors ?? [];

  return (
    <span className="inline-flex flex-wrap items-center gap-1" data-testid="walk">
      <span className="text-slate-600">{binding.where?.length ? "," : ""} linked {current.anchorEnd === "from" ? "from" : "to"}</span>
      <select aria-label={`${name}: starting at`} className={className} value={current.anchor}
        onChange={(event) => onChange({ ...binding, via: { rel: current.rel, [current.anchorEnd]: event.target.value, ...keep() } as Via })}>
        {!anchors.includes(current.anchor) && <option value={current.anchor}>{current.anchor || "choose…"}</option>}
        {anchors.map((a) => <option key={a} value={a}>{a} ({earlier.find((b) => b.index === a)?.set})</option>)}
      </select>
      <span className="text-slate-600">by</span>
      <select aria-label={`${name}: relationship`} className={className} value={walkKey(current.rel, current.anchorEnd)}
        onChange={(event) => {
          const picked = offers.find((o) => walkKey(o.rel, o.anchorEnd) === event.target.value);
          if (!picked) return;
          const anchor = picked.anchors.includes(current.anchor) ? current.anchor : picked.anchors[0];
          const depth = picked.loops && via.depth ? { depth: via.depth } : {};
          onChange({ ...binding, via: { rel: picked.rel, [picked.anchorEnd]: anchor, ...depth, ...(via.as ? { as: via.as } : {}) } as Via });
        }}>
        {!offer && <option value={walkKey(current.rel, current.anchorEnd)}>{current.rel || "choose…"}</option>}
        {offers.map((o) => (
          <option key={walkKey(o.rel, o.anchorEnd)} value={walkKey(o.rel, o.anchorEnd)}>{o.rel}{direction(o.anchorEnd, o.loops)}</option>
        ))}
      </select>
      {(loops || (via.depth && via.depth !== "one")) && (
        <select aria-label={`${name}: how far`} className={className} value={via.depth ?? "one"}
          onChange={(event) => {
            const { depth: _old, ...rest } = via;
            onChange({ ...binding, via: event.target.value === "one" ? rest : { ...rest, depth: event.target.value as Via["depth"] } });
          }}>
          {Object.entries(DEPTH_WORDS).map(([value, words]) => <option key={value} value={value}>{words}</option>)}
        </select>
      )}
      <span className="text-slate-600">, links called</span>
      <input aria-label={`${name}: name of each link`} className={`${className} w-14 font-mono`} placeholder="—" value={via.as ?? ""}
        title="Name the links to read their own numbers, such as a distance or a share"
        onChange={(event) => {
          const { as: _old, ...rest } = via;
          const next = event.target.value.trim();
          onChange({ ...binding, via: next ? { ...rest, as: next } : rest });
        }} />
      <button type="button" className="text-xs text-rose-700" aria-label={`Remove ${name}`} title="Range over all of them again" onClick={clear}>
        ✕
      </button>
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
          onChange={(event) => onChange({ attr: { ...term.attr, along: event.target.value as AttrTerm["attr"]["along"] } })}>
          {!term.attr.along && <option value="">choose…</option>}
          {PATH_COMBINATIONS.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        of {number} along {which}
      </span>
    );
  }
  return <span className="inline-flex flex-wrap items-center gap-1">{number} of {which}</span>;
}
