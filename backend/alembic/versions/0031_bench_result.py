"""`bench_result`: the benchmark's history, so it can be queried.

One row per (instance, backend, technique value, seed), as `bench.run`
writes them with `--store`. Kept apart from `run`: a benchmark solves
generated or MIPLIB models that have no scenario, dataset or domain, and
mixing them into `run` would put rows in the product that no planner made.
"""

from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE bench_result (
            id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            recorded_at     timestamptz NOT NULL DEFAULT now(),
            family          text NOT NULL,
            size            text NOT NULL,
            instance        text NOT NULL,
            model_class     text NOT NULL,
            backend         text NOT NULL,
            technique       text,
            technique_value text,
            seed            integer NOT NULL,
            status          text NOT NULL,
            objective       double precision,
            bound           double precision,
            gap             double precision CHECK (gap IS NULL OR gap >= 0),
            compile_s       double precision NOT NULL CHECK (compile_s >= 0),
            solve_s         double precision NOT NULL CHECK (solve_s >= 0),
            time_limit_s    double precision NOT NULL CHECK (time_limit_s > 0),
            wrong           boolean NOT NULL
        );
        CREATE INDEX bench_result_lookup_idx
            ON bench_result (family, size, backend, technique, recorded_at DESC);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE bench_result")
