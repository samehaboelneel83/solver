_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS analytics.solver_runs
    (
        organization_id UUID,
        problem_id UUID,
        scenario_id UUID,
        solver_run_id UUID,
        solver_type LowCardinality(String),
        started_at DateTime64(3),
        finished_at Nullable(DateTime64(3)),
        duration_ms UInt64,
        status LowCardinality(String),
        objective_value Float64,
        best_bound Float64,
        gap Float64,
        variables UInt64,
        constraints UInt64,
        iterations UInt64,
        nodes UInt64
    )
    ENGINE = MergeTree
    ORDER BY (organization_id, problem_id, started_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS analytics.solution_metrics
    (
        organization_id UUID,
        problem_id UUID,
        scenario_id UUID,
        solution_id UUID,
        metric_code LowCardinality(String),
        metric_value Float64,
        measured_at DateTime64(3),
        dimensions Map(String, String)
    )
    ENGINE = MergeTree
    ORDER BY (organization_id, problem_id, metric_code, measured_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS analytics.constraint_violations
    (
        organization_id UUID,
        problem_id UUID,
        solution_id UUID,
        constraint_id UUID,
        entity_id UUID,
        severity LowCardinality(String),
        violation_value Float64,
        penalty Float64,
        occurred_at DateTime64(3)
    )
    ENGINE = MergeTree
    ORDER BY (organization_id, problem_id, constraint_id, occurred_at)
    """,
]


def create_analytics_schema(client) -> None:
    """Create the ClickHouse analytics tables if they don't already exist.

    Safe to call on every backend startup.
    """
    for statement in _STATEMENTS:
        client.command(statement)
