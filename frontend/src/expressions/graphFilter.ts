import type { EntityType } from "../api/v1";
import type { GraphResponse } from "../types/graph";
import type { ExpressionDocument } from "./document";
import {
  buildFieldCatalogue,
  RELATIONSHIP_DIRECTIONS,
  type FieldCatalogue,
  type RelationshipTypeRef,
} from "./fields";
import { degreeKey, evaluateExpression, type EvaluationTarget } from "./evaluate";

/**
 * The graph's adapter: what the loaded `GraphResponse` can honestly
 * answer.
 *
 * **The catalogue here offers no entity columns, deliberately.** The graph
 * wire contract carries `entity.attrs` verbatim and the relationships, but
 * not `key`, `sort_order` or `active` at all -- and its `label` is
 * `entity.label OR entity.key` (`graph/service.py:_node_label`), which is
 * not the `label` column. Offering them would mean the same document
 * filtered one way on this canvas and another way in Task 14d's SQL, which
 * is worse than a rule that cannot be written. (The brief lists the four
 * columns under the shared catalogue; they are there, and `buildFieldCatalogue`
 * serves them to a consumer that has them.)
 *
 * Filtering is client-side over the graph already in memory: no endpoint,
 * no round trip.
 */

export function graphCatalogue(
  entityTypes: readonly EntityType[],
  relationshipTypes: readonly RelationshipTypeRef[]
): FieldCatalogue {
  return buildFieldCatalogue({ entityTypes, relationshipTypes, columns: [] });
}

/**
 * One evaluation target per node, with its relationship counts.
 *
 * A node whose entity type is not in the payload is left out rather than
 * given a guessed type: it cannot satisfy a rule about any type's
 * attribute, and inventing one would make it satisfy the wrong one.
 */
export function graphTargets(graph: GraphResponse): Map<string, EvaluationTarget> {
  const entityTypeIdByName = new Map(graph.entity_types.map((t) => [t.name, t.id]));
  const relationshipTypeIdByName = new Map(graph.relationship_types.map((t) => [t.name, t.id]));

  const degrees = new Map<string, Map<string, number>>();
  const bump = (nodeId: string, relationshipTypeId: string, direction: (typeof RELATIONSHIP_DIRECTIONS)[number]) => {
    let byKey = degrees.get(nodeId);
    if (!byKey) {
      byKey = new Map();
      degrees.set(nodeId, byKey);
    }
    const key = degreeKey(relationshipTypeId, direction);
    byKey.set(key, (byKey.get(key) ?? 0) + 1);
  };

  for (const edge of graph.edges) {
    const relationshipTypeId = relationshipTypeIdByName.get(edge.type);
    if (relationshipTypeId === undefined) continue;
    bump(edge.source, relationshipTypeId, "outgoing");
    bump(edge.target, relationshipTypeId, "incoming");
    bump(edge.source, relationshipTypeId, "any");
    // A self-loop is ONE relationship row; counting it at both ends would
    // report two where the database holds one.
    if (edge.target !== edge.source) bump(edge.target, relationshipTypeId, "any");
  }

  const targets = new Map<string, EvaluationTarget>();
  for (const node of graph.nodes) {
    const entityTypeId = entityTypeIdByName.get(node.type);
    if (entityTypeId === undefined) continue;
    targets.set(node.id, {
      entityTypeId,
      columns: {},
      attrs: node.attributes ?? {},
      degrees: degrees.get(node.id) ?? new Map(),
    });
  }
  return targets;
}

/** The ids of the nodes the expression matches. */
export function matchingNodeIds(
  graph: GraphResponse,
  catalogue: FieldCatalogue,
  document: ExpressionDocument
): Set<string> {
  const targets = graphTargets(graph);
  const matched = new Set<string>();
  for (const node of graph.nodes) {
    const target = targets.get(node.id);
    if (!target) {
      // An untypable node cannot satisfy a rule -- except that an empty
      // expression constrains nothing, and it should not vanish then.
      if (document.query.rules.length === 0) matched.add(node.id);
      continue;
    }
    if (evaluateExpression(document, catalogue, target)) matched.add(node.id);
  }
  return matched;
}
