from sqlalchemy import create_engine, inspect

from app.core.config import get_settings


def test_domain_group_b_tables_exist_after_migration():
    engine = create_engine(get_settings().database_url)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names(schema="domain"))
    assert {
        "hierarchy",
        "hierarchy_node",
        "role_type",
        "entity_role",
        "state_type",
        "entity_state",
    }.issubset(tables)
