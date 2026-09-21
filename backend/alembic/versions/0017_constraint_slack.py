"""0017: slack on constraint_result -- the rule with no room left.

A planner reading a run already sees which rules held and which paid a
penalty. What they cannot see is which of the ones that held are *tight*:
coverage met exactly, hours sitting on the cap. That is the residual of the
constraint at the recorded assignment, and every backend already knows it
because it produced the assignment.

**Residual, not dual.** GLOP has duals and CP-SAT does not. Storing a dual
would make "which constraints matter" a property of the solver rather than
of the answer, and a column only one backend could fill. The residual is
backend-agnostic: left minus right (or the other way) with violation
variables stripped, so a soft rule that paid is short and a hard rule that
sits on its bound is zero.

Nullable so a run written before this migration still reads; the compiler
fills it on every solved run from here on.
"""

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE constraint_result
            ADD COLUMN slack numeric(15, 6);
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE constraint_result DROP COLUMN slack;")
