"""0085: domain-owned encrypted connections and persisted ingestion jobs."""
from alembic import op

revision = "0085"
down_revision = "0084"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE integration_connection (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            domain_id bigint NOT NULL REFERENCES domain(id),
            organization_id uuid NOT NULL REFERENCES iam.organization(id),
            name text NOT NULL CHECK(length(name) BETWEEN 1 AND 200),
            config jsonb NOT NULL,
            credential jsonb NOT NULL DEFAULT '{}'::jsonb,
            enabled boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE TRIGGER a_integration_connection_tenant BEFORE INSERT OR UPDATE ON integration_connection
          FOR EACH ROW EXECUTE FUNCTION tenant_inherit('domain:domain_id:bigint');
        ALTER TABLE integration_connection ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON integration_connection
          USING (organization_id = app_org()) WITH CHECK (organization_id = app_org());
        CREATE TABLE ingestion_job (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            connection_id bigint NOT NULL REFERENCES integration_connection(id),
            organization_id uuid NOT NULL REFERENCES iam.organization(id),
            requested_by uuid NOT NULL REFERENCES iam.user_account(id),
            state text NOT NULL DEFAULT 'queued' CHECK (state IN ('queued','running','extracted','failed','cancelled')),
            attempt uuid,
            cancel_requested boolean NOT NULL DEFAULT false,
            created_at timestamptz NOT NULL DEFAULT now(),
            started_at timestamptz,
            finished_at timestamptz,
            artifact_id uuid,
            error_code text
        );
        CREATE TRIGGER a_ingestion_job_tenant BEFORE INSERT OR UPDATE ON ingestion_job
          FOR EACH ROW EXECUTE FUNCTION tenant_inherit('integration_connection:connection_id:bigint');
        ALTER TABLE ingestion_job ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON ingestion_job
          USING (organization_id = app_org()) WITH CHECK (organization_id = app_org());
        CREATE INDEX ingestion_queue_idx ON ingestion_job(state, created_at);
        CREATE UNIQUE INDEX ingestion_one_active ON ingestion_job(connection_id) WHERE state IN ('queued','running');
        GRANT SELECT, INSERT, UPDATE ON integration_connection, ingestion_job TO solver_app;
        GRANT USAGE, SELECT ON SEQUENCE integration_connection_id_seq, ingestion_job_id_seq TO solver_app;
        INSERT INTO iam.capability(code, "group", description) VALUES
          ('integration.manage', 'integration', 'Manage domain connections and encrypted credentials'),
          ('integration.run', 'integration', 'Read domain connections and submit or cancel ingestion jobs');
        INSERT INTO iam.role_capability(role_id, capability_code)
          SELECT id, c FROM iam.role CROSS JOIN (VALUES ('integration.manage'), ('integration.run')) AS v(c)
          WHERE code = 'admin' ON CONFLICT DO NOTHING;
    """)


def downgrade():
    op.execute("DROP TABLE ingestion_job; DROP TABLE integration_connection;")
    op.execute("DELETE FROM iam.capability WHERE code IN ('integration.manage','integration.run')")
