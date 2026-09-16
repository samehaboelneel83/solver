from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models.domain import Entity, EntityType, Hierarchy, HierarchyNode, Relationship, RelationshipType
from app.models.iam import Organization


def _get_or_create_entity_type(db: Session, organization_id, *, code: str, name: str) -> EntityType:
    existing = (
        db.query(EntityType).filter(EntityType.organization_id == organization_id, EntityType.code == code).first()
    )
    if existing:
        return existing
    row = EntityType(organization_id=organization_id, code=code, name=name)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _get_or_create_relationship_type(
    db: Session, *, code: str, name: str, is_directed: bool, source_entity_type, target_entity_type
) -> RelationshipType:
    existing = db.query(RelationshipType).filter(RelationshipType.code == code).first()
    if existing:
        return existing
    row = RelationshipType(
        code=code,
        name=name,
        is_directed=is_directed,
        source_entity_type=source_entity_type,
        target_entity_type=target_entity_type,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _get_or_create_hierarchy(db: Session, organization_id, *, code: str, name: str) -> Hierarchy:
    existing = db.query(Hierarchy).filter(Hierarchy.organization_id == organization_id, Hierarchy.code == code).first()
    if existing:
        return existing
    row = Hierarchy(organization_id=organization_id, code=code, name=name)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _get_or_create_entity(db: Session, organization_id, entity_type_id, *, code: str, name: str) -> Entity:
    existing = (
        db.query(Entity)
        .filter(
            Entity.organization_id == organization_id,
            Entity.entity_type_id == entity_type_id,
            Entity.code == code,
        )
        .first()
    )
    if existing:
        return existing
    row = Entity(organization_id=organization_id, entity_type_id=entity_type_id, code=code, name=name)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _get_or_create_relationship(db: Session, relationship_type_id, source_entity_id, target_entity_id) -> Relationship:
    existing = (
        db.query(Relationship)
        .filter(
            Relationship.relationship_type_id == relationship_type_id,
            Relationship.source_entity_id == source_entity_id,
            Relationship.target_entity_id == target_entity_id,
        )
        .first()
    )
    if existing:
        return existing
    row = Relationship(
        relationship_type_id=relationship_type_id,
        source_entity_id=source_entity_id,
        target_entity_id=target_entity_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _get_or_create_hierarchy_node(db: Session, hierarchy_id, entity_id, *, parent_node_id, level: int) -> HierarchyNode:
    existing = (
        db.query(HierarchyNode)
        .filter(HierarchyNode.hierarchy_id == hierarchy_id, HierarchyNode.entity_id == entity_id)
        .first()
    )
    if existing:
        return existing
    row = HierarchyNode(hierarchy_id=hierarchy_id, entity_id=entity_id, parent_node_id=parent_node_id, level=level)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def seed_graph_demo(db: Session) -> None:
    """Create a small Employee/Unit demo dataset for the graph editor.
    Idempotent -- safe to run more than once. Requires the platform's
    normal admin seed (seed_admin) to have already run, for the default
    organization."""
    org = db.query(Organization).filter(Organization.code == "default").first()
    if org is None:
        raise RuntimeError("default organization not found -- run app.seed.seed_admin first")

    employee_type = _get_or_create_entity_type(db, org.id, code="employee-demo", name="Employee")
    unit_type = _get_or_create_entity_type(db, org.id, code="unit-demo", name="Unit")
    works_for = _get_or_create_relationship_type(
        db,
        code="works_for-demo",
        name="Works For",
        is_directed=True,
        source_entity_type=employee_type.id,
        target_entity_type=unit_type.id,
    )
    hierarchy = _get_or_create_hierarchy(db, org.id, code="org-chart-demo", name="Org Chart")

    unit_a = _get_or_create_entity(db, org.id, unit_type.id, code="unit-a-demo", name="Engineering")
    unit_b = _get_or_create_entity(db, org.id, unit_type.id, code="unit-b-demo", name="Operations")

    ahmed = _get_or_create_entity(db, org.id, employee_type.id, code="ahmed-demo", name="Ahmed")
    sara = _get_or_create_entity(db, org.id, employee_type.id, code="sara-demo", name="Sara")
    mostafa = _get_or_create_entity(db, org.id, employee_type.id, code="mostafa-demo", name="Mostafa")

    _get_or_create_relationship(db, works_for.id, ahmed.id, unit_a.id)
    _get_or_create_relationship(db, works_for.id, sara.id, unit_a.id)
    _get_or_create_relationship(db, works_for.id, mostafa.id, unit_b.id)

    unit_a_node = _get_or_create_hierarchy_node(db, hierarchy.id, unit_a.id, parent_node_id=None, level=0)
    unit_b_node = _get_or_create_hierarchy_node(db, hierarchy.id, unit_b.id, parent_node_id=None, level=0)
    _get_or_create_hierarchy_node(db, hierarchy.id, ahmed.id, parent_node_id=unit_a_node.id, level=1)
    _get_or_create_hierarchy_node(db, hierarchy.id, sara.id, parent_node_id=unit_a_node.id, level=1)
    _get_or_create_hierarchy_node(db, hierarchy.id, mostafa.id, parent_node_id=unit_b_node.id, level=1)


if __name__ == "__main__":
    db = SessionLocal()
    try:
        seed_graph_demo(db)
        print("Graph demo data seeded.")
    finally:
        db.close()
