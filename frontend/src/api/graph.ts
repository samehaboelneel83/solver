import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";
import { formatApiError } from "./errors";
import { useEntityTypes, useRelationshipTypes, useVersion, validationErrors, type Id } from "./v1";
import { buildModelView } from "../lib/modelGraph";

// What the optimization view shows before there is a model to draw.
const EMPTY_MODEL = buildModelView({}, []);
import {
  EMPTY_PALETTE,
  buildTypesView,
  objectsPalette,
  type GraphMode,
  type GraphPalette,
} from "../lib/typesGraph";
import type { GraphResponse } from "../types/graph";

/**
 * The graph read, and the one piece of error handling the canvas needs that
 * the shared formatter cannot do.
 *
 * Reads only. Every write the graph editor performs goes through the v1
 * routers' own hooks in `api/v1.ts` (`useCreateEntity`,
 * `useCreateRelationship`, ...): schema v1 removed the graph-specific write
 * routes deliberately (Ruling 22), because they were a second
 * implementation of rules the database owns. The query key lives under the
 * same `"v1"` prefix those mutations invalidate, so creating an entity or a
 * relationship redraws the canvas without any extra wiring.
 */

export function graphQueryPath(domainId: Id, hierarchyTypeId: Id | null): string {
  const params = new URLSearchParams({ domain_id: String(domainId) });
  if (hierarchyTypeId !== null && hierarchyTypeId !== undefined) {
    // The nesting comes from ONE relationship type's rows -- without this the
    // graph comes back flat (every node's `parent` is null), which is the
    // "No hierarchy nesting" option.
    params.set("hierarchy_type_id", String(hierarchyTypeId));
  }
  return `/api/v1/graph?${params.toString()}`;
}

export function graphQueryKey(domainId: Id | null, hierarchyTypeId: Id | null) {
  return ["v1", "graph", domainId, hierarchyTypeId] as const;
}

export function useGraph(
  domainId: Id | null,
  hierarchyTypeId: Id | null,
  options: { enabled?: boolean } = {}
) {
  return useQuery({
    queryKey: graphQueryKey(domainId, hierarchyTypeId),
    queryFn: () => apiFetch<GraphResponse>(graphQueryPath(domainId as Id, hierarchyTypeId)),
    // `enabled` is how the types view avoids requesting a graph it will not
    // draw -- see `useGraphView`.
    enabled: domainId !== null && domainId !== undefined && options.enabled !== false,
  });
}

/** What both halves of the graph page consume, whichever mode is showing:
 * the same `GraphResponse` shape plus the colours to draw it in. Shaped
 * like a React Query result so the page's loading/offline/error branches
 * did not have to grow a second set. */
export type GraphView = {
  data: GraphResponse | undefined;
  palette: GraphPalette;
  isLoading: boolean;
  error: Error | null;
  fetchStatus: "fetching" | "paused" | "idle";
  refetch: () => void;
  /** The optimization view only: the IR the graph was built from, which
   * the Blockly style draws term by term. */
  ir?: Record<string, unknown> | null;
};

/**
 * The graph for `mode`.
 *
 * **Objects** is `GET /api/v1/graph`, unchanged. **Types** is built on the
 * client from `useEntityTypes` and `useRelationshipTypes` -- the brief's
 * "no new endpoint", and correct rather than merely cheap: those two
 * queries are already in flight for the create-node form and the property
 * panel, React Query serves them once, and every mutation that changes a
 * type already invalidates them, so the schema view refreshes itself.
 *
 * Both hooks are called unconditionally (rules of hooks); only the
 * inactive one's `enabled` is false, so the mode that is not showing costs
 * no request.
 */
export function useGraphView(
  domainId: Id | null,
  hierarchyTypeId: Id | null,
  mode: GraphMode,
  // The model version the optimization view draws; ignored by the others.
  modelVersionId: Id | null = null
): GraphView {
  const isTypes = mode === "types";
  const isModel = mode === "model";
  const objects = useGraph(domainId, hierarchyTypeId, { enabled: mode === "objects" });
  // The model's sets are entity types, drawn in their colours, so the
  // optimization view reads the same list the ERD does.
  const entityTypes = useEntityTypes(domainId, { limit: 500 }, { enabled: isTypes || isModel });
  const relationshipTypes = useRelationshipTypes(domainId, { limit: 500 }, { enabled: isTypes });
  const version = useVersion(isModel ? modelVersionId : null);

  const objectsData = objects.data;
  const typeItems = entityTypes.data?.items;
  const relationshipItems = relationshipTypes.data?.items;

  const built = useMemo(
    () => (typeItems && relationshipItems ? buildTypesView(typeItems, relationshipItems) : null),
    [typeItems, relationshipItems]
  );
  const objectsColours = useMemo(
    () => (objectsData ? objectsPalette(objectsData) : null),
    [objectsData]
  );
  const ir = version.data?.ir;
  const model = useMemo(
    () => (isModel && ir && typeItems ? buildModelView(ir, typeItems) : null),
    [isModel, ir, typeItems]
  );

  if (isModel) {
    return {
      // No version to draw (a domain with no problems, or a problem with no
      // versions) is an empty drawing, not a load that never finishes.
      data: model?.graph ?? (modelVersionId === null && !entityTypes.isLoading ? EMPTY_MODEL.graph : undefined),
      palette: model?.palette ?? EMPTY_PALETTE,
      ir: (ir as Record<string, unknown> | undefined) ?? null,
      isLoading: entityTypes.isLoading || (modelVersionId !== null && version.isLoading),
      error: entityTypes.error ?? version.error ?? null,
      fetchStatus:
        entityTypes.fetchStatus === "paused" || version.fetchStatus === "paused"
          ? "paused"
          : entityTypes.fetchStatus === "fetching" || version.fetchStatus === "fetching"
            ? "fetching"
            : "idle",
      refetch: () => {
        void entityTypes.refetch();
        void version.refetch();
      },
    };
  }

  if (mode === "objects") {
    return {
      data: objectsData,
      palette: objectsColours ?? EMPTY_PALETTE,
      isLoading: objects.isLoading,
      error: objects.error,
      fetchStatus: objects.fetchStatus,
      refetch: () => void objects.refetch(),
    };
  }
  return {
    data: built?.graph,
    palette: built?.palette ?? EMPTY_PALETTE,
    isLoading: entityTypes.isLoading || relationshipTypes.isLoading,
    error: entityTypes.error ?? relationshipTypes.error ?? null,
    // Offline, React Query pauses rather than fails; the page needs to know
    // that about whichever query is actually paused.
    fetchStatus:
      entityTypes.fetchStatus === "paused" || relationshipTypes.fetchStatus === "paused"
        ? "paused"
        : entityTypes.fetchStatus === "fetching" || relationshipTypes.fetchStatus === "fetching"
          ? "fetching"
          : "idle",
    refetch: () => {
      void entityTypes.refetch();
      void relationshipTypes.refetch();
    },
  };
}

/** The fields a relationship write actually carries in its body. Anything
 * else in a 422's `loc` is not a field of the request. */
const RELATIONSHIP_BODY_FIELDS = new Set([
  "relationship_type_id",
  "from_entity_id",
  "to_entity_id",
  "attrs",
  "valid_from",
  "valid_to",
]);

/**
 * A relationship write's failure as one readable message.
 *
 * `relationship_validate` names the **relationship type** in `field`, not a
 * column (Task 7), so a cardinality, cycle or type_mismatch 422 arrives at
 * `loc: ["body", "reports_to"]`. `formatApiError` renders every list-shaped
 * 422 as "<field>: <msg>", which for those reads
 * `reports_to: relationship "reports_to": would create a cycle` -- the type
 * named twice, once as a field that is not on screen.
 *
 * The branch is on `loc`, not on `kind` (Ruling 30): an entry whose `loc`
 * names a real body field keeps its field prefix, and anything else is the
 * trigger talking about the relationship as a whole, so its message stands
 * alone. A `kind` this code has never seen therefore still renders as a
 * sentence rather than as raw JSON.
 */
export function relationshipErrorMessage(err: unknown): string {
  const items = validationErrors(err);
  if (items.length === 0) return formatApiError(err);
  return items
    .map((item) => {
      const field = item.loc?.[1];
      return typeof field === "string" && RELATIONSHIP_BODY_FIELDS.has(field)
        ? `${field}: ${item.msg}`
        : rewordTriggerMessage(item.msg);
    })
    .join("\n");
}

/**
 * `relationship_validate`'s two cardinality refusals, in the words the
 * forms use.
 *
 * The trigger says `relationship "supplied_to": source already has a
 * target`. "Source" and "target" appear nowhere else in this UI -- every
 * form, column heading and hint calls the two ends **From** and **To** --
 * and the sentence never said what to do about it, so the reader was left
 * holding a rule in a vocabulary they had not been taught, and no way out
 * of it.
 *
 * Matched on the SENTENCE, not on `kind`. `kind` is `cardinality` for
 * both of these and says nothing about WHICH end is full, and the cycle
 * and type-mismatch refusals arrive at the same `loc`; the sentence is
 * the only thing that identifies the rule that fired. Anything not
 * recognised here -- including a rule added to the trigger later --
 * passes through unchanged rather than being mangled into a guess.
 */
const TRIGGER_REWORDINGS: { pattern: RegExp; reword: (name: string) => string }[] = [
  {
    // `many_to_one` / `one_to_one`: the From end may hold only one edge.
    pattern: /^relationship "(.+)": source already has a target$/,
    reword: (name) =>
      `"${name}" allows each From entity at most one To entity, and this From entity already has one. ` +
      `Delete the existing "${name}" relationship first, or change the cardinality of the type.`,
  },
  {
    // `one_to_many` / `one_to_one`: the To end may hold only one edge --
    // for a hierarchy, this is "that child already has a parent".
    pattern: /^relationship "(.+)": target already has a source$/,
    reword: (name) =>
      `"${name}" allows each To entity at most one From entity, and this To entity already has one. ` +
      `Delete the existing "${name}" relationship first, or change the cardinality of the type.`,
  },
];

/** A trigger sentence about the relationship as a whole, reworded where
 * this app has better words for it. Exported so the screens that show
 * these refusals outside the graph share exactly one wording. */
export function rewordTriggerMessage(message: string): string {
  for (const { pattern, reword } of TRIGGER_REWORDINGS) {
    const match = pattern.exec(message);
    if (match) return reword(match[1]);
  }
  return message;
}
