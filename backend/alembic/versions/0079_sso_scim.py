"""0079: OIDC SSO + SCIM (queue R35, R36).

Per-organization IdP config (issuer, client id, encrypted secret, group→role
map, SSO-required). Users gain ``external_sub`` and ``token_version`` so a
deprovision bumps the version and every issued JWT stops working. SCIM bearer
tokens are stored hashed per organization.
"""

from alembic import op

revision = "0079"
down_revision = "0078"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE iam.user_account
            ADD COLUMN external_sub text,
            ADD COLUMN token_version integer NOT NULL DEFAULT 0;
        CREATE UNIQUE INDEX user_account_org_external_sub_uidx
            ON iam.user_account (organization_id, external_sub)
            WHERE external_sub IS NOT NULL;

        CREATE TABLE iam.oidc_provider (
            organization_id  uuid PRIMARY KEY REFERENCES iam.organization(id) ON DELETE CASCADE,
            issuer           text NOT NULL,
            client_id        text NOT NULL,
            client_secret_enc text NOT NULL,
            scopes           text NOT NULL DEFAULT 'openid profile email',
            group_claim      text NOT NULL DEFAULT 'groups',
            role_map         jsonb NOT NULL DEFAULT '{}'::jsonb,
            sso_required     boolean NOT NULL DEFAULT false,
            updated_at       timestamptz NOT NULL DEFAULT now()
        );
        ALTER TABLE iam.oidc_provider ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_all ON iam.oidc_provider
            USING (organization_id = app_org() OR app_is_operator())
            WITH CHECK (organization_id = app_org() OR app_is_operator());
        GRANT SELECT, INSERT, UPDATE, DELETE ON iam.oidc_provider TO solver_app;

        CREATE TABLE iam.scim_token (
            organization_id  uuid PRIMARY KEY REFERENCES iam.organization(id) ON DELETE CASCADE,
            token_hash       text NOT NULL,
            prefix           text NOT NULL,
            created_at       timestamptz NOT NULL DEFAULT now()
        );
        ALTER TABLE iam.scim_token ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_all ON iam.scim_token
            USING (organization_id = app_org() OR app_is_operator())
            WITH CHECK (organization_id = app_org() OR app_is_operator());
        GRANT SELECT, INSERT, UPDATE, DELETE ON iam.scim_token TO solver_app;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS iam.scim_token;
        DROP TABLE IF EXISTS iam.oidc_provider;
        DROP INDEX IF EXISTS iam.user_account_org_external_sub_uidx;
        ALTER TABLE iam.user_account
            DROP COLUMN IF EXISTS external_sub,
            DROP COLUMN IF EXISTS token_version;
        """
    )
