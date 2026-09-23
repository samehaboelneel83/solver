_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS {db}.solver_runs
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
    CREATE TABLE IF NOT EXISTS {db}.solution_metrics
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
    CREATE TABLE IF NOT EXISTS {db}.constraint_violations
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
    # One row per settled run (app.analytics). Replacing, keyed by run: a
    # run written twice is one row once merged, and `FINAL` reads it so now.
    """
    CREATE TABLE IF NOT EXISTS {db}.run_fact
    (
        run_id UInt64,
        organization_id UUID,
        domain_id UInt64,
        problem_id UInt64,
        scenario_id UInt64,
        model_version_id UInt64,
        solver LowCardinality(String),
        model_class LowCardinality(String),
        status LowCardinality(String),
        optimality LowCardinality(String),
        objective Nullable(Float64),
        best_bound Nullable(Float64),
        gap Nullable(Float64),
        wall_time_s Nullable(Float64),
        time_limit_s Float64,
        workers UInt16,
        seed Int64,
        variables Nullable(UInt32),
        rules Nullable(UInt32),
        fingerprint String DEFAULT '',
        trace_id String,
        queued_at DateTime64(3, 'UTC'),
        started_at Nullable(DateTime64(3, 'UTC')),
        finished_at Nullable(DateTime64(3, 'UTC')),
        queue_wait_s Nullable(Float64),
        written_at DateTime64(3, 'UTC')
    )
    ENGINE = ReplacingMergeTree(written_at)
    ORDER BY (organization_id, run_id)
    """,
    # Added to a table created before Phase 17: the fingerprint as JSON
    # (`JSONExtractInt(fingerprint, 'rows_cover')` reads one number).
    "ALTER TABLE {db}.run_fact ADD COLUMN IF NOT EXISTS fingerprint String DEFAULT '' AFTER rules",
]


def create_analytics_schema(client) -> None:
    """Create the ClickHouse analytics tables if they don't already exist.

    Safe to call on every backend startup.
    """
    for statement in _STATEMENTS:
        # The client's own database: `analytics` live, `analytics_test`
        # under pytest (conftest), so a test never writes the live one.
        client.command(statement.replace("{db}", client.database))
