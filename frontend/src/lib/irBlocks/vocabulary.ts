/**
 * The editable block vocabulary (Blockly edit mode spec §3): one block per
 * IR construct. A choice is a dropdown filled from the workspace's catalogue
 * and the block's own surroundings (`catalogue.ts`), so it only offers what
 * the contract would accept there.
 *
 * Two rules keep a loaded model exactly what the draft says:
 *
 * - **A dropdown keeps any value it is given.** Blockly's own dropdown
 *   refuses a value missing from its options; ours (`OpenDropdown`) takes
 *   it and lists it, so a set whose type was renamed or a decision since
 *   deleted is shown by name and refused by the validators -- never blanked.
 * - **Nothing is judged while loading.** Name rules and the parameter
 *   index lookup apply to what a person types or picks; `loadBlocks` turns
 *   them off while a draft is being shown, so a draft with a bad name is
 *   shown with its bad name.
 *
 * `toBlocks.ts` and `toIr.ts` rely on the field and input names here; the
 * plan's Task 3 table lists them.
 */
import * as Blockly from "blockly";
import { FILTER_OPERATORS, FUNCTIONS, OBJECTIVE_MODES, PATH_COMBINATIONS, RELATIONS, SENSES, SEVERITIES, TRAVERSAL_DEPTHS, UNCERTAINTY_KINDS } from "../../ir/contract";
import { NONE, bindingsOf, catalogueOf, declared, edgeOf, menu, scopeAt } from "./catalogue";

const NAME = /^[a-z][a-z0-9_]*$/;
const MAX_ARITY = 4;
const MAX_ADD = 16;
/** The most points a curve block holds. */
export const MAX_POINTS = 12;

// Loose typing for block `this`: Blockly's `Block` plus our own shape state.
type B = Blockly.Block & {
  arity?: number;
  count?: number;
  index?: string[];
  version?: number;
  isGiven?: boolean;
  emptyGiven?: boolean;
  json?: unknown;
  setSlots?(n: number): void;
  setTerms?(n: number): void;
  setPoints?(n: number): void;
};

let loading = false;

/** Load a serialised workspace without judging what it says (see the module note). */
export function loadBlocks(workspace: Blockly.Workspace, json: object): void {
  loading = true;
  try {
    Blockly.serialization.workspaces.load(json, workspace);
  } finally {
    loading = false;
  }
}

/** A dropdown that accepts any string value and always lists the one it holds. */
class OpenDropdown extends Blockly.FieldDropdown {
  protected override doClassValidation_(newValue?: string): string | null {
    return typeof newValue === "string" ? newValue : null;
  }

  /**
   * Never from Blockly's cache. The cache is filled when the block is made,
   * before its value is loaded -- with no catalogue (the read-only view) it
   * then lacks the value, and the field shows "(choose)" over a set that is
   * there. Recomputed, the list always holds the current value; it is small.
   */
  override getOptions(_useCache?: boolean): Blockly.MenuOption[] {
    return super.getOptions(false);
  }
}

/** Options recomputed each time the menu opens, from the block's surroundings. */
function dynamic(
  values: (block: Blockly.Block) => string[],
  label?: (value: string) => string,
  validator?: (value: string) => string | null
): Blockly.FieldDropdown {
  return new OpenDropdown(function (this: Blockly.FieldDropdown) {
    const block = this.getSourceBlock();
    return menu(block ? values(block) : [], this.getValue(), label);
  }, validator);
}

/** A fixed list of choices, still keeping a value from outside it. */
function fixed(values: readonly string[], label?: (value: string) => string, validator?: (value: string) => string | null): Blockly.FieldDropdown {
  // Not through `dynamic`: a fixed list needs no block, and at construction
  // there is none -- the first option must still be the default.
  return new OpenDropdown(function (this: Blockly.FieldDropdown) {
    return menu([...values], this.getValue(), label ?? ((v) => v));
  }, validator);
}

/** A name the platform accepts and no other block of these kinds uses in `field`. */
function nameField(initial: string, kinds: readonly string[], field: string): Blockly.FieldTextInput {
  return new Blockly.FieldTextInput(initial, function (this: Blockly.FieldTextInput, text: string) {
    if (loading) return text;
    if (!NAME.test(text)) return null;
    const self = this.getSourceBlock();
    const clash = self?.workspace
      .getAllBlocks(false)
      .some((other) => other !== self && kinds.includes(other.type) && other.getFieldValue(field) === text);
    return clash ? null : text;
  });
}

/** A number as text, or empty for "not given" -- never other text. */
function numberText(initial: string): Blockly.FieldTextInput {
  return new Blockly.FieldTextInput(initial, (text: string) =>
    loading || text === "" || Number.isFinite(Number(text)) ? text : null
  );
}

function rerender(block: Blockly.Block) {
  if ((block as Blockly.BlockSvg).rendered) (block as Blockly.BlockSvg).queueRender();
}

/** Grow or shrink a row of slots named `${prefix}${i}` to `n`, each placed before `before` when given. */
function reshape(block: B, key: "arity" | "count", n: number, add: (i: number) => void, prefix: string, before?: string) {
  const had = block[key] ?? 0;
  for (let i = had - 1; i >= n; i -= 1) block.removeInput(`${prefix}${i}`, true);
  for (let i = had; i < n; i += 1) {
    add(i);
    if (before && block.getInput(before)) block.moveInputBefore(`${prefix}${i}`, before);
  }
  block[key] = n;
  rerender(block);
}

/**
 * Index slots IDX0.. of a reference: each offers the indices bound here to
 * the set its declaration expects there. `scope` is where the indices come
 * from -- around the block by default; a scheduling rule's own slots read
 * its own FORALL and OVER. `before` places the slots ahead of that input.
 */
function refSlots(
  block: B,
  n: number,
  expected: (i: number) => string | undefined,
  scope: (b: Blockly.Block) => Map<string, string> = scopeAt,
  before?: string
) {
  reshape(
    block,
    "arity",
    n,
    (i) =>
      block
        .appendDummyInput(`SLOT${i}`)
        .appendField(i === 0 ? "[" : ",")
        .appendField(
          dynamic((b) => {
            const inScope = [...scope(b)];
            const names = inScope.filter(([, set]) => expected(i) === undefined || set === expected(i)).map(([index]) => index);
            // Queue R20b: an entity-valued parameter's cell stands where its set is wanted,
            // read at the first index bound to each of its own sets.
            const cells = [...declared(b.workspace).parameters]
              .filter(([, spec]) => spec.entity !== undefined && spec.entity === expected(i))
              .map(([name, spec]) => {
                const at = spec.index.map((set) => inScope.find(([, s]) => s === set)?.[0]);
                return at.every((x) => x !== undefined) ? `${name}[${at.join(", ")}]` : null;
              })
              .filter((x): x is string => x !== null);
            return [...names, ...cells];
          }),
          `IDX${i}`
        ),
    "SLOT",
    before
  );
}

/** The decisions declared in the model that `keep` admits, by name. */
function decisions(b: Blockly.Block, keep: (spec: { index: string[]; domain: string }) => boolean): string[] {
  return [...declared(b.workspace).variables].filter(([, spec]) => keep(spec)).map(([name]) => name);
}

/** The indices a scheduling rule's own interval slots may use: those around it, then its FORALL and OVER. */
function ownScope(b: Blockly.Block): Map<string, string> {
  const scope = new Map(scopeAt(b));
  for (const [index, set] of [...bindingsOf(b.getInputTargetBlock("FORALL")), ...bindingsOf(b.getInputTargetBlock("OVER"))]) {
    if (index && !scope.has(index)) scope.set(index, set);
  }
  return scope;
}

const sameIndex = (a: string[], b: string[]) => a.length === b.length && a.every((set, i) => set === b[i]);

const COLOUR = {
  model: "#475569",
  set: "#0d9488",
  decision: "#2563eb",
  data: "#64748b",
  rule: "#334155",
  binding: "#0f766e",
  goal: "#16a34a",
  variable: "#3b82f6",
  parameter: "#94a3b8",
  constant: "#78716c",
  attribute: "#14b8a6",
  sum: "#7c3aed",
  operator: "#59c059",
  opaque: "#a8a29e",
};

const choose = (v: string) => v || "(choose)";

/** A reference to a declared decision or data: NAME, then its index slots. */
function referenceBlock(kind: "variables" | "parameters", word: string, colour: string) {
  const declaration = (ws: Blockly.Workspace, name: string) => declared(ws)[kind].get(name);
  return {
    init(this: B) {
      const input = this.appendDummyInput("HEAD");
      if (word) input.appendField(word);
      input.appendField(
        dynamic(
          (b) =>
            [...declared(b.workspace)[kind]]
              .filter(([, spec]) => kind !== "variables" || (spec as { domain: string }).domain !== "interval")
              // An entity-valued parameter is an index, never a number (queue R20b).
              .filter(([, spec]) => kind !== "parameters" || !(spec as { entity?: string }).entity)
              .map(([name]) => name),
          choose,
          (name: string) => {
            if (!loading) {
              const spec = declaration(this.workspace, name);
              if (spec) refSlots(this, spec.index.length, (i) => declaration(this.workspace, this.getFieldValue("NAME"))?.index[i]);
            }
            return name;
          }
        ),
        "NAME"
      );
      this.setOutput(true, "Number");
      this.setInputsInline(true);
      this.setColour(colour);
      this.arity = 0;
    },
    saveExtraState(this: B) {
      return { arity: this.arity ?? 0 };
    },
    loadExtraState(this: B, state: { arity: number }) {
      refSlots(this, state.arity, (i) => declaration(this.workspace, this.getFieldValue("NAME"))?.index[i]);
    },
  };
}

function opaqueBlock(shape: "declaration" | "rule" | "term") {
  return {
    init(this: B) {
      this.appendDummyInput().appendField(new Blockly.FieldLabelSerializable(""), "LABEL");
      if (shape === "term") this.setOutput(true, "Number");
      else {
        this.setPreviousStatement(true, shape);
        this.setNextStatement(true, shape);
      }
      this.setColour(COLOUR.opaque);
      this.setTooltip("Part of the model the blocks cannot edit yet: it is kept exactly as it is. The forms can edit it.");
    },
    saveExtraState(this: B) {
      return { json: this.json };
    },
    loadExtraState(this: B, state: { json: unknown }) {
      this.json = state.json;
    },
  };
}

/** A scheduling rule: intervals that never overlap, or that never use more than a capacity at once. */
function schedulingBlock(kind: "no_overlap" | "cumulative") {
  return {
    init(this: B) {
      const spec = (name: string) => declared(this.workspace).variables.get(name);
      this.appendDummyInput()
        .appendField("rule")
        .appendField(nameField("c_1", RULE_KINDS, "ID"), "ID")
        .appendField(kind === "no_overlap" ? "no two overlap" : "shares a capacity");
      this.appendDummyInput().appendField("means").appendField(new Blockly.FieldTextInput(""), "NOTE");
      this.appendStatementInput("FORALL").setCheck("binding").appendField("for every");
      this.appendDummyInput("HEAD")
        .appendField("the intervals")
        .appendField(
          dynamic((b) => decisions(b, (v) => v.domain === "interval"), choose, (name: string) => {
            if (!loading) refSlots(this, spec(name)?.index.length ?? 0, (i) => spec(this.getFieldValue("INTERVAL"))?.index[i], ownScope, "OVER");
            return name;
          }),
          "INTERVAL"
        );
      this.appendStatementInput("OVER").setCheck("binding").appendField("over");
      if (kind === "cumulative") {
        this.appendValueInput("DEMAND").setCheck("Number").appendField("each using");
        this.appendValueInput("CAPACITY").setCheck("Number").appendField("never more than, at once");
      }
      this.setPreviousStatement(true, "rule");
      this.setNextStatement(true, "rule");
      this.setColour(COLOUR.rule);
      this.setTooltip(
        kind === "no_overlap"
          ? "Of the intervals over these indices, no two are ever running at the same time"
          : "The intervals over these indices, each using its amount while it runs, never use more than the capacity at once"
      );
      this.arity = 0;
    },
    saveExtraState(this: B) {
      return { arity: this.arity ?? 0 };
    },
    loadExtraState(this: B, state: { arity: number }) {
      refSlots(this, state.arity, (i) => declared(this.workspace).variables.get(this.getFieldValue("INTERVAL"))?.index[i], ownScope, "OVER");
    },
  };
}

export function defineIrBlocks(): void {
  if (Blockly.Blocks.ir_model) return;

  Blockly.Blocks.ir_model = {
    init(this: B) {
      this.appendDummyInput().appendField("optimization model").appendField(new Blockly.FieldLabelSerializable(""), "TITLE");
      this.appendDummyInput()
        .appendField("the goal is to")
        .appendField(fixed(SENSES), "SENSE")
        .appendField("its terms")
        .appendField(fixed(OBJECTIVE_MODES, (m) => (m === "lex" ? "in order of importance" : "weighted together")), "MODE");
      this.appendStatementInput("DECLARE").setCheck("declaration").appendField("sets, decisions and data");
      this.appendStatementInput("RULES").setCheck("rule").appendField("rules");
      this.appendStatementInput("GOAL").setCheck("goal_term").appendField("goal");
      this.setDeletable(false);
      this.setColour(COLOUR.model);
      this.version = 2;
    },
    saveExtraState(this: B) {
      return { version: this.version };
    },
    loadExtraState(this: B, state: { version: number }) {
      this.version = state.version;
    },
  };

  Blockly.Blocks.ir_set = {
    init(this: B) {
      this.appendDummyInput()
        .appendField("set")
        .appendField(
          dynamic((b) => {
            const taken = declared(b.workspace).sets;
            const own = b.getFieldValue("SET");
            return catalogueOf(b.workspace).entityTypes.map((t) => t.name).filter((n) => n === own || !taken.includes(n));
          }, choose),
          "SET"
        );
      this.setPreviousStatement(true, "declaration");
      this.setNextStatement(true, "declaration");
      this.setColour(COLOUR.set);
      this.setTooltip("A set the model ranges over: every entity of this type");
    },
  };

  Blockly.Blocks.ir_variable = {
    init(this: B) {
      this.appendDummyInput("HEAD")
        .appendField("decide")
        .appendField(nameField("x", ["ir_variable"], "NAME"), "NAME")
        .appendField("over")
        .appendField(
          fixed(["0", "1", "2", "3", "4"], (n) => (n === "1" ? "1 set" : `${n} sets`), (n: string) => {
            this.setSlots!(Number(n));
            return n;
          }),
          "ARITY"
        );
      // Ends its row: an interval's start, end and length go on the next line, not off the right edge.
      this.appendEndRowInput("DOMAIN_ROW")
        .appendField("as")
        .appendField(
          fixed(
            ["binary", "integer", "continuous", "interval"],
            (d) => ({ binary: "yes or no", interval: "an interval of time" })[d] ?? d,
            (domain: string) => {
              for (const name of ["FROM", "LOWER", "TO", "UPPER"]) this.getField(name)?.setVisible(domain === "integer" || domain === "continuous");
              this.getInput("INTERVAL_ROW")?.setVisible(domain === "interval");
              rerender(this);
              return domain;
            }
          ),
          "DOMAIN"
        )
        .appendField(new Blockly.FieldLabel("from"), "FROM")
        .appendField(numberText(""), "LOWER")
        .appendField(new Blockly.FieldLabel("to"), "TO")
        .appendField(numberText(""), "UPPER")
        .appendField(
          fixed(["", "1", "2"], (s) => ({ "": "(one stage)", "1": "decided now", "2": "once the data is known" })[s] ?? s),
          "STAGE"
        );
      // An interval (scheduling): its start and end are integer decisions
      // with its own index, its length a whole number or data, and it may
      // be optional -- present only when a yes-or-no decision says so.
      const ownSets = (b: Blockly.Block) => Array.from({ length: Number(b.getFieldValue("ARITY")) }, (_, i) => b.getFieldValue(`SET${i}`));
      const part = (keep: (domain: string) => boolean) =>
        dynamic((b) => decisions(b, (spec) => keep(spec.domain) && sameIndex(spec.index, ownSets(b))), choose);
      this.appendDummyInput("INTERVAL_ROW")
        .appendField("starts at")
        .appendField(part((d) => d === "integer"), "START")
        .appendField("ends at")
        .appendField(part((d) => d === "integer"), "END")
        .appendField("lasts")
        .appendField(
          new Blockly.FieldTextInput("1", (text: string) => (loading || /^\d+$/.test(text) || NAME.test(text) ? text : null)),
          "SIZE"
        )
        .appendField(
          dynamic(
            (b) => [NONE, ...decisions(b, (spec) => spec.domain === "binary" && sameIndex(spec.index, ownSets(b)))],
            (v) => (v ? `only if ${v}` : "(always there)")
          ),
          "PRESENCE"
        );
      this.getInput("INTERVAL_ROW")!.setVisible(false);
      for (const name of ["FROM", "LOWER", "TO", "UPPER"]) this.getField(name)!.setVisible(false);
      this.setInputsInline(true);
      this.setPreviousStatement(true, "declaration");
      this.setNextStatement(true, "declaration");
      this.setColour(COLOUR.decision);
      this.setTooltip("A decision the solver makes. An interval lasts a whole number of steps, or as long as the data of that name says");
      this.arity = 0;
    },
    setSlots(this: B, n: number) {
      reshape(
        this,
        "arity",
        Math.max(0, Math.min(MAX_ARITY, n)),
        (i) =>
          this.appendDummyInput(`SETSLOT${i}`)
            .appendField(i === 0 ? "[" : "×")
            .appendField(dynamic((b) => catalogueOf(b.workspace).entityTypes.map((t) => t.name), choose), `SET${i}`),
        "SETSLOT",
        "DOMAIN_ROW"
      );
    },
    saveExtraState(this: B) {
      return { arity: this.arity ?? 0 };
    },
    loadExtraState(this: B, state: { arity: number }) {
      this.setSlots!(state.arity);
      this.setFieldValue(String(state.arity), "ARITY");
    },
  };

  Blockly.Blocks.ir_parameter = {
    init(this: B) {
      this.appendDummyInput()
        .appendField("data")
        .appendField(
          dynamic(
            (b) => {
              const taken = [...declared(b.workspace).parameters.keys()];
              const own = b.getFieldValue("NAME");
              return catalogueOf(b.workspace).parameters.map((p) => p.name).filter((n) => n === own || !taken.includes(n));
            },
            choose,
            (name: string) => {
              if (!loading) {
                const def = catalogueOf(this.workspace).parameters.find((p) => p.name === name);
                this.index = def ? [...def.index] : [];
                this.setFieldValue(this.index.length ? `[${this.index.join(", ")}]` : "", "INDEX");
                this.setFieldValue(def?.entity ?? "", "ENTITY");
              }
              return name;
            }
          ),
          "NAME"
        )
        .appendField(new Blockly.FieldLabelSerializable(""), "INDEX")
        // Queue R20b: what the values are, as the domain says -- a set's entities, or numbers ("").
        .appendField(new Blockly.FieldLabelSerializable(""), "ENTITY");
      const deviates = (kind: string) => {
        for (const name of ["DEVIATION", "GAMMA_LABEL", "GAMMA", "CELLS"]) this.getField(name)?.setVisible(kind === "interval");
        rerender(this);
        return kind;
      };
      this.appendDummyInput("UNCERTAINTY_ROW")
        .appendField(
          fixed(["exact", ...UNCERTAINTY_KINDS], (k) => ({ exact: "known exactly", interval: "may deviate by", scenarios: "varies by scenario" })[k] ?? k, deviates),
          "UNCERTAINTY"
        )
        .appendField(numberText("0.1"), "DEVIATION")
        .appendField(new Blockly.FieldLabel("of each value, in at most"), "GAMMA_LABEL")
        .appendField(numberText(""), "GAMMA")
        .appendField(new Blockly.FieldLabel("cells at once"), "CELLS");
      for (const name of ["DEVIATION", "GAMMA_LABEL", "GAMMA", "CELLS"]) this.getField(name)!.setVisible(false);
      this.setPreviousStatement(true, "declaration");
      this.setNextStatement(true, "declaration");
      this.setColour(COLOUR.data);
      this.setTooltip(
        "Numbers the model reads, from the domain's parameter of this name. If they are uncertain, a robust solve protects against them: a deviation is a fraction of each value; leave the cell count empty for all of them"
      );
      this.index = [];
    },
    saveExtraState(this: B) {
      return { index: this.index ?? [] };
    },
    loadExtraState(this: B, state: { index: string[] }) {
      this.index = [...state.index];
    },
  };

  Blockly.Blocks.ir_rule = {
    init(this: B) {
      this.appendDummyInput()
        .appendField("rule")
        .appendField(nameField("c_1", RULE_KINDS, "ID"), "ID")
        .appendField(
          fixed(SEVERITIES, (s) => (s === "hard" ? "must hold" : "may bend, at"), (severity: string) => {
            this.getField("WEIGHT")?.setVisible(severity === "soft");
            this.getField("PER_UNIT")?.setVisible(severity === "soft");
            rerender(this);
            return severity;
          }),
          "SEVERITY"
        )
        .appendField(numberText("1"), "WEIGHT")
        .appendField(new Blockly.FieldLabel("per unit"), "PER_UNIT");
      this.appendDummyInput().appendField("means").appendField(new Blockly.FieldTextInput(""), "NOTE");
      // A chance (version 2): the share of sampled futures it may fail in; empty for always.
      this.appendDummyInput("CHANCE_ROW")
        .appendField("may fail in")
        .appendField(numberText(""), "CHANCE")
        .appendField("of futures (a share; empty: never)");
      this.appendStatementInput("FORALL").setCheck("binding").appendField("for every");
      this.appendStatementInput("WHEN").setCheck("when").appendField("only when");
      this.appendValueInput("LEFT").setCheck("Number");
      this.appendDummyInput().appendField(fixed(RELATIONS, (r) => ({ "<=": "≤", ">=": "≥" })[r] ?? r), "RELATION");
      this.appendValueInput("RIGHT").setCheck("Number");
      this.setPreviousStatement(true, "rule");
      this.setNextStatement(true, "rule");
      this.setColour(COLOUR.rule);
      this.setTooltip("A rule every answer must satisfy, or may break at a price");
      this.getField("WEIGHT")!.setVisible(false);
      this.getField("PER_UNIT")!.setVisible(false);
    },
  };

  Blockly.Blocks.ir_binding = {
    init(this: B) {
      this.appendDummyInput()
        .appendField(
          new Blockly.FieldTextInput("i", (text: string) => (loading || NAME.test(text) ? text : null)),
          "INDEX"
        )
        .appendField("in")
        .appendField(dynamic((b) => declared(b.workspace).sets, choose), "SET");
      const walks = (value: string) => {
        for (const name of ["VIA_END", "VIA_ANCHOR", "VIA_DEPTH", "VIA_AS"]) this.getField(name)?.setVisible(value !== NONE);
        rerender(this);
        return value;
      };
      this.appendDummyInput("VIA")
        .appendField(
          dynamic(
            (b) => {
              const set = b.getFieldValue("SET");
              return [NONE, ...catalogueOf(b.workspace).relationships.filter((r) => r.from === set || r.to === set).map((r) => r.name)];
            },
            (v) => (v ? `via ${v}` : "(every one)"),
            walks
          ),
          "VIA_REL"
        )
        .appendField(fixed(["from", "to"], (e) => (e === "from" ? "from" : "back to")), "VIA_END")
        .appendField(
          dynamic((b) => {
            const rel = catalogueOf(b.workspace).relationships.find((r) => r.name === b.getFieldValue("VIA_REL"));
            const anchorSet = rel ? (b.getFieldValue("VIA_END") === "from" ? rel.from : rel.to) : undefined;
            return [...scopeAt(b)].filter(([, set]) => anchorSet === undefined || set === anchorSet).map(([index]) => index);
          }, choose),
          "VIA_ANCHOR"
        )
        .appendField(fixed([NONE, ...TRAVERSAL_DEPTHS], (d) => ({ "": "one step", one: "exactly one step", any: "any number of steps", any_or_self: "any steps, or itself" })[d] ?? d), "VIA_DEPTH")
        // Queue R19: the edge taken, so a value can read its own attributes; empty names none.
        .appendField(
          new Blockly.FieldTextInput("", (text: string) => (loading || text === "" || NAME.test(text) ? text : null)),
          "VIA_AS"
        );
      this.appendStatementInput("WHERE").setCheck("filter").appendField("only where");
      for (const name of ["VIA_END", "VIA_ANCHOR", "VIA_DEPTH", "VIA_AS"]) this.getField(name)!.setVisible(false);
      this.setPreviousStatement(true, "binding");
      this.setNextStatement(true, "binding");
      this.setColour(COLOUR.binding);
      this.setTooltip("An index ranging over a set: once for every entity of it, or only those a filter keeps");
    },
  };

  Blockly.Blocks.ir_filter = {
    init(this: B) {
      this.appendDummyInput()
        .appendField(
          dynamic((b) => {
            const set = b.getSurroundParent()?.getFieldValue("SET");
            return (catalogueOf(b.workspace).entityTypes.find((t) => t.name === set)?.attributes ?? []).map((a) => a.name);
          }, choose),
          "ATTR"
        )
        .appendField(fixed(FILTER_OPERATORS, (o) => ({ "!=": "≠", "<=": "≤", ">=": "≥", in: "is one of", notIn: "is none of" })[o] ?? o), "OP")
        .appendField(
          new Blockly.FieldTextInput('""', (text: string) => {
            if (loading) return text;
            try {
              JSON.parse(text);
              return text;
            } catch {
              return null;
            }
          }),
          "VALUE"
        );
      this.setPreviousStatement(true, "filter");
      this.setNextStatement(true, "filter");
      this.setColour(COLOUR.binding);
      this.setTooltip('A value as written in JSON: 3, "north", true, or a list ["a", "b"] for "is one of"');
    },
  };

  Blockly.Blocks.ir_goal_term = {
    init(this: B) {
      this.appendDummyInput()
        .appendField("goal term")
        .appendField(nameField("o_1", ["ir_goal_term"], "ID"), "ID")
        .appendField("weight")
        .appendField(numberText("1"), "WEIGHT");
      this.appendValueInput("EXPRESSION").setCheck("Number").appendField("of");
      this.setPreviousStatement(true, "goal_term");
      this.setNextStatement(true, "goal_term");
      this.setColour(COLOUR.goal);
    },
  };

  Blockly.Blocks.ir_const = {
    init(this: B) {
      this.appendDummyInput().appendField(numberText("0"), "VALUE");
      this.setOutput(true, "Number");
      this.setColour(COLOUR.constant);
    },
  };

  Blockly.Blocks.ir_var = referenceBlock("variables", "", COLOUR.variable);
  Blockly.Blocks.ir_par = referenceBlock("parameters", "", COLOUR.parameter);

  Blockly.Blocks.ir_attr = {
    init(this: B) {
      this.appendDummyInput()
        .appendField(
          dynamic((b) => {
            const set = scopeAt(b).get(b.getFieldValue("OF"));
            const edge = edgeOf(set);
            // An edge (queue R19) offers what its relationship type declares for its edges.
            const attributes = edge
              ? (catalogueOf(b.workspace).relationships.find((r) => r.name === edge.rel)?.attributes ?? [])
              : (catalogueOf(b.workspace).entityTypes.find((t) => t.name === set)?.attributes ?? []);
            return attributes.filter((a) => a.data_type === "integer" || a.data_type === "number").map((a) => a.name);
          }, choose),
          "NAME"
        )
        .appendField("of")
        .appendField(dynamic((b) => [...scopeAt(b).keys()], choose), "OF")
        .appendField(
          fixed([NONE, ...PATH_COMBINATIONS], (c) => ({ "": "(one value)", sum: "summed along the path", min: "least along the path", max: "most along the path", product: "multiplied along the path", count: "edges carrying it" })[c] ?? c),
          "ALONG"
        );
      this.getField("ALONG")!.setVisible(false);
      this.setOutput(true, "Number");
      this.setInputsInline(true);
      this.setColour(COLOUR.attribute);
      this.setTooltip("A number an entity carries, or an edge a via named -- along a path, combined as chosen");
    },
    // The path choice shows only where there is a path to combine along (or one is already chosen).
    onchange(this: B) {
      const field = this.getField("ALONG");
      if (!field) return;
      const wanted = Boolean(edgeOf(scopeAt(this).get(this.getFieldValue("OF")))?.path) || this.getFieldValue("ALONG") !== NONE;
      if (field.isVisible() !== wanted) {
        field.setVisible(wanted);
        rerender(this);
      }
    },
  };

  Blockly.Blocks.ir_sum = {
    init(this: B) {
      this.appendStatementInput("OVER").setCheck("binding").appendField("sum over");
      this.appendValueInput("BODY").setCheck("Number").appendField("of");
      this.setOutput(true, "Number");
      this.setColour(COLOUR.sum);
    },
  };

  Blockly.Blocks.ir_add = {
    init(this: B) {
      this.appendDummyInput("HEAD")
        .appendField("add")
        .appendField(
          fixed(
            Array.from({ length: MAX_ADD - 1 }, (_, i) => String(i + 2)),
            (n) => `${n} terms`,
            (n: string) => {
              this.setTerms!(Number(n));
              return n;
            }
          ),
          "COUNT"
        );
      this.setOutput(true, "Number");
      this.setInputsInline(true);
      this.setColour(COLOUR.operator);
      this.count = 0;
      this.setTerms!(2);
    },
    setTerms(this: B, n: number) {
      reshape(this, "count", Math.max(2, Math.min(MAX_ADD, n)), (i) => {
        const input = this.appendValueInput(`T${i}`).setCheck("Number");
        if (i > 0) input.appendField("+");
      }, "T");
    },
    saveExtraState(this: B) {
      return { count: this.count ?? 2 };
    },
    loadExtraState(this: B, state: { count: number }) {
      this.setTerms!(state.count);
      this.setFieldValue(String(state.count), "COUNT");
    },
  };

  Blockly.Blocks.ir_mul = {
    init(this: B) {
      this.appendValueInput("A").setCheck("Number");
      this.appendValueInput("B").setCheck("Number").appendField("×");
      this.setOutput(true, "Number");
      this.setInputsInline(true);
      this.setColour(COLOUR.operator);
    },
  };

  Blockly.Blocks.ir_when = {
    init(this: B) {
      const spec = (name: string) => declared(this.workspace).variables.get(name);
      this.appendDummyInput("HEAD").appendField(
        dynamic((b) => decisions(b, (v) => v.domain === "binary"), choose, (name: string) => {
          if (!loading) refSlots(this, spec(name)?.index.length ?? 0, (i) => spec(this.getFieldValue("VAR"))?.index[i], scopeAt, "IS_ROW");
          return name;
        }),
        "VAR"
      );
      this.appendDummyInput("IS_ROW")
        .appendField("is")
        .appendField(
          fixed(["1", "0"], (v) => (v === "1" ? "yes" : "no"), (v: string) => {
            if (!loading) this.isGiven = true;
            return v;
          }),
          "IS"
        );
      this.setInputsInline(true);
      this.setPreviousStatement(true, "when");
      this.setColour(COLOUR.binding);
      this.setTooltip("The rule holds only when this yes-or-no decision is yes (or no); otherwise it does not apply");
      this.arity = 0;
      this.isGiven = false;
    },
    saveExtraState(this: B) {
      return { arity: this.arity ?? 0, isGiven: this.isGiven ?? false };
    },
    loadExtraState(this: B, state: { arity: number; isGiven?: boolean }) {
      refSlots(this, state.arity, (i) => declared(this.workspace).variables.get(this.getFieldValue("VAR"))?.index[i], scopeAt, "IS_ROW");
      this.isGiven = !!state.isGiven;
    },
  };

  Blockly.Blocks.ir_no_overlap = schedulingBlock("no_overlap");
  Blockly.Blocks.ir_cumulative = schedulingBlock("cumulative");

  Blockly.Blocks.ir_connected = {
    init(this: B) {
      this.appendDummyInput()
        .appendField("rule")
        .appendField(nameField("c_1", RULE_KINDS, "ID"), "ID")
        .appendField("keeps each group in one piece");
      this.appendDummyInput().appendField("means").appendField(new Blockly.FieldTextInput(""), "NOTE");
      const seed = (set: string) => set.match(/[a-z]/)?.[0] ?? "i";
      const indexName = () => new Blockly.FieldTextInput("", (t: string) => (loading || NAME.test(t) ? t : null));
      this.appendDummyInput()
        .appendField("the decision")
        .appendField(
          dynamic(
            (b) => decisions(b, (v) => v.domain === "binary" && v.index.length === 2 && v.index[0] !== v.index[1]),
            choose,
            (name: string) => {
              const spec = declared(this.workspace).variables.get(name);
              if (!loading && spec && spec.index.length === 2) {
                // Choosing the decision decides the rest: its first set is the units, its second the groups.
                const [units, groups] = spec.index;
                const u = seed(units);
                const z = seed(groups) === u ? `${seed(groups)}2` : seed(groups);
                this.setFieldValue(units, "U_SET");
                this.setFieldValue(groups, "Z_SET");
                this.setFieldValue(u, "U_INDEX");
                this.setFieldValue(z, "Z_INDEX");
              }
              return name;
            }
          ),
          "VAR"
        )
        .appendField("puts each")
        .appendField(indexName(), "U_INDEX")
        .appendField("in")
        .appendField(dynamic((b) => declared(b.workspace).sets, choose), "U_SET")
        .appendField("in one")
        .appendField(indexName(), "Z_INDEX")
        .appendField("in")
        .appendField(dynamic((b) => declared(b.workspace).sets, choose), "Z_SET");
      this.appendDummyInput()
        .appendField("neighbours by")
        .appendField(
          dynamic((b) => {
            const units = b.getFieldValue("U_SET");
            return catalogueOf(b.workspace).relationships.filter((r) => r.from === units && r.to === units).map((r) => r.name);
          }, choose),
          "VIA"
        )
        .appendField(
          fixed(["forbidden", "allowed"], (e) => (e === "forbidden" ? "and no group empty" : "and a group may be empty"), (e: string) => {
            if (!loading) this.emptyGiven = true;
            return e;
          }),
          "EMPTY"
        );
      this.setPreviousStatement(true, "rule");
      this.setNextStatement(true, "rule");
      this.setColour(COLOUR.rule);
      this.setTooltip("Every group's units form one connected piece, where two units are neighbours by the relationship chosen");
      this.emptyGiven = false;
    },
    saveExtraState(this: B) {
      return { emptyGiven: this.emptyGiven ?? false };
    },
    loadExtraState(this: B, state: { emptyGiven?: boolean }) {
      this.emptyGiven = !!state.emptyGiven;
    },
  };

  Blockly.Blocks.ir_route = {
    init(this: B) {
      this.appendDummyInput()
        .appendField("rule")
        .appendField(nameField("c_1", RULE_KINDS, "ID"), "ID")
        .appendField("sends vehicles round every stop");
      this.appendDummyInput().appendField("means").appendField(new Blockly.FieldTextInput(""), "NOTE");
      const seed = (set: string) => set.match(/[a-z]/)?.[0] ?? "i";
      const indexName = () => new Blockly.FieldTextInput("", (t: string) => (loading || NAME.test(t) ? t : null));
      const text = () => new Blockly.FieldTextInput("", (t: string) => (loading || t === "" || NAME.test(t) ? t : null));
      this.appendDummyInput()
        .appendField("the decision")
        .appendField(
          dynamic(
            (b) => decisions(b, (v) => v.domain === "binary" && v.index.length === 3 && v.index[1] === v.index[2]),
            choose,
            (name: string) => {
              const spec = declared(this.workspace).variables.get(name);
              if (!loading && spec && spec.index.length === 3) {
                // Choosing the decision decides the rest: [vehicle, stop, next stop].
                const [vehicles, stops] = spec.index;
                const v = seed(vehicles);
                const i = seed(stops) === v ? `${seed(stops)}2` : seed(stops);
                this.setFieldValue(vehicles, "V_SET");
                this.setFieldValue(stops, "S_SET");
                this.setFieldValue(v, "V_INDEX");
                this.setFieldValue(i, "S_INDEX");
                this.setFieldValue(`${i}_next`, "TO_INDEX");
              }
              return name;
            }
          ),
          "VAR"
        )
        .appendField("takes each")
        .appendField(indexName(), "V_INDEX")
        .appendField("in")
        .appendField(dynamic((b) => declared(b.workspace).sets, choose), "V_SET")
        .appendField("from")
        .appendField(indexName(), "S_INDEX")
        .appendField("to")
        .appendField(indexName(), "TO_INDEX")
        .appendField("in")
        .appendField(dynamic((b) => declared(b.workspace).sets, choose), "S_SET");
      this.appendDummyInput()
        .appendField("starting and ending at")
        .appendField(new Blockly.FieldTextInput("depot", (t: string) => (loading || t !== "" ? t : null)), "DEPOT");
      this.appendDummyInput()
        .appendField("each stop's load")
        .appendField(text(), "DEMAND")
        .appendField("within each vehicle's")
        .appendField(text(), "CAPACITY")
        .appendField("(both blank: no loads)");
      this.setPreviousStatement(true, "rule");
      this.setNextStatement(true, "rule");
      this.setColour(COLOUR.rule);
      this.setTooltip("Every stop but the depot is visited once, each vehicle leaving the depot at most once and coming back; with loads named, no vehicle carries more than its capacity");
    },
  };

  Blockly.Blocks.ir_pwl = {
    init(this: B) {
      const spec = (name: string) => declared(this.workspace).variables.get(name);
      this.appendDummyInput("HEAD")
        .appendField("curve of")
        .appendField(
          dynamic((b) => decisions(b, (v) => v.domain !== "interval"), choose, (name: string) => {
            if (!loading) refSlots(this, spec(name)?.index.length ?? 0, (i) => spec(this.getFieldValue("VAR"))?.index[i], scopeAt, "COUNT_ROW");
            return name;
          }),
          "VAR"
        );
      this.appendDummyInput("COUNT_ROW")
        .appendField("through")
        .appendField(
          fixed(
            Array.from({ length: MAX_POINTS - 1 }, (_, i) => String(i + 2)),
            (n) => `${n} points`,
            (n: string) => {
              this.setPoints!(Number(n));
              return n;
            }
          ),
          "COUNT"
        );
      this.setOutput(true, "Number");
      this.setColour(COLOUR.sum);
      this.setTooltip("A curve through these points, straight between them, read at the decision's value: x rising from point to point");
      this.arity = 0;
      this.count = 0;
      this.setPoints!(2);
    },
    setPoints(this: B, n: number) {
      reshape(
        this,
        "count",
        Math.max(2, Math.min(MAX_POINTS, n)),
        (i) =>
          this.appendDummyInput(`P${i}`)
            .appendField(i === 0 ? "at" : "then")
            .appendField(numberText(String(i)), `X${i}`)
            .appendField("→")
            .appendField(numberText("0"), `Y${i}`),
        "P"
      );
    },
    saveExtraState(this: B) {
      return { arity: this.arity ?? 0, count: this.count ?? 2 };
    },
    loadExtraState(this: B, state: { arity: number; count: number }) {
      refSlots(this, state.arity, (i) => declared(this.workspace).variables.get(this.getFieldValue("VAR"))?.index[i], scopeAt, "COUNT_ROW");
      this.setPoints!(state.count);
      this.setFieldValue(String(state.count), "COUNT");
    },
  };

  Blockly.Blocks.ir_fn = {
    init(this: B) {
      this.appendValueInput("OF")
        .setCheck("Number")
        .appendField(fixed(Object.keys(FUNCTIONS), (n) => `${n} — ${FUNCTIONS[n]?.convexity ?? "?"}`), "NAME")
        .appendField("of");
      this.setOutput(true, "Number");
      this.setInputsInline(true);
      this.setColour(COLOUR.operator);
      this.setTooltip(
        Object.entries(FUNCTIONS)
          .map(([name, f]) => `${name}: ${f.text} (${f.convexity})`)
          .join("; ")
      );
    },
  };

  Blockly.Blocks.ir_opaque_declaration = opaqueBlock("declaration");
  Blockly.Blocks.ir_opaque_rule = opaqueBlock("rule");
  Blockly.Blocks.ir_opaque_term = opaqueBlock("term");
}

/** Rule-like blocks, whose ids share one namespace (constraint ids are unique). */
export const RULE_KINDS = ["ir_rule", "ir_opaque_rule", "ir_no_overlap", "ir_cumulative", "ir_connected", "ir_route"] as const;

export const IR_BLOCK_TYPES = [
  "ir_model", "ir_set", "ir_variable", "ir_parameter", "ir_rule", "ir_binding", "ir_filter", "ir_goal_term",
  "ir_const", "ir_var", "ir_par", "ir_attr", "ir_sum", "ir_add", "ir_mul",
  "ir_when", "ir_no_overlap", "ir_cumulative", "ir_connected", "ir_route", "ir_pwl", "ir_fn",
  "ir_opaque_declaration", "ir_opaque_rule", "ir_opaque_term",
] as const;

/**
 * The toolbox, by category (spec §3). A block is offered only when the
 * domain has something to fill it with: no data block without a parameter,
 * no set without an entity type, no attribute without a numeric attribute.
 */
export function toolboxFor(catalogue: import("./catalogue").BlockCatalogue) {
  const hasTypes = catalogue.entityTypes.length > 0;
  const hasParameters = catalogue.parameters.length > 0;
  const hasNumbers = catalogue.entityTypes.some((t) => t.attributes.some((a) => a.data_type === "integer" || a.data_type === "number"));
  const hasAttributes = catalogue.entityTypes.some((t) => t.attributes.length > 0);
  const hasSelfRelationship = catalogue.relationships.some((r) => r.from === r.to);
  const blocks = (types: (string | false)[]) => types.filter((t): t is string => !!t).map((type) => ({ kind: "block", type }));
  return {
    kind: "categoryToolbox",
    contents: [
      { kind: "category", name: "Declare", colour: "#0d9488", contents: blocks([hasTypes && "ir_set", "ir_variable", hasParameters && "ir_parameter"]) },
      {
        kind: "category",
        name: "Rules",
        colour: "#334155",
        contents: blocks(["ir_rule", hasTypes && "ir_binding", hasAttributes && "ir_filter", "ir_when"]),
      },
      {
        kind: "category",
        name: "Scheduling and areas",
        colour: "#0f766e",
        contents: blocks(["ir_no_overlap", "ir_cumulative", hasSelfRelationship && "ir_connected", "ir_route"]),
      },
      { kind: "category", name: "Goal", colour: "#16a34a", contents: blocks(["ir_goal_term"]) },
      { kind: "category", name: "Values", colour: "#3b82f6", contents: blocks(["ir_const", "ir_var", hasParameters && "ir_par", hasNumbers && "ir_attr"]) },
      { kind: "category", name: "Arithmetic", colour: "#7c3aed", contents: blocks(["ir_sum", "ir_add", "ir_mul", "ir_pwl", "ir_fn"]) },
    ],
  };
}
