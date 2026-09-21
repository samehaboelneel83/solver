from sqlalchemy import create_engine, inspect

from app.core.config import get_settings


def test_iam_tables_exist_after_migration():
    engine = create_engine(get_settings().database_url)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names(schema="iam"))
    # `capability` and `role_capability` are migration 0013: a role holds
    # capabilities, and the API checks for those by name rather than for a
    # role, so the policy lives in one place.
    assert tables == {
        "organization",
        "user_account",
        "role",
        "user_role",
        "capability",
        "role_capability",
    }
