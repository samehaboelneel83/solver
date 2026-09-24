import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import BlocksEditor from "../BlocksEditor";
import { useToast } from "../ToastProvider";
import { formatApiError } from "../../api/errors";
import { useCreateVersion, useEntityTypes, useParameters, useRelationshipTypes, type Id } from "../../api/v1";
import { checkIrShape } from "../../ir";
import { catalogueFrom } from "../../lib/irBlocks/catalogue";
import DraftBar, { DraftConflict } from "../../model/DraftBar";
import { EMPTY_MODEL, publishable } from "../../model/draftIr";
import { clearDraft, readDraft, updateDraftIr, useModelDraft, writeDraft, type DraftBase } from "../../model/draftStore";

export type BlocklyEditProps = {
  domainId: Id;
  problemId: Id;
  /** The version on screen, the draft's starting point; null for a problem with no model yet. */
  versionId: Id | null;
  versionNumber: number | null;
  /** That version's IR (undefined while it loads, or when there is none). */
  ir: Record<string, unknown> | null | undefined;
  /** Move the view to another version: the one just published, or the one a draft started from. */
  onVersion: (versionId: Id) => void;
};

/**
 * The optimization view's Edit mode (Blockly edit mode spec §6): the model
 * as editable blocks over the same shared draft the Model editor's forms and
 * Blocks tab edit, with the same bar -- unpublished changes, Publish, Discard.
 * Publishing writes a new version and moves the view to it.
 */
export default function BlocklyEdit({ domainId, problemId, versionId, versionNumber, ir, onVersion }: BlocklyEditProps) {
  const entityTypes = useEntityTypes(domainId, { limit: 500, offset: 0 });
  const relationshipTypes = useRelationshipTypes(domainId, { limit: 500, offset: 0 });
  const parameters = useParameters(domainId, { limit: 500, offset: 0 });
  const createVersion = useCreateVersion();
  const toast = useToast();
  const [failure, setFailure] = useState<string | null>(null);
  const [outside, setOutside] = useState(0);
  // A draft started from scratch, continued over a problem that has versions.
  const [scratchChosen, setScratchChosen] = useState(false);

  const problem = Number(problemId);
  const stored = useModelDraft(problem);
  const scratch = versionId === null || (scratchChosen && stored?.base === "scratch");
  const seedKey: DraftBase = scratch ? "scratch" : `version-${Number(versionId)}`;
  const conflict = stored !== null && stored.base !== seedKey;
  const baseIr = scratch ? (EMPTY_MODEL as unknown as Record<string, unknown>) : ir ?? null;
  const workingIr = !conflict && stored ? stored.ir : baseIr;

  const catalogue = useMemo(
    () => catalogueFrom(entityTypes.data?.items ?? [], parameters.data?.items ?? [], relationshipTypes.data?.items ?? []),
    [entityTypes.data, parameters.data, relationshipTypes.data]
  );
  const toPublish = useMemo(() => (workingIr ? publishable(workingIr) : null), [workingIr]);
  const refusal = toPublish ? checkIrShape(toPublish) : null;

  if (conflict && stored) {
    return (
      <div className="p-4">
        <DraftConflict
          draft={stored}
          shownVersion={scratch ? null : versionNumber}
          onContinue={() => {
            if (stored.base === "scratch") setScratchChosen(true);
            else onVersion(Number(stored.base.slice("version-".length)));
          }}
          onStartAgain={() => clearDraft(problem)}
        />
      </div>
    );
  }
  if (!workingIr || entityTypes.isLoading || parameters.isLoading || relationshipTypes.isLoading) {
    return (
      <p role="status" className="p-4 text-sm text-slate-500">
        Loading the model as blocks…
      </p>
    );
  }

  function setIr(next: Record<string, unknown>) {
    if (readDraft(problem)) updateDraftIr(problem, () => next);
    else writeDraft({ problemId: problem, base: seedKey, baseVersion: scratch ? null : versionNumber, ir: next });
  }

  function publish() {
    if (!toPublish) return;
    setFailure(null);
    createVersion.mutate(
      { problemId, body: { ir: toPublish, note: "edited as blocks in the optimization view" } },
      {
        onSuccess: (created: { id: Id; version: number }) => {
          toast.success(`Published version ${created.version}`);
          clearDraft(problem);
          setScratchChosen(false);
          onVersion(created.id);
        },
        onError: (error: unknown) => setFailure(formatApiError(error)),
      }
    );
  }

  const blocked =
    outside > 0
      ? `${outside} ${outside === 1 ? "block is" : "blocks are"} outside the model: put ${outside === 1 ? "it" : "them"} inside, or delete ${outside === 1 ? "it" : "them"}`
      : refusal
        ? refusal.message
        : null;

  return (
    <div className="flex h-full flex-col gap-2 p-2" data-testid="blockly-edit">
      <div className="min-h-0 flex-1">
        <BlocksEditor
          ir={workingIr}
          catalogue={catalogue}
          fill
          onChange={(next, _paths, left) => {
            setOutside(left);
            setIr(next);
          }}
        />
      </div>
      {refusal && (
        <p role="alert" className="text-sm text-red-600">
          {refusal.message}
        </p>
      )}
      {failure && (
        <p role="alert" className="whitespace-pre-line text-sm text-red-600">
          {failure}
        </p>
      )}
      <DraftBar
        draft={stored}
        publishing={createVersion.isPending}
        blocked={blocked}
        onPublish={publish}
        onDiscard={() => clearDraft(problem)}
      />
      <p className="text-xs text-slate-500">
        Drag blocks from the toolbox on the left into the model. The{" "}
        <Link className="underline" to={`/model?problem=${problemId}`}>
          Model editor
        </Link>
        &rsquo;s forms edit the same draft, and are the keyboard and screen-reader way to edit it.
      </p>
    </div>
  );
}
