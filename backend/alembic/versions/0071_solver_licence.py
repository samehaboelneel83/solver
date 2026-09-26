"""0071: an organization's own solver licences (queue R42), and which solvers it allows.

`iam.solver_licence` holds, per organization and added solver (an adapter, queue R41), the
licence that organization brings: environment values and/or a licence file, as one JSON object
**encrypted** (Fernet, under `SOLVER_SECRETS_KEY` from the environment -- never in the database,
never in the repository). `fingerprint` is a short hash of the plaintext, so a person can tell two
licences apart without either being shown; nothing ever reads the payload back out through the
API. A solve decrypts it into its own sandboxed child only.

Row-level security as for `iam.api_key`: a request sees and writes its own organization's rows;
the worker (BYPASSRLS, 0037) reads the one it needs for the run it is solving.

Two settings, `solve.allowed_solvers` and `solve.denied_solvers` (comma-separated solver names,
empty by default): when `allowed` is set, only those solve; a `denied` one never does.
"""

from alembic import op

revision = "0071"
down_revision = "0070"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE iam.solver_licence (
            organization_id uuid NOT NULL REFERENCES iam.organization(id) ON DELETE CASCADE,
            adapter     text NOT NULL CHECK (adapter ~ '^[a-z][a-z0-9_-]{0,39}$'),
            payload     bytea NOT NULL,
            fingerprint text NOT NULL,
            set_by      text,
            set_at      timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (organization_id, adapter)
        );
        GRANT SELECT, INSERT, UPDATE, DELETE ON iam.solver_licence TO solver_app;
        ALTER TABLE iam.solver_licence ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON iam.solver_licence
            USING (organization_id = app_org())
            WITH CHECK (organization_id = app_org());
    """)
    op.execute("""
        INSERT INTO setting_key (key, value_type, default_value, description) VALUES
        ('solve.allowed_solvers', 'string', CAST('""' AS jsonb),
         'Only these solvers may solve (comma-separated names); empty allows every one'),
        ('solve.denied_solvers', 'string', CAST('""' AS jsonb),
         'These solvers never solve (comma-separated names)')
    """)


def downgrade() -> None:
    op.execute("DELETE FROM setting WHERE key IN ('solve.allowed_solvers', 'solve.denied_solvers')")
    op.execute("DELETE FROM setting_key WHERE key IN ('solve.allowed_solvers', 'solve.denied_solvers')")
    op.execute("DROP TABLE iam.solver_licence")
