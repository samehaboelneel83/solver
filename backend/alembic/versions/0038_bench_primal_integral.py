"""`bench_result.primal_integral`: how long a run spent without a good answer.

Computed by `bench.primal` from the incumbents a backend streams while it
solves (seconds; smaller is better; the whole run time when it found
nothing). Null on rows stored before this column, and on instances nothing
found an answer to.
"""

from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE bench_result ADD COLUMN primal_integral double precision"
        " CHECK (primal_integral IS NULL OR primal_integral >= 0)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE bench_result DROP COLUMN primal_integral")
