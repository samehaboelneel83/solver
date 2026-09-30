import { createContext, useContext, useEffect, useMemo, useRef, useState } from "react";
import {
  QueryBuilder,
  Rule as DefaultRule,
  type ActionProps,
  type FullField,
  type RuleGroupType,
  type RuleProps,
  type ValueEditorProps,
  type ValueSelectorProps,
} from "react-querybuilder";
import { parseAttrValue } from "../components/attrTypes";
import {
  emptyDocument,
  toDocument,
  toQuery,
  type ExpressionDocument,
} from "./document";
import { defaultFieldId, defaultOperatorFor, defaultRule, defaultValueFor } from "./defaults";
import { ListPlus, Plus } from "lucide-react";
import { groupFields, type FieldCatalogue } from "./fields";
import { EXPRESSION_OPERATORS, operatorsForField } from "./operators";
import { validateExpression } from "./validate";

/**
 * The expression builder: react-querybuilder, wired to this app's field
 * catalogue and operator table, and dressed in this app's own controls.
 *
 * The controls are ours rather than the library's because the library's
 * defaults give every control a `title` and nothing else: five rules
 * produce five selects all called "Field", and the remove button is a bare
 * "⨯" glyph with no CSS behind it. axe has been 0 on every state of this
 * app so far (Tasks 10-14b), and the audit's H-9 target-size finding is
 * open, so the defaults are replaced rather than accepted:
 *
 * - every select is named for the condition it belongs to ("Field for
 *   condition 2.1"), so a screen reader user can tell them apart;
 * - every add/remove button has a name beyond its glyph, and a 28px
 *   minimum box (WCAG 2.2 target size is 24px);
 * - the value editor is typed, so an integer field's value reaches the
 *   document as a NUMBER. What is typed but not yet a number is passed
 *   through as text, and the validator says why -- the alternative is a
 *   box showing "1x" over a filter that quietly used 1.
 *
 * Nothing here decides what is valid; `validate.ts` does, once, for this
 * and for Task 14d.
 */

type CatalogueContext = { catalogue: FieldCatalogue; invalidPaths: ReadonlySet<string>; query: RuleGroupType | null; bindingFilter: boolean };
const BuilderContext = createContext<CatalogueContext>({
  catalogue: { fields: [], get: () => undefined },
  invalidPaths: new Set(),
  query: null,
  bindingFilter: false,
});

/** The children of the group at `path` in `query` ([] = the root). */
function childrenAt(query: RuleGroupType | null, path: number[]): RuleGroupType["rules"] {
  let group: RuleGroupType | null = query;
  for (const step of path) {
    const next: unknown = group?.rules[step];
    group = next && typeof next === "object" && "rules" in next ? (next as RuleGroupType) : null;
  }
  return group?.rules ?? [];
}

const pathKey = (path: number[]) => path.join(".");
/** A rule's position as a person would say it: `[1, 0]` is "2.1". */
const pathLabel = (path: number[]) => (path.length === 0 ? "1" : path.map((i) => i + 1).join("."));

const ACTION_CLASS =
  "rounded-md border border-slate-300 px-2 py-1 text-xs text-slate-700 hover:bg-slate-100";
// Inline rather than a utility class so the size is asserted, not assumed:
// jsdom reports inline styles, so `ExpressionBuilder.test.tsx` can check it.
const ACTION_SIZE = { minWidth: 28, minHeight: 28 } as const;
const SELECT_CLASS = "rounded-md border border-slate-300 px-2 py-1 text-xs";

// --- typed value editors ----------------------------------------------------

/** Re-exported: it moved to `defaults.ts`, beside `defaultFieldId` and
 * `isUntouchedRule`, so that "what a new rule is" has exactly one
 * definition and the filter layer can compare against it without importing
 * a .tsx module. */
export { defaultValueFor } from "./defaults";

function displayString(value: unknown): string {
  if (value === null || value === undefined) return "";
  return typeof value === "string" ? value : String(value);
}

/**
 * A numeric box that keeps what the user typed.
 *
 * Emitting `Number(draft)` alone is not enough: `Number("1.")` is 1, so a
 * controlled input rendered from the value would erase the decimal point
 * the moment it was typed. The draft is re-synced from the outside only
 * when the incoming value is not what the draft already means.
 */
function NumericEditor({
  value,
  dataType,
  label,
  ariaLabel,
  onChange,
}: {
  value: unknown;
  dataType: "integer" | "number";
  label: string;
  ariaLabel: string;
  onChange: (value: unknown) => void;
}) {
  const [draft, setDraft] = useState(() => displayString(value));

  const meaning = (text: string): unknown => {
    const parsed = parseAttrValue(dataType, text, [], label);
    return parsed.ok && parsed.value !== null ? parsed.value : text;
  };

  useEffect(() => {
    if (meaning(draft) !== value) setDraft(displayString(value));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  return (
    <input
      type="text"
      inputMode={dataType === "integer" ? "numeric" : "decimal"}
      data-testid="expression-value"
      aria-label={ariaLabel}
      className={SELECT_CLASS}
      value={draft}
      onChange={(e) => {
        setDraft(e.target.value);
        onChange(meaning(e.target.value));
      }}
    />
  );
}

function ExpressionValueEditor(props: ValueEditorProps) {
  const { catalogue } = useContext(BuilderContext);
  const field = catalogue.get(props.field);
  const arity = EXPRESSION_OPERATORS[props.operator]?.arity;
  // "is empty" takes no value at all.
  if (!field || arity === "unary") return null;

  const name = `Value for condition ${pathLabel(props.path)}`;
  const handle = (value: unknown) => props.handleOnChange(value);

  if (arity === "list") {
    const chosen = Array.isArray(props.value) ? (props.value as unknown[]) : [];
    return (
      <div
        role="group"
        aria-label={name}
        data-testid="expression-value"
        className="flex flex-wrap items-center gap-2 text-xs"
      >
        {(field.enumValues ?? []).map((option) => (
          <label key={option} className="flex items-center gap-1">
            <input
              type="checkbox"
              checked={chosen.includes(option)}
              onChange={() =>
                handle(
                  chosen.includes(option)
                    ? chosen.filter((v) => v !== option)
                    : [...chosen, option]
                )
              }
            />
            {option}
          </label>
        ))}
      </div>
    );
  }

  switch (field.dataType) {
    case "boolean":
      return (
        <select
          data-testid="expression-value"
          aria-label={name}
          className={SELECT_CLASS}
          value={props.value === true ? "true" : "false"}
          onChange={(e) => handle(e.target.value === "true")}
        >
          <option value="true">True</option>
          <option value="false">False</option>
        </select>
      );
    case "enum":
      return (
        <select
          data-testid="expression-value"
          aria-label={name}
          className={SELECT_CLASS}
          value={displayString(props.value)}
          onChange={(e) => handle(e.target.value)}
        >
          {(field.enumValues ?? []).map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      );
    case "integer":
    case "number":
      return (
        <NumericEditor
          key={`${pathKey(props.path)}:${props.field}`}
          value={props.value}
          dataType={field.dataType}
          label={field.label}
          ariaLabel={name}
          onChange={handle}
        />
      );
    case "date":
    case "time":
      return (
        <input
          type={field.dataType}
          data-testid="expression-value"
          aria-label={name}
          className={SELECT_CLASS}
          value={displayString(props.value)}
          onChange={(e) => handle(e.target.value)}
        />
      );
    default:
      return (
        <input
          type="text"
          data-testid="expression-value"
          aria-label={name}
          className={SELECT_CLASS}
          value={displayString(props.value)}
          onChange={(e) => handle(e.target.value)}
        />
      );
  }
}

// --- selectors --------------------------------------------------------------

function FieldSelector(props: ValueSelectorProps) {
  const { catalogue } = useContext(BuilderContext);
  const groups = useMemo(() => groupFields(catalogue), [catalogue]);
  return (
    <select
      data-testid="expression-field"
      aria-label={`Field for condition ${pathLabel(props.path)}`}
      className={SELECT_CLASS}
      value={props.value ?? ""}
      onChange={(e) => props.handleOnChange(e.target.value)}
    >
      {groups.map((group) => (
        <optgroup key={group.group} label={group.group}>
          {group.fields.map((field) => (
            <option key={field.id} value={field.id}>
              {field.label}
            </option>
          ))}
        </optgroup>
      ))}
    </select>
  );
}

type SelectorOption = { name?: string; value?: string; label?: string };

function flatOptions(options: unknown): SelectorOption[] {
  return Array.isArray(options) ? (options as SelectorOption[]) : [];
}

function OperatorSelector(props: ValueSelectorProps) {
  return (
    <select
      data-testid="expression-operator"
      aria-label={`Comparison for condition ${pathLabel(props.path)}`}
      className={SELECT_CLASS}
      value={props.value ?? ""}
      onChange={(e) => props.handleOnChange(e.target.value)}
    >
      {flatOptions(props.options).map((option) => {
        const name = option.name ?? option.value ?? "";
        return (
          <option key={name} value={name}>
            {option.label ?? name}
          </option>
        );
      })}
    </select>
  );
}

function CombinatorSelector(props: ValueSelectorProps) {
  // A binding's filter joins its conditions with "and", and a group directly
  // under it with "or": each says so rather than offering a choice it would refuse.
  // Joiners sit between rules, at the path of the rule after them: one deep
  // is the top level, two deep inside a group.
  if (useContext(BuilderContext).bindingFilter) {
    return <span data-testid="expression-combinator" className="text-xs text-slate-600">{props.path.length <= 1 ? "and" : "or"}</span>;
  }
  return (
    <select
      data-testid="expression-combinator"
      aria-label={
        props.path.length === 0
          ? "How the conditions in this filter are joined"
          : `How the conditions in group ${pathLabel(props.path)} are joined`
      }
      className={SELECT_CLASS}
      value={props.value ?? "and"}
      onChange={(e) => props.handleOnChange(e.target.value)}
    >
      <option value="and">and</option>
      <option value="or">or</option>
    </select>
  );
}

// --- actions ----------------------------------------------------------------

function action(testID: string, text: string, describe: (path: number[]) => string, headerOnly = false) {
  return function Action(props: ActionProps) {
    // A group's adds sit beside its last condition (see InvalidAwareRule).
    // The header keeps them only where there is no such row: an empty group,
    // or one that ends in a sub-group.
    if (headerOnly) {
      const children = (props.ruleOrGroup as RuleGroupType | undefined)?.rules ?? [];
      const last = children[children.length - 1];
      if (last && typeof last === "object" && !("rules" in last)) return null;
    }
    return (
      <button
        type="button"
        data-testid={testID}
        aria-label={describe(props.path)}
        className={ACTION_CLASS}
        style={ACTION_SIZE}
        disabled={props.disabled}
        onClick={(e) => props.handleOnClick(e)}
      >
        {text}
      </button>
    );
  };
}

const AddRule = action("expression-add-rule", "+ Condition", (path) =>
  path.length === 0 ? "Add a condition" : `Add a condition to group ${pathLabel(path)}`
, true);
const AddGroupButton = action("expression-add-group", "+ Group", (path) =>
  path.length === 0 ? "Add a group of conditions" : `Add a group inside group ${pathLabel(path)}`
, true);
/** A binding's filter has groups only at its top level (see `bindingFilter`). */
function AddGroup(props: ActionProps) {
  return useContext(BuilderContext).bindingFilter && props.path.length > 0 ? null : <AddGroupButton {...props} />;
}

const ICON_CLASS =
  "inline-flex items-center justify-center rounded-md border border-slate-300 text-slate-600 hover:border-slate-400 hover:bg-slate-50 hover:text-slate-900 disabled:opacity-50";
const RemoveRule = action("expression-remove-rule", "Remove", (path) => `Remove condition ${pathLabel(path)}`);
const RemoveGroup = action("expression-remove-group", "Remove group", (path) => `Remove group ${pathLabel(path)}`);

/** The default rule, wrapped so the row can say whether the validator
 * objected to it. */
function InvalidAwareRule(props: RuleProps) {
  const { invalidPaths, catalogue, query, bindingFilter } = useContext(BuilderContext);
  const invalid = invalidPaths.has(pathKey(props.path));
  const parent = props.path.slice(0, -1);
  const isLast = props.path[props.path.length - 1] === childrenAt(query, parent).length - 1;
  const where = parent.length === 0 ? "" : ` to group ${pathLabel(parent)}`;
  return (
    <div
      data-testid="expression-rule"
      data-invalid={invalid ? "true" : "false"}
      className={`flex flex-wrap items-center gap-2 ${invalid ? "rounded-md border border-red-300 bg-red-50 p-1" : ""}`}
    >
      <DefaultRule {...props} />
      {isLast && (
        <span className="inline-flex items-center gap-1">
          <button
            type="button"
            data-testid="expression-add-rule"
            aria-label={`Add a condition${where}`}
            title="Add a condition"
            className={ICON_CLASS}
            style={ACTION_SIZE}
            disabled={props.disabled}
            onClick={() => {
              const rule = defaultRule(catalogue);
              if (rule) props.actions.onRuleAdd(rule as never, parent);
            }}
          >
            <Plus size={14} aria-hidden="true" />
          </button>
          {(!bindingFilter || parent.length === 0) && <button
            type="button"
            data-testid="expression-add-group"
            aria-label={parent.length === 0 ? "Add a group of conditions" : `Add a group inside group ${pathLabel(parent)}`}
            title="Add a group of conditions"
            className={ICON_CLASS}
            style={ACTION_SIZE}
            disabled={props.disabled}
            onClick={() => props.actions.onGroupAdd({ combinator: bindingFilter ? "or" : "and", rules: [] } as never, parent)}
          >
            <ListPlus size={14} aria-hidden="true" />
          </button>}
        </span>
      )}
    </div>
  );
}

const CONTROL_ELEMENTS = {
  fieldSelector: FieldSelector,
  operatorSelector: OperatorSelector,
  combinatorSelector: CombinatorSelector,
  valueEditor: ExpressionValueEditor,
  addRuleAction: AddRule,
  addGroupAction: AddGroup,
  removeRuleAction: RemoveRule,
  removeGroupAction: RemoveGroup,
  rule: InvalidAwareRule,
} as const;

const CONTROL_CLASSNAMES = {
  queryBuilder: "text-xs",
  ruleGroup: "rounded-md",
  header: "flex flex-wrap items-center gap-2",
  body: "mt-2 flex flex-col gap-2 border-l-2 border-slate-200 pl-2",
  rule: "flex flex-wrap items-center gap-2",
};

export type ExpressionBuilderProps = {
  catalogue: FieldCatalogue;
  value: ExpressionDocument | null;
  onChange: (document: ExpressionDocument) => void;
  /**
   * Problems this component did not find -- in practice a server refusal
   * of a document `validate.ts` accepted (Task 14d). They are rendered and
   * highlighted exactly like its own, because to the person reading the
   * screen there is no difference between "this condition is wrong" and
   * "the server says this condition is wrong", and a second box in a
   * second place would be the only thing that told them apart.
   */
  extraProblems?: readonly { path: number[]; message: string }[];
  /**
   * Names this builder. react-querybuilder renders its own `role="form"`
   * landmark and offers no prop to label it, so two builders on one page are
   * two indistinguishable landmarks (`landmark-unique`). One is fine --
   * which is why this was not needed until the model editor put a filter on
   * every binding. The label is applied to both the group wrapper and, by
   * effect, the library's form.
   */
  label?: string;
  /**
   * A model's binding filter: conditions joined by "and", and groups directly
   * under them joined by "or" -- "(A or B) and C" -- one level deep, which is
   * all a binding's `where` says. Offering more (a group in a group, an
   * "and" group) only led to a refusal after it was built.
   */
  bindingFilter?: boolean;
};

export default function ExpressionBuilder({
  catalogue,
  value,
  onChange,
  extraProblems,
  label,
  bindingFilter = false,
}: ExpressionBuilderProps) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  // react-querybuilder gives its root `role="form"`, which is a **landmark**.
  // A filter is not a form -- it is a control inside one -- and several on a
  // page are several landmarks competing for a screen-reader user's landmark
  // list (axe `landmark-unique`, seen with three filters in the model
  // editor). Naming them was not enough, so the role is corrected to `group`,
  // which is what it actually is. The library offers no prop for either.
  //
  // No dependency list on purpose: the library re-renders its own tree as the
  // query changes, and the corrected role must survive that.
  useEffect(() => {
    // Only the role: the wrapper above already carries the name, and naming
    // both would put two identically-named groups in the tree.
    rootRef.current
      ?.querySelectorAll('[role="form"]')
      .forEach((node) => node.setAttribute("role", "group"));
  });
  const query = useMemo(() => toQuery(value), [value]);
  const validation = useMemo(
    () => validateExpression(value ?? emptyDocument(), catalogue),
    [value, catalogue]
  );
  const result = useMemo(
    () => ({
      ...validation,
      problems: [
        ...validation.problems,
        ...(extraProblems ?? []).map((problem) => ({
          path: problem.path,
          code: "malformed" as const,
          message: problem.message,
        })),
      ],
    }),
    [validation, extraProblems]
  );
  const context = useMemo<CatalogueContext>(
    () => ({ catalogue, invalidPaths: new Set(result.problems.map((p) => pathKey(p.path))), query, bindingFilter }),
    [catalogue, result, query, bindingFilter]
  );

  const fields = useMemo(
    () =>
      groupFields(catalogue).map((group) => ({
        label: group.group,
        options: group.fields.map((field) => ({ name: field.id, label: field.label })),
      })),
    [catalogue]
  );

  return (
    <BuilderContext.Provider value={context}>
      <div
        ref={rootRef}
        data-testid="expression-builder"
        role="group"
        aria-label={label ?? "Filter conditions"}
      >
        <QueryBuilder
          query={query}
          onQueryChange={(next: RuleGroupType) => onChange(toDocument(next))}
          // Report edits only. By default the library also reports the query
          // once on mount, a tick after the render it came from; a parent
          // that rebuilds its value from that render's props then writes a
          // stale copy over whatever was changed in between (in the model
          // editor, a rule's strength snapped back). Nothing here needs the
          // mount report: the document shown is the one we passed in.
          enableMountQueryChange={false}
          fields={fields}
          // `defaults.ts`, not `catalogue.fields[0]`: that was the
          // alphabetically first field including the generated calls, i.e.
          // `abs(<some attribute>)`. Both of these and `getDefaultValue`
          // come from there, so the rule "+ Condition" builds is the same
          // one `isUntouchedRule` compares against.
          getDefaultField={defaultFieldId(catalogue)}
          getDefaultOperator={(fieldName: string) => defaultOperatorFor(catalogue.get(fieldName))}
          getDefaultValue={(rule) => defaultValueFor(catalogue.get(rule.field), rule.operator)}
          getOperators={(fieldName: string) => {
            const field = catalogue.get(fieldName);
            return field ? operatorsForField(field).map((o) => ({ name: o.name, label: o.label })) : null;
          }}
          // A binding filter's groups say "or", and sit only at its top level.
          onAddGroup={bindingFilter ? (group: RuleGroupType, parentPath: number[]) => (parentPath.length === 0 ? { ...group, combinator: "or" } : false) : undefined}
          controlElements={CONTROL_ELEMENTS}
          controlClassnames={CONTROL_CLASSNAMES}
          // No `listsAsArrays`: the library's flag only governs ITS value
          // editors, and ours emits a real JSON array itself (see the
          // `list` branch of ExpressionValueEditor). Removing the flag
          // changed nothing any test could see, so it is not shipped --
          // configuration no test can distinguish is configuration nobody
          // can rely on.
          resetOnFieldChange
          // "and"/"or" between conditions, not ahead of the first: one
          // condition joins nothing.
          showCombinatorsBetweenRules
        />
        {/* `role="alert"` goes on a WRAPPER, never on the <ul> itself: the
            role overrides the element's own list role, which orphans every
            <li> inside it. axe reported exactly that (`listitem`,
            `aria-allowed-role`) on the first browser run. */}
        {result.problems.length > 0 && (
          <div
            role="alert"
            data-testid="expression-problems"
            className="mt-2 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-700"
          >
            <ul className="list-disc pl-4">
              {result.problems.map((problem, index) => (
                <li key={`${pathKey(problem.path)}-${problem.code}-${index}`}>
                  Condition {pathLabel(problem.path)}: {problem.message}
                </li>
              ))}
            </ul>
          </div>
        )}
        {result.warnings.length > 0 && (
          <div
            data-testid="expression-warnings"
            className="mt-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800"
          >
            <ul className="list-disc pl-4">
              {result.warnings.map((warning, index) => (
                <li key={`${pathKey(warning.path)}-${index}`}>{warning.message}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </BuilderContext.Provider>
  );
}

export type { FullField };
