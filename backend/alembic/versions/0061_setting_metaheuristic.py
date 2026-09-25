"""Setting `solve.metaheuristic`: a search over whole answers after an exact solver ended with nothing (queue R14).

On: when the chosen solver ends a run with no answer -- out of time, or
crashed -- a genetic algorithm (or, for a continuous model, the search the
bench found best) takes a quarter of the run's time again
(`app.solve.evolve`). Its answer keeps every rule and claims nothing:
`feasible`, no bound, never optimal. CMA-ES, particle swarm and the genetic
algorithm can also be asked for by name; the rules never choose them.
"""

import sqlalchemy as sa
from alembic import op

revision = "0061"
down_revision = "0060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "INSERT INTO setting_key (key, value_type, default_value, description)"
            " VALUES ('solve.metaheuristic', 'boolean', CAST('false' AS jsonb),"
            "         'When the solver ends with no answer, search for one (an answer, never proven best)')"
        )
    )


def downgrade() -> None:
    op.execute("DELETE FROM setting WHERE key = 'solve.metaheuristic'")
    op.execute("DELETE FROM setting_key WHERE key = 'solve.metaheuristic'")
