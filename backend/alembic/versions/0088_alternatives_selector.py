"""0088: alternative plans, and the learned selector allowed to act (Epic engine).

`run_alternative` is a run's list of next-best distinct plans (E-1,
`app.solve.alternatives`): each one a finished run of its own, like a Pareto
point (0045), with its goal value and how many yes-or-no decisions differ
from the best. Written by the worker only; requests read it.

`solve.selector_acts` (E-4) lets the learned selector (`app.solve.selector`,
queue R11) choose the solver when its vote is confident. Off by default: the
selector keeps running in shadow and recording its pick either way.
"""

import sqlalchemy as sa
from alembic import op

revision = "0088"
down_revision = "0087"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE run_alternative (
            run_id          bigint NOT NULL REFERENCES run(id) ON DELETE CASCADE,
            seq             integer NOT NULL CHECK (seq >= 1),
            objective       double precision NOT NULL,
            changed         integer NOT NULL CHECK (changed >= 1),
            status          text NOT NULL CHECK (status IN ('optimal', 'feasible')),
            point_run_id    bigint REFERENCES run(id) ON DELETE SET NULL,
            organization_id uuid NOT NULL REFERENCES iam.organization(id),
            PRIMARY KEY (run_id, seq)
        );
        CREATE INDEX run_alternative_organization_idx ON run_alternative (organization_id);
        -- On insert only, for the reason 0045 gives for pareto_point.
        CREATE TRIGGER a_run_alternative_tenant BEFORE INSERT ON run_alternative
            FOR EACH ROW EXECUTE FUNCTION tenant_inherit('run:run_id:bigint');
        ALTER TABLE run_alternative ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON run_alternative
            USING (organization_id = app_org())
            WITH CHECK (organization_id = app_org());
        GRANT SELECT ON run_alternative TO solver_app;
        REVOKE INSERT, UPDATE, DELETE ON run_alternative FROM solver_app;
        """
    )
    op.get_bind().execute(
        sa.text(
            "INSERT INTO setting_key (key, value_type, default_value, description)"
            " VALUES ('solve.selector_acts', 'boolean', CAST('false' AS jsonb),"
            "         'Let the learned selector choose the solver when its vote is confident')"
        )
    )


def downgrade() -> None:
    op.execute("DELETE FROM setting WHERE key = 'solve.selector_acts'")
    op.execute("DELETE FROM setting_key WHERE key = 'solve.selector_acts'")
    op.execute("DROP TABLE IF EXISTS run_alternative")
