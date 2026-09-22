"""0028: say whether an optimum is the best overall, or only the best nearby.

`run.status = 'optimal'` has always meant one thing, because every model this
platform could express was linear and every solver it ran proves the global
optimum of a linear model. That stops being true the moment a nonlinear model
exists. A local solver such as IPOPT reports "optimal" for a point no
neighbour improves on -- and on a nonconvex model a better point can sit
somewhere else entirely. Shown as "optimal", that answer looks exactly like
the best one, and a planner has no way to tell. It is the worst failure a
nonlinear feature can have, which is why this column arrives before any
nonlinear model can.

    run.optimality  'global' | 'local' | 'none' | NULL

- `global` -- proven the best of all possible answers;
- `local`  -- the best among its neighbours; a better one may exist;
- `none`   -- an answer found, with no claim that it is the best (the time
  limit ran out: status `feasible`);
- NULL     -- no answer to make a claim about (queued, infeasible, error).

It is not derived from the model class or guessed from the status. Each
backend declares what its "optimal" proves, in the registry, and the run
records that -- so a future local solver cannot be added without saying so.

Existing runs are backfilled from what was true when they ran: every one was
solved by a linear backend, so `optimal` meant `global` and `feasible` meant
`none`.
"""

from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE run
            ADD COLUMN optimality text
            CONSTRAINT run_optimality_known CHECK (optimality IN ('global', 'local', 'none'));

        -- An optimality claim belongs to an answer, and only to one.
        ALTER TABLE run
            ADD CONSTRAINT run_optimality_needs_an_answer CHECK (
                optimality IS NULL OR status IN ('optimal', 'feasible')
            );

        UPDATE run SET optimality = 'global' WHERE status = 'optimal';
        UPDATE run SET optimality = 'none'   WHERE status = 'feasible';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE run DROP CONSTRAINT run_optimality_needs_an_answer;
        ALTER TABLE run DROP COLUMN optimality;
        """
    )
