"""A front's points carry every goal's value: fronts between three goals or more (10 October 2026).

`first_value` and `second_value` stay (the first two goals, as every reader of a two-goal front takes them);
`goal_values` holds all of them in the goal's order, so a front between three to six goals is stored whole
(`app.solve.pareto.many_front`).
"""

from alembic import op

revision = "0121"
down_revision = "0120"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE pareto_point ADD COLUMN goal_values jsonb")


def downgrade() -> None:
    op.execute("ALTER TABLE pareto_point DROP COLUMN goal_values")
