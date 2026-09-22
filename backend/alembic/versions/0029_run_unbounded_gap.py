"""Run status `unbounded`; the best bound and gap of every answer.

Two things a run could not say.

**Unbounded.** A goal that can improve without limit was reported as
`unknown` -- or worse, since every variable gets a default ceiling, as an
`optimal` answer sitting on a ceiling nobody set. `unbounded` names the
modelling mistake: a variable is missing a bound, or a rule is missing.

**Gap.** `feasible` said "an answer, not proven best" and nothing about how
far from best. `best_bound` is the solver's proven limit on the goal and
`gap` is `|objective - best_bound| / max(|objective|, 1e-9)`: 0 for a proven
optimum, null when the solver had no bound. `double precision`, not
`numeric(15, 6)`: an early bound can be far larger than any answer.

The enum label stays on downgrade (see 0018).
"""

from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE run_status ADD VALUE IF NOT EXISTS 'unbounded'")
    op.execute(
        """
        ALTER TABLE run
            ADD COLUMN best_bound double precision,
            ADD COLUMN gap double precision,
            ADD CONSTRAINT run_gap_not_negative CHECK (gap IS NULL OR gap >= 0),
            ADD CONSTRAINT run_bound_needs_an_answer CHECK (
                (best_bound IS NULL AND gap IS NULL)
                OR status IN ('optimal', 'feasible')
            );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE run
            DROP CONSTRAINT run_bound_needs_an_answer,
            DROP CONSTRAINT run_gap_not_negative,
            DROP COLUMN gap,
            DROP COLUMN best_bound;
        """
    )
