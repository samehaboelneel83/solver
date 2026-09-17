from app.core.db import SessionLocal
from app.models.domain import AttributeDefinition, Entity, EntityAttribute, EntityType, HierarchyNode, Relationship
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


def test_seed_graph_demo_creates_typed_attribute_definitions_and_values():
    db = SessionLocal()
    try:
        seed_admin(db)
        seed_graph_demo(db)
        seed_graph_demo(db)  # run twice -- must not duplicate attribute rows

        employee_type = db.query(EntityType).filter(EntityType.code == "employee-demo").first()
        assert employee_type is not None

        attribute_definitions = (
            db.query(AttributeDefinition).filter(AttributeDefinition.entity_type_id == employee_type.id).all()
        )
        codes = {d.code for d in attribute_definitions}
        assert "rank" in codes
        assert "is_manager" in codes
        assert len([d for d in attribute_definitions if d.code == "rank"]) == 1
        assert len([d for d in attribute_definitions if d.code == "is_manager"]) == 1

        rank_def = next(d for d in attribute_definitions if d.code == "rank")
        assert rank_def.data_type == "number"
        is_manager_def = next(d for d in attribute_definitions if d.code == "is_manager")
        assert is_manager_def.data_type == "boolean"

        ahmed = db.query(Entity).filter(Entity.code == "ahmed-demo").first()
        sara = db.query(Entity).filter(Entity.code == "sara-demo").first()
        mostafa = db.query(Entity).filter(Entity.code == "mostafa-demo").first()

        def rank_value(entity):
            row = (
                db.query(EntityAttribute)
                .filter(EntityAttribute.entity_id == entity.id, EntityAttribute.attribute_id == rank_def.id)
                .first()
            )
            assert row is not None
            return float(row.value_number)

        assert rank_value(ahmed) == 3.0
        assert rank_value(sara) == 2.0
        assert rank_value(mostafa) == 1.0

        ahmed_is_manager = (
            db.query(EntityAttribute)
            .filter(EntityAttribute.entity_id == ahmed.id, EntityAttribute.attribute_id == is_manager_def.id)
            .first()
        )
        assert ahmed_is_manager is not None
        assert ahmed_is_manager.value_boolean is True
    finally:
        db.close()
