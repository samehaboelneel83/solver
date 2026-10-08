"""0119: notices -- what the platform did for a person while they were away.

A scheduled refresh (0116) that found changes to review, applied them (and queued runs), or could not finish, says
so to the person who set it: one notice each, read in the app. Notices belong to one person in one organization
(row-level security by organization; the API shows each person their own).
"""
from alembic import op

revision = "0119"
down_revision = "0118"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE notice (
            id bigserial PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES iam.organization(id),
            user_id uuid NOT NULL REFERENCES iam.user_account(id) ON DELETE CASCADE,
            kind text NOT NULL,
            title text NOT NULL,
            body text NOT NULL DEFAULT '',
            link text,
            created_at timestamptz NOT NULL DEFAULT now(),
            read_at timestamptz
        );
        ALTER TABLE notice ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON notice
          USING (organization_id = app_org()) WITH CHECK (organization_id = app_org());
        CREATE INDEX notice_unread ON notice (user_id, created_at DESC) WHERE read_at IS NULL;
        GRANT SELECT, INSERT, UPDATE, DELETE ON notice TO solver_app;
        GRANT USAGE, SELECT ON SEQUENCE notice_id_seq TO solver_app;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS notice")
