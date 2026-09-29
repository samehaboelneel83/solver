"""0091: graph layouts saved on the server (OAAS plan §7.3, follow-up).

Where a person put the cards of a problem's Visual Graph. Presentation only:
never part of the IR, its hash or its versions. One row per person and
problem, owned by the stable `iam.user_account.id`, so the arrangement
follows the person to another browser or device. A tenant table: row-level
security, and an `organization_id` inherited from the problem and the owner.
"""

from alembic import op

revision = "0091"
down_revision = "0090"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE graph_layout (
            organization_id uuid NOT NULL REFERENCES iam.organization(id),
            problem_id      bigint NOT NULL REFERENCES problem(id) ON DELETE CASCADE,
            owner_id        uuid NOT NULL REFERENCES iam.user_account(id) ON DELETE CASCADE,
            positions       jsonb NOT NULL CHECK (jsonb_typeof(positions) = 'object'),
            updated_at      timestamptz NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY (problem_id, owner_id)
        );
        CREATE INDEX graph_layout_organization_idx ON graph_layout (organization_id);
        CREATE TRIGGER graph_layout_set_updated_at BEFORE UPDATE ON graph_layout
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        CREATE TRIGGER a_graph_layout_tenant BEFORE INSERT OR UPDATE ON graph_layout
            FOR EACH ROW EXECUTE FUNCTION tenant_inherit(
                'problem:problem_id:bigint', 'iam.user_account:owner_id:uuid');
        ALTER TABLE graph_layout ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_all ON graph_layout
            USING (organization_id = app_org() OR app_is_operator())
            WITH CHECK (organization_id = app_org() OR app_is_operator());
        GRANT SELECT, INSERT, UPDATE, DELETE ON graph_layout TO solver_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS graph_layout")
