"""0086: server-saved model drafts and idempotent publication (OAAS M2).

`model_draft` is one person's unpublished model for one problem -- the
server copy of what the browser's draft store keeps locally, so a draft
survives another browser, a cleared cache and a different device. It is
owned by the stable `iam.user_account.id`, never by a username, and carries
a `revision` the API compares on every save, so a save built on an older
read is refused instead of overwriting newer work.

`model_publication` records which version a keyed publish request created.
A retry with the same `Idempotency-Key` returns that version rather than
publishing a second one; a different request under a reused key is refused.

Both are tenant tables: row-level security, and an `organization_id`
inherited from their parents (and required to agree with them).
"""

from alembic import op

revision = "0086"
down_revision = "0085"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE model_draft (
            id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES iam.organization(id),
            problem_id      bigint NOT NULL REFERENCES problem(id) ON DELETE CASCADE,
            owner_id        uuid NOT NULL REFERENCES iam.user_account(id) ON DELETE CASCADE,
            base_version_id bigint,
            ir              jsonb NOT NULL CHECK (jsonb_typeof(ir) = 'object'),
            revision        integer NOT NULL DEFAULT 1 CHECK (revision >= 1),
            created_at      timestamptz NOT NULL DEFAULT now(),
            updated_at      timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (problem_id, owner_id),
            -- A draft starts from a version of its own problem, or from nothing.
            FOREIGN KEY (base_version_id, problem_id)
                REFERENCES model_version (id, problem_id) ON DELETE CASCADE
        );
        CREATE INDEX model_draft_organization_idx ON model_draft (organization_id);
        CREATE TRIGGER model_draft_set_updated_at BEFORE UPDATE ON model_draft
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        CREATE TRIGGER a_model_draft_tenant BEFORE INSERT OR UPDATE ON model_draft
            FOR EACH ROW EXECUTE FUNCTION tenant_inherit(
                'problem:problem_id:bigint', 'iam.user_account:owner_id:uuid');
        ALTER TABLE model_draft ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_all ON model_draft
            USING (organization_id = app_org() OR app_is_operator())
            WITH CHECK (organization_id = app_org() OR app_is_operator());
        GRANT SELECT, INSERT, UPDATE, DELETE ON model_draft TO solver_app;

        CREATE TABLE model_publication (
            id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            organization_id  uuid NOT NULL REFERENCES iam.organization(id),
            problem_id       bigint NOT NULL REFERENCES problem(id) ON DELETE CASCADE,
            actor_id         uuid NOT NULL REFERENCES iam.user_account(id) ON DELETE CASCADE,
            idempotency_key  text NOT NULL CHECK (length(idempotency_key) BETWEEN 1 AND 200),
            request_digest   text NOT NULL,
            model_version_id bigint NOT NULL REFERENCES model_version(id) ON DELETE CASCADE,
            created_at       timestamptz NOT NULL DEFAULT now(),
            UNIQUE (problem_id, actor_id, idempotency_key)
        );
        CREATE INDEX model_publication_organization_idx ON model_publication (organization_id);
        CREATE TRIGGER a_model_publication_tenant BEFORE INSERT OR UPDATE ON model_publication
            FOR EACH ROW EXECUTE FUNCTION tenant_inherit(
                'problem:problem_id:bigint', 'model_version:model_version_id:bigint',
                'iam.user_account:actor_id:uuid');
        ALTER TABLE model_publication ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_all ON model_publication
            USING (organization_id = app_org() OR app_is_operator())
            WITH CHECK (organization_id = app_org() OR app_is_operator());
        GRANT SELECT, INSERT, DELETE ON model_publication TO solver_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS model_publication")
    op.execute("DROP TABLE IF EXISTS model_draft")
