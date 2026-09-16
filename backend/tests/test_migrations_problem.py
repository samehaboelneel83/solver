from sqlalchemy import create_engine, inspect

from app.core.config import get_settings


def test_problem_tables_exist_after_migration():
    engine = create_engine(get_settings().database_url)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names(schema="problem"))
    assert tables == {
        "problem",
        "scenario",
        "variable_definition",
        "variable_dimension",
        "constraint_definition",
        "constraint_scope",
        "objective",
        "objective_component",
        "parameter",
    }
