"""`pareto_point`: a run's trade-off front between its goal's two terms.

A run asked for a front (`pareto_steps`, `app.solve.pareto`) records one row
per point: the two terms' values, the bound it was found under, and the
run that holds its answer -- each point is solved in full and recorded as
a run of its own (`params.pareto_of`), so the chart on the run page can
open any point's roster. Target roadmap Phase 15.
"""

from alembic import op

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE pareto_point (
            run_id          bigint NOT NULL REFERENCES run(id) ON DELETE CASCADE,
            seq             integer NOT NULL CHECK (seq >= 1),
            first_value     double precision NOT NULL,
            second_value    double precision NOT NULL,
            epsilon         double precision,
            status          text NOT NULL CHECK (status IN ('optimal', 'feasible')),
            point_run_id    bigint REFERENCES run(id) ON DELETE SET NULL,
            organization_id uuid NOT NULL REFERENCES iam.organization(id),
            PRIMARY KEY (run_id, seq)
        );
        CREATE INDEX pareto_point_organization_idx ON pareto_point (organization_id);

        -- On insert only. The one update this table sees is the foreign key
        -- nulling point_run_id when a point's run is deleted -- often in the
        -- same statement that deletes the parent, which the trigger would
        -- then fail to find ("no run with id ..."), refusing the delete.
        -- run_id never changes, and RLS still checks every write.
        CREATE TRIGGER a_pareto_point_tenant BEFORE INSERT ON pareto_point
            FOR EACH ROW EXECUTE FUNCTION tenant_inherit('run:run_id:bigint');

        ALTER TABLE pareto_point ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON pareto_point
            USING (organization_id = app_org())
            WITH CHECK (organization_id = app_org());
        -- Requests read the front; only the worker writes it.
        REVOKE INSERT, UPDATE, DELETE ON pareto_point FROM solver_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE pareto_point")
