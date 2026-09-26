"""0070: how far each number may move (queue R27) -- `solution.ranges`.

LP ranging from a linear solver at a proven optimum of a model with no
whole-number decision: `rows` (each binding rule instance's limit, its dual and
the range the limit may move in with that dual exact) and `costs` (each used
decision's goal coefficient and the range it may move in with the plan
unchanged). NULL for every other run: ranging is not defined for a MIP, and a
relaxation's numbers are not shown in its place.
"""

from alembic import op

revision = "0070"
down_revision = "0069"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE solution ADD COLUMN ranges jsonb")


def downgrade() -> None:
    op.execute("ALTER TABLE solution DROP COLUMN IF EXISTS ranges")
