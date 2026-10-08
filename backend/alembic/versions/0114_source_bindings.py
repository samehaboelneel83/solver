"""0114: where a domain's data came from -- a database source bound to the records, links or values it fills.

A plan built from a source (the Assistant's `use_source`, loaded with *_from_file) recorded nothing of it: the
records looked typed in, so "read the database again and solve again" could not find what to update (the
database-source test, October 2026). A binding keeps the source (connection), the mapping from its columns to
the target (a kind of record, a relationship type, a parameter) and which extraction was last applied, so a
refresh can read the source again, report what changed and write it.
"""
from alembic import op

revision = "0114"
down_revision = "0113"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE source_binding (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            domain_id bigint NOT NULL REFERENCES domain(id) ON DELETE CASCADE,
            organization_id uuid NOT NULL REFERENCES iam.organization(id),
            connection_id bigint NOT NULL REFERENCES integration_connection(id),
            kind text NOT NULL CHECK (kind IN ('entities', 'relationships', 'parameter_values')),
            target text NOT NULL CHECK (length(target) BETWEEN 1 AND 200),
            mapping jsonb NOT NULL,
            job_id bigint REFERENCES ingestion_job(id),
            sha256 text,
            created_at timestamptz NOT NULL DEFAULT now(),
            refreshed_at timestamptz,
            UNIQUE (domain_id, connection_id, kind, target)
        );
        CREATE TRIGGER a_source_binding_tenant BEFORE INSERT OR UPDATE ON source_binding
          FOR EACH ROW EXECUTE FUNCTION tenant_inherit('domain:domain_id:bigint');
        ALTER TABLE source_binding ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON source_binding
          USING (organization_id = app_org()) WITH CHECK (organization_id = app_org());
        GRANT SELECT, INSERT, UPDATE, DELETE ON source_binding TO solver_app;
        GRANT USAGE, SELECT ON SEQUENCE source_binding_id_seq TO solver_app;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS source_binding")
