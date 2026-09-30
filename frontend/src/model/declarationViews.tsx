/**
 * A declaration -- a set, a parameter or a variable -- in the same four views
 * as rules and goals (docs/design/nested-blocks.md):
 *
 *   Sentence   "The solver decides overtime for every employee: any number from 0 to 20."
 *   Boxes      a Decision box holding its For each, its Kind and its Range
 *   Diagram    a drill-down of the same parts, and what reads it
 *   Equation   `0 <= overtime[employee] <= 20, continuous`
 *
 * Sets and parameters are chosen from the domain, not typed, so their views
 * read them; a variable's kind and bounds can be changed in its boxes and in
 * its equation. Its name and index are fixed here: rules refer to them, and
 * changing them is a new variable.
 */
import { useState, type ReactNode } from "react";
import EquationField from "./EquationField";
import { Children } from "./EquationDiagram";
import { Box, Summary } from "./NestedBlocks";
import type { Problem } from "./blockCheck";
import { describeUncertainty, withDomain, withStage, type ParameterSpec, type VariableSpec } from "./declarations";
import type { VariableDomain } from "../ir/contract";
import type { EquationView } from "./ViewToggle";

export type DeclarationKind = "set" | "parameter" | "variable";
type Attribute = { name: string; data_type: string };

const SELECT = "inline-block rounded-md border border-slate-300 bg-white px-2 py-1 text-sm text-slate-900";
const NUMERIC = new Set(["integer", "number"]);

function list(items: string[]): string {
  if (items.length <= 1) return items.join("");
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

function everyOf(index: string[]): string {
  return index.length ? `for ${index.map((set) => `every ${set}`).join(" and ")}` : "once";
}

function readBy(usedBy: string[]): string {
  return usedBy.length ? `Read by ${list(usedBy)}.` : "No rule or goal reads it yet.";
}

function kindWords(spec: VariableSpec): string {
  if (spec.domain === "binary") return "yes or no";
  const what = spec.domain === "integer" ? "a whole number" : "any number";
  if (spec.lower !== undefined && spec.upper !== undefined) return `${what} from ${spec.lower} to ${spec.upper}`;
  if (spec.lower !== undefined) return `${what} of at least ${spec.lower}, with no upper limit`;
  if (spec.upper !== undefined) return `${what} of at most ${spec.upper}`;
  return `${what}, with no limits`;
}

// -- the check -------------------------------------------------------------------

/** What is wrong with a declaration itself (what uses it is the rules' check). */
export function checkDeclaration(kind: DeclarationKind, spec: VariableSpec | ParameterSpec | null, sets: string[]): Problem[] {
  const out: Problem[] = [];
  if (!spec) return out;
  for (const set of spec.index) {
    if (!sets.includes(set)) {
      out.push({ path: ["for each"], level: "primitive", message: `“${set}” is not a set of this model: tick it under Sets` });
    }
  }
  if (kind === "variable") {
    const v = spec as VariableSpec;
    if (v.lower !== undefined && v.upper !== undefined && v.lower > v.upper) {
      out.push({ path: ["range"], level: "primitive", message: `at least ${v.lower} is above at most ${v.upper}, so no value is allowed` });
    }
    if (v.domain === "interval" && (!v.start || !v.end)) {
      out.push({ path: [], level: "primitive", message: "a span of time needs a start and an end" });
    }
  }
  return out;
}

// -- Sentence ---------------------------------------------------------------------

export function declarationSentence(kind: DeclarationKind, name: string, spec: VariableSpec | ParameterSpec | null,
  attributes: Attribute[], unit: string | null | undefined): string {
  if (kind === "set") {
    const numbers = attributes.filter((a) => NUMERIC.has(a.data_type)).map((a) => a.name);
    const has = numbers.length ? ` Each ${name} has the ${numbers.length === 1 ? "number" : "numbers"} ${list(numbers)}.` : "";
    return `The rules can range over every ${name} record of this domain.${has}`;
  }
  if (kind === "parameter") {
    const p = spec as ParameterSpec;
    const uncertain = describeUncertainty(p.uncertainty);
    return `${name} is data the domain holds: ${p.index.length ? `one number ${everyOf(p.index)}` : "a single number"}${unit ? `, in ${unit}` : ""}.` +
      (uncertain ? ` It is not exact: ${uncertain}.` : "");
  }
  const v = spec as VariableSpec;
  if (v.domain === "interval") {
    return `The solver decides ${name}${v.index.length ? ` ${everyOf(v.index)}` : ""}: a span of time from ${v.start ?? "?"} to ${v.end ?? "?"}, lasting ${v.size ?? "?"}` +
      `${v.presence ? `, and only if ${v.presence} is yes` : ""}.`;
  }
  const stage = v.stage === 1 ? " It is decided now, before the uncertain data is known." : v.stage === 2 ? " It is decided once the uncertain data is known." : "";
  return `The solver decides ${name}${v.index.length ? ` ${everyOf(v.index)}` : ""}: ${kindWords(v)}.${stage}`;
}

// -- Equation ---------------------------------------------------------------------

export function printVariable(name: string, spec: VariableSpec): string {
  const head = `${name}[${spec.index.join(", ")}]`;
  if (spec.domain === "binary") return `${head} in {0, 1}`;
  if (spec.domain === "interval") return `${head} = span(${spec.start ?? "?"}, ${spec.end ?? "?"}, ${spec.size ?? "?"})`;
  return `${spec.lower !== undefined ? `${spec.lower} <= ` : ""}${head}${spec.upper !== undefined ? ` <= ${spec.upper}` : ""}, ${spec.domain}`;
}

type Parsed = { ok: true; value: VariableSpec } | { ok: false; message: string; at: number; end: number };
const NUMBER = String.raw`-?\d+(?:\.\d+)?`;

/** A variable's line read back: its kind and bounds may change; its name and index may not. */
export function parseVariable(text: string, name: string, spec: VariableSpec): Parsed {
  const fail = (message: string): Parsed => ({ ok: false, message, at: 0, end: text.length });
  const match = new RegExp(
    String.raw`^\s*(?:(${NUMBER})\s*<=\s*)?([a-z][a-z0-9_]*)\s*\[([^\]]*)\]\s*(?:<=\s*(${NUMBER})\s*)?(?:(in\s*\{\s*0\s*,\s*1\s*\})|,\s*([a-z]+))\s*$`,
  ).exec(text);
  if (!match) {
    return fail(`Write it as “0 <= ${name}[${spec.index.join(", ")}] <= 10, integer”, “…, continuous”, or “${name}[…] in {0, 1}”.`);
  }
  const [, low, written, index, high, binary, kind] = match;
  if (written !== name) return fail(`This line is ${name}; to make “${written}”, add a new variable.`);
  const sets = index.split(",").map((s) => s.trim()).filter(Boolean);
  if (sets.join(",") !== spec.index.join(",")) {
    return fail(`${name} is one for every ${spec.index.join(" and ") || "nothing"}; changing that is a new variable.`);
  }
  const domain: VariableDomain | null = binary ? "binary" : kind === "integer" ? "integer" : kind === "continuous" ? "continuous" : null;
  if (!domain) return fail(`“${kind}” is not a kind: use integer, continuous, or in {0, 1}.`);
  if (domain === "binary" && (low !== undefined || high !== undefined)) return fail("Yes or no is already 0 or 1: it takes no bounds.");
  const lower = low === undefined ? undefined : Number(low);
  const upper = high === undefined ? undefined : Number(high);
  if (domain === "integer" && [lower, upper].some((b) => b !== undefined && !Number.isInteger(b))) {
    return fail("A whole number's bounds are whole numbers.");
  }
  const { lower: _l, upper: _u, ...rest } = withStage(withDomain(spec, domain), spec.stage);
  return { ok: true, value: { ...rest, ...(lower !== undefined ? { lower } : {}), ...(upper !== undefined ? { upper } : {}) } };
}

function staticLine(kind: DeclarationKind, name: string, spec: VariableSpec | ParameterSpec | null): string {
  if (kind === "set") return `set ${name}`;
  const p = spec as ParameterSpec;
  const u = p.uncertainty;
  const off = u?.kind === "interval" ? ` ± ${Number((u.deviation * 100).toPrecision(6))}%` : u?.kind === "scenarios" ? " (per scenario)" : "";
  return `data ${name}[${p.index.join(", ")}]${off}`;
}

// -- Boxes --------------------------------------------------------------------------

function BoundInput({ label, value, onChange }: { label: string; value: number | undefined; onChange: (next: number | undefined) => void }) {
  const [text, setText] = useState(value === undefined ? "" : String(value));
  return (
    <input aria-label={label} inputMode="decimal" className={`${SELECT} w-24 font-mono`} value={text} placeholder="no limit"
      onChange={(event) => {
        setText(event.target.value);
        const raw = event.target.value.trim();
        if (raw === "") return onChange(undefined);
        const next = Number(raw);
        if (Number.isFinite(next)) onChange(next);
      }} />
  );
}

function IndexBox({ index, problems }: { index: string[]; problems: Problem[] }) {
  return (
    <Box role="scope" title="For each" label={index.length ? "one for every" : "just one"} problems={problems} path={["for each"]}>
      <div className="flex flex-wrap gap-1">
        {index.length === 0 && <span className="text-sm text-slate-600">a single value, not one per item</span>}
        {index.map((set, i) => <span key={i} className="rounded border border-teal-300 px-2 py-0.5 font-mono text-xs text-teal-800">{set}</span>)}
      </div>
    </Box>
  );
}

function DeclarationBlocks({ kind, name, spec, attributes, unit, usedBy, problems, onChange }: {
  kind: DeclarationKind;
  name: string;
  spec: VariableSpec | ParameterSpec | null;
  attributes: Attribute[];
  unit?: string | null;
  usedBy: string[];
  problems: Problem[];
  onChange?: (next: VariableSpec) => void;
}) {
  const footer = <p className="mt-1 text-xs text-slate-500">{readBy(usedBy)}</p>;
  if (kind === "set") {
    return (
      <Box role="scope" title="Set" label={name} problems={problems} path={[]}>
        <div className="flex flex-wrap items-start gap-2">
          {attributes.length === 0 && <span className="text-sm text-slate-600">Its records carry no attributes yet.</span>}
          {attributes.map((a) => (
            <Box key={a.name} role={NUMERIC.has(a.data_type) ? "data" : "number"} title={NUMERIC.has(a.data_type) ? "Data of each" : "Label of each"}
              label={a.name} problems={[]} path={["attr", a.name]} />
          ))}
        </div>
        {footer}
      </Box>
    );
  }
  if (kind === "parameter") {
    const p = spec as ParameterSpec;
    const uncertain = describeUncertainty(p.uncertainty);
    return (
      <Box role="data" title="Data" label={name} problems={problems} path={[]}>
        <div className="flex flex-wrap items-start gap-2">
          <IndexBox index={p.index} problems={problems} />
          {unit && <Box role="number" title="Unit" label={unit} problems={[]} path={["unit"]} />}
          <Box role="operation" title="Exact?" label={uncertain ? "not exact" : "exact"} problems={[]} path={["uncertainty"]}>
            <p className="text-xs text-slate-700">{uncertain ?? "Each value is taken as given."}</p>
          </Box>
        </div>
        {footer}
      </Box>
    );
  }
  const v = spec as VariableSpec;
  return (
    <Box role="decision" title="Decision" label={name} problems={problems} path={[]}>
      <div className="flex flex-wrap items-start gap-2">
        <IndexBox index={v.index} problems={problems} />
        {v.domain === "interval" ? (
          <Box role="operation" title="Span of time" label="from start to end" problems={problems} path={["span"]}>
            <p className="text-xs text-slate-700">from {v.start} to {v.end}, lasting {String(v.size)}{v.presence ? `, only if ${v.presence}` : ""}</p>
          </Box>
        ) : (
          <>
            <Box role="number" title="Kind" label="what it can be" problems={problems} path={["kind"]}>
              <select aria-label={`${name}: kind`} className={SELECT} value={v.domain}
                onChange={(event) => onChange?.(withStage(withDomain(v, event.target.value as VariableDomain), v.stage))}>
                <option value="binary">yes or no</option>
                <option value="integer">a whole number</option>
                <option value="continuous">any number</option>
              </select>
            </Box>
            {v.domain !== "binary" && (
              <Box role="number" title="Range" label="its limits" problems={problems} path={["range"]}>
                <div className="flex flex-wrap items-center gap-1 text-sm text-slate-700">
                  at least
                  <BoundInput key={`lo-${v.lower}`} label={`${name}: at least`} value={v.lower}
                    onChange={(lower) => { const { lower: _l, ...rest } = v; onChange?.(lower === undefined ? rest : { ...rest, lower }); }} />
                  at most
                  <BoundInput key={`hi-${v.upper}`} label={`${name}: at most`} value={v.upper}
                    onChange={(upper) => { const { upper: _u, ...rest } = v; onChange?.(upper === undefined ? rest : { ...rest, upper }); }} />
                </div>
                {v.upper === undefined && (
                  <p className="mt-1 text-xs text-amber-800">With no upper limit, an answer may grow without limit.</p>
                )}
              </Box>
            )}
          </>
        )}
      </div>
      {footer}
    </Box>
  );
}

// -- Diagram ------------------------------------------------------------------------

function Node({ label, kind, children }: { label: string; kind: string; children?: ReactNode[] }) {
  const [open, setOpen] = useState(true);
  const has = (children?.length ?? 0) > 0;
  return (
    <div className="rounded-md border border-dotted border-slate-400 bg-white" data-testid="declaration-node">
      <div className="flex items-center gap-2 rounded-t-md bg-blue-50/60 px-2 py-1">
        {has ? (
          <button type="button" aria-expanded={open} aria-label={`${open ? "Close" : "Open"} ${label}`} onClick={() => setOpen(!open)}
            className="inline-flex h-7 w-7 items-center justify-center rounded text-slate-600 hover:bg-slate-100">
            <span aria-hidden="true">{open ? "▼" : "▶"}</span>
          </button>
        ) : <span className="inline-block w-7" aria-hidden="true" />}
        <span className="text-xs font-semibold text-slate-700">{label}</span>
        <span className="rounded bg-slate-100 px-1.5 text-xs text-slate-600">{kind}</span>
      </div>
      {open && has && <Children>{children!}</Children>}
    </div>
  );
}

function DeclarationDiagram({ kind, name, spec, attributes, unit, usedBy }: {
  kind: DeclarationKind;
  name: string;
  spec: VariableSpec | ParameterSpec | null;
  attributes: Attribute[];
  unit?: string | null;
  usedBy: string[];
}) {
  const users = usedBy.length ? [<Node key="used" label="read by" kind={list(usedBy)} />] : [<Node key="used" label="read by" kind="nothing yet" />];
  if (kind === "set") {
    return <Node label={name} kind="set" children={[...attributes.map((a) => <Node key={a.name} label={a.name} kind={NUMERIC.has(a.data_type) ? "number" : a.data_type} />), ...users]} />;
  }
  const index = (spec?.index ?? []).map((set) => <Node key={`i-${set}`} label={`every ${set}`} kind="one for" />);
  if (kind === "parameter") {
    const p = spec as ParameterSpec;
    return <Node label={name} kind="data" children={[...index, ...(unit ? [<Node key="u" label={unit} kind="unit" />] : []),
      <Node key="x" label={describeUncertainty(p.uncertainty) ?? "exact"} kind="values" />, ...users]} />;
  }
  const v = spec as VariableSpec;
  const range = v.domain === "binary" || v.domain === "interval" ? [] : [
    <Node key="lo" label={v.lower === undefined ? "no lower limit" : `at least ${v.lower}`} kind="range" />,
    <Node key="hi" label={v.upper === undefined ? "no upper limit" : `at most ${v.upper}`} kind="range" />,
  ];
  return <Node label={name} kind="decision" children={[...index, <Node key="k" label={v.domain === "interval" ? "span of time" : kindWords({ ...v, lower: undefined, upper: undefined }).replace(", with no limits", "")} kind="kind" />, ...range, ...users]} />;
}

// -- one declaration, in the view asked for ------------------------------------------

export function DeclarationView({ kind, name, spec, view, sets, attributes = [], unit, usedBy, onChange, onBoxes }: {
  kind: DeclarationKind;
  name: string;
  spec: VariableSpec | ParameterSpec | null;
  view: EquationView;
  sets: string[];
  attributes?: Attribute[];
  unit?: string | null;
  usedBy: string[];
  onChange?: (next: VariableSpec) => void;
  onBoxes: () => void;
}) {
  const problems = checkDeclaration(kind, spec, sets);
  if (view === "sentence") {
    return (
      <div className="space-y-2 rounded-md border border-slate-200 bg-slate-50 p-3" data-testid="declaration-sentence">
        <p className="text-sm leading-relaxed text-slate-900">{declarationSentence(kind, name, spec, attributes, unit)} {readBy(usedBy)}</p>
        <Summary problems={problems} />
        <button type="button" className="text-xs text-blue-700 underline" onClick={onBoxes}>See it in boxes</button>
      </div>
    );
  }
  if (view === "boxes") {
    return (
      <div className="space-y-2" data-testid="declaration-blocks">
        <Summary problems={problems} />
        <DeclarationBlocks kind={kind} name={name} spec={spec} attributes={attributes} unit={unit} usedBy={usedBy} problems={problems} onChange={onChange} />
      </div>
    );
  }
  if (view === "diagram") {
    return <div data-testid="declaration-diagram"><DeclarationDiagram kind={kind} name={name} spec={spec} attributes={attributes} unit={unit} usedBy={usedBy} /></div>;
  }
  if (kind === "variable" && spec && (spec as VariableSpec).domain !== "interval" && onChange) {
    const v = spec as VariableSpec;
    return (
      <EquationField<VariableSpec>
        label={`Equation for ${name}`}
        equation={printVariable(name, v)}
        parse={(text) => parseVariable(text, name, v)}
        onCommit={(next) => onChange(next)}
        chips={[]}
        sets={sets}
      />
    );
  }
  return (
    <p className="rounded-md bg-slate-50 px-3 py-2 font-mono text-sm text-slate-800" aria-label={`Equation for ${name}`}>
      {kind === "variable" ? printVariable(name, spec as VariableSpec) : staticLine(kind, name, spec)}
    </p>
  );
}
