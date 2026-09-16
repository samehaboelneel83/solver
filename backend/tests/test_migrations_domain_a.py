from sqlalchemy import create_engine, inspect

from app.core.config import get_settings


def test_domain_group_a_tables_exist_after_migration():
    engine = create_engine(get_settings().database_url)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names(schema="domain"))
    assert {
        "entity_type",
        "entity",
        "attribute_definition",
        "entity_attribute",
        "relationship_type",
        "relationship",
    }.issubset(tables)
