import uuid
from typing import Any

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
from app.models.domain import (
    AttributeDefinition,
    Entity,
    EntityAttribute,
    EntityType,
    Hierarchy,
    HierarchyNode,
    Relationship,
    RelationshipType,
)


def _node_label(entity: Entity) -> str:
    return entity.name or entity.code or str(entity.id)


def _attribute_value(row: EntityAttribute) -> Any:
    for column in ("value_string", "value_number", "value_boolean", "value_date", "value_datetime", "value_json"):
        value = getattr(row, column)
        if value is not None:
            return value
    return None


def get_domain_graph(
    db: Session, *, organization_id: uuid.UUID, hierarchy_id: uuid.UUID | None = None
) -> GraphResponse:
    """Assemble the full domain graph for one organization.

    hierarchy_id, if given, determines each node's `parent` (for Cytoscape
    compound-node nesting) from that hierarchy's hierarchy_node rows.
    relationship_type has no organization_id column (verified against the
    model) -- it is a global taxonomy, so all relationship types are
    returned regardless of organization.
    """
    entities = db.query(Entity).filter(Entity.organization_id == organization_id).all()
    entity_type_by_id = {
        et.id: et for et in db.query(EntityType).filter(EntityType.organization_id == organization_id).all()
    }
    entity_ids = [e.id for e in entities]

    parent_by_entity_id: dict[uuid.UUID, uuid.UUID | None] = {}
    if hierarchy_id is not None and entity_ids:
        nodes_in_hierarchy = (
            db.query(HierarchyNode)
            .filter(HierarchyNode.hierarchy_id == hierarchy_id, HierarchyNode.entity_id.in_(entity_ids))
            .all()
        )
        node_by_id = {n.id: n for n in nodes_in_hierarchy}
        for n in nodes_in_hierarchy:
            parent_entity_id = None
            if n.parent_node_id is not None:
                parent_node = node_by_id.get(n.parent_node_id)
                if parent_node is not None:
                    parent_entity_id = parent_node.entity_id
            parent_by_entity_id[n.entity_id] = parent_entity_id

    attributes_by_entity_id: dict[uuid.UUID, dict] = {}
    if entity_ids:
        attr_rows = db.query(EntityAttribute).filter(EntityAttribute.entity_id.in_(entity_ids)).all()
        attr_def_ids = {row.attribute_id for row in attr_rows}
        attribute_defs_by_id = {}
        if attr_def_ids:
            attribute_defs_by_id = {
                d.id: d for d in db.query(AttributeDefinition).filter(AttributeDefinition.id.in_(attr_def_ids)).all()
            }
        for row in attr_rows:
            definition = attribute_defs_by_id.get(row.attribute_id)
            if definition is None:
                continue
            attributes_by_entity_id.setdefault(row.entity_id, {})[definition.code] = _attribute_value(row)

    nodes = []
    for entity in entities:
        entity_type = entity_type_by_id.get(entity.entity_type_id)
        attrs: dict[str, Any] = {
            "code": entity.code,
            "status": entity.status,
            "description": entity.description,
        }
        attrs.update(attributes_by_entity_id.get(entity.id, {}))
        parent_entity_id = parent_by_entity_id.get(entity.id)
        nodes.append(
            GraphNode(
                id=str(entity.id),
                type=entity_type.code if entity_type else "",
                label=_node_label(entity),
                parent=str(parent_entity_id) if parent_entity_id else None,
                attributes=attrs,
            )
        )

    relationships = []
    if entity_ids:
        relationships = db.query(Relationship).filter(Relationship.source_entity_id.in_(entity_ids)).all()
    relationship_type_by_id = {rt.id: rt for rt in db.query(RelationshipType).all()}

    edges = []
    for rel in relationships:
        rel_type = relationship_type_by_id.get(rel.relationship_type_id)
        edges.append(
            GraphEdge(
                id=str(rel.id),
                source=str(rel.source_entity_id),
                target=str(rel.target_entity_id),
                type=rel_type.code if rel_type else "",
                label=rel_type.name if rel_type else "",
                attributes=rel.attributes or {},
            )
        )

    entity_types = [
        EntityTypeOption(id=str(et.id), code=et.code, name=et.name, is_abstract=et.is_abstract)
        for et in entity_type_by_id.values()
    ]
    relationship_types = [
        RelationshipTypeOption(
            id=str(rt.id),
            code=rt.code,
            name=rt.name,
            is_directed=rt.is_directed,
            source_entity_type=(
                entity_type_by_id[rt.source_entity_type].code
                if rt.source_entity_type in entity_type_by_id
                else None
            ),
            target_entity_type=(
                entity_type_by_id[rt.target_entity_type].code
                if rt.target_entity_type in entity_type_by_id
                else None
            ),
        )
        for rt in relationship_type_by_id.values()
    ]
    hierarchies = [
        HierarchyOption(id=str(h.id), code=h.code, name=h.name)
        for h in db.query(Hierarchy).filter(Hierarchy.organization_id == organization_id).all()
    ]
    attribute_definitions = []
    if entity_type_by_id:
        attribute_definitions = [
            AttributeDefinitionOption(
                id=str(d.id), entity_type_id=str(d.entity_type_id), code=d.code, name=d.name, data_type=d.data_type
            )
            for d in db.query(AttributeDefinition)
            .filter(AttributeDefinition.entity_type_id.in_(entity_type_by_id.keys()))
            .all()
        ]

    return GraphResponse(
        nodes=nodes,
        edges=edges,
        entity_types=entity_types,
        relationship_types=relationship_types,
        hierarchies=hierarchies,
        attribute_definitions=attribute_definitions,
    )
