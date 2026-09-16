from app.core.db import SessionLocal
from app.models.domain import Entity, HierarchyNode, Relationship
from app.seed import seed_admin
from app.seed_graph_demo import seed_graph_demo


def test_seed_graph_demo_is_idempotent_and_wires_relationships_and_hierarchy():
    db = SessionLocal()
    try:
        seed_admin(db)
        seed_graph_demo(db)
        seed_graph_demo(db)  # run twice -- must not duplicate rows

        demo_entities = db.query(Entity).filter(Entity.code.like("%-demo")).all()
        assert len(demo_entities) == 5

        ahmed = next(e for e in demo_entities if e.code == "ahmed-demo")
        unit_a = next(e for e in demo_entities if e.code == "unit-a-demo")

        relationship = (
            db.query(Relationship)
            .filter(Relationship.source_entity_id == ahmed.id, Relationship.target_entity_id == unit_a.id)
            .first()
        )
        assert relationship is not None

        hierarchy_node = db.query(HierarchyNode).filter(HierarchyNode.entity_id == ahmed.id).first()
        assert hierarchy_node is not None
        assert hierarchy_node.parent_node_id is not None
    finally:
        db.close()
