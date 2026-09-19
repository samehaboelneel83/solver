"""Assemble one domain's graph for the editor, over schema v1.

This module answers a single question -- "what should the canvas draw?" --
and it is read-only. Every write that used to live here now belongs to a
purpose-built router: nodes to `app/api/entities.py`, edges and edge types
to `app/api/relationships.py`. Keeping a second set of write paths here
would mean a second implementation of rules the database already owns.

What replaced what
------------------
v0 had `hierarchy` and `hierarchy_node` tables: a hierarchy was a named
object, and each node in it carried a `parent_node_id`. Schema v1 has
neither. A hierarchy is a `relationship_type` with `is_hierarchy = true`,
and the nesting is just its `relationship` rows, read as **from_entity is
the parent of to_entity**. So the compound-parent map, which v0 built by
joining `hierarchy_node` to itself, is now one query over `relationship`
filtered to the selected type -- and `hierarchies[]` on the wire is the
list of `is_hierarchy` relationship types in the domain, whose ids are
what `hierarchy_type_id` takes back.

The wire contract (`app/graph/schemas.py`, mirrored by
`frontend/src/types/graph.ts`) was deliberately unchanged through task 14,
which owned the frontend types. Task 14b adds exactly one field to each of
the two type-option models -- `colour` -- because the user asked for
behaviour the old contract cannot express; `frontend/src/types/graph.ts`
moved with it. Everything else below is as task 7 mapped it. Four of its fields have no v1 column behind them, so the
mapping below is a decision rather than a translation. Stated once, here,
because a wrong choice renders wrong labels in the UI without failing any
backend test:

=========================  ==================================================
wire field                 v1 source
=========================  ==================================================
GraphNode.type             entity_type.name
GraphNode.label            entity.label, falling back to entity.key
GraphNode.attributes       entity.attrs verbatim (see below)
GraphEdge.type / .label    relationship_type.name (v1 has no display name)
GraphEdge.attributes       relationship.attrs verbatim
EntityTypeOption.code      entity_type.name -- v1's machine identifier
EntityTypeOption.name      entity_type.name -- v1 has no separate label
EntityTypeOption.is_abstract  **hardcoded False**: v1 dropped the column and
                           has no notion of a type that cannot be instantiated
EntityTypeOption.colour    entity_type.colour (migration 0009) -- lowercase
                           '#rrggbb' or None. Task 14b; the one field Task 7
                           could not map because the column did not exist
RelationshipTypeOption.code / .name     relationship_type.name
RelationshipTypeOption.is_directed      **hardcoded True**: every v1
                           relationship is directed (from -> to), which is
                           what the hierarchy and cardinality rules read
RelationshipTypeOption.colour           relationship_type.colour, as above
RelationshipTypeOption.source_entity_type / .target_entity_type
                           entity_type.name of from_type_id / to_type_id.
                           NOT NULL in v1, so never v0's nullable "any"
HierarchyOption            one per relationship_type with is_hierarchy = true;
                           id/code/name from that row
AttributeDefinitionOption.code / .name  attribute_def.name
AttributeDefinitionOption.data_type     attribute_def.data_type verbatim, so
                           these are v1's attr_type labels (integer, number,
                           text, boolean, enum, time, date), not v0's
ids                        str(bigint) -- the wire contract is strings
=========================  ==================================================

`GraphNode.attributes` is `entity.attrs` and nothing else. v0 folded the
entity's own `code`/`status`/`description` columns in on top of the EAV
values, because those columns had no other way to reach the client. v1 has
no such columns, and `attrs` already *is* the complete declared attribute
set -- so folding `key`/`active`/`sort_order` in would only create the
shadowing hazard v0's M-9 fix was about, in reverse: an entity type is
entitled to declare an attribute named `key`.

Two v1 columns have no home in this contract and are therefore not
returned: `relationship.valid_from` / `valid_to`. They are available from
`GET /api/v1/relationships`, and folding them into `attributes` would
shadow a relationship attribute of the same name.
"""

from sqlalchemy.orm import Session

from app.graph.schemas import (
    AttributeDefinitionOption,
    EntityTypeOption,
    GraphEdge,
    GraphNode,
    GraphResponse,
    HierarchyOption,
    RelationshipTypeOption,
)
from app.models.v1_domain import (
    AttributeDef,
    Entity,
    EntityType,
    Relationship,
    RelationshipType,
)


class HierarchyTypeNotFound(Exception):
    """`hierarchy_type_id` names nothing, names a relationship type in a
    different domain, or names one whose `is_hierarchy` is false. Mapped to
    HTTP 404 by the route layer -- it is a bad reference to a resource, not
    a malformed request body."""


def _node_label(entity: Entity) -> str:
    """`label` is the human name and `key` the stable identifier; an entity
    may have only the latter, and a node with no text at all is unusable on
    a canvas."""
    return entity.label or entity.key


def get_domain_graph(
    db: Session, *, domain_id: int, hierarchy_type_id: int | None = None
) -> GraphResponse:
    """Assemble the full graph for one domain.

    `hierarchy_type_id`, when given, determines each node's `parent` (for
    Cytoscape compound-node nesting) from that relationship type's rows.
    Rows of *other* relationship types never set a parent, whether or not
    they are hierarchies themselves -- only one nesting can be drawn at a
    time, which is why the parameter exists.

    An unknown `domain_id` is an empty graph rather than a 404: the client
    picks a domain from a list it was given, and an empty canvas is a
    better answer to a stale selection than an error dialog.
    """
    entity_types = (
        db.query(EntityType)
        .filter(EntityType.domain_id == domain_id)
        .order_by(EntityType.name.asc(), EntityType.id.asc())
        .all()
    )
    entity_type_by_id = {et.id: et for et in entity_types}

    relationship_types = (
        db.query(RelationshipType)
        .filter(RelationshipType.domain_id == domain_id)
        .order_by(RelationshipType.name.asc(), RelationshipType.id.asc())
        .all()
    )
    relationship_type_by_id = {rt.id: rt for rt in relationship_types}

    if hierarchy_type_id is not None:
        selected = relationship_type_by_id.get(hierarchy_type_id)
        if selected is None or not selected.is_hierarchy:
            raise HierarchyTypeNotFound(
                f"relationship type {hierarchy_type_id} is not a hierarchy of this domain"
            )

    entities: list[Entity] = []
    if entity_type_by_id:
        entities = (
            db.query(Entity)
            .filter(Entity.entity_type_id.in_(entity_type_by_id.keys()))
            # Same order as GET /api/v1/entities: `sort_order` is what makes
            # mon..sun come back in week order rather than alphabetically,
            # and `key`/`id` complete the total order.
            .order_by(Entity.sort_order.asc(), Entity.key.asc(), Entity.id.asc())
            .all()
        )
    entity_ids = {e.id for e in entities}

    relationships: list[Relationship] = []
    if relationship_type_by_id and entity_ids:
        relationships = (
            db.query(Relationship)
            .filter(
                Relationship.relationship_type_id.in_(relationship_type_by_id.keys()),
                # A relationship_type's from_type_id/to_type_id are plain FKs
                # to entity_type with no same-domain constraint, so an edge
                # could in principle reach outside this domain's nodes.
                # Cytoscape cannot draw an edge to a node it was not given,
                # so those are excluded rather than returned dangling.
                Relationship.from_entity_id.in_(entity_ids),
                Relationship.to_entity_id.in_(entity_ids),
            )
            .order_by(Relationship.id.asc())
            .all()
        )

    parent_by_entity_id: dict[int, int] = {}
    if hierarchy_type_id is not None:
        parent_by_entity_id = {
            rel.to_entity_id: rel.from_entity_id
            for rel in relationships
            if rel.relationship_type_id == hierarchy_type_id
        }

    attribute_defs: list[AttributeDef] = []
    if entity_type_by_id:
        attribute_defs = (
            db.query(AttributeDef)
            .filter(AttributeDef.entity_type_id.in_(entity_type_by_id.keys()))
            .order_by(AttributeDef.entity_type_id.asc(), AttributeDef.name.asc())
            .all()
        )

    nodes = [
        GraphNode(
            id=str(entity.id),
            type=entity_type_by_id[entity.entity_type_id].name,
            label=_node_label(entity),
            parent=(
                str(parent_by_entity_id[entity.id])
                if entity.id in parent_by_entity_id
                else None
            ),
            attributes=entity.attrs or {},
        )
        for entity in entities
    ]

    edges = [
        GraphEdge(
            id=str(rel.id),
            source=str(rel.from_entity_id),
            target=str(rel.to_entity_id),
            type=relationship_type_by_id[rel.relationship_type_id].name,
            label=relationship_type_by_id[rel.relationship_type_id].name,
            attributes=rel.attrs or {},
        )
        for rel in relationships
    ]

    def _type_name(entity_type_id: int) -> str | None:
        entity_type = entity_type_by_id.get(entity_type_id)
        return entity_type.name if entity_type is not None else None

    return GraphResponse(
        nodes=nodes,
        edges=edges,
        entity_types=[
            EntityTypeOption(
                id=str(et.id),
                code=et.name,
                name=et.name,
                is_abstract=False,
                colour=et.colour,
            )
            for et in entity_types
        ],
        relationship_types=[
            RelationshipTypeOption(
                id=str(rt.id),
                code=rt.name,
                name=rt.name,
                is_directed=True,
                source_entity_type=_type_name(rt.from_type_id),
                target_entity_type=_type_name(rt.to_type_id),
                colour=rt.colour,
            )
            for rt in relationship_types
        ],
        hierarchies=[
            HierarchyOption(id=str(rt.id), code=rt.name, name=rt.name)
            for rt in relationship_types
            if rt.is_hierarchy
        ],
        attribute_definitions=[
            AttributeDefinitionOption(
                id=str(ad.id),
                entity_type_id=str(ad.entity_type_id),
                code=ad.name,
                name=ad.name,
                data_type=ad.data_type,
            )
            for ad in attribute_defs
        ],
    )
