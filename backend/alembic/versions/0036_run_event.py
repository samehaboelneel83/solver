"""`run_event`: what a run did while it ran (target roadmap Phase 8).

A run's row says how it ended; this says how it got there. While a solver
works, each better answer it finds (`incumbent`) and each tightening of the
bound on how good an answer could be (`bound`) is recorded, with the seconds
since the solve began, and so are the run's stages (`stage`: compiled,
solving, settled) and anything worth a line of text (`log`).

That is what draws a live chart of the answer and the bound closing on each
other, and what a later look at a slow run replays. Written by the worker at
most twice a second per run, so a solver finding a thousand answers a second
costs a handful of rows; each insert is followed by `pg_notify('run_<id>')`
so a listener learns of it at once.

Tenant table: its organization is its run's (migration 0032).
"""

from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE run_event (
            run_id          bigint NOT NULL REFERENCES run(id) ON DELETE CASCADE,
            seq             integer NOT NULL CHECK (seq >= 1),
            at              timestamptz NOT NULL DEFAULT now(),
            kind            text NOT NULL CHECK (kind IN ('incumbent', 'bound', 'stage', 'log')),
            payload         jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(payload) = 'object'),
            organization_id uuid NOT NULL REFERENCES iam.organization(id),
            PRIMARY KEY (run_id, seq)
        );
        CREATE INDEX run_event_organization_idx ON run_event (organization_id);

        CREATE TRIGGER a_run_event_tenant BEFORE INSERT OR UPDATE ON run_event
            FOR EACH ROW EXECUTE FUNCTION tenant_inherit('run:run_id:bigint');

        ALTER TABLE run_event ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON run_event
            USING (organization_id = app_org())
            WITH CHECK (organization_id = app_org());
        -- Requests read events; only the worker writes them.
        REVOKE INSERT, UPDATE, DELETE ON run_event FROM solver_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE run_event")
