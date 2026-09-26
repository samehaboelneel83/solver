"""0072: what the conformance kit found (queue R43) -- `solver_conformance`.

One row per run of the kit (`app.solve.conformance`) on an added solver: its name and version as
the manifest gave them, whether it passed, every check with its result, when and by whom. An
adapter whose *current* version's latest row passed may be chosen by the rules unasked; any other
runs only when named. A platform table, not a tenant's: an adapter is installed for everyone, and
only an operator runs the kit.
"""

from alembic import op

revision = "0072"
down_revision = "0071"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE solver_conformance (
            id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            adapter  text NOT NULL CHECK (adapter ~ '^[a-z][a-z0-9_-]{0,39}$'),
            version  text NOT NULL,
            passed   boolean NOT NULL,
            checks   jsonb NOT NULL,
            ran_by   text,
            ran_at   timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX solver_conformance_latest_idx ON solver_conformance (adapter, version, ran_at DESC);
        GRANT SELECT, INSERT ON solver_conformance TO solver_app;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE solver_conformance")
