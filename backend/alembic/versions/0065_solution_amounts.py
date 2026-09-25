"""How much, not only which: `amounts` on a solution (queue R17).

`solution.assignments` lists the index tuples each decision took -- enough to
draw a yes-or-no answer, not an amount: shipping 40 and shipping 2 read the
same. `amounts` holds each whole-number or continuous decision's non-zero
values, `{variable: [{"index": [...], "value": n}]}`, so a run can be drawn
as a heat matrix, bars or a line. NULL for runs recorded before it.
"""

from alembic import op

revision = "0065"
down_revision = "0064"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE solution ADD COLUMN amounts jsonb")


def downgrade() -> None:
    op.execute("ALTER TABLE solution DROP COLUMN amounts")
