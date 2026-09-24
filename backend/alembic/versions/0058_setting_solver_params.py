"""Settings `solve.solver_params` and `solve.tuned_from`: a tuning search's options, per domain or problem (queue R10).

`solve.solver_params` is text -- "cp-sat.symmetry_level=0, cp-sat.linearization_level=0" -- each option
and value on the whitelist (`app.solve.params`), applied over the platform's enabled ones to every solve of
that backend in the problem or domain it is set on; empty (the default) applies nothing. `solve.tuned_from`
says where they came from -- the date and the tuning report (`bench.tune`) -- and is recorded on the run
beside them.
"""

import sqlalchemy as sa
from alembic import op

revision = "0058"
down_revision = "0057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "INSERT INTO setting_key (key, value_type, default_value, description) VALUES"
            " ('solve.solver_params', 'string', to_jsonb(''::text),"
            "  'Solver options from a tuning search, e.g. cp-sat.symmetry_level=0 -- whitelisted options only'),"
            " ('solve.tuned_from', 'string', to_jsonb(''::text),"
            "  'Where the tuned solver options came from: the date and the tuning report')"
        )
    )


def downgrade() -> None:
    op.execute("DELETE FROM setting WHERE key IN ('solve.solver_params', 'solve.tuned_from')")
    op.execute("DELETE FROM setting_key WHERE key IN ('solve.solver_params', 'solve.tuned_from')")
