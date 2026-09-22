"""API keys and a per-caller rate limit (target roadmap Phase 7).

**`iam.api_key`** -- a credential for a program rather than a person. The
token is `sk_<prefix>_<secret>`: the prefix finds the row, the secret is
checked against `secret_hash`. The hash is a keyed SHA-256, not bcrypt:
the secret is 256 random bits, which no dictionary holds, and a slow hash
would cost every API request a quarter of a second. A key belongs to the
user who made it and can do at most what that user can do *now* -- its
`capabilities` are intersected with the user's on every request -- so a
key never outlives the permission it was cut from. The secret itself is
shown once, at creation, and never stored.

**`iam.rate_bucket`** -- one token bucket per caller (a key, or a signed-in
user), refilled at the organization's `requests_per_minute` quota (a new
column; null = no limit). Written only by the connecting role, before a
request becomes a tenant, so it has no row-level security and no grant.
"""

from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE iam.api_key (
            id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES iam.organization(id) ON DELETE CASCADE,
            user_id         uuid NOT NULL REFERENCES iam.user_account(id) ON DELETE CASCADE,
            name            text NOT NULL CHECK (length(trim(name)) > 0),
            prefix          text NOT NULL UNIQUE CHECK (prefix ~ '^[a-f0-9]{12}$'),
            secret_hash     text NOT NULL,
            capabilities    text[] NOT NULL,
            created_at      timestamptz NOT NULL DEFAULT now(),
            expires_at      timestamptz,
            last_used_at    timestamptz,
            revoked_at      timestamptz,
            CHECK (expires_at IS NULL OR expires_at > created_at)
        );
        CREATE INDEX api_key_user_idx ON iam.api_key (user_id);

        -- A key belongs to its user's organization; it is not chosen.
        CREATE TRIGGER a_iam_api_key_tenant BEFORE INSERT OR UPDATE ON iam.api_key
            FOR EACH ROW EXECUTE FUNCTION tenant_inherit('iam.user_account:user_id:uuid');

        GRANT SELECT, INSERT, UPDATE ON iam.api_key TO solver_app;
        ALTER TABLE iam.api_key ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON iam.api_key
            USING (organization_id = app_org())
            WITH CHECK (organization_id = app_org());

        CREATE TABLE iam.rate_bucket (
            caller      text PRIMARY KEY,
            tokens      double precision NOT NULL,
            refilled_at timestamptz NOT NULL DEFAULT now()
        );
        REVOKE ALL ON iam.rate_bucket FROM solver_app;

        ALTER TABLE iam.quota ADD COLUMN requests_per_minute integer
            CHECK (requests_per_minute IS NULL OR requests_per_minute >= 1);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE iam.quota DROP COLUMN requests_per_minute;
        DROP TABLE iam.rate_bucket;
        DROP TABLE iam.api_key;
        """
    )
