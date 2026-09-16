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


class GraphNotFoundError(Exception):
    """Raised when a write targets an entity/relationship id that doesn't
    exist. Mapped to HTTP 404 by the route layer."""


class GraphConflictError(Exception):
    """Raised when a write would violate a DB relationship (e.g. deleting
    a still-referenced entity). Mapped to HTTP 409 by the route layer."""


class GraphValidationError(Exception):
    """Raised when a write fails a domain-level validation (e.g. an
    edge's relationship_type doesn't match the two entities' types).
    Mapped to HTTP 422 by the route layer."""


def _entity_to_node(db: Session, entity: Entity, *, hierarchy_id: uuid.UUID | None) -> GraphNode:
    entity_type = db.get(EntityType, entity.entity_type_id)
    attrs: dict[str, Any] = {
        "code": entity.code,
        "status": entity.status,
        "description": entity.description,
    }
    attr_rows = db.query(EntityAttribute).filter(EntityAttribute.entity_id == entity.id).all()
    for row in attr_rows:
        definition = db.get(AttributeDefinition, row.attribute_id)
        if definition is not None:
            attrs[definition.code] = _attribute_value(row)

    parent_entity_id = None
    if hierarchy_id is not None:
        node = (
            db.query(HierarchyNode)
            .filter(HierarchyNode.hierarchy_id == hierarchy_id, HierarchyNode.entity_id == entity.id)
            .first()
        )
        if node is not None and node.parent_node_id is not None:
            parent_node = db.get(HierarchyNode, node.parent_node_id)
            if parent_node is not None:
                parent_entity_id = parent_node.entity_id

    return GraphNode(
        id=str(entity.id),
        type=entity_type.code if entity_type else "",
        label=_node_label(entity),
        parent=str(parent_entity_id) if parent_entity_id else None,
        attributes=attrs,
    )


def _write_entity_attributes(
    db: Session, *, entity_id: uuid.UUID, entity_type_id: uuid.UUID, attributes: dict[str, Any]
) -> None:
    if not attributes:
        return
    definitions = {
        d.code: d
        for d in db.query(AttributeDefinition).filter(AttributeDefinition.entity_type_id == entity_type_id).all()
    }
    for code, value in attributes.items():
        definition = definitions.get(code)
        if definition is None:
            continue  # unknown attribute code for this entity type -- silently skip
        existing = (
            db.query(EntityAttribute)
            .filter(EntityAttribute.entity_id == entity_id, EntityAttribute.attribute_id == definition.id)
            .first()
        )
        row = existing or EntityAttribute(entity_id=entity_id, attribute_id=definition.id)
        row.value_string = None
        row.value_number = None
        row.value_boolean = None
        row.value_date = None
        row.value_datetime = None
        row.value_json = None
        if definition.data_type == "string":
            row.value_string = str(value)
        elif definition.data_type == "number":
            row.value_number = value
        elif definition.data_type == "boolean":
            row.value_boolean = bool(value)
        elif definition.data_type == "date":
            row.value_date = value
        elif definition.data_type == "datetime":
            row.value_datetime = value
        else:
            row.value_json = value
        if existing is None:
            db.add(row)


def create_node(
    db: Session,
    *,
    organization_id: uuid.UUID,
    entity_type_id: uuid.UUID,
    name: str,
    code: str | None = None,
    status: str | None = None,
    description: str | None = None,
    attributes: dict[str, Any] | None = None,
    hierarchy_id: uuid.UUID | None = None,
    parent_entity_id: uuid.UUID | None = None,
) -> GraphNode:
    entity = Entity(
        organization_id=organization_id,
        entity_type_id=entity_type_id,
        name=name,
        code=code,
        status=status,
        description=description,
    )
    db.add(entity)
    db.flush()  # populate entity.id before using it below

    _write_entity_attributes(db, entity_id=entity.id, entity_type_id=entity_type_id, attributes=attributes or {})

    if hierarchy_id is not None:
        parent_node_id = None
        if parent_entity_id is not None:
            parent_node = (
                db.query(HierarchyNode)
                .filter(HierarchyNode.hierarchy_id == hierarchy_id, HierarchyNode.entity_id == parent_entity_id)
                .first()
            )
            parent_node_id = parent_node.id if parent_node else None
        db.add(HierarchyNode(hierarchy_id=hierarchy_id, entity_id=entity.id, parent_node_id=parent_node_id, level=0))

    db.commit()
    db.refresh(entity)
    return _entity_to_node(db, entity, hierarchy_id=hierarchy_id)


def update_node(
    db: Session,
    entity_id: uuid.UUID,
    *,
    name: str | None = None,
    code: str | None = None,
    status: str | None = None,
    description: str | None = None,
    attributes: dict[str, Any] | None = None,
    hierarchy_id: uuid.UUID | None = None,
    parent_entity_id: uuid.UUID | None = None,
) -> GraphNode:
    entity = db.get(Entity, entity_id)
    if entity is None:
        raise GraphNotFoundError(f"entity {entity_id} not found")

    if name is not None:
        entity.name = name
    if code is not None:
        entity.code = code
    if status is not None:
        entity.status = status
    if description is not None:
        entity.description = description

    if attributes:
        _write_entity_attributes(db, entity_id=entity.id, entity_type_id=entity.entity_type_id, attributes=attributes)

    if hierarchy_id is not None:
        # hierarchy_id being given at all is the "touch placement" signal;
        # parent_entity_id=None within that means "move to root".
        node = (
            db.query(HierarchyNode)
            .filter(HierarchyNode.hierarchy_id == hierarchy_id, HierarchyNode.entity_id == entity.id)
            .first()
        )
        parent_node_id = None
        if parent_entity_id is not None:
            parent_node = (
                db.query(HierarchyNode)
                .filter(HierarchyNode.hierarchy_id == hierarchy_id, HierarchyNode.entity_id == parent_entity_id)
                .first()
            )
            parent_node_id = parent_node.id if parent_node else None
        if node is None:
            db.add(
                HierarchyNode(
                    hierarchy_id=hierarchy_id, entity_id=entity.id, parent_node_id=parent_node_id, level=0
                )
            )
        else:
            node.parent_node_id = parent_node_id

    db.commit()
    db.refresh(entity)
    return _entity_to_node(db, entity, hierarchy_id=hierarchy_id)


def delete_node(db: Session, entity_id: uuid.UUID) -> None:
    entity = db.get(Entity, entity_id)
    if entity is None:
        raise GraphNotFoundError(f"entity {entity_id} not found")

    relationship_count = (
        db.query(Relationship)
        .filter((Relationship.source_entity_id == entity_id) | (Relationship.target_entity_id == entity_id))
        .count()
    )
    hierarchy_node_rows = db.query(HierarchyNode).filter(HierarchyNode.entity_id == entity_id).all()
    child_count = 0
    for node in hierarchy_node_rows:
        child_count += db.query(HierarchyNode).filter(HierarchyNode.parent_node_id == node.id).count()

    if relationship_count or child_count:
        parts = []
        if relationship_count:
            parts.append(f"{relationship_count} relationship(s)")
        if child_count:
            parts.append(f"{child_count} child hierarchy placement(s)")
        raise GraphConflictError(f"entity still has {' and '.join(parts)} — remove them first")

    # entity_attribute rows are the entity's own data, not a connection to
    # something else -- delete them automatically rather than blocking on them.
    db.query(EntityAttribute).filter(EntityAttribute.entity_id == entity_id).delete()
    for node in hierarchy_node_rows:
        db.delete(node)
    db.delete(entity)
    db.commit()
