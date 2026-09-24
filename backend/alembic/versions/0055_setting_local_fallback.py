"""Setting `solve.local_fallback`: IPOPT after SCIP ends a continuous nonlinear model without a proof (queue R6).

When on, a continuous NLP, QP or QCQP that SCIP ends with no answer, or an
answer but no proof, gets a further quarter of its time on IPOPT
(`app.solve.ipopt`), started from SCIP's answer when there is one. With no
answer from SCIP, IPOPT's is the run's and claims `local`; with one, a better
answer is kept under SCIP's still-valid global bound. The default is the
bench's call (bench/results/2026-09-24-ipopt.md).
"""

import sqlalchemy as sa
from alembic import op

revision = "0055"
down_revision = "0054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "INSERT INTO setting_key (key, value_type, default_value, description)"
            " VALUES ('solve.local_fallback', 'boolean', CAST('false' AS jsonb),"
            "         'After a global nonlinear solve with no proof, IPOPT from its answer: the best answer nearby')"
        )
    )


def downgrade() -> None:
    op.execute("DELETE FROM setting WHERE key = 'solve.local_fallback'")
    op.execute("DELETE FROM setting_key WHERE key = 'solve.local_fallback'")
