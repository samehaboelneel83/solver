"""Setting `solve.memory`: a problem remembers the solver that proved it fastest.

When on and no solver is named, a run takes the admissible solver that
proved the problem's recent runs in the least median time (at least two
proven runs each; `app.solve.memory`), and `why_solver` quotes the evidence.
On by default, on the bench's evidence (bench/results/2026-09-24-memory.md):
faster on five of seven families, never twice as slow, no wrong answer; on
the other two the rules' pick was already the fastest.
"""

import sqlalchemy as sa
from alembic import op

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "INSERT INTO setting_key (key, value_type, default_value, description)"
            " VALUES ('solve.memory', 'boolean', CAST('true' AS jsonb),"
            "         'When no solver is named, use the one that proved this problem''s recent runs fastest')"
        )
    )


def downgrade() -> None:
    op.execute("DELETE FROM setting WHERE key = 'solve.memory'")
    op.execute("DELETE FROM setting_key WHERE key = 'solve.memory'")
