"""Setting `solve.network_engine`: which algorithm walks a network model (the network lane, 0062).

`networkx` (the default): NetworkX's network simplex. `ortools`: OR-Tools' SimpleMinCostFlow, the
lane's engine until now and about ten times quicker on large networks (a 400 x 400 assignment:
0.1 s against 1.1 s). Both are exact on whole numbers and prove the same optimum. NetworkX is also
a solver of its own, `networkx`, asked for by name (app.solve.backends).
"""

import sqlalchemy as sa
from alembic import op

revision = "0108"
down_revision = "0107"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "INSERT INTO setting_key (key, value_type, default_value, description)"
            " VALUES ('solve.network_engine', 'string', to_jsonb('networkx'::text),"
            "         'Which min-cost flow walks a network model: networkx (network simplex) or ortools')"
        )
    )


def downgrade() -> None:
    op.execute("DELETE FROM setting WHERE key = 'solve.network_engine'")
    op.execute("DELETE FROM setting_key WHERE key = 'solve.network_engine'")
