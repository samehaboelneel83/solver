"""0081: admin gate override for a failed acceptance check (queue R30 follow-up).

An operator (or someone with model.publish) may put a version into use despite
failed cases when they record a reason. The override is per model_version and
is written to the audit log.
"""

from alembic import op

revision = "0081"
down_revision = "0080"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE suite_gate_override (
            model_version_id  bigint PRIMARY KEY REFERENCES model_version(id),
            organization_id   uuid NOT NULL REFERENCES iam.organization(id),
            reason            text NOT NULL,
            actor_id          uuid,
            at                timestamptz NOT NULL DEFAULT now()
        );
        ALTER TABLE suite_gate_override ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_all ON suite_gate_override
            USING (organization_id = app_org() OR app_is_operator())
            WITH CHECK (organization_id = app_org() OR app_is_operator());
        GRANT SELECT, INSERT, UPDATE, DELETE ON suite_gate_override TO solver_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS suite_gate_override")
