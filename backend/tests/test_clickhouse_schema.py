from app.clickhouse_schema import create_analytics_schema
from app.core.db import get_clickhouse_client


def test_analytics_tables_are_created():
    client = get_clickhouse_client()
    create_analytics_schema(client)

    result = client.query(
        "SELECT name FROM system.tables WHERE database = 'analytics'"
    )
    table_names = {row[0] for row in result.result_rows}
    assert {"solver_runs", "solution_metrics", "constraint_violations"}.issubset(table_names)


def test_create_analytics_schema_is_idempotent():
    client = get_clickhouse_client()
    create_analytics_schema(client)
    create_analytics_schema(client)  # must not raise
