import CoverageRecipeForm from "../model/CoverageRecipeForm";
import { exampleWords } from "../lib/examples";
import EmptyRanges from "../components/EmptyRanges";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import OfflineNotice from "../components/OfflineNotice";
import Skeleton from "../components/Skeleton";
import { INPUT_CLASS } from "../components/attrTypes";
import { useToast } from "../components/ToastProvider";
import { formatApiError, isStaleRecordError } from "../api/errors";
import { useCapabilities } from "../hooks/useCapability";
import {
  useApplyTemplate,
  useCreateVersion,
  solveProblem,
  useClassify,
  useCreateAttribute,
  useCreateEntityType,
  useCreateParameter,
  useEntityTypes,
  useParameters,
  useRelationshipTypes,
  useTemplates,
  useVersion,
  useVersions,
  type ApplyTemplateResult,
  type Id,
} from "../api/v1";
import { isName, RELATIONS, SENSES, SEVERITIES } from "../ir/contract";
import WhenEditor from "../model/WhenEditor";
import ConnectedEditor from "../model/ConnectedEditor";
import RouteEditor from "../model/RouteEditor";
import SchedulingEditor, { newSchedulingRule } from "../model/SchedulingEditor";
import TermBuilder, { BindingsEditor } from "../model/TermBuilder";
import DeclarationsEditor from "../model/DeclarationsEditor";
import GuidedCreation from "../model/GuidedCreation";
import { applyGuidedCommand } from "../model/guidedCommands";
import DraftBar, { DraftConflict } from "../model/DraftBar";
import BlocksEditor from "../components/BlocksEditor";
import type { ModelPart } from "../lib/modelGraph";
import ModelGraphPreview from "../components/ModelGraphPreview";
import { stableKeys } from "../model/ruleKeys";
import { applyPattern } from "../model/patterns";
import ModelReview from "../model/ModelReview";
import { catalogueFrom } from "../lib/irBlocks/catalogue";
import { EMPTY_MODEL, formDraftOf, publishable, withFormDraft, type FormDraft } from "../model/draftIr";
import LegacyDraftRecovery from "../model/LegacyDraftRecovery";
import EquationField, { chipsFor } from "../model/EquationField";
import { GoalDiagram, RuleDiagram } from "../model/EquationDiagram";
import { GoalBlocks, GoalSentence, RuleBlocks, RuleSentence } from "../model/NestedBlocks";
import { useCardView, useEquationView, viewAt, ViewToggle, type EquationView } from "../model/ViewToggle";
import { EditorLevelContext, useEditorLevel } from "../model/editorLevel";
import AddMenu, { AddChoice } from "../components/AddMenu";
import { checkGoal, checkRule, explain } from "../model/blockCheck";
import { checkDeclaration } from "../model/declarationViews";
import { StepNav, Stepper, ThingsToFix, useStepByStep, type Fix, type Step, type StepStatus } from "../model/ModelSteps";
import { ruleSentence, termSentence } from "../model/ruleSentence";
import { GOAL_SHAPES, goalFromShape, RULE_SHAPES, ruleFromShape, type GoalShape, type RuleShape } from "../model/shapes";
import { goalEquation, parseGoal, parseRule, ruleEquation, withEquation } from "../model/formula";
import ProblemPicker from "../components/ProblemPicker";
import LoadFailure from "../components/LoadFailure";
import { useDomainProblem } from "../hooks/useDomainProblem";
import ServerDraftSync, { saveToServer } from "../model/ServerDraftSync";
import { discardServerDraft, publishServerDraft } from "../api/drafts";
import { clearDraft, readDraft, readServerLink, updateDraftIr, useModelDraft, writeDraft, type DraftBase } from "../model/draftStore";
import { useDraftRefusal } from "../model/useDraftRefusal";
import { TreeItem, TreeView } from "../components/ui/tree-view";
import {
  parameterOptions,
} from "../model/declarations";
import {
  describeSchedule,
  newConnectedRule,
  newRouteRule,
  routeChoices,
  describeTerm,
  describeWhen,
  freeNumberedId,
  nextBinding,
  type Binding,
  type Constraint,
  type ModelContext,
  type ObjectiveTerm,
  type Term,
} from "../model/terms";
import { useDomain } from "../hooks/useDomain";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { parseRouteId } from "../lib/routeId";
import { ApiError } from "../api/client";
import ContextMismatch from "../components/ContextMismatch";
import ProblemReadiness from "../components/ProblemReadiness";

/**
 * Writing a model: its constraints and its objective.
 *
 * **Where react-querybuilder sits.** Every binding's filter — "only the
 * weekend days", "only senior employees" — is edited with it, because a
 * filter is a boolean condition tree and that is what the library builds.
 * The arithmetic around the filters (`8 * sum(assign) <= hours_per_week`)
 * is not a condition tree, so `TermBuilder` handles that; `terms.ts`
 * explains why in full.
 *
 * **Versions are immutable, so this publishes rather than saves.** Editing
 * starts from the latest version's model and writes a new one, which is
 * what keeps a run's answer attributable to an exact model for ever. The
 * server validates against the IR contract and refuses with the offending
 * path, so a model this screen builds wrongly is named, not stored.
 *
 * Sets, parameters and variables are shown read-only: they are declared by
 * the domain and by the previous version, and changing them is a different
 * job from writing a rule.
 */


type Draft = FormDraft;

export default function ModelEditor() {
  useDocumentTitle("Model editor");
  const { domainId } = useDomain();

  return (
    <div className="max-w-5xl">
      <h1 className="mb-1 text-lg font-semibold text-slate-900">Model editor</h1>
      <p className="mb-4 text-sm text-slate-500">
        The rules a solver must respect, and what it should make as small or as large as it can.
        Publishing writes a new version: the old one keeps working, and every run stays attributable
        to the exact model that produced it.
      </p>
      {domainId === null ? (
        <div className="rounded-md border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
          <p>Choose a domain in the sidebar&rsquo;s Domain selector (under Menu on a small screen).</p>
        </div>
      ) : (
        <ForDomain domainId={domainId} />
      )}
    </div>
  );
}

function ForDomain({ domainId }: { domainId: Id }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const route = useParams();
  const chooseProblem = (id: string) => route.problemId
    ? navigate(`/domains/${domainId}/problems/${id}/model`)
    : setSearchParams({ problem: id }, { replace: true });
  const found = useDomainProblem(domainId, route.problemId ?? searchParams.get("problem"));
  if (found.state === "mismatch") {
    return <ContextMismatch title="This problem is not available here"
      detail="The requested problem is missing, invalid, or belongs to another domain. Nothing was substituted."
      parentHref={`/domains/${domainId}/problems`} parentLabel="Open problems in this domain" />;
  }
  if (found.state === "failed") return <LoadFailure subject={found.subject} error={found.error} retry={found.retry} />;
  if (found.state === "offline") return <OfflineNotice subject="The problem" />;
  if (found.state === "loading") return <Skeleton rows={3} cols={4} />;

  if (found.state === "empty") {
    return (
      <Note>
        <p>This domain has no problems yet, and a model belongs to one.</p>
        <p className="mt-1">
          Create one on the{" "}
          <Link to="/public/problem" className="inline-block rounded py-1 text-blue-600 underline">
            Problems page
          </Link>
          , or start from a template. Missing types are created from its seed.
        </p>
        <StartFromTemplates
          domainId={domainId}
          onApplied={(result) => chooseProblem(String(result.problem_id))}
        />
      </Note>
    );
  }

  const { problem, firstPage, total } = found;
  const problemId = Number(problem.id);

  return (
    <>
      <LegacyDraftRecovery problemId={problemId} />
      <ProblemReadiness problemId={problemId} />
      {/* Inside a problem's own pages the problem is already chosen: a switch here would
          leave with a draft in hand (UX audit B-2). The sidebar's "Other problems" still goes. */}
      {!route.problemId && (
        <ProblemPicker
          domainId={domainId}
          current={problem}
          firstPage={firstPage}
          total={total}
          onChoose={chooseProblem}
        />
      )}
      <Editor key={problemId} problemId={problemId} domainId={domainId} />
    </>
  );
}

function Editor({ problemId, domainId }: { problemId: Id; domainId: Id }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const versions = useVersions(problemId, { limit: 50, offset: 0 });
  const rawVersion = searchParams.get("version");
  const requestedVersion = parseRouteId(rawVersion);
  const listedVersions = versions.data?.items ?? [];
  const baseId = requestedVersion ?? (rawVersion === null ? listedVersions[0]?.id ?? null : null);
  const latest = useVersion(baseId);
  const validVersion = latest.data?.problem_id === Number(problemId) && latest.data?.id === baseId;
  const base = validVersion ? latest.data : listedVersions.find(row => row.id === baseId);
  const versionItems = validVersion && !listedVersions.some(row => row.id === baseId)
    ? [...listedVersions, latest.data!] : listedVersions;
  const versionMissing = (rawVersion !== null && requestedVersion === null)
    || (latest.data !== undefined && !validVersion)
    || (latest.error instanceof ApiError && latest.error.status === 404);
  const [scratch, setScratch] = useState(false);
  const entityTypes = useEntityTypes(domainId, { limit: 500, offset: 0 });
  const relationshipTypes = useRelationshipTypes(domainId, { limit: 500, offset: 0 });
  const parameters = useParameters(domainId, { limit: 500, offset: 0 });
  const createVersion = useCreateVersion();
  const queryClient = useQueryClient();
  const toast = useToast();
  // A planner may read a model but not change it (operator trial F22): the
  // editors are shown disabled rather than inviting edits Publish would refuse.
  const { can, known } = useCapabilities();
  const canEdit = !known || can("model.publish");
  // Making new record types, numbers on them and data changes the domain, which is its own capability.
  const canShape = canEdit && (!known || can("domain.edit"));
  const createType = useCreateEntityType();
  const createAttribute = useCreateAttribute();
  const createParameterDef = useCreateParameter();

  const [failure, setFailure] = useState<string | null>(null);
  // Publishing never moves a scenario (operator trial F29): say so, and where to move them.
  const [justPublished, setJustPublished] = useState<number | null>(null);
  const [solvingNow, setSolvingNow] = useState(false);
  const navigate = useNavigate();
  const [storedView, setEquationView] = useEquationView();
  // Simple or Expert (editorLevel.ts): Simple shows the plain views, one card open at a time, one “+ Add” per section.
  const [level] = useEditorLevel();
  const simple = level === "simple";
  const equationView = viewAt(storedView, simple);
  // Step by step at Simple (ModelSteps.tsx): which step is on screen, or all of them.
  const [simpleSteps, setSimpleSteps] = useStepByStep();
  // Expert may go step by step too (user trial: the whole editor on one page is a long scroll);
  // off unless asked, so the page an expert knows stays as it was.
  const [expertSteps, setExpertSteps] = useState(false);
  const [step, setStep] = useState<Step>("sets");
  // “Go to it” from the list of things to fix: which card to open; `seq` changes each time.
  const [opening, setOpening] = useState<{ kind: "rule" | "goal" | "variable" | "parameter"; id: string; seq: number } | null>(null);
  // One key per publication attempt, kept across retries (see publishFromServer).
  const publishKey = useRef<{ key: string; revision: number } | null>(null);
  const [serverPublishing, setServerPublishing] = useState(false);
  // Forms | Blocks (Blockly edit mode spec §6), in the URL so a reload keeps it.
  const requestedView = searchParams.get("view");
  const asked = requestedView === "blocks" || requestedView === "graph" || requestedView === "ir" || requestedView === "review" ? requestedView : "forms";
  // Simple builds in the forms and checks in Review; the other tabs are Expert's.
  const view = simple && asked !== "review" ? "forms" : asked;
  const setView = (next: "forms" | "blocks" | "graph" | "ir" | "review") =>
    setSearchParams(
      (current) => {
        const params = new URLSearchParams(current);
        if (next !== "forms") params.set("view", next);
        else params.delete("view");
        return params;
      },
      { replace: true }
    );
  // Blocks dropped beside the model rather than in it: not part of it, so
  // Publish waits until they are placed or deleted.
  const [outside, setOutside] = useState(0);
  const [graphFocus, setGraphFocus] = useState<{ part: ModelPart; id: string; ruleKey?: string } | null>(null);
  const focusedPart = view === "graph" ? graphFocus?.part : undefined;

  const ir = (scratch ? EMPTY_MODEL : validVersion ? latest.data?.ir : undefined) as Record<string, unknown> | undefined;
  const seedKey: DraftBase | null = scratch ? "scratch" : baseId === null ? null : `version-${Number(baseId)}`;

  // The shared draft (Blockly edit mode spec §2): the Model editor's forms,
  // its Blocks tab and the optimization view's Edit mode all edit this one.
  // There is none until something is edited, so opening the page changes
  // nothing. A draft started from another version than the one shown is
  // never swapped silently: the page asks (`DraftConflict`).
  const stored = useModelDraft(Number(problemId));
  const conflict = stored !== null && seedKey !== null && stored.base !== seedKey;
  const workingIr = !conflict && stored ? stored.ir : ir;
  const draft: Draft | null = useMemo(() => (workingIr ? formDraftOf(workingIr) : null), [workingIr]);
  // Stable identities for the rules (Epic UX, U-3): a rename, or deleting another rule, keeps focus and state on this one.
  const ruleIdentity = useRef<{ ids: string[]; keys: string[] }>({ ids: [], keys: [] });
  const ruleIds = (draft?.constraints ?? []).map((rule) => rule.id);
  // Rules composed from a shape in this visit, which open in their boxes.
  const [composed, setComposed] = useState<Set<string>>(() => new Set());
  const ruleKeys = useMemo(() => {
    const keys = stableKeys(ruleIdentity.current.ids, ruleIdentity.current.keys, ruleIds);
    ruleIdentity.current = { ids: ruleIds, keys };
    return keys;
  }, [ruleIds.join("\u0000")]); // eslint-disable-line react-hooks/exhaustive-deps
  // A focused rule deleted (from the graph or its card) leaves nothing to focus: show every editor again.
  useEffect(() => {
    if (graphFocus?.ruleKey !== undefined && !ruleKeys.includes(graphFocus.ruleKey)) setGraphFocus(null);
  }, [graphFocus, ruleKeys]);

  // A draft started from scratch resumes as one: without this, a reload of a
  // problem with no version would offer "Start a model" over the draft.
  useEffect(() => {
    if (stored?.base === "scratch" && !scratch && baseId === null && !versions.isLoading) setScratch(true);
  }, [stored?.base, scratch, baseId, versions.isLoading]);

  /** Every edit, through the store: from its current value when a draft exists, else seeding one. */
  function setDraft(update: (current: Draft | null) => Draft | null) {
    if (!workingIr || seedKey === null) return;
    if (readDraft(Number(problemId))) {
      updateDraftIr(Number(problemId), (current) => {
        const next = update(formDraftOf(current));
        return next ? withFormDraft(current, next) : current;
      });
      return;
    }
    const next = update(formDraftOf(workingIr));
    if (!next) return;
    writeDraft({
      problemId: Number(problemId),
      base: seedKey,
      baseVersion: seedKey === "scratch" ? null : base?.version ?? null,
      ir: withFormDraft(workingIr, next),
    }, workingIr);
  }

  /** A whole-IR edit (the Blocks tab), through the same store as `setDraft`. */
  function setIr(next: Record<string, unknown>) {
    if (seedKey === null) return;
    if (readDraft(Number(problemId))) updateDraftIr(Number(problemId), () => next);
    else writeDraft({ problemId: Number(problemId), base: seedKey, baseVersion: seedKey === "scratch" ? null : base?.version ?? null, ir: next }, workingIr);
  }

  const catalogue = useMemo(
    () => catalogueFrom(entityTypes.data?.items ?? [], parameters.data?.items ?? [], relationshipTypes.data?.items ?? []),
    [entityTypes.data, parameters.data, relationshipTypes.data]
  );

  const context: ModelContext | null = useMemo(() => {
    if (!ir || !draft) return null;
    const types = entityTypes.data?.items ?? [];
    // From the **draft**, not the stored version: a set or variable declared
    // a moment ago has to be offered by the term editor immediately, or the
    // two halves of this page disagree about what the model is.
    const sets = draft.sets;
    return {
      sets,
      setIds: Object.fromEntries(
        sets.map((name) => [name, Number(types.find((t) => t.name === name)?.id ?? 0)])
      ),
      attributes: Object.fromEntries(
        sets.map((name) => [
          name,
          (types.find((t) => t.name === name)?.attributes ?? []).map((a) => ({
            name: a.name,
            data_type: a.data_type,
            enum_values: a.enum_values ?? null,
          })),
        ])
      ),
      variables: draft.variables as ModelContext["variables"],
      parameters: draft.parameters as ModelContext["parameters"],
      // Every relationship type of the domain whose BOTH ends are sets this
      // model declares. An edge to a type the model does not carry could not
      // bind an index to anything, so offering it would only produce a
      // refusal. Which of these the IR declares is decided on save, from the
      // walks actually written -- see `declaredRelationships`.
      relationships: (relationshipTypes.data?.items ?? [])
        .map((rel) => ({
          name: rel.name,
          from: types.find((t) => t.id === rel.from_type_id)?.name ?? "",
          to: types.find((t) => t.id === rel.to_type_id)?.name ?? "",
          hierarchy: rel.is_hierarchy,
          attributes: (rel.attributes ?? []).map((a) => ({ name: a.name, data_type: a.data_type })),
        }))
        .filter((rel) => sets.includes(rel.from) && sets.includes(rel.to)),
      // Declared in the IR itself; the form draft does not carry them.
      predictors: ((workingIr as Record<string, unknown> | null)?.predictors ?? {}) as ModelContext["predictors"],
    };
  }, [ir, draft, workingIr, entityTypes.data, relationshipTypes.data]);

  const nextIr = useMemo(() => (workingIr && draft ? publishable(withFormDraft(workingIr, draft)) : null), [workingIr, draft]);
  // Why Publish would be refused: the contract's shape rules at once, the
  // domain's own from the server's dry run a moment later (`useDraftRefusal`).
  const refusal = useDraftRefusal(problemId, canEdit ? (nextIr as Record<string, unknown> | null) : null);
  const classification = useClassify(
    nextIr !== null && refusal === null ? (nextIr as Record<string, unknown>) : null,
    problemId
  );

  if (versionMissing) {
    return (
      <ContextMismatch
        title="This model version is not available"
        detail="The link asked for a model version that is missing on this problem. Nothing was substituted."
        parentHref={`/versions?problem=${problemId}`}
        parentLabel="Open versions for this problem"
      />
    );
  }

  if (versions.isError) return <LoadFailure subject="Model versions" error={versions.error} retry={() => { void versions.refetch(); }} />;
  if (latest.isError) return <LoadFailure subject="The selected model version" error={latest.error} retry={() => { void latest.refetch(); }} />;
  if ((versions.fetchStatus === "paused" && !versions.data) || (baseId !== null && latest.fetchStatus === "paused" && !latest.data)) return <OfflineNotice subject="The model version" />;
  if (versions.isLoading || (baseId !== null && latest.isLoading) || entityTypes.isLoading) {
    return <Skeleton rows={4} cols={3} />;
  }
  if (baseId === null && !scratch) {
    return (
      <Note>
        <p>This problem has no model yet.</p>
        <p className="mt-1">
          Starting one declares what it is about — which sets it ranges over, which of the
          domain&rsquo;s parameters it reads — and then its rules.
        </p>
        <button
          type="button"
          className="mt-3 rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700"
          onClick={() => {
            setScratch(true);
            writeDraft({ problemId: Number(problemId), base: "scratch", baseVersion: null, ir: { ...EMPTY_MODEL } });
          }}
        >
          Start a model
        </button>
        <StartFromTemplates
          domainId={domainId}
          problemId={problemId}
          onApplied={() => {
            versions.refetch();
          }}
        />
        <div className="mt-3"><ServerDraftSync problemId={Number(problemId)} draft={null} disabled={false} /></div>
      </Note>
    );
  }
  if (conflict && stored) {
    return (
      <DraftConflict
        draft={stored}
        shownVersion={scratch ? null : base?.version ?? null}
        onContinue={() => {
          if (stored.base === "scratch") {
            setScratch(true);
            return;
          }
          setScratch(false);
          setSearchParams({ problem: String(problemId), version: stored.base.slice("version-".length) }, { replace: true });
        }}
        onStartAgain={() => clearDraft(Number(problemId))}
      />
    );
  }
  if (!draft || !context || !ir || nextIr === null) return <Skeleton rows={4} cols={3} />;
  const toPublish = nextIr as Record<string, unknown>;

  function published(created: { id: Id; version: number }) {
    toast.success(`Published version ${created.version}`);
    setJustPublished(created.version);
    clearDraft(Number(problemId));
    setScratch(false);
    setSearchParams(
      { problem: String(problemId), version: String(created.id) },
      { replace: true }
    );
    versions.refetch();
    // Everything else that counts versions (the "Continue this problem" checklist, the overview,
    // the runs page's "Solve version N") reads its own query: refresh them all, not just this list.
    void queryClient.invalidateQueries({ queryKey: ["v1"] });
  }

  // A draft saved to the server publishes from there: the server validates
  // the exact revision it holds, and the Idempotency-Key makes a retried
  // click answer with the version the first one created.
  async function publishFromServer() {
    const current = readDraft(Number(problemId));
    const link = readServerLink(Number(problemId));
    if (!current || !link) return;
    setServerPublishing(true);
    try {
      // A retry of an unchanged draft repeats the same request under the same
      // key; anything edited since is saved as a new revision with a new key.
      const pending = publishKey.current;
      const retry = pending !== null && pending.revision === link.revision && link.savedEditedAt === current.editedAt;
      if (!retry) {
        const saved = await saveToServer({ ...current, ir: toPublish }, link.revision);
        publishKey.current = { key: crypto.randomUUID(), revision: saved.revision };
      }
      const { key, revision } = publishKey.current!;
      const created = await publishServerDraft(
        Number(problemId), { expected_revision: revision, note: "edited in the model editor" }, key
      );
      publishKey.current = null;
      published(created);
    } catch (error) {
      setFailure(isStaleRecordError(error)
        ? "The server copy of this draft changed in another tab or browser. Resolve it with Save to server, then publish."
        : formatApiError(error));
    } finally {
      setServerPublishing(false);
    }
  }

  function publish() {
    setFailure(null);
    if (readServerLink(Number(problemId))) {
      void publishFromServer();
      return;
    }
    createVersion.mutate(
      { problemId, body: { ir: toPublish, note: "edited in the model editor" } },
      {
        onSuccess: published,
        onError: (error: unknown) => setFailure(formatApiError(error)),
      }
    );
  }

  async function discard() {
    const link = readServerLink(Number(problemId));
    // The server copy goes first, so nothing offers to reopen it afterwards.
    if (link) {
      try {
        await discardServerDraft(Number(problemId), link.revision);
      } catch (error) {
        if (!(error instanceof ApiError && error.status === 404)) {
          setFailure(`The server copy was not discarded: ${formatApiError(error)}`);
        }
      }
    }
    clearDraft(Number(problemId));
  }

  const stepsOn = simple ? simpleSteps : expertSteps;
  const setStepsOn = simple ? setSimpleSteps : setExpertSteps;
  const stepByStep = stepsOn;
  const currentStep: Step = view === "review" ? "check" : step;
  function goToStep(next: Step) {
    if (next === "check") {
      setView("review");
      return;
    }
    setStep(next);
    if (view !== "forms") setView("forms");
  }
  function goTo(kind: "rule" | "goal" | "variable" | "parameter", id: string) {
    goToStep(kind === "rule" ? "rules" : kind === "goal" ? "goal" : kind === "variable" ? "decisions" : "data");
    setOpening((current) => ({ kind, id, seq: (current?.seq ?? 0) + 1 }));
    // After the card has opened: bring it into view.
    window.setTimeout(() => {
      const target = document.getElementById(kind === "rule" ? `rule-card-${id}` : kind === "goal" ? "objective-editor" : `${kind}-card-${id}`);
      target?.scrollIntoView?.({ block: "center", behavior: "smooth" });
    }, 0);
  }
  const ruleFixes: Fix[] = draft.constraints.flatMap((rule) => checkRule(rule, context).map((problem, i) => ({
    key: `rule-${rule.id}-${i}`, where: `Rule ${rule.id || "(unnamed)"}`, message: explain(problem), go: () => goTo("rule", rule.id),
  })));
  const goalFixes: Fix[] = draft.objective.terms.flatMap((term) => (term.expression ? checkGoal(term.expression, context) : []).map((problem, i) => ({
    key: `goal-${term.id}-${i}`, where: `Goal ${term.id || "(unnamed)"}`, message: explain(problem), go: () => goTo("goal", term.id),
  })));
  const variableFixes: Fix[] = Object.entries(draft.variables).flatMap(([name, spec]) => checkDeclaration("variable", spec, draft.sets).map((problem, i) => ({
    key: `variable-${name}-${i}`, where: `Decision ${name}`, message: explain(problem), go: () => goTo("variable", name),
  })));
  const parameterFixes: Fix[] = Object.entries(draft.parameters).flatMap(([name, spec]) => checkDeclaration("parameter", spec, draft.sets).map((problem, i) => ({
    key: `parameter-${name}-${i}`, where: `Data ${name}`, message: explain(problem), go: () => goTo("parameter", name),
  })));
  const fixes = [...parameterFixes, ...variableFixes, ...ruleFixes, ...goalFixes];
  // A rule with no decision in it -- a blank rule's "0 ≤ 0" -- is valid IR and would publish as a
  // rule that says nothing (UX audit B-4): Publish waits until it is filled in or removed.
  const idleRules = draft.constraints.filter((rule) => rule.left != null && rule.right != null &&
    checkRule(rule, context).some((problem) => problem.message.startsWith("neither side reads a decision"))).map((rule) => rule.id);
  const stepStatus: Record<Step, StepStatus> = {
    sets: draft.sets.length ? "done" : "todo",
    data: parameterFixes.length ? "fix" : Object.keys(draft.parameters).length ? "done" : "optional",
    decisions: variableFixes.length ? "fix" : Object.keys(draft.variables).length ? "done" : "todo",
    rules: ruleFixes.length ? "fix" : draft.constraints.length ? "done" : "todo",
    goal: goalFixes.length ? "fix" : draft.objective.terms.length ? "done" : "optional",
    check: refusal !== null || fixes.length ? "fix" : "todo",
  };

  return (
    <EditorLevelContext.Provider value={level}>
      {justPublished !== null && (
        // Where the page lands after publishing, with the next step on it (UX audit B-7).
        <div role="status" className="mb-4 rounded-md border border-blue-200 bg-blue-50 p-3 text-sm text-blue-900">
          <p>
            Version {justPublished} is published.{" "}
            <Link className="underline" to={`/domains/${domainId}/problems/${problemId}/versions`}>See the versions</Link>.
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-3">
            {can("run.submit") && (
              <button type="button" disabled={solvingNow}
                className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
                onClick={async () => {
                  setSolvingNow(true);
                  try {
                    const run = await solveProblem(Number(problemId));
                    navigate(`/domains/${domainId}/problems/${problemId}/runs/${run.id}`);
                  } catch (error) {
                    setFailure(formatApiError(error));
                  } finally {
                    setSolvingNow(false);
                  }
                }}>
                {solvingNow ? "Starting…" : `Solve version ${justPublished} now`}
              </button>
            )}
            <span className="text-xs text-blue-800">It solves on the Base scenario; other scenarios keep their version until moved on the Scenarios page.</span>
          </div>
        </div>
      )}
      {versionItems.length > 0 && !scratch ? (
        <div className="mb-4">
          <label htmlFor="model-base" className="block text-sm font-medium text-slate-700">
            Starting from
          </label>
          <select
            id="model-base"
            className={`${INPUT_CLASS} max-w-sm`}
            value={String(baseId ?? "")}
            onChange={(event) => {
              setSearchParams(
                { problem: String(problemId), version: event.target.value },
                { replace: true }
              );
            }}
          >
            {versionItems.map((row) => (
              <option key={String(row.id)} value={String(row.id)}>
                version {row.version}
                {row.note ? ` — ${row.note}` : ""}
              </option>
            ))}
          </select>
          <p className="mt-1 text-xs text-slate-500">
            Publishing writes a new version either way: an older one is a starting point, never
            something this overwrites.
          </p>
        </div>
      ) : (
        <p className="mb-4 text-sm text-slate-600">Starting a model from nothing.</p>
      )}

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div role="tablist" aria-label="How to edit the model" className="flex overflow-hidden rounded-md border border-slate-300">
          {(simple ? ["forms", "review"] as const : canEdit ? ["forms", "graph", "blocks", "ir", "review"] as const : ["forms", "graph", "ir", "review"] as const).map((tab) => (
            <button
              key={tab}
              type="button"
              role="tab"
              aria-selected={view === tab}
              onClick={() => setView(tab)}
              className={`px-3 py-1.5 text-sm ${view === tab ? "bg-blue-700 text-white" : "bg-white text-slate-700"}`}
            >
              {{ forms: simple ? "Build" : "Guided Form", graph: "Visual Graph", blocks: "Blocks", ir: "Exact IR", review: simple ? "Check" : "Review" }[tab]}
            </button>
          ))}
        </div>
        {canEdit && !simple && (view === "forms" || view === "blocks") && <p className="text-xs text-slate-500">
          Blocks are a drag-and-drop view of the same model. The forms are the keyboard and screen-reader way to edit it.
        </p>}
      </div>

      {!canEdit && (
        <p role="note" className="mb-4 rounded-md border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700">
          This account may read the model but not change it. Ask someone who may publish models to make a change.
        </p>
      )}
      {!simple && <details className="mb-4 text-sm text-slate-600">
        <summary className="cursor-pointer py-2">Advanced views</summary>
        <p className="my-2">Blocks edits the same draft. Exact IR is read-only. Legacy visualizations show published model versions.</p>
        <Link className="inline-block py-2 text-blue-700 underline" to={`/domains/${domainId}/data/explore?mode=model&problem=${problemId}`}>Open legacy visualizations</Link>
      </details>}

      {canEdit && simple && <ThingsToFix items={fixes} />}
      {stepByStep && (
        <Stepper current={currentStep} status={stepStatus} onStep={goToStep} onAll={() => setStepsOn(false)} />
      )}
      {!stepsOn && view !== "graph" && view !== "blocks" && view !== "ir" && (
        <p className="mb-3 text-xs">
          <button type="button" className="text-blue-700 underline" onClick={() => setStepsOn(true)}>Go step by step</button>
        </p>
      )}
      {view === "graph" && workingIr && <ModelGraphPreview ir={workingIr} entityTypes={entityTypes.data?.items ?? []}
        layoutKey={`problem-${problemId}`} layoutProblemId={problemId}
        selection={graphFocus?.part === "rules" && graphFocus.ruleKey !== undefined
          ? `model-con-${draft.constraints[ruleKeys.indexOf(graphFocus.ruleKey)]?.id}` : graphFocus?.id ?? null}
        onSelect={(id, part) => setGraphFocus({ id, part, ...(part === "rules" ? { ruleKey: ruleKeys[draft.constraints.findIndex(rule => `model-con-${rule.id}` === id)] } : {}) })}
        draft={canEdit ? draft : null}
        onEdit={canEdit ? (edit) => setDraft((current) => current && edit(current)) : undefined}
        editorHref={part => part === "objective" ? "#objective-editor" : part === "rules" ? "#constraints-editor" : "#declarations-editor"} />}
      {view === "review" && draft ? <ModelReview draft={draft}
        units={Object.fromEntries((parameters.data?.items ?? []).map((parameter) => [parameter.name, parameter.unit]))}
        planner={classification.data?.planner ?? []} wouldSolve={classification.data?.would_solve ?? null} />
      : view === "ir" ? <section aria-label="Exact IR" className="mb-6"><p className="mb-2 text-sm text-slate-600">Read-only current draft. Use Guided Form or Blocks to edit.</p><pre className="max-h-[32rem] overflow-auto rounded-lg bg-slate-50 p-4 text-sm">{JSON.stringify(workingIr, null, 2)}</pre></section>
      : view === "blocks" && workingIr && canEdit ? (
        <div className="mb-6">
          <BlocksEditor
            ir={workingIr}
            catalogue={catalogue}
            refusal={refusal}
            onChange={(next, _paths, left) => {
              setOutside(left);
              setIr(next);
            }}
          />
        </div>
      ) : (
      <>
      {view === "graph" && graphFocus && <div role="status" className="mb-4 rounded border border-blue-200 p-3">
        <p>{focusedPart === "rules" ? "Editing the selected rule" : focusedPart === "objective" ? "Editing the objective" : "Editing declarations"}. Changes update this graph and Guided Form.</p>
        <button type="button" className="mt-2 rounded border px-3 py-2" onClick={() => setGraphFocus(null)}>Show all model editors</button>
      </div>}
      <fieldset disabled={!canEdit} aria-label={canEdit ? undefined : "The model, read only"} className="m-0 min-w-0 border-0 p-0">
      {canEdit && !simple && !stepByStep && <GuidedCreation draft={draft} availableSets={(entityTypes.data?.items ?? []).map(type => type.name)}
        onApply={command => setDraft(current => current && applyGuidedCommand(current, command, (entityTypes.data?.items ?? []).map(type => type.name)))}
        onPattern={command => setDraft(current => current && applyPattern(current, command, (entityTypes.data?.items ?? []).map(type => type.name)))}
        relationships={context?.relationships ?? []}
        units={Object.fromEntries((parameters.data?.items ?? []).map((parameter) => [parameter.name, parameter.unit]))} />}
      {canEdit && !graphFocus && (!stepByStep || step === "sets") && (
        <CoverageRecipeForm
          kinds={(entityTypes.data?.items ?? []).map((t) => ({ id: Number(t.id), name: t.name, attributes: t.attributes }))}
          data={parameterOptions(parameters.data?.items ?? [], entityTypes.data?.items ?? [])}
          links={(relationshipTypes.data?.items ?? []).map((rel) => ({
            name: rel.name,
            from: entityTypes.data?.items.find((t) => t.id === rel.from_type_id)?.name ?? "",
            to: entityTypes.data?.items.find((t) => t.id === rel.to_type_id)?.name ?? "",
          }))}
          onApply={(edit) => setDraft((current) => current && edit(current))}
          startOpen={draft.constraints.length === 0 && Object.keys(draft.variables).length === 0}
        />
      )}
      <div hidden={focusedPart === "rules" || focusedPart === "objective" || (stepByStep && !["sets", "data", "decisions"].includes(step))} id="declarations-editor" tabIndex={-1} aria-label="Declarations editor">
      <DeclarationsEditor
        sets={draft.sets}
        parameters={draft.parameters}
        variables={draft.variables}
        entityTypeNames={(entityTypes.data?.items ?? []).map((type) => type.name)}
        parameterOptions={parameterOptions(
          parameters.data?.items ?? [],
          entityTypes.data?.items ?? []
        )}
        constraints={draft.constraints}
        objectiveTerms={draft.objective.terms}
        onChange={(next) => setDraft((current) => current && { ...current, ...next })}
        view={equationView}
        onView={setEquationView}
        simple={simple}
        onlyGroup={stepByStep && (step === "sets" || step === "data" || step === "decisions") ? step : undefined}
        opening={opening && (opening.kind === "variable" || opening.kind === "parameter") ? { name: opening.id, seq: opening.seq } : null}
        {...(canShape ? {
          onCreateSet: async (name: string) => {
            await createType.mutateAsync({ domain_id: domainId as Id, name, role: "other" });
          },
          onCreateAttribute: async (set: string, name: string, unit: string) => {
            const type = (entityTypes.data?.items ?? []).find((t) => t.name === set);
            if (!type) throw new Error(`${set} is not a record type of this domain.`);
            await createAttribute.mutateAsync({ entityTypeId: type.id, body: { name, data_type: "number", ...(unit ? { unit } : {}) } });
          },
          onCreateParameter: async (made: { name: string; index: string[]; defaultValue: number; unit: string }) => {
            const types = entityTypes.data?.items ?? [];
            const ids = made.index.map((set) => types.find((t) => t.name === set)?.id);
            if (ids.some((id) => id === undefined)) throw new Error("Every set it is over must be a record type of this domain.");
            await createParameterDef.mutateAsync({
              domain_id: domainId as Id, name: made.name, index_type_ids: ids as Id[], default_value: made.defaultValue,
              ...(made.unit ? { unit: made.unit } : {}),
            });
          },
        } : {})}
        attributes={context?.attributes ?? {}}
        units={Object.fromEntries((parameters.data?.items ?? []).map((parameter) => [parameter.name, parameter.unit]))}
      />

      </div>
      <section hidden={(focusedPart !== undefined && focusedPart !== "rules") || (stepByStep && step !== "rules")} id="constraints-editor" tabIndex={-1} aria-labelledby="constraints-heading" className="mb-6">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <h2 id="constraints-heading" className="text-base font-semibold text-slate-900">
            What must be true
          </h2>
          <ViewToggle value={equationView} onChange={setEquationView} name="all" />
        </div>
        {draft.constraints.length === 0 && (
          <p className="mb-2 text-sm text-slate-600">No rules yet. Add one that must hold.</p>
        )}
        <div className="space-y-1">
          {draft.constraints.map((constraint, position) => focusedPart === "rules" && graphFocus?.ruleKey !== ruleKeys[position] ? null : (
            <ConstraintCard
              key={ruleKeys[position]}
              view={equationView}
              startIn={composed.has(constraint.id) ? "boxes" : undefined}
              simple={simple}
              openSignal={opening?.kind === "rule" && opening.id === constraint.id ? opening.seq : undefined}
              constraint={constraint}
              otherIds={draft.constraints
                .filter((_, i) => i !== position)
                .map((c) => c.id)}
              context={context}
              onChange={(next) =>
                setDraft((current) =>
                  current && {
                    ...current,
                    constraints: current.constraints.map((c, i) => (i === position ? next : c)),
                  }
                )
              }
              onRemove={() => {
                setGraphFocus(null);
                setDraft((current) =>
                  current && {
                    ...current,
                    constraints: current.constraints.filter((_, i) => i !== position),
                  }
                );
              }}
            />
          ))}
        </div>
        {simple ? (
          <AddMenu label="Add a rule">
            {(close) => (
              <>
                {RULE_SHAPES.map((shape) => (
                  <AddChoice key={shape.shape} title={shape.title} disabledReason={shape.needs(context)}
                    hint="Filled in from this model's names; change any part afterwards."
                    onPick={() => {
                      const id = freeNumberedId("c_", draft.constraints.map((constraint) => constraint.id));
                      setComposed((current) => new Set(current).add(id));
                      setDraft((current) => current && { ...current, constraints: [...current.constraints, ruleFromShape(shape.shape, id, context)] });
                      close();
                      goTo("rule", id);
                    }} />
                ))}
                <AddChoice title="A blank rule" hint="Starts as “0 is at most 0”: fill in both sides before publishing."
                  onPick={() => {
                    const id = freeNumberedId("c_", draft.constraints.map((constraint) => constraint.id));
                    setComposed((current) => new Set(current).add(id));
                    setDraft((current) => current && {
                      ...current,
                      constraints: [...current.constraints, {
                        id,
                        ...(context.sets.length > 0 ? { forall: [nextBinding([], context)] } : {}),
                        left: { const: 0 }, relation: "<=", right: { const: 0 }, severity: "hard",
                      } as Constraint],
                    });
                    close();
                    goTo("rule", id);
                  }} />
                <p className="text-xs text-slate-500">Scheduling, connected and route rules are under Expert.</p>
              </>
            )}
          </AddMenu>
        ) : (
          <>
        <button
          type="button"
          className="mt-3 rounded border border-slate-300 px-3 py-2 text-sm text-slate-700"
          onClick={() => {
            // The new rule opens where it is seen (UX audit B-4), not below the fold.
            const id = freeNumberedId("c_", draft.constraints.map((constraint) => constraint.id));
            setDraft((current) =>
              current && {
                ...current,
                constraints: [
                  ...current.constraints,
                {
                  id,
                  // No set yet → a global rule (omit forall). Naming an
                  // empty set would publish a binding the contract refuses.
                  ...(context.sets.length > 0
                    ? { forall: [nextBinding([], context)] }
                    : {}),
                  left: { const: 0 },
                  relation: "<=",
                  right: { const: 0 },
                  severity: "hard",
                } as Constraint,
                ],
              }
            );
            goTo("rule", id);
          }}
        >
          Add a rule
        </button>
        <ShapePicker
          label="Start a rule from a shape"
          shapes={RULE_SHAPES.map((s) => ({ value: s.shape, title: s.title, needs: s.needs(context) }))}
          onPick={(shape) => {
            const id = freeNumberedId("c_", draft.constraints.map((constraint) => constraint.id));
            const rule = ruleFromShape(shape as RuleShape, id, context);
            setComposed((current) => new Set(current).add(id));
            setDraft((current) => current && { ...current, constraints: [...current.constraints, rule] });
            goTo("rule", id);
          }}
        />
        {newSchedulingRule("c_", context) !== null && (
          <button
            type="button"
            className="ml-2 mt-3 rounded border border-slate-300 px-3 py-2 text-sm text-slate-700"
            onClick={() =>
              setDraft((current) => {
                if (!current) return current;
                const rule = newSchedulingRule(
                  freeNumberedId("c_", current.constraints.map((constraint) => constraint.id)),
                  context
                );
                return rule ? { ...current, constraints: [...current.constraints, rule] } : current;
              })
            }
          >
            Add a scheduling rule
          </button>
        )}
        {newConnectedRule("c_", context) !== null && (
          <button
            type="button"
            className="ml-2 mt-3 rounded border border-slate-300 px-3 py-2 text-sm text-slate-700"
            onClick={() =>
              setDraft((current) => {
                if (!current) return current;
                const rule = newConnectedRule(
                  freeNumberedId("c_", current.constraints.map((constraint) => constraint.id)),
                  context
                );
                return rule ? { ...current, constraints: [...current.constraints, rule] } : current;
              })
            }
          >
            Add a connected rule
          </button>
        )}
        {routeChoices(context).length > 0 && (
          <button
            type="button"
            className="ml-2 mt-3 rounded border border-slate-300 px-3 py-2 text-sm text-slate-700"
            onClick={() =>
              setDraft((current) => {
                if (!current) return current;
                const rule = newRouteRule(
                  freeNumberedId("c_", current.constraints.map((constraint) => constraint.id)),
                  context
                );
                return rule ? { ...current, constraints: [...current.constraints, rule] } : current;
              })
            }
          >
            Add a route rule
          </button>
        )}
          </>
        )}
      </section>

      <section hidden={(focusedPart !== undefined && focusedPart !== "objective") || (stepByStep && step !== "goal")} id="objective-editor" tabIndex={-1} aria-labelledby="objective-heading" className="mb-6">
        <h2 id="objective-heading" className="mb-2 text-base font-semibold text-slate-900">
          What to make best
        </h2>
        <ObjectiveEditor
          view={equationView}
          simple={simple}
          openGoal={opening?.kind === "goal" ? { id: opening.id, seq: opening.seq } : null}
          objective={draft.objective}
          context={context}
          onChange={(objective) => setDraft((current) => current && { ...current, objective })}
        />
      </section>
      </fieldset>
      {stepByStep && <StepNav current={currentStep} onStep={goToStep} />}
      </>
      )}
      {stepByStep && view === "review" && <StepNav current={currentStep} onStep={goToStep} />}

      {/* The review says this itself, under "How it will be solved" (UX audit B-7: shown twice). */}
      {refusal === null && classification.data && view !== "review" && (
        <aside aria-label="What this model is" className="mb-4 rounded-md border border-slate-200 bg-slate-50 p-3">
          <h2 className="mb-1 text-sm font-semibold text-slate-900">What this model is</h2>
          {classification.data.planner.length > 0 && (
            <ul className="list-disc space-y-1 pl-5 text-sm text-slate-700">
              {classification.data.planner.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          )}
          {classification.data.would_solve ? (
            <p className={`text-sm text-slate-700 ${classification.data.planner.length > 0 ? "mt-2" : ""}`}>
              {classification.data.would_solve}
            </p>
          ) : (
            <p
              className={`text-sm text-amber-800 ${classification.data.planner.length > 0 ? "mt-2" : ""}`}
            >
              No solver this platform has can take this model.
            </p>
          )}
        </aside>
      )}

      {refusal === null && (classification.data?.empty_ranges.length ?? 0) > 0 && (
        <aside
          aria-label="Rules that ranged over nobody"
          className="mb-4 rounded-md border border-slate-200 bg-slate-50 p-3"
        >
          <h2 className="mb-1 text-sm font-semibold text-slate-900">Rules that ranged over nobody</h2>
          <p className="mb-2 text-sm text-slate-700">
            A rule that matches nobody never constrains anyone. Check the filter, or the data it ranges
            over.
          </p>
          <EmptyRanges items={classification.data?.empty_ranges ?? []} />
        </aside>
      )}

      {refusal && (
        <p role="alert" className="mb-3 text-sm text-red-600">
          {refusal.message}
        </p>
      )}
      {failure && (
        <p role="alert" className="mb-3 whitespace-pre-line text-sm text-red-600">
          {failure}
        </p>
      )}

      {view !== "review" && (
        <p className="mb-2 text-sm">
          <button type="button" className="text-blue-700 underline" onClick={() => setView("review")}>Review the whole model</button>{" "}
          <span className="text-slate-600">before publishing: every rule in words, and what looks unfinished.</span>
        </p>
      )}
      {canEdit && <>
      <DraftBar
        draft={stored}
        publishing={createVersion.isPending || serverPublishing}
        blocked={
          view === "blocks" && outside > 0
            ? `${outside} ${outside === 1 ? "block is" : "blocks are"} outside the model: put ${outside === 1 ? "it" : "them"} inside, or delete ${outside === 1 ? "it" : "them"}`
            : refusal
              ? refusal.message
              : idleRules.length
                ? `${idleRules.join(", ")} ${idleRules.length === 1 ? "decides" : "decide"} nothing yet (neither side reads a decision): fill ${idleRules.length === 1 ? "it" : "them"} in, or remove ${idleRules.length === 1 ? "it" : "them"}`
                : null
        }
        onPublish={publish}
        onDiscard={() => void discard()}
      />
      <div className="mt-3">
        <ServerDraftSync problemId={Number(problemId)} draft={stored} disabled={createVersion.isPending || serverPublishing} />
      </div>
      </>}
    </EditorLevelContext.Provider>
  );
}


function ConstraintCard({
  view,
  constraint,
  otherIds,
  context,
  onChange,
  onRemove,
  startIn,
  simple = false,
  openSignal,
}: {
  view: EquationView;
  constraint: Constraint;
  otherIds: string[];
  context: ModelContext;
  onChange: (next: Constraint) => void;
  onRemove: () => void;
  /** Where a card just composed opens. */
  startIn?: EquationView;
  /** Simple: the card is one line -- its sentence and whether it checks out -- until opened. */
  simple?: boolean;
  /** Each new value opens the card (a “go to it” from the list of things to fix). */
  openSignal?: number;
}) {
  const idField = useId();
  const noteField = useId();
  // Condition, chance and the structure tree: advanced, so folded away unless
  // the rule already uses a chance.
  const [structure, setStructure] = useState(Boolean(constraint.chance));
  const equation = useMemo(() => ruleEquation(constraint, context), [constraint, context]);
  const [shown, setShown] = useCardView(view, startIn);
  const bound: Binding[] = constraint.forall ?? [];
  const idProblem = !constraint.id
    ? "A rule needs a name."
    : !isName(constraint.id)
      ? "A name starts with a letter and uses lower-case letters, digits and underscores."
      : otherIds.includes(constraint.id)
        ? `Another rule is already called ${constraint.id}.`
        : null;

  return (
    <article id={`rule-card-${constraint.id}`} className="rounded-md border border-slate-200 bg-white p-2">
    <TreeItem
      name={constraint.id || "rule"}
      defaultOpen={!simple || startIn !== undefined}
      openSignal={openSignal}
      collapsedHeader={simple ? <OneLine name={constraint.id || "rule"} text={ruleSentence(constraint, context.relationships)} problems={checkRule(constraint, context).length} /> : undefined}
      header={
        <div className="flex min-w-0 flex-1 flex-wrap items-end gap-3">
          <div>
            <label htmlFor={idField} className="block text-xs text-slate-600">
              Name
            </label>
            <input
              id={idField}
              className={`${INPUT_CLASS} w-48 text-sm`}
              value={constraint.id}
              aria-invalid={idProblem ? "true" : undefined}
              aria-describedby={idProblem ? `${idField}-problem` : undefined}
              onChange={(event) => onChange({ ...constraint, id: event.target.value })}
            />
            {idProblem && (
              <p id={`${idField}-problem`} role="alert" className="mt-1 text-xs text-red-600">
                {idProblem}
              </p>
            )}
          </div>
          <div className="min-w-0 flex-1">
            <label htmlFor={noteField} className="block text-xs text-slate-600">
              What it means
            </label>
            <input
              id={noteField}
              className={`${INPUT_CLASS} text-sm`}
              value={constraint.note ?? ""}
              onChange={(event) => onChange({ ...constraint, note: event.target.value })}
            />
          </div>
        </div>
      }
      actions={
        <button type="button" onClick={onRemove} className="rounded px-2 py-1 text-sm text-red-700 underline">
          Remove
        </button>
      }
    >
      {describeSchedule(constraint) !== null ? (
        <SchedulingEditor constraint={constraint} context={context} onChange={onChange} />
      ) : constraint.connected !== undefined ? (
        <ConnectedEditor constraint={constraint} context={context} onChange={onChange} />
      ) : constraint.route !== undefined ? (
        <RouteEditor constraint={constraint} context={context} onChange={onChange} />
      ) : constraint.left == null || constraint.right == null ? (
        <div className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          <p>
            This rule is named but not expressed — a leftover of versions that
            predate the contract. There is nothing here to edit, and publishing
            it as-is is refused.
          </p>
          <button
            type="button"
            className="mt-2 rounded px-2 py-1 text-sm text-amber-950 underline"
            onClick={() =>
              onChange({
                ...constraint,
                left: { const: 0 },
                relation: constraint.relation ?? "<=",
                right: { const: 0 },
                severity: constraint.severity ?? "hard",
              })
            }
          >
            Start expressing it
          </button>
        </div>
      ) : equation !== null ? (
        <div className="space-y-2 px-2 py-1">
          <div className="flex flex-wrap items-start gap-3">
            <div className="min-w-0 flex-1 space-y-1">
              <ViewToggle value={shown} onChange={setShown} name={constraint.id || "this rule"} size="xs" />
              {shown === "sentence" ? (
                <RuleSentence rule={constraint} context={context} onEdit={() => setShown("boxes")} onChange={onChange} />
              ) : shown === "boxes" ? (
                <RuleBlocks rule={constraint} context={context} onChange={onChange} />
              ) : shown === "diagram" ? (
                <RuleDiagram rule={constraint} context={context} onChange={onChange} />
              ) : (
                <EquationField
                  label={`Equation for ${constraint.id || "this rule"}`}
                  equation={equation}
                  parse={(text) => parseRule(text, context)}
                  onCommit={(parsed) => onChange(withEquation(constraint, parsed))}
                  chips={chipsFor(context)}
                  sets={context.sets}
                />
              )}
            </div>
            <div className="flex flex-wrap items-end gap-3">
              <Choice
                label="Strength"
                value={constraint.severity ?? "hard"}
                options={SEVERITIES.map((s) => ({
                  value: s,
                  label: s === "hard" ? "required" : "preferred",
                }))}
                onChange={(severity) => {
                  const next = severity as Constraint["severity"];
                  if (next === "soft") {
                    // A preferred rule takes no condition and no chance (contract: when_on_soft, chance_misplaced).
                    const { when: _unswitched, chance: _unchanced, ...rest } = constraint;
                    onChange({
                      ...rest,
                      severity: next,
                      weight: constraint.weight && constraint.weight >= 1 ? constraint.weight : 1,
                    });
                    return;
                  }
                  const { weight: _dropped, ...rest } = constraint;
                  onChange({ ...rest, severity: next });
                }}
              />
              {constraint.severity === "soft" && (
                <div>
                  <label className="block text-xs text-slate-600" htmlFor={`${idField}-weight`}>
                    How much it matters
                  </label>
                  <input
                    id={`${idField}-weight`}
                    inputMode="numeric"
                    className={`${INPUT_CLASS} w-28 text-sm`}
                    value={String(constraint.weight ?? 1)}
                    onChange={(event) => {
                      // A soft cost must be a positive integer (contract §3.4).
                      // Rejecting 0 here keeps the field honest — Publish used
                      // to coerce it silently while the box still showed 0.
                      const raw = event.target.value;
                      if (!/^\d*$/.test(raw)) return;
                      if (raw === "") {
                        onChange({ ...constraint, weight: 1 });
                        return;
                      }
                      const next = Number(raw);
                      if (Number.isSafeInteger(next) && next >= 1) {
                        onChange({ ...constraint, weight: next });
                      }
                    }}
                  />
                </div>
              )}
            </div>
          </div>
          <button
            type="button"
            aria-expanded={structure}
            className="rounded py-1 text-xs font-medium text-blue-700 underline"
            onClick={() => setStructure((open) => !open)}
          >
            {structure ? "Fewer options" : "More options"}
          </button>
          {structure && (
            <>
          <WhenEditor
            when={constraint.when}
            soft={constraint.severity === "soft"}
            bound={bound}
            context={context}
            onChange={(when) => {
              if (when === undefined) {
                const { when: _dropped, ...rest } = constraint;
                onChange(rest);
                return;
              }
              // A conditional rule takes no chance: the chance is its own switch (contract: chance_misplaced).
              const { chance: _dropped, ...rest } = constraint;
              onChange({ ...rest, when });
            }}
          />
          {constraint.severity !== "soft" && !constraint.when && (
            <ChanceField
              id={`${idField}-chance`}
              chance={constraint.chance}
              onChange={(chance) => {
                const { chance: _previous, ...rest } = constraint;
                onChange(chance === undefined ? rest : { ...rest, chance });
              }}
            />
          )}
            </>
          )}
          {structure && (
            <TreeView>
          <BindingsEditor
            bindings={bound}
            onChange={(forall) => {
              // Omit the key when there is nothing to range over — an empty
              // array is refused (contract §3.4).
              if (forall.length === 0) {
                const { forall: _dropped, ...rest } = constraint;
                onChange(rest);
                return;
              }
              onChange({ ...constraint, forall });
            }}
            context={context}
            outer={[]}
            legend="For every"
            minBindings={0}
          />

          <TermBuilder
            value={constraint.left}
            onChange={(left) => onChange({ ...constraint, left })}
            context={context}
            bound={bound}
            label="This"
          />

          <div className="flex flex-wrap items-end gap-3 px-2 py-1">
            <Choice
              label="Must be"
              value={constraint.relation ?? "<="}
              options={RELATIONS.map((r) => ({ value: r, label: relationLabel(r) }))}
              onChange={(relation) =>
                onChange({ ...constraint, relation: relation as Constraint["relation"] })
              }
            />
          </div>

          <TermBuilder
            value={constraint.right}
            onChange={(right) => onChange({ ...constraint, right })}
            context={context}
            bound={bound}
            label="That"
          />
            </TreeView>
          )}
        </div>
      ) : shown === "sentence" || shown === "boxes" ? (
        <div className="space-y-2 px-2 py-1">
          <ViewToggle value={shown} onChange={setShown} name={constraint.id || "this rule"} size="xs" />
          {shown === "sentence" ? (
            <RuleSentence rule={constraint} context={context} onEdit={() => setShown("boxes")} onChange={onChange} />
          ) : (
            <RuleBlocks rule={constraint} context={context} onChange={onChange} />
          )}
          <p className="text-xs text-slate-500">
            This rule cannot be written as one equation line yet, so Equation and Diagram open its full editor.
          </p>
        </div>
      ) : (
        <TreeView>
          <div className="px-2 pb-1">
            <ViewToggle value={shown} onChange={setShown} name={constraint.id || "this rule"} size="xs" />
          </div>
          <p className="mb-1 px-2 font-mono text-xs text-slate-500">
            {describeTerm(constraint.left)} {constraint.relation} {describeTerm(constraint.right)}
            {describeWhen(constraint.when) ? `, ${describeWhen(constraint.when)}` : ""}
          </p>

          <BindingsEditor
            bindings={bound}
            onChange={(forall) => {
              // Omit the key when there is nothing to range over — an empty
              // array is refused (contract §3.4).
              if (forall.length === 0) {
                const { forall: _dropped, ...rest } = constraint;
                onChange(rest);
                return;
              }
              onChange({ ...constraint, forall });
            }}
            context={context}
            outer={[]}
            legend="For every"
            minBindings={0}
          />

          <TermBuilder
            value={constraint.left}
            onChange={(left) => onChange({ ...constraint, left })}
            context={context}
            bound={bound}
            label="This"
          />

          <div className="flex flex-wrap items-end gap-3 px-2 py-1">
            <Choice
              label="Must be"
              value={constraint.relation ?? "<="}
              options={RELATIONS.map((r) => ({ value: r, label: relationLabel(r) }))}
              onChange={(relation) =>
                onChange({ ...constraint, relation: relation as Constraint["relation"] })
              }
            />
            <Choice
              label="Strength"
              value={constraint.severity ?? "hard"}
              options={SEVERITIES.map((s) => ({
                value: s,
                label: s === "hard" ? "required" : "preferred",
              }))}
              onChange={(severity) => {
                const next = severity as Constraint["severity"];
                if (next === "soft") {
                  // A preferred rule takes no condition and no chance (contract: when_on_soft, chance_misplaced).
                  const { when: _unswitched, chance: _unchanced, ...rest } = constraint;
                  onChange({
                    ...rest,
                    severity: next,
                    weight: constraint.weight && constraint.weight >= 1 ? constraint.weight : 1,
                  });
                  return;
                }
                const { weight: _dropped, ...rest } = constraint;
                onChange({ ...rest, severity: next });
              }}
            />
            {constraint.severity === "soft" && (
              <div>
                <label className="block text-xs text-slate-600" htmlFor={`${idField}-weight`}>
                  How much it matters
                </label>
                <input
                  id={`${idField}-weight`}
                  inputMode="numeric"
                  className={`${INPUT_CLASS} w-28 text-sm`}
                  value={String(constraint.weight ?? 1)}
                  onChange={(event) => {
                    // A soft cost must be a positive integer (contract §3.4).
                    // Rejecting 0 here keeps the field honest — Publish used
                    // to coerce it silently while the box still showed 0.
                    const raw = event.target.value;
                    if (!/^\d*$/.test(raw)) return;
                    if (raw === "") {
                      onChange({ ...constraint, weight: 1 });
                      return;
                    }
                    const next = Number(raw);
                    if (Number.isSafeInteger(next) && next >= 1) {
                      onChange({ ...constraint, weight: next });
                    }
                  }}
                />
              </div>
            )}
          </div>

          <TermBuilder
            value={constraint.right}
            onChange={(right) => onChange({ ...constraint, right })}
            context={context}
            bound={bound}
            label="That"
          />

          <WhenEditor
            when={constraint.when}
            soft={constraint.severity === "soft"}
            bound={bound}
            context={context}
            onChange={(when) => {
              if (when === undefined) {
                const { when: _dropped, ...rest } = constraint;
                onChange(rest);
                return;
              }
              // A conditional rule takes no chance: the chance is its own switch (contract: chance_misplaced).
              const { chance: _dropped, ...rest } = constraint;
              onChange({ ...rest, when });
            }}
          />
          {constraint.severity !== "soft" && !constraint.when && (
            <ChanceField
              id={`${idField}-chance`}
              chance={constraint.chance}
              onChange={(chance) => {
                const { chance: _previous, ...rest } = constraint;
                onChange(chance === undefined ? rest : { ...rest, chance });
              }}
            />
          )}
        </TreeView>
      )}
    </TreeItem>
    </article>
  );
}

/**
 * A rule's chance (version 2, queue R8): the share of a stochastic solve's
 * sampled futures it may fail in, typed as a percentage. Empty is never --
 * every other solve holds the rule always, whatever this says.
 */
function ChanceField({
  id,
  chance,
  onChange,
}: {
  id: string;
  chance: { epsilon: number } | undefined;
  onChange: (chance: { epsilon: number } | undefined) => void;
}) {
  const [text, setText] = useState(chance ? String(Number((chance.epsilon * 100).toPrecision(6))) : "");
  const percent = text === "" ? null : Number(text);
  const valid = percent === null || (Number.isFinite(percent) && percent > 0 && percent < 100);
  return (
    <div className="mt-2">
      <label className="block text-xs text-slate-600" htmlFor={id}>
        May fail in at most this % of sampled futures (a stochastic solve; empty: never)
      </label>
      <input
        id={id}
        inputMode="decimal"
        className={`${INPUT_CLASS} w-28 text-sm`}
        value={text}
        aria-invalid={!valid}
        onChange={(event) => {
          const raw = event.target.value.trim();
          setText(raw);
          if (raw === "") {
            onChange(undefined);
            return;
          }
          const next = Number(raw);
          if (Number.isFinite(next) && next > 0 && next < 100) onChange({ epsilon: next / 100 });
        }}
      />
      {!valid && (
        <p role="alert" className="mt-1 text-xs text-red-600">
          A share of futures is more than 0% and less than 100%.
        </p>
      )}
    </div>
  );
}

/** A goal's expression as an equation, with its structure a click away; a
 * goal the equation form cannot write exactly keeps the structure editor. */
function GoalExpression({ view, goalId, expression, context, onChange, startIn }: {
  view: EquationView;
  /** Where a goal just composed opens. */
  startIn?: EquationView;
  goalId: string;
  expression: Term;
  context: ModelContext;
  onChange: (expression: Term) => void;
}) {
  const [structure, setStructure] = useState(false);
  const equation = useMemo(() => goalEquation(expression, context), [expression, context]);
  const [shown, setShown] = useCardView(view, startIn);
  const builder = <TermBuilder value={expression} onChange={onChange} context={context} bound={[]} label="Count" />;
  if (equation === null) {
    // The equation line cannot write it: the words and the boxes still can.
    return (
      <div className="space-y-2 px-2 py-1">
        <ViewToggle value={shown} onChange={setShown} name={goalId || "this goal"} size="xs" />
        {shown === "sentence" ? (
          <GoalSentence expression={expression} context={context} onEdit={() => setShown("boxes")} onChange={onChange} />
        ) : shown === "boxes" ? (
          <GoalBlocks label={goalId || "the goal"} expression={expression} context={context} onChange={onChange} />
        ) : builder}
      </div>
    );
  }
  return (
    <div className="space-y-2 px-2 py-1">
      <ViewToggle value={shown} onChange={setShown} name={goalId || "this goal"} size="xs" />
      {shown === "sentence" ? (
        <GoalSentence expression={expression} context={context} onEdit={() => setShown("boxes")} onChange={onChange} />
      ) : shown === "boxes" ? (
        <GoalBlocks label={goalId || "the goal"} expression={expression} context={context} onChange={onChange} />
      ) : shown === "diagram" ? (
        <GoalDiagram label={goalId || "goal"} expression={expression} context={context} onChange={onChange} />
      ) : <EquationField
        label={`Equation for ${goalId || "this goal"}`}
        equation={equation}
        parse={(text) => parseGoal(text, context)}
        onCommit={(next) => onChange(next)}
        chips={chipsFor(context)}
        sets={context.sets}
      />}
      <button
        type="button"
        aria-expanded={structure}
        className="rounded py-1 text-xs font-medium text-blue-700 underline"
        onClick={() => setStructure((open) => !open)}
      >
        {structure ? "Fewer options" : "More options"}
      </button>
      {structure && builder}
    </div>
  );
}

function ObjectiveEditor({
  view,
  simple = false,
  openGoal = null,
  objective,
  context,
  onChange,
}: {
  view: EquationView;
  /** Simple: goals collapse to a line, and one “+ Add a goal” menu. */
  simple?: boolean;
  /** Open this goal's card (a “go to it” from the list of things to fix). */
  openGoal?: { id: string; seq: number } | null;
  objective: { sense: string; mode: string; terms: ObjectiveTerm[] };
  context: ModelContext;
  onChange: (next: { sense: string; mode: string; terms: ObjectiveTerm[] }) => void;
}) {
  const lex = objective.mode === "lex";
  // Goals composed from a shape in this visit, which open in their boxes.
  const [composedGoals, setComposedGoals] = useState<Set<string>>(() => new Set());

  function moveTerm(from: number, to: number) {
    if (to < 0 || to >= objective.terms.length) return;
    const terms = [...objective.terms];
    const [moved] = terms.splice(from, 1);
    terms.splice(to, 0, moved);
    onChange({ ...objective, terms });
  }

  return (
    <div className="rounded-md border border-slate-200 bg-white p-4">
      <Choice
        label="The solver should"
        value={objective.sense}
        options={SENSES.map((s) => ({ value: s, label: s === "minimize" ? "make it as small as possible" : "make it as large as possible" }))}
        onChange={(sense) => onChange({ ...objective, sense })}
      />
      <Choice
        label="When there is more than one goal"
        value={objective.mode}
        options={[
          { value: "weighted", label: "mix them by weight" },
          { value: "lex", label: "this order: first goal, then the next" },
        ]}
        onChange={(mode) => onChange({ ...objective, mode })}
      />

      <div className="mt-3 space-y-1">
        {objective.terms.length === 0 && (
          <p className="text-sm text-slate-600">
            No goals yet. Leave it empty for a feasibility problem, or add one.
          </p>
        )}
        {objective.terms.length > 0 && !simple && (() => {
          const parts = objective.terms.map((term) => goalEquation(term.expression, context));
          if (parts.some((part) => part === null)) return null;
          const joined = objective.mode === "lex"
            ? parts.join(", then ")
            : objective.terms.map((term, i) => `${term.weight ?? 1} × (${parts[i]})`).join(" + ");
          return (
            <p data-testid="objective-equation" className="mb-2 overflow-x-auto whitespace-nowrap rounded bg-slate-50 px-2 py-1 font-mono text-xs text-slate-700">
              {objective.sense ?? "minimize"} {joined}
            </p>
          );
        })()}
        {objective.terms.map((term, position) => {
          const otherIds = objective.terms
            .filter((_, i) => i !== position)
            .map((t) => t.id);
          const idProblem = !term.id
            ? "A goal needs a name."
            : !isName(term.id)
              ? "A name starts with a letter and uses lower-case letters, digits and underscores."
              : otherIds.includes(term.id)
                ? `Another goal is already called ${term.id}.`
                : null;
          return (
          <TreeItem
            key={position}
            name={term.id || "objective term"}
            defaultOpen={!simple || composedGoals.has(term.id)}
            openSignal={openGoal?.id === term.id ? openGoal.seq : undefined}
            collapsedHeader={simple ? <OneLine name={term.id || "goal"} text={term.expression ? `Counts ${termSentence(term.expression, context.relationships)}.` : "Counts nothing yet."}
              problems={term.expression ? checkGoal(term.expression, context).length : 1} /> : undefined}
            header={
              <div className="flex flex-wrap items-end gap-3">
                <div>
                  <label className="block text-xs text-slate-600" htmlFor={`obj-${position}-id`}>
                    Name
                  </label>
                  <input
                    id={`obj-${position}-id`}
                    className={`${INPUT_CLASS} w-48 text-sm`}
                    value={term.id}
                    aria-invalid={idProblem ? "true" : undefined}
                    aria-describedby={idProblem ? `obj-${position}-id-problem` : undefined}
                    onChange={(event) =>
                      onChange({
                        ...objective,
                        terms: objective.terms.map((t, i) =>
                          i === position ? { ...t, id: event.target.value } : t
                        ),
                      })
                    }
                  />
                  {idProblem && (
                    <p
                      id={`obj-${position}-id-problem`}
                      role="alert"
                      className="mt-1 text-xs text-red-600"
                    >
                      {idProblem}
                    </p>
                  )}
                </div>
                {lex ? (
                  <div>
                    <span className="block text-xs text-slate-600">Goal order</span>
                    <p className="mt-1 font-mono text-sm text-slate-900" data-testid={`goal-order-${position}`}>
                      {ordinal(position + 1)}
                    </p>
                  </div>
                ) : (
                  <div>
                    <label className="block text-xs text-slate-600" htmlFor={`obj-${position}-weight`}>
                      Weight
                    </label>
                    <input
                      id={`obj-${position}-weight`}
                      inputMode="numeric"
                      className={`${INPUT_CLASS} w-24 text-sm`}
                      value={String(term.weight)}
                      onChange={(event) => {
                        const next = Number(event.target.value);
                        if (/^[+-]?\d*$/.test(event.target.value) && Number.isSafeInteger(next)) {
                          onChange({
                            ...objective,
                            terms: objective.terms.map((t, i) =>
                              i === position ? { ...t, weight: next } : t
                            ),
                          });
                        }
                      }}
                    />
                  </div>
                )}
              </div>
            }
            actions={
              <span className="flex flex-wrap items-center gap-1">
                {lex && position > 0 && (
                  <button
                    type="button"
                    className="rounded px-2 py-1 text-sm text-slate-700 underline"
                    onClick={() => moveTerm(position, position - 1)}
                    aria-label={`Make ${term.id || "goal"} earlier`}
                  >
                    Earlier
                  </button>
                )}
                {lex && position < objective.terms.length - 1 && (
                  <button
                    type="button"
                    className="rounded px-2 py-1 text-sm text-slate-700 underline"
                    onClick={() => moveTerm(position, position + 1)}
                    aria-label={`Make ${term.id || "goal"} later`}
                  >
                    Later
                  </button>
                )}
                <button
                  type="button"
                  className="rounded px-2 py-1 text-sm text-red-700 underline"
                  onClick={() =>
                    onChange({ ...objective, terms: objective.terms.filter((_, i) => i !== position) })
                  }
                >
                  Remove
                </button>
              </span>
            }
          >
            {term.expression == null ? (
              <div className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                <p>This term is named but has nothing to count.</p>
                <button
                  type="button"
                  className="mt-2 rounded px-2 py-1 text-sm text-amber-950 underline"
                  onClick={() =>
                    onChange({
                      ...objective,
                      terms: objective.terms.map((t, i) =>
                        i === position ? { ...t, expression: { const: 0 } } : t
                      ),
                    })
                  }
                >
                  Start expressing it
                </button>
              </div>
            ) : (
              <GoalExpression
                view={view}
                startIn={composedGoals.has(term.id) ? "boxes" : undefined}
                goalId={term.id}
                expression={term.expression}
                context={context}
                onChange={(expression) =>
                  onChange({
                    ...objective,
                    terms: objective.terms.map((t, i) =>
                      i === position ? { ...t, expression } : t
                    ),
                  })
                }
              />
            )}
          </TreeItem>
          );
        })}
      </div>

{simple ? (
        <AddMenu label="Add a goal">
          {(close) => (
            <>
              {GOAL_SHAPES.map((shape) => (
                <AddChoice key={shape.shape} title={shape.title} disabledReason={shape.needs(context)}
                  hint="Filled in from this model's names; change any part afterwards."
                  onPick={() => {
                    const id = freeNumberedId("o_", objective.terms.map((term) => term.id));
                    setComposedGoals((current) => new Set(current).add(id));
                    onChange({ ...objective, terms: [...objective.terms, goalFromShape(shape.shape, id, context)] });
                    close();
                  }} />
              ))}
              <AddChoice title="A blank goal" hint="Start from nothing counted and build it in boxes."
                onPick={() => {
                  const id = freeNumberedId("o_", objective.terms.map((term) => term.id));
                  setComposedGoals((current) => new Set(current).add(id));
                  onChange({ ...objective, terms: [...objective.terms, { id, weight: 1, expression: { const: 0 } as Term }] });
                  close();
                }} />
            </>
          )}
        </AddMenu>
      ) : (
        <>
            <ShapePicker
        label="Start a goal from a shape"
        shapes={GOAL_SHAPES.map((s) => ({ value: s.shape, title: s.title, needs: s.needs(context) }))}
        onPick={(shape) => {
          const id = freeNumberedId("o_", objective.terms.map((term) => term.id));
          setComposedGoals((current) => new Set(current).add(id));
          onChange({ ...objective, terms: [...objective.terms, goalFromShape(shape as GoalShape, id, context)] });
        }}
      />
      <button
        type="button"
        className="mt-3 rounded border border-slate-300 px-3 py-2 text-sm text-slate-700"
        onClick={() =>
          onChange({
            ...objective,
            terms: [
              ...objective.terms,
              {
                id: freeNumberedId(
                  "o_",
                  objective.terms.map((term) => term.id)
                ),
                weight: 1,
                expression: { const: 0 } as Term,
              },
            ],
          })
        }
      >
        Add something to count
      </button>
        </>
      )}
    </div>
  );
}

/** 1 → 1st, 2 → 2nd, 11 → 11th — the place a lex goal takes in the order. */
function ordinal(n: number): string {
  const mod100 = n % 100;
  if (mod100 >= 11 && mod100 <= 13) return `${n}th`;
  switch (n % 10) {
    case 1:
      return `${n}st`;
    case 2:
      return `${n}nd`;
    case 3:
      return `${n}rd`;
    default:
      return `${n}th`;
  }
}

function relationLabel(relation: string): string {
  if (relation === "<=") return "at most";
  if (relation === ">=") return "at least";
  return "exactly";
}

function Choice({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
}) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="block text-xs text-slate-600">
        {label}
      </label>
      <select
        id={id}
        className={`${INPUT_CLASS} w-auto text-sm`}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}

function Note({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">{children}</div>
  );
}

function StartFromTemplates({
  domainId,
  problemId,
  onApplied,
}: {
  domainId: Id;
  problemId?: Id;
  onApplied: (result: ApplyTemplateResult) => void;
}) {
  const { can } = useCapabilities();
  const templates = useTemplates();
  const apply = useApplyTemplate();
  const [failure, setFailure] = useState<string | null>(null);
  if (!can("model.publish")) return null;
  const items = templates.data?.items ?? [];
  if (items.length === 0) return null;
  return (
    <div className="mt-3">
      {items.map((row) => (
        <button
          key={String(row.id)}
          type="button"
          disabled={apply.isPending}
          className="mr-2 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-60"
          onClick={() => {
            setFailure(null);
            apply.mutate(
              {
                id: row.id,
                body: problemId
                  ? { problem_id: problemId, domain_id: domainId }
                  : { domain_id: domainId },
              },
              {
                onSuccess: onApplied,
                onError: (error: unknown) => setFailure(formatApiError(error)),
              }
            );
          }}
        >
          {apply.isPending ? "Starting…" : `Start from “${exampleWords(row.name).title}”`}
        </button>
      ))}
      {failure && (
        <p role="alert" className="mt-2 text-sm text-red-600">
          {failure}
        </p>
      )}
    </div>
  );
}



/** "Start a rule from a shape": each shape, or why it cannot be offered yet. */
function ShapePicker({ label, shapes, onPick }: {
  label: string;
  shapes: { value: string; title: string; needs: string | null }[];
  onPick: (shape: string) => void;
}) {
  return (
    // Long shape titles must not stretch the select past the page (user trial): it takes the width there
    // is and no more, and the label keeps its words on one line.
    <label className="ml-2 mt-3 inline-flex min-w-0 max-w-full flex-wrap items-center gap-2 text-sm text-slate-700">
      <span className="whitespace-nowrap">{label}</span>
      <select aria-label={label} className="w-full min-w-0 max-w-xl truncate rounded border border-slate-300 bg-white px-2 py-2 text-sm sm:w-auto" value=""
        onChange={(event) => event.target.value && onPick(event.target.value)}>
        <option value="">choose…</option>
        {shapes.map((shape) => (
          <option key={shape.value} value={shape.value} disabled={shape.needs !== null}>
            {shape.title}{shape.needs ? ` (needs ${shape.needs})` : ""}
          </option>
        ))}
      </select>
    </label>
  );
}

/** A card closed to one line: its name, its sentence, and a mark for whether it checks out. */
function OneLine({ name, text, problems }: { name: string; text: string; problems: number }) {
  return (
    <span className="flex min-w-0 items-center gap-2 text-sm">
      <span aria-hidden="true" className={problems ? "text-rose-600" : "text-emerald-600"}>{problems ? "●" : "✓"}</span>
      <span className="shrink-0 font-mono text-xs text-slate-500">{name}</span>
      <span className="min-w-0 truncate text-slate-900" title={text}>{text}</span>
      {problems > 0 && <span className="shrink-0 text-xs text-rose-700">{problems} to fix</span>}
    </span>
  );
}
