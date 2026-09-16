from sqlalchemy import create_engine, inspect

from app.core.config import get_settings


def test_iam_tables_exist_after_migration():
    engine = create_engine(get_settings().database_url)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names(schema="iam"))
    assert tables == {"organization", "user_account", "role", "user_role"}
