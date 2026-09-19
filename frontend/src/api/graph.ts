import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";
import { formatApiError } from "./errors";
import { validationErrors, type Id } from "./v1";
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

export function useGraph(domainId: Id | null, hierarchyTypeId: Id | null) {
  return useQuery({
    queryKey: graphQueryKey(domainId, hierarchyTypeId),
    queryFn: () => apiFetch<GraphResponse>(graphQueryPath(domainId as Id, hierarchyTypeId)),
    enabled: domainId !== null && domainId !== undefined,
  });
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
