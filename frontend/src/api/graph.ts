import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";
import { formatApiError } from "./errors";
import { useEntityTypes, useRelationshipTypes, validationErrors, type Id } from "./v1";
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
  mode: GraphMode
): GraphView {
  const isTypes = mode === "types";
  const objects = useGraph(domainId, hierarchyTypeId, { enabled: !isTypes });
  const entityTypes = useEntityTypes(domainId, { limit: 500 }, { enabled: isTypes });
  const relationshipTypes = useRelationshipTypes(domainId, { limit: 500 }, { enabled: isTypes });

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

  if (!isTypes) {
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
        : item.msg;
    })
    .join("\n");
}
