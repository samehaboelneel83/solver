"""0115: files kept in a workspace, by version, as sources the domain's data is bound to.

A file attached to the Assistant lived in one conversation: the records built from it could not be refreshed
from next week's file, and a colleague could not see which file they came from. A workspace file keeps every
version of a file by name (its tables as read, its SHA-256, who added it), and a source binding (0114) may now
name a workspace file instead of a database connection, so a newer version is compared and applied the same way.
"""
from alembic import op

revision = "0115"
down_revision = "0114"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE workspace_file (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            domain_id bigint NOT NULL REFERENCES domain(id) ON DELETE CASCADE,
            organization_id uuid NOT NULL REFERENCES iam.organization(id),
            name text NOT NULL CHECK (length(name) BETWEEN 1 AND 255),
            version integer NOT NULL CHECK (version >= 1),
            sha256 text NOT NULL,
            sheets jsonb NOT NULL,
            rows integer NOT NULL DEFAULT 0,
            added_by uuid REFERENCES iam.user_account(id),
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (domain_id, name, version)
        );
        CREATE TRIGGER a_workspace_file_tenant BEFORE INSERT OR UPDATE ON workspace_file
          FOR EACH ROW EXECUTE FUNCTION tenant_inherit('domain:domain_id:bigint');
        ALTER TABLE workspace_file ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON workspace_file
          USING (organization_id = app_org()) WITH CHECK (organization_id = app_org());
        GRANT SELECT, INSERT ON workspace_file TO solver_app;
        GRANT USAGE, SELECT ON SEQUENCE workspace_file_id_seq TO solver_app;

        ALTER TABLE source_binding ALTER COLUMN connection_id DROP NOT NULL;
        ALTER TABLE source_binding ADD COLUMN file_name text;
        ALTER TABLE source_binding ADD COLUMN file_version integer;
        ALTER TABLE source_binding ADD CONSTRAINT source_binding_one_source
          CHECK ((connection_id IS NOT NULL) <> (file_name IS NOT NULL));
        CREATE UNIQUE INDEX source_binding_file_target ON source_binding (domain_id, file_name, kind, target)
          WHERE file_name IS NOT NULL;
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM source_binding WHERE file_name IS NOT NULL;
        DROP INDEX IF EXISTS source_binding_file_target;
        ALTER TABLE source_binding DROP CONSTRAINT IF EXISTS source_binding_one_source;
        ALTER TABLE source_binding DROP COLUMN IF EXISTS file_version;
        ALTER TABLE source_binding DROP COLUMN IF EXISTS file_name;
        ALTER TABLE source_binding ALTER COLUMN connection_id SET NOT NULL;
        DROP TABLE IF EXISTS workspace_file;
    """)
