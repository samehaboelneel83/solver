"""0116: a workspace refreshes itself from its sources on a schedule, and may solve again.

A refresh was something a person started (0114). A schedule repeats it: every N hours the ingestion worker reads
each bound database source again, compares it with the workspace (and the latest version of each kept file), and
either keeps the report for a person to apply, or applies it and solves again every scenario that reads the data.
It acts as the person who set it, with that person's current permissions, checked at each run.
"""
from alembic import op

revision = "0116"
down_revision = "0115"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE source_schedule (
            domain_id bigint PRIMARY KEY REFERENCES domain(id) ON DELETE CASCADE,
            organization_id uuid NOT NULL REFERENCES iam.organization(id),
            owner_id uuid NOT NULL REFERENCES iam.user_account(id),
            every_hours integer NOT NULL CHECK (every_hours BETWEEN 1 AND 8760),
            mode text NOT NULL DEFAULT 'report' CHECK (mode IN ('report', 'apply')),
            solve boolean NOT NULL DEFAULT false,
            enabled boolean NOT NULL DEFAULT true,
            next_at timestamptz NOT NULL,
            state text NOT NULL DEFAULT 'idle' CHECK (state IN ('idle', 'extracting')),
            pending jsonb NOT NULL DEFAULT '{}'::jsonb,
            started_at timestamptz,
            last_at timestamptz,
            last_report jsonb,
            last_error text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE TRIGGER a_source_schedule_tenant BEFORE INSERT OR UPDATE ON source_schedule
          FOR EACH ROW EXECUTE FUNCTION tenant_inherit('domain:domain_id:bigint');
        ALTER TABLE source_schedule ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON source_schedule
          USING (organization_id = app_org()) WITH CHECK (organization_id = app_org());
        CREATE INDEX source_schedule_due ON source_schedule (next_at) WHERE enabled;
        GRANT SELECT, INSERT, UPDATE, DELETE ON source_schedule TO solver_app;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS source_schedule")
