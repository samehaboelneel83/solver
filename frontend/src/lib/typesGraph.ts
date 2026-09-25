/**
 * The graph's two modes, and the colours each one draws with.
 *
 * **Objects** (the default, and what the canvas has always drawn) is one
 * node per `entity` and one edge per `relationship`, and it comes from
 * `GET /api/v1/graph`.
 *
 * **Types** is the domain's *schema*, drawn as an entity-relationship
 * diagram in Chen's notation -- the picture people already know how to read:
 *
 * - an entity type is a **rectangle**;
 * - a relationship type is a **diamond**, joined to the two types it relates
 *   by plain lines that carry the cardinality at each end (`1`, `n`, `m`),
 *   so a self-referencing hierarchy is a diamond with both lines on one
 *   rectangle;
 * - an attribute is an **ellipse** around its owner, in the owner's chosen
 *   sort order (migration 0027), and the entity's `key` -- what model
 *   expressions address an entity by -- is the underlined one, as a primary
 *   key is in the notation.
 *
 * It needs **no new endpoint** -- `useEntityTypes` and
 * `useRelationshipTypes` already return every field it draws, including
 * `cardinality`, `is_hierarchy`, `colour` and each type's attributes -- so
 * it is built here, on the client, from those two lists.
 *
 * **A diamond is a node, and it still selects as the relationship type.**
 * The panel beside the canvas resolves a selection by id prefix, so the
 * diamond keeps the `reltype-<id>` id the old edge had and reports itself as
 * an *edge* selection; tapping one of its lines does the same, and tapping
 * an attribute selects its owner. The side panel did not have to learn
 * anything about the drawing.
 *
 * Two things are worth knowing about the shape it builds:
 *
 * **Ids are namespaced.** An entity type is `type-<id>`, a relationship
 * type's diamond `reltype-<id>`, an attribute `attr-<id>` and a key
 * `typekey-<id>`, because an entity and an entity type can perfectly well
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

import type { Cardinality, EntityType, RelationshipType } from "../api/v1";
// Moved to `lib/cardinality` when the relationship-type form became its
// third consumer (Task 14f); re-exported so the graph's own readers keep
// importing it from the module that draws with it.
import { CARDINALITY_LABEL } from "./cardinality";
export { CARDINALITY_LABEL };
import type { GraphResponse } from "../types/graph";
import { labelForeground, typeColour } from "./colour";
import { nodeImage } from "./entityIcons";

/** The three views: `types` is the ERD, `objects` the entity graph, and
 * `model` the optimization view (lib/modelGraph.ts). The values predate the
 * button labels and are kept, because they are in stored preferences and in
 * links (`?mode=types`). */
export type GraphMode = "objects" | "types" | "model";

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
  /**
   * Extra cytoscape data per node / per edge, merged in by `applyGraphToCy`.
   * The ER drawing's shapes, sizes and end labels travel here, and the
   * stylesheet selects on them (`node[er = "entity"]`); `selectKind` and
   * `selectId` say what tapping the element selects. Optional, because the
   * objects view needs none of it.
   */
  nodeData?: Record<string, ErData>;
  edgeData?: Record<string, ErData>;
};

/** What an element of the ER drawing carries beyond its label and colour. */
export type ErData = {
  er:
    | "entity"
    | "relationship"
    | "attribute"
    | "connector"
    | "attribute-link"
    // A type inheriting from another (queue R18): child -> parent, the notation's open triangle.
    | "inherits"
    // The optimization view (lib/modelGraph.ts).
    | "set"
    | "variable"
    | "parameter"
    | "constraint"
    | "objective"
    | "uses"
    | "ranges"
    // The objects view (Graph View): an entity drawn as its type's picture,
    // and a compound node (one with children), which keeps the tinted box.
    | "object"
    | "object-group";
  /** Drawn width in px, estimated from the label (nodes only). */
  w?: number;
  /** Drawn height in px, for an `object` node's picture. */
  h?: number;
  /** An `object` node's picture, a `data:` URI (`lib/entityIcons.ts`). */
  image?: string;
  /** A connector's cardinality at its entity end: `1`, `n` or `m`. */
  end?: string;
  /** Which end of the connector the entity is at, so the cardinality is
   * drawn beside it. The `from` line runs entity -> diamond and the `to`
   * line diamond -> entity, which is what lets a layered layout set the
   * diamond between the two types. */
  endAt?: "source" | "target";
  /** Hierarchy diamonds draw a double border. */
  hierarchy?: "yes" | "no";
  /** A rule that may bend draws a dashed border (optimization view). */
  soft?: "yes" | "no";
  /** An ellipse's place among its owner's, from 0 (the key). The layout
   * reads this rather than trusting collection order. */
  seq?: number;
  /** What a tap on this element selects, when it is not the element itself. */
  selectKind?: "node" | "edge";
  selectId?: string;
};

export const EMPTY_PALETTE: GraphPalette = { nodeFill: {}, nodeLabel: {}, edgeColour: {} };

/** The attribute-ellipse ids. Namespaced like the rest. */
export const ATTRIBUTE_NODE_PREFIX = "attr-";
export const KEY_NODE_PREFIX = "typekey-";

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
  // Migration 0033: an entity is drawn as its type's picture. A node with
  // children is a compound box, which a picture would sit on top of, so it
  // is marked `object-group` and keeps the tinted box -- set explicitly
  // rather than left out, because `applyGraphToCy` MERGES data and a node
  // that gains a child would otherwise keep its old `er: "object"`.
  palette.nodeData = {};
  const parents = new Set(graph.nodes.map((node) => node.parent).filter(Boolean));
  for (const node of graph.nodes) {
    const option = entityTypeByName.get(node.type);
    // A node whose type is missing from the options can only happen if the
    // two halves of the payload disagree; keying the fallback on the name
    // keeps it stable rather than throwing.
    const fill = typeColour(option ?? { id: node.type, colour: null });
    paletteEntry(palette, node.id, fill);
    if (parents.has(node.id)) {
      palette.nodeData[node.id] = { er: "object-group" };
    } else {
      const drawn = nodeImage({
        name: option?.name ?? node.type,
        role: option?.role,
        icon: option?.icon,
        colour: fill,
      });
      palette.nodeData[node.id] = { er: "object", image: drawn.image, w: drawn.w, h: drawn.h };
    }
  }
  for (const edge of graph.edges) {
    const option = relationshipTypeByName.get(edge.type);
    palette.edgeColour[edge.id] = typeColour(option ?? { id: edge.type, colour: null });
  }
  return palette;
}

/**
 * Each end of a relationship, as Chen writes it beside the entity at that
 * end: one employee `has_rank` one rank is `1` and `1`; a customer who
 * `has` many accounts is `1` beside Customer and `n` beside Account; and
 * many-to-many is `m` and `n`, so the two ends read as two independent
 * "many"s rather than as the same number twice.
 */
export const CARDINALITY_ENDS: Record<Cardinality, { from: string; to: string }> = {
  one_to_one: { from: "1", to: "1" },
  one_to_many: { from: "1", to: "n" },
  many_to_one: { from: "n", to: "1" },
  many_to_many: { from: "m", to: "n" },
};

/** Combining low line after every character: the only underline a canvas
 * label can have, and the notation's mark for a key. */
export function underlined(text: string): string {
  return [...text].map((char) => `${char}̲`).join("");
}

/** A label's drawn width, estimated. Cytoscape needs a number before it has
 * drawn anything, and an estimate that is a little generous is what keeps
 * the text inside its shape. */
function textWidth(text: string, pxPerChar: number): number {
  return [...text.replace(/̲/g, "")].length * pxPerChar;
}

function byChosenOrder(a: { sort_order?: number; name: string }, b: { sort_order?: number; name: string }) {
  return (a.sort_order ?? 0) - (b.sort_order ?? 0) || a.name.localeCompare(b.name);
}

/**
 * The types-mode graph and its palette, from the two lists the API already
 * serves, drawn as an ER diagram (see this module's header).
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
  const nodeData: Record<string, ErData> = {};
  const edgeData: Record<string, ErData> = {};
  const palette: GraphPalette = { nodeFill: {}, nodeLabel: {}, edgeColour: {}, nodeData, edgeData };
  const known = new Set(entityTypes.map((type) => String(type.id)));
  const nodes: GraphResponse["nodes"] = [];
  const edges: GraphResponse["edges"] = [];

  // An ellipse per attribute, and a grey line to whatever owns it. The
  // ellipse is white with dark text whatever its owner's colour: it is a
  // property of the owner, not a thing in its own right, and a canvas of
  // forty coloured ellipses would drown the rectangles it is describing.
  const seqByOwner = new Map<string, number>();
  const addAttribute = (id: string, label: string, ownerId: string, ownerType: string, selectKind: "node" | "edge") => {
    const seq = seqByOwner.get(ownerId) ?? 0;
    seqByOwner.set(ownerId, seq + 1);
    nodes.push({
      id,
      // The owner's role, so the role filter takes the ellipse with it.
      type: ownerType,
      label,
      parent: null,
      attributes: { er: "attribute", owner: ownerId },
    });
    palette.nodeFill[id] = "#ffffff";
    palette.nodeLabel[id] = "#0f172a";
    nodeData[id] = {
      er: "attribute",
      w: Math.max(60, textWidth(label, 7.6) + 28),
      seq,
      selectKind,
      selectId: ownerId,
    };
    const linkId = `attrlink-${id}`;
    edges.push({ id: linkId, source: ownerId, target: id, type: "attribute", label: "", attributes: {} });
    palette.edgeColour[linkId] = "#94a3b8";
    edgeData[linkId] = { er: "attribute-link", selectKind, selectId: ownerId };
  };

  for (const type of entityTypes) {
    const nodeId = typeNodeId(type.id);
    paletteEntry(palette, nodeId, typeColour({ id: String(type.id), colour: type.colour }));
    nodes.push({
      id: nodeId,
      // The ROLE, not the name -- see this module's header.
      type: type.role,
      label: type.name,
      parent: null,
      attributes: { er: "entity", role: type.role, attributes: (type.own_attributes ?? type.attributes).length },
    });
    nodeData[nodeId] = { er: "entity", w: Math.max(100, textWidth(type.name, 10.2) + 40) };

    // Every entity has a key -- a column, not an attribute_def -- and it is
    // how a model addresses the entity, so it is drawn first and underlined,
    // the way the notation marks a primary key.
    addAttribute(`${KEY_NODE_PREFIX}${type.id}`, underlined("key"), nodeId, type.role, "node");
    // The API already returns them in their chosen order (0027); sorting
    // again keeps the drawing right if a caller hands over another order.
    // The type's own attributes: an inherited one is drawn once, on the type that declares it.
    for (const attribute of [...(type.own_attributes ?? type.attributes)].sort(byChosenOrder)) {
      addAttribute(`${ATTRIBUTE_NODE_PREFIX}${attribute.id}`, attribute.name, nodeId, type.role, "node");
    }
  }

  // "is a": each type to the type it inherits from (queue R18).
  for (const type of entityTypes) {
    if (type.inherited_from == null || !known.has(String(type.inherited_from))) continue;
    const id = `isa-${type.id}`;
    edges.push({ id, source: typeNodeId(type.id), target: typeNodeId(type.inherited_from), type: "inherits", label: "is a", attributes: {} });
    palette.edgeColour[id] = "#64748b";
    edgeData[id] = { er: "inherits", selectKind: "node", selectId: typeNodeId(type.id) };
  }

  const drawable = relationshipTypes.filter(
    (type) => known.has(String(type.from_type_id)) && known.has(String(type.to_type_id))
  );
  for (const type of drawable) {
    // The diamond keeps the id the relationship type's edge used to have,
    // so a selection of it is still `reltype-<id>` -- see the header.
    const diamondId = typeEdgeId(type.id);
    paletteEntry(palette, diamondId, typeColour({ id: String(type.id), colour: type.colour }));
    nodes.push({
      id: diamondId,
      type: "relationship",
      label: type.name,
      parent: null,
      attributes: {
        er: "relationship",
        cardinality: type.cardinality,
        is_hierarchy: type.is_hierarchy,
        ends: [typeNodeId(type.from_type_id), typeNodeId(type.to_type_id)],
      },
    });
    nodeData[diamondId] = {
      er: "relationship",
      // Text sits in the middle half of a diamond, so it needs roughly twice
      // the text's width to stay inside the points.
      w: Math.max(120, textWidth(type.name, 8) * 1.9 + 36),
      hierarchy: type.is_hierarchy ? "yes" : "no",
      selectKind: "edge",
      selectId: diamondId,
    };

    // Two plain lines, running from_type -> diamond -> to_type, so that a
    // layered layout sets the diamond BETWEEN the two types it relates
    // rather than below both. Each carries its side's cardinality at the
    // end beside the rectangle -- the source of the first, the target of the
    // second.
    const ends = CARDINALITY_ENDS[type.cardinality] ?? { from: "", to: "" };
    const lines: [string, string, string, string, "source" | "target"][] = [
      ["from", typeNodeId(type.from_type_id), diamondId, ends.from, "source"],
      ["to", diamondId, typeNodeId(type.to_type_id), ends.to, "target"],
    ];
    for (const [side, source, target, end, endAt] of lines) {
      const connectorId = `rellink-${type.id}-${side}`;
      edges.push({
        id: connectorId,
        source,
        target,
        type: type.name,
        label: "",
        attributes: { cardinality: type.cardinality, is_hierarchy: type.is_hierarchy },
      });
      palette.edgeColour[connectorId] = "#334155";
      edgeData[connectorId] = { er: "connector", end, endAt, selectKind: "edge", selectId: diamondId };
    }

    for (const attribute of [...(type.attributes ?? [])].sort(byChosenOrder)) {
      addAttribute(`${ATTRIBUTE_NODE_PREFIX}${attribute.id}`, attribute.name, diamondId, "relationship", "edge");
    }
  }

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

/** What an ER node is, read off its graph data: `entity`, `relationship`,
 * `attribute`, or null for an objects-view node. */
export function erKind(node: { attributes?: Record<string, unknown> }): string | null {
  const kind = node.attributes?.er;
  return typeof kind === "string" ? kind : null;
}

/** True for the ellipses -- the one kind of ER node that is a description of
 * another node rather than a thing to navigate to or count. */
export function isErDecoration(node: { attributes?: Record<string, unknown> }): boolean {
  return erKind(node) === "attribute";
}

/**
 * Which nodes are showing, given which *primary* nodes the filters let
 * through -- every objects-view node, and the entity types of an ER drawing.
 *
 * Attributes and diamonds are never filtered on their own terms: an ellipse
 * shows exactly when its owner does, and a diamond exactly when both of the
 * types it relates do. Otherwise searching "employee" would leave the
 * employee rectangle bare of its attributes, and hiding a role would leave
 * diamonds pointing at nothing.
 */
export function withErDependents<T extends { id: string; attributes?: Record<string, unknown> }>(
  nodes: readonly T[],
  primaryShown: (node: T) => boolean
): Set<string> {
  const shown = new Set<string>();
  for (const node of nodes) {
    const kind = erKind(node);
    if (kind !== "attribute" && kind !== "relationship" && primaryShown(node)) shown.add(node.id);
  }
  for (const node of nodes) {
    if (erKind(node) !== "relationship") continue;
    const ends = node.attributes?.ends;
    if (Array.isArray(ends) && ends.every((end) => shown.has(String(end)))) shown.add(node.id);
  }
  for (const node of nodes) {
    if (erKind(node) !== "attribute") continue;
    if (shown.has(String(node.attributes?.owner))) shown.add(node.id);
  }
  return shown;
}
