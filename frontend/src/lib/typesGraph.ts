/**
 * The graph's two modes, and the colours each one draws with.
 *
 * **Objects** (the default, and what the canvas has always drawn) is one
 * node per `entity` and one edge per `relationship`, and it comes from
 * `GET /api/v1/graph`.
 *
 * **Types** is the domain's *schema*: one node per `entity_type`, one edge
 * per `relationship_type` drawn `from_type_id → to_type_id`, so a
 * self-referencing hierarchy is a loop on its own node. It needs **no new
 * endpoint** -- `useEntityTypes` and `useRelationshipTypes` already return
 * every field it draws, including `cardinality`, `is_hierarchy` and now
 * `colour` -- so it is built here, on the client, from those two lists.
 *
 * Two things are worth knowing about the shape it builds:
 *
 * **Ids are namespaced.** A types node is `type-<id>` and a types edge is
 * `reltype-<id>`, because an entity and an entity type can perfectly well
 * share the number 3. Without the prefixes a mode switch would look to
 * `applyGraphToCy` like an *update* of the same elements (wrong labels,
 * stale positions, no relayout), and a `?focus=<entityId>` deep link could
 * match a type node. With them, switching modes is a clean
 * remove-everything/add-everything, which is what triggers a fresh layout.
 *
 * **A types node's `type` is its entity type's ROLE, not its name.** That
 * is what the filter bar filters on, and filtering the schema by role
 * (agents, resources, tasks...) is the only grouping a schema view has --
 * filtering types by their own names would just duplicate the search box.
 * Colours therefore cannot be resolved through `node.type` in this mode,
 * which is why the palette is built here rather than derived later.
 */

import type { EntityType, RelationshipType, Cardinality } from "../api/v1";
// Moved to `lib/cardinality` when the relationship-type form became its
// third consumer (Task 14f); re-exported so the graph's own readers keep
// importing it from the module that draws with it.
import { CARDINALITY_LABEL } from "./cardinality";
export { CARDINALITY_LABEL };
import type { GraphResponse } from "../types/graph";
import { labelForeground, typeColour } from "./colour";

export type GraphMode = "objects" | "types";

/**
 * Per-element drawing colours, keyed by the id `applyGraphToCy` writes into
 * cytoscape. Separate from `GraphResponse` on purpose: that type mirrors
 * the server's wire contract byte for byte, and a client-side derivation
 * has no business inside it.
 */
export type GraphPalette = {
  /** node id -> node fill, `#rrggbb`. */
  nodeFill: Record<string, string>;
  /** node id -> the label colour that is readable on that fill. */
  nodeLabel: Record<string, string>;
  /** edge id -> line and arrow colour, `#rrggbb`. */
  edgeColour: Record<string, string>;
};

export const EMPTY_PALETTE: GraphPalette = { nodeFill: {}, nodeLabel: {}, edgeColour: {} };

export const TYPE_NODE_PREFIX = "type-";
export const TYPE_EDGE_PREFIX = "reltype-";

export function typeNodeId(entityTypeId: number | string): string {
  return `${TYPE_NODE_PREFIX}${entityTypeId}`;
}

export function typeEdgeId(relationshipTypeId: number | string): string {
  return `${TYPE_EDGE_PREFIX}${relationshipTypeId}`;
}

/** The entity type id behind a types-mode node id, or null if that is not
 * what the id is. */
export function entityTypeIdFromNodeId(nodeId: string): number | null {
  return idAfter(nodeId, TYPE_NODE_PREFIX);
}

/** The relationship type id behind a types-mode edge id, or null. */
export function relationshipTypeIdFromEdgeId(edgeId: string): number | null {
  return idAfter(edgeId, TYPE_EDGE_PREFIX);
}

function idAfter(value: string, prefix: string): number | null {
  if (!value.startsWith(prefix)) return null;
  const rest = value.slice(prefix.length);
  if (!/^[1-9][0-9]*$/.test(rest)) return null;
  const id = Number(rest);
  return Number.isSafeInteger(id) ? id : null;
}

/** The second line of a types edge's label: what the model says about this
 * relationship, which is the whole reason to look at the schema. */
export function relationshipTypeLabel(type: {
  name: string;
  cardinality: Cardinality;
  is_hierarchy: boolean;
}): string {
  const shape = CARDINALITY_LABEL[type.cardinality] ?? type.cardinality;
  return `${type.name}\n${shape}${type.is_hierarchy ? " · hierarchy" : ""}`;
}

function paletteEntry(palette: GraphPalette, nodeId: string, fill: string): void {
  palette.nodeFill[nodeId] = fill;
  palette.nodeLabel[nodeId] = labelForeground(fill);
}

/**
 * The colours for an objects-mode graph, resolved through each element's
 * TYPE: a node is drawn in its entity type's colour, an edge in its
 * relationship type's. `GraphNode.type` is the entity type's *name*
 * (Task 7's mapping), which is the only handle the payload gives, so the
 * type options are looked up by name -- and the fallback is keyed by the
 * option's **id**, so it survives a rename.
 */
export function objectsPalette(graph: GraphResponse): GraphPalette {
  const palette: GraphPalette = { nodeFill: {}, nodeLabel: {}, edgeColour: {} };
  const entityTypeByName = new Map(graph.entity_types.map((option) => [option.name, option]));
  const relationshipTypeByName = new Map(
    graph.relationship_types.map((option) => [option.name, option])
  );
  for (const node of graph.nodes) {
    const option = entityTypeByName.get(node.type);
    // A node whose type is missing from the options can only happen if the
    // two halves of the payload disagree; keying the fallback on the name
    // keeps it stable rather than throwing.
    paletteEntry(palette, node.id, typeColour(option ?? { id: node.type, colour: null }));
  }
  for (const edge of graph.edges) {
    const option = relationshipTypeByName.get(edge.type);
    palette.edgeColour[edge.id] = typeColour(option ?? { id: edge.type, colour: null });
  }
  return palette;
}

/**
 * The types-mode graph and its palette, from the two lists the API already
 * serves.
 *
 * A relationship type whose `from_type_id` or `to_type_id` is not among
 * the given entity types is dropped: cytoscape throws synchronously on an
 * edge to a node it was not given. Migration 0009's rule 3 now makes that
 * impossible in the database, but the lists are paginated, so a domain
 * with more than 500 entity types could still produce one.
 */
export function buildTypesView(
  entityTypes: readonly EntityType[],
  relationshipTypes: readonly RelationshipType[]
): { graph: GraphResponse; palette: GraphPalette } {
  const palette: GraphPalette = { nodeFill: {}, nodeLabel: {}, edgeColour: {} };
  const known = new Set(entityTypes.map((type) => String(type.id)));

  const nodes = entityTypes.map((type) => {
    const nodeId = typeNodeId(type.id);
    paletteEntry(palette, nodeId, typeColour({ id: String(type.id), colour: type.colour }));
    return {
      id: nodeId,
      // The ROLE, not the name -- see this module's header.
      type: type.role,
      label: type.name,
      parent: null,
      attributes: { role: type.role, attributes: type.attributes.length },
    };
  });

  const drawable = relationshipTypes.filter(
    (type) => known.has(String(type.from_type_id)) && known.has(String(type.to_type_id))
  );
  const edges = drawable.map((type) => {
    const edgeId = typeEdgeId(type.id);
    palette.edgeColour[edgeId] = typeColour({ id: String(type.id), colour: type.colour });
    return {
      id: edgeId,
      source: typeNodeId(type.from_type_id),
      target: typeNodeId(type.to_type_id),
      type: type.name,
      label: relationshipTypeLabel(type),
      attributes: { cardinality: type.cardinality, is_hierarchy: type.is_hierarchy },
    };
  });

  // One filter option per role actually present, so the bar offers what is
  // on the canvas rather than the whole `ENTITY_ROLES` list. `name` is what
  // FilterBar matches against `node.type`, so it must be the raw role.
  const roles = [...new Set(entityTypes.map((type) => type.role))].sort();

  return {
    graph: {
      nodes,
      edges,
      entity_types: roles.map((role) => ({
        id: `role-${role}`,
        code: role,
        name: role,
        is_abstract: false,
        colour: null,
      })),
      relationship_types: drawable.map((type) => ({
        id: typeEdgeId(type.id),
        code: type.name,
        name: type.name,
        is_directed: true,
        source_entity_type: null,
        target_entity_type: null,
        colour: type.colour,
      })),
      // Nothing nests in the schema view: the hierarchy picker is about
      // which relationship rows nest *entities*, and there are no rows here.
      hierarchies: [],
      attribute_definitions: [],
    },
    palette,
  };
}
