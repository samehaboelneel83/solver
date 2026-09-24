"""PDLP (roadmap Phase 14, queue R1): an `approximate` optimality, and the setting `solve.pdlp`.

PDLP -- a first-order method for very large linear programs -- stops when
its primal and dual answers agree to a tolerance. Its "optimal" is the best
answer *to that tolerance*, not a proven vertex: a third claim beside
`global` (proven best) and `local` (best nearby), so a run can never show it
as a proven optimum. The result cache and per-problem memory already take
only `global` answers.

`solve.pdlp` (off by default) lets a linear program past the size threshold
in `app.solve.pdlp` go to PDLP instead of the simplex or interior-point
solvers; its default is the benchmark's call
(`bench/results/2026-09-24-pdlp.md`).
"""

import sqlalchemy as sa
from alembic import op

revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE run DROP CONSTRAINT run_optimality_known;
        ALTER TABLE run ADD CONSTRAINT run_optimality_known
            CHECK (optimality IN ('global', 'local', 'approximate', 'none'));
        """
    )
    op.get_bind().execute(
        sa.text(
            "INSERT INTO setting_key (key, value_type, default_value, description)"
            " VALUES ('solve.pdlp', 'boolean', CAST('false' AS jsonb),"
            "         'Send a very large linear program to PDLP, whose answer is optimal to a tolerance')"
        )
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM run WHERE optimality = 'approximate') THEN
                RAISE EXCEPTION 'runs hold approximate answers; delete them before downgrading 0051';
            END IF;
        END $$;
        """
    )
    op.execute("DELETE FROM setting WHERE key = 'solve.pdlp'")
    op.execute("DELETE FROM setting_key WHERE key = 'solve.pdlp'")
    op.execute(
        """
        ALTER TABLE run DROP CONSTRAINT run_optimality_known;
        ALTER TABLE run ADD CONSTRAINT run_optimality_known
            CHECK (optimality IN ('global', 'local', 'none'));
        """
    )
