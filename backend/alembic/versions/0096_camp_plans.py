"""0096: camp plans -- a camp drawn on the map and its solved layouts (camp layout engine).

A `camp_plan` is one camp as the person drew it: the problem as
`camp-problem/1` JSON (`camp_layout.serial`) in local metres around its
origin longitude and latitude, and how to solve it. A `camp_solve` is one
request to lay it out: the problem frozen as it was asked, the worker's
progress, and the result -- the input and the layout as GeoJSON (local
metres), the report and the layout record. A later edit of the plan never
changes an earlier answer.

Solves are queued here and claimed by the worker with `FOR UPDATE SKIP
LOCKED`, as runs are; a worker heartbeats on the one it holds.
"""

from alembic import op

revision = "0096"
down_revision = "0095"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE camp_plan (
            id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES iam.organization(id),
            domain_id       bigint NOT NULL REFERENCES domain(id) ON DELETE CASCADE,
            name            text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
            problem         jsonb NOT NULL CHECK (jsonb_typeof(problem) = 'object'),
            options         jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(options) = 'object'),
            created_by      uuid REFERENCES iam.user_account(id) ON DELETE SET NULL,
            created_at      timestamptz NOT NULL DEFAULT now(),
            updated_at      timestamptz NOT NULL DEFAULT clock_timestamp()
        );
        CREATE INDEX camp_plan_domain_idx ON camp_plan (domain_id);
        CREATE INDEX camp_plan_organization_idx ON camp_plan (organization_id);
        CREATE TRIGGER camp_plan_set_updated_at BEFORE UPDATE ON camp_plan
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        CREATE TRIGGER a_camp_plan_tenant BEFORE INSERT OR UPDATE ON camp_plan
            FOR EACH ROW EXECUTE FUNCTION tenant_inherit('domain:domain_id:bigint');
        ALTER TABLE camp_plan ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_all ON camp_plan
            USING (organization_id = app_org() OR app_is_operator())
            WITH CHECK (organization_id = app_org() OR app_is_operator());
        GRANT SELECT, INSERT, UPDATE, DELETE ON camp_plan TO solver_app;
        GRANT USAGE, SELECT ON SEQUENCE camp_plan_id_seq TO solver_app;

        CREATE TABLE camp_solve (
            id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES iam.organization(id),
            camp_plan_id    bigint NOT NULL REFERENCES camp_plan(id) ON DELETE CASCADE,
            problem         jsonb NOT NULL CHECK (jsonb_typeof(problem) = 'object'),
            options         jsonb NOT NULL DEFAULT '{}'::jsonb,
            status          text NOT NULL DEFAULT 'queued'
                            CHECK (status IN ('queued', 'running', 'done', 'failed', 'cancelled')),
            progress        jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(progress) = 'array'),
            cancel_requested boolean NOT NULL DEFAULT false,
            error           text,
            result          jsonb,
            beds            integer,
            valid           boolean,
            created_by      uuid REFERENCES iam.user_account(id) ON DELETE SET NULL,
            queued_at       timestamptz NOT NULL DEFAULT now(),
            started_at      timestamptz,
            heartbeat_at    timestamptz,
            finished_at     timestamptz
        );
        CREATE INDEX camp_solve_plan_idx ON camp_solve (camp_plan_id, id DESC);
        CREATE INDEX camp_solve_queue_idx ON camp_solve (queued_at) WHERE status = 'queued';
        CREATE TRIGGER a_camp_solve_tenant BEFORE INSERT OR UPDATE ON camp_solve
            FOR EACH ROW EXECUTE FUNCTION tenant_inherit('camp_plan:camp_plan_id:bigint');
        ALTER TABLE camp_solve ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_all ON camp_solve
            USING (organization_id = app_org() OR app_is_operator())
            WITH CHECK (organization_id = app_org() OR app_is_operator());
        GRANT SELECT, INSERT, UPDATE, DELETE ON camp_solve TO solver_app;
        GRANT USAGE, SELECT ON SEQUENCE camp_solve_id_seq TO solver_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS camp_solve; DROP TABLE IF EXISTS camp_plan")
