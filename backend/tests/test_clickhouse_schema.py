from app.clickhouse_schema import create_analytics_schema
from app.core.db import get_clickhouse_client


def test_analytics_tables_are_created():
    client = get_clickhouse_client()
    create_analytics_schema(client)

    # The client's own database -- `analytics_test` under pytest (conftest),
    # which is where create_analytics_schema writes. Asking about the live
    # `analytics` passed only where a running app had already made it.
    result = client.query(
        "SELECT name FROM system.tables WHERE database = {db:String}",
        parameters={"db": client.database},
    )
    table_names = {row[0] for row in result.result_rows}
    assert {"solver_runs", "solution_metrics", "constraint_violations"}.issubset(table_names)


def test_create_analytics_schema_is_idempotent():
    client = get_clickhouse_client()
    create_analytics_schema(client)
    create_analytics_schema(client)  # must not raise
