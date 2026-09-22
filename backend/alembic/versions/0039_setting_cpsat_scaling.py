"""Setting `solve.cpsat_scaling`: let CP-SAT take whole-number models with fractional data.

A model whose every decision is whole but whose numbers have decimals
(7.5-hour shifts, rates to the cent) needs `fractional-data`, which CP-SAT
did not provide: it works in integers, and rounding would answer a
different question. With this setting on, such a model whose numbers have
at most 4 decimal places is multiplied into whole numbers exactly
(`app/solve/scaling.py`) and CP-SAT may take it. Off by default: the
benchmark decides whether that is a better choice than the backends that
take the fractions as they are (`bench/results/2026-09-23-cpsat-scaling.md`).
"""

import sqlalchemy as sa
from alembic import op

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "INSERT INTO setting_key (key, value_type, default_value, description)"
            " VALUES ('solve.cpsat_scaling', 'boolean', CAST('false' AS jsonb),"
            "         'Let CP-SAT take a whole-number model whose data has up to 4 decimal"
            " places, by scaling each rule to whole numbers exactly')"
        )
    )


def downgrade() -> None:
    op.execute("DELETE FROM setting_key WHERE key = 'solve.cpsat_scaling'")
