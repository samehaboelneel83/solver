/**
 * Why a draft may not be published yet, and where in it: the contract's
 * shape rules at once (`checkIrShape`), then the domain's own -- a set that
 * is not one of its entity types, data it does not hold -- from the server's
 * dry run, asked once the draft has been still for half a second. The same
 * refusal Publish would meet, before Publish is pressed; `loc` lets the
 * block editor put it on the block that caused it.
 */
import { irRefusalOf, useValidateVersion, type Id } from "../api/v1";
import { checkIrShape } from "../ir";

export type DraftRefusal = { loc: (string | number)[]; message: string };

export function useDraftRefusal(problemId: Id | null | undefined, toPublish: Record<string, unknown> | null): DraftRefusal | null {
  const local = toPublish ? checkIrShape(toPublish) : null;
  // Only a draft the shape rules accept goes to the server: the local refusal is the one to fix first.
  const server = useValidateVersion(problemId, toPublish && !local ? toPublish : null);
  if (local) return { loc: local.loc, message: local.message };
  return server.isError ? irRefusalOf(server.error) : null;
}
